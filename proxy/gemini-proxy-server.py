from __future__ import annotations

import os
import time
import threading
import logging
from typing import Any, Dict, Iterable, Tuple, Optional
from dotenv import load_dotenv


import base64
import json

import requests
from flask import Flask, request, Response, jsonify

# If you're using service account auth outside GCP:
from google.oauth2 import service_account
import google.auth.transport.requests

# Load .env if present
load_dotenv()

LOGGER = logging.getLogger("gemini-proxy")
logging.basicConfig(level=logging.INFO)

app = Flask(__name__)

# -------------------------------
# Your retry helper (kept simple)
# -------------------------------
def make_request_with_retries(max_retries=5, wait_time=30, method="POST", *args, **kwargs):
    retries = 0
    while retries < max_retries:
        resp = requests.request(method, *args, **kwargs)
        if resp.status_code == 429:
            retries += 1
            LOGGER.warning(
                f"Rate limit hit. Retrying in {wait_time}s... (Attempt {retries}/{max_retries})"
            )
            time.sleep(wait_time)
            continue
        return resp
    raise RuntimeError(f"Failed after {max_retries} retries due to rate limiting.")


# -----------------------------------------
# Token provider using YOUR auth conventions
# -----------------------------------------
class VertexTokenProvider:
    """
    Mirrors your GeminiModel auth patterns:
      - Outside GCP: service account file via GOOGLE_APPLICATION_CREDENTIALS
      - Inside GCP: metadata server token
    Provides:
      - get_access_token() that refreshes token when needed
      - project_id, location for building upstream host
    """

    METADATA_URL = "http://metadata.google.internal/computeMetadata/v1"
    METADATA_HEADERS = {"Metadata-Flavor": "Google"}

    def __init__(self, deployed_gcp: bool, refresh_margin_s: int = 120):
        self.deployed_gcp = deployed_gcp
        self.refresh_margin_s = refresh_margin_s

        self._lock = threading.Lock()
        self._token: Optional[str] = None
        self._token_expiry_epoch: Optional[float] = None

        # outside GCP: keep credentials object to refresh
        self._creds = None
        self._request_adapter = google.auth.transport.requests.Request()

        if self.deployed_gcp:
            self._project_id = self._get_project_id_gcp()
            self._location = self._get_project_location_gcp()
        else:
            self._project_id = self._get_project_id_env()
            self._location = self._get_project_location_env()

            # Prepare service-account creds once; refresh on demand
            self._creds = service_account.Credentials.from_service_account_file(
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"],
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )

        # Prime token on startup
        self._refresh_token()

    @property
    def project_id(self) -> str:
        return self._project_id

    @property
    def location(self) -> str:
        return self._location

    def _get_project_id_env(self) -> str:
        return os.environ["GOOGLE_CLOUD_PROJECT"]

    def _get_project_location_env(self) -> str:
        return os.environ["GOOGLE_CLOUD_LOCATION"]

    # ---- GCP metadata auth helpers (your style) ----
    def _get_metadata_gcp(self, path: str) -> str:
        resp = requests.get(f"{self.METADATA_URL}/{path}", headers=self.METADATA_HEADERS, timeout=5)
        resp.raise_for_status()
        return resp.text

    def _get_access_token_gcp(self) -> Dict[str, Any]:
        resp = requests.get(
            f"{self.METADATA_URL}/instance/service-accounts/default/token",
            headers=self.METADATA_HEADERS,
            timeout=5,
        )
        resp.raise_for_status()
        return resp.json()  # includes access_token, expires_in, token_type

    def _get_project_id_gcp(self) -> str:
        # project/project-id exists on metadata server
        return self._get_metadata_gcp("project/project-id")

    def _get_project_location_gcp(self) -> str:
        # instance/zone => projects/.../zones/us-central1-a
        full_zone = self._get_metadata_gcp("instance/zone")
        zone = full_zone.split("/")[-1]
        return zone.rsplit("-", 1)[0]  # us-central1

    # ---- token refresh ----
    def _refresh_token(self) -> None:
        with self._lock:
            if self.deployed_gcp:
                tok = self._get_access_token_gcp()
                self._token = tok["access_token"]
                # expires_in is seconds from now
                self._token_expiry_epoch = time.time() + float(tok.get("expires_in", 3000))
            else:
                assert self._creds is not None
                self._creds.refresh(self._request_adapter)
                self._token = self._creds.token
                # creds.expiry is a datetime (may be None in rare cases)
                if self._creds.expiry is not None:
                    self._token_expiry_epoch = self._creds.expiry.timestamp()
                else:
                    # fallback: refresh often
                    self._token_expiry_epoch = time.time() + 1800

    def get_access_token(self) -> str:
        """
        Returns a valid token; refreshes if near expiry.
        """
        with self._lock:
            if self._token is None or self._token_expiry_epoch is None:
                # should not happen, but safe
                pass
            else:
                if time.time() < (self._token_expiry_epoch - self.refresh_margin_s):
                    return self._token

        # refresh outside lock to avoid long hold? token refresh is quick; keep simple
        self._refresh_token()
        return self._token


# -------------------------------
# Proxy config
# -------------------------------
DEPLOYED_GCP = os.getenv("DEPLOYED_GCP", "false").lower() == "true"
PORT = int(os.getenv("PORT", "8080"))
HOST = os.getenv("HOST", "0.0.0.0")

# Upstream timeout/retries
UPSTREAM_TIMEOUT = float(os.getenv("UPSTREAM_TIMEOUT", "120"))
RATE_LIMIT_RETRIES = int(os.getenv("RATE_LIMIT_RETRIES", "5"))
RATE_LIMIT_WAIT = int(os.getenv("RATE_LIMIT_WAIT", "30"))

token_provider = VertexTokenProvider(deployed_gcp=DEPLOYED_GCP)

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
}


def _filter_request_headers() -> Dict[str, str]:
    hdrs: Dict[str, str] = {}
    for k, v in request.headers.items():
        if k.lower() in HOP_BY_HOP_HEADERS:
            continue
        # We'll overwrite Authorization anyway
        if k.lower() == "authorization":
            continue
        hdrs[k] = v

    # Inject fresh token
    hdrs["Authorization"] = f"Bearer {token_provider.get_access_token()}"

    # Keep original client IP chain
    prior = request.headers.get("X-Forwarded-For", "")
    client_ip = request.remote_addr or ""
    hdrs["X-Forwarded-For"] = f"{prior}, {client_ip}".strip(", ").strip()

    return hdrs


def _filter_response_headers(upstream_headers: requests.structures.CaseInsensitiveDict) -> Iterable[Tuple[str, str]]:
    for k, v in upstream_headers.items():
        if k.lower() in HOP_BY_HOP_HEADERS:
            continue
        yield k, v


@app.get("/healthz")
def healthz():
    return jsonify(
        {
            "ok": True,
            "project_id": token_provider.project_id,
            "location": token_provider.location,
            "upstream_host": f"{token_provider.location}-aiplatform.googleapis.com",
        }
    )


@app.route(
    "/gemini/<path:subpath>",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
)
def gemini_proxy(subpath: str):
    """
    Forward:
      http://localhost:PORT/gemini/<subpath>
    to:
      https://{location}-aiplatform.googleapis.com/<subpath>

    Example subpath:
      v1/projects/{project}/locations/{loc}/publishers/google/models/{model}:generateContent
    """
    upstream_host = f"{token_provider.location}-aiplatform.googleapis.com"
    upstream_url = f"https://{upstream_host}/{subpath}"

    # Query params (support repeated keys)
    params = request.args.to_dict(flat=False)

    # Raw body (bytes)
    body = request.get_data()

    headers = _filter_request_headers()

    LOGGER.debug(f" Upstream URL: {upstream_url}")
    LOGGER.debug(f"→ Params: {params}")
    LOGGER.debug(f"→ Body: {body}")

    LOGGER.info("→ %s %s", request.method, upstream_url)

    try:
        upstream_resp = make_request_with_retries(
            max_retries=RATE_LIMIT_RETRIES,
            wait_time=RATE_LIMIT_WAIT,
            method=request.method,
            url=upstream_url,
            headers=headers,
            params=params,
            data=body if body else None,
            timeout=UPSTREAM_TIMEOUT,
            stream=True,
            allow_redirects=False,
        )
    except Exception as e:
        LOGGER.exception("Upstream call failed")
        return jsonify({"error": str(e)}), 502
    
    return Response(
        upstream_resp.content,
        status=upstream_resp.status_code,
        content_type=upstream_resp.headers.get("Content-Type", "application/octet-stream"),
    )




def encode_body_to_b64(body: bytes) -> str:
    return base64.b64encode(body).decode("utf-8")

def make_b64_json_response(status_code: int, headers: Dict[str, str], body_b64: str) -> Response:
    resp_obj = {
        "status_code": status_code,
        "headers": headers,
        "body_b64": body_b64,
    }
    return jsonify(resp_obj)


@app.route(
    "/geminib64/<path:subpath>",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
)
def gemini_proxy_b64(subpath: str):
    """
    Base64 proxy endpoint.

    Client sends a base64-encoded body to:
      http://localhost:PORT/geminib64/<subpath>

    We decode body -> forward bytes to upstream -> return base64(response bytes).

    Accepted request formats:
    1) Raw base64 text in body:
         <base64-string>
    2) JSON wrapper:
         {"b64": "<base64-string>"}
       or {"body_b64": "<base64-string>"}

    Response format (JSON):
      {
        "status_code": 200,
        "headers": {...},        # optional (safe subset)
        "body_b64": "<base64-string>"
      }
    """
    upstream_host = f"{token_provider.location}-aiplatform.googleapis.com"
    upstream_url = f"https://{upstream_host}/{subpath}"

    params = request.args.to_dict(flat=False)

    try:
        headers = _filter_request_headers()
    except Exception as e:
        err_msg = f"Failed to prepare request headers: {str(e)}"
        LOGGER.error(err_msg)
        return make_b64_json_response(500, {}, encode_body_to_b64(err_msg.encode())), 500

    # --------- Decode incoming base64 body ----------
    raw = request.get_data()  # bytes
    decoded_body: bytes = b""

    if raw:
        # Try JSON wrapper first (nice for Postman)
        try:
            obj = json.loads(raw.decode("utf-8"))
            b64 = obj.get("b64") or obj.get("body_b64")
            if not b64 or not isinstance(b64, str):
                err_msg = "JSON must contain 'b64' or 'body_b64' string"
                LOGGER.error(err_msg)
                return make_b64_json_response(400, {}, encode_body_to_b64(err_msg.encode())), 400
            decoded_body = base64.b64decode(b64, validate=True)
        except (UnicodeDecodeError, json.JSONDecodeError):
            # Not JSON; treat as raw base64 text
            try:
                b64 = raw.decode("utf-8").strip()
                decoded_body = base64.b64decode(b64, validate=True)
            except Exception as e:
                err_msg = f"Invalid base64 body: {str(e)}"
                LOGGER.error(err_msg)
                return make_b64_json_response(400, {}, encode_body_to_b64(err_msg.encode())), 400

    # NOTE: Your upstream expects JSON; ensure content-type is application/json if you want.
    # If you decoded JSON bytes, keep/force Content-Type.
    headers.setdefault("Content-Type", "application/json")

    # For debugging:
    # print("Decoded body bytes:", decoded_body[:200])

    try:
        upstream_resp = make_request_with_retries(
            max_retries=RATE_LIMIT_RETRIES,
            wait_time=RATE_LIMIT_WAIT,
            method=request.method,
            url=upstream_url,
            headers=headers,
            params=params,
            data=decoded_body if decoded_body else None,
            timeout=UPSTREAM_TIMEOUT,
            stream=False,  # simplest: read whole response, then b64 encode
            allow_redirects=False,
        )
    except Exception as e:
        LOGGER.exception("Upstream call failed")
        err_msg = f"Upstream call failed: {str(e)}"
        return make_b64_json_response(502, {}, encode_body_to_b64(err_msg.encode())), 502

    # --------- Encode upstream response as base64 ----------
    resp_bytes = upstream_resp.content or b""
    if not resp_bytes:
        LOGGER.error("Upstream response has no body")
        err_msg = f"Upstream response has no body. Response code: {upstream_resp.status_code}"
        return make_b64_json_response(502, {}, encode_body_to_b64(err_msg.encode())), 502
    
    body_b64 = encode_body_to_b64(resp_bytes)

    # Optionally return a safe subset of headers
    safe_headers = {}
    for k, v in upstream_resp.headers.items():
        lk = k.lower()
        if lk in {"content-type", "content-encoding", "cache-control"}:
            safe_headers[k] = v

    return make_b64_json_response(upstream_resp.status_code, safe_headers, body_b64), upstream_resp.status_code





if __name__ == "__main__":
    LOGGER.info("Starting proxy on http://%s:%d", HOST, PORT)
    LOGGER.info("DEPLOYED_GCP=%s", DEPLOYED_GCP)
    LOGGER.info("Proxy base: http://%s:%d/gemini/<path>", HOST, PORT)
    LOGGER.info("Upstream: https://%s-aiplatform.googleapis.com/", token_provider.location)
    app.run(host=HOST, port=PORT, debug=False, threaded=True)
