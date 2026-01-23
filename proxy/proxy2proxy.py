"""
Local proxy-to-proxy Flask server (runs on localhost:8081)

Flow:
genai-sdk/langchain (normal JSON body)  ->
  localhost:8081/gemini/<subpath>  ->
    (kubectl exec into a running GKE pod) ->
      inside pod: send base64 request to localhost:8080/geminib64/<subpath> ->
      pod prints JSON {status_code, headers, body_b64} to STDOUT
    local server parses STDOUT, base64-decodes body_b64, returns normal upstream response bytes to client.

Notes:
- This server does NOT do Gemini auth. It just tunnels via kubectl into your pod.
- You must have kubectl configured, context set, and permissions to exec into the pod.
- Requires: Python 3.10+, Flask, requests
"""

from __future__ import annotations

import os
import sys
import json
import base64
import shlex
import logging
import subprocess
import platform
from typing import Dict, Any, Optional, List, Tuple

from flask import Flask, request, Response, jsonify

logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger("proxy-to-proxy")

app = Flask(__name__)

# ----------------------------
# Config (env-driven)
# ----------------------------
# Kubernetes selection
KUBE_NAMESPACE = os.getenv("KUBE_NAMESPACE", "default")
KUBE_CONTEXT = os.getenv("KUBE_CONTEXT", "")  # optional
POD_SELECTOR = os.getenv("POD_SELECTOR", "app=gemini-proxy")  # label selector for your 8080 pod
POD_NAME = os.getenv("POD_NAME", "")  # if set, overrides POD_SELECTOR
CONTAINER = os.getenv("KUBE_CONTAINER", "")  # optional container name if multiple in pod

# Pod-local service target
POD_LOCAL_PROXY_HOST = os.getenv("POD_LOCAL_PROXY_HOST", "127.0.0.1")
POD_LOCAL_PROXY_PORT = int(os.getenv("POD_LOCAL_PROXY_PORT", "8080"))
POD_LOCAL_B64_PREFIX = os.getenv("POD_LOCAL_B64_PREFIX", "/geminib64") 

# kubectl exec behavior
KUBECTL_BIN = os.getenv("KUBECTL_BIN", "kubectl")
KUBECTL_TIMEOUT = int(os.getenv("KUBECTL_TIMEOUT", "120"))

# Debug logging
DEBUG_DUMP = os.getenv("DEBUG_DUMP", "false").lower() == "true"


# ----------------------------
# Utilities
# ----------------------------

def is_windows() -> bool:
    return platform.system().lower().startswith("win")


def build_kubectl_base_args() -> List[str]:
    """
    Build base kubectl args that work on Windows/Mac/Linux.
    Use list args (no shell=True) for safety/correctness.
    """
    args = [KUBECTL_BIN]
    if KUBE_CONTEXT:
        args += ["--context", KUBE_CONTEXT]
    if KUBE_NAMESPACE:
        args += ["-n", KUBE_NAMESPACE]
    return args


def run_subprocess(cmd: List[str], timeout: int = KUBECTL_TIMEOUT) -> subprocess.CompletedProcess:
    if DEBUG_DUMP:
        LOGGER.info("Running cmd: %s", " ".join(shlex.quote(c) for c in cmd))
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        check=False,
    )


def get_target_pod_name() -> str:
    """
    Determine the pod to exec into.
    Priority: POD_NAME env override -> first pod from POD_SELECTOR.
    """
    if POD_NAME:
        return POD_NAME

    base = build_kubectl_base_args()
    cmd = base + [
        "get", "pods",
        "-l", POD_SELECTOR,
        "-o", "json",
    ]
    cp = run_subprocess(cmd)
    if cp.returncode != 0:
        raise RuntimeError(f"kubectl get pods failed: {cp.stderr.strip() or cp.stdout.strip()}")

    data = json.loads(cp.stdout)
    items = data.get("items", [])
    if not items:
        raise RuntimeError(f"No pods found for selector: {POD_SELECTOR} in ns={KUBE_NAMESPACE}")

    # pick first Running pod if possible
    for it in items:
        phase = (it.get("status") or {}).get("phase")
        if phase == "Running":
            return it["metadata"]["name"]

    return items[0]["metadata"]["name"]


def build_python_exec_script(
    pod_url: str,
    method: str,
    headers: Dict[str, str],
    params: Dict[str, Any],
    body_b64: str,
) -> str:
    """
    Build a small Python program to run inside the pod.
    It POSTs to pod-local 8080 /geminib64 endpoint with base64 request body.
    It prints *only* one JSON object to STDOUT (so we can parse it reliably).
    """
    # Keep only relevant headers to send upstream; avoid Host/Content-Length etc.
    # Force JSON wrapper with "b64" to avoid raw-base64 parsing ambiguity.
    # IMPORTANT: ensure Content-Type is application/json.
    headers = {k: v for k, v in headers.items() if k.lower() not in ("host", "content-length")}
    headers.setdefault("Content-Type", "application/json")

    payload = {"b64": body_b64}

    # We embed JSON safely using json.dumps; no f-string quoting issues.
    program = f"""
import json, sys, requests

url = {json.dumps(pod_url)}
method = {json.dumps(method)}
headers = json.loads({json.dumps(json.dumps(headers))})
params = json.loads({json.dumps(json.dumps(params))})
payload = json.loads({json.dumps(json.dumps(payload))})

try:
    r = requests.request(method, url, headers=headers, params=params, json=payload, timeout=60)
    # print the pod's JSON response (status_code/headers/body_b64 or error)
    print(r.text)
except Exception as e:
    print(json.dumps({{"error": str(e)}}))
"""
    return program.strip()


def kubectl_exec_python(pod: str, python_code: str) -> str:
    """
    Exec into pod and run:
      python -c "<code>"
    Returns STDOUT (string).
    """
    base = build_kubectl_base_args()
    cmd = base + ["exec", "-i", pod]
    if CONTAINER:
        cmd += ["-c", CONTAINER]
    cmd += ["--", "python", "-c", python_code]

    cp = run_subprocess(cmd, timeout=KUBECTL_TIMEOUT)
    if cp.returncode != 0:
        raise RuntimeError(
            f"kubectl exec failed (rc={cp.returncode}): {cp.stderr.strip() or cp.stdout.strip()}"
        )
    return cp.stdout.strip()


def extract_json_from_stdout(stdout: str) -> Dict[str, Any]:
    """
    Pods may print extra logs. We try:
      - parse whole stdout as JSON
      - else parse last JSON object line
    """
    if not stdout:
        raise RuntimeError("Empty stdout from pod exec")

    # 1) direct parse
    try:
        return json.loads(stdout)
    except Exception:
        pass

    # 2) attempt last line json
    lines = [ln.strip() for ln in stdout.splitlines() if ln.strip()]
    for ln in reversed(lines):
        try:
            return json.loads(ln)
        except Exception:
            continue

    # 3) fail with context
    raise RuntimeError(f"Could not parse JSON from pod stdout. Tail:\n{stdout[-800:]}")


def decode_b64_body(body_b64: str) -> bytes:
    return base64.b64decode(body_b64.encode("utf-8"), validate=True)


def safe_passthrough_headers(pod_headers: Dict[str, str]) -> Dict[str, str]:
    """
    Minimal header passthrough back to the SDK.
    Keep content-type; you can add more if needed.
    """
    out = {}
    for k, v in (pod_headers or {}).items():
        lk = k.lower()
        if lk in ("content-type", "cache-control"):
            out[k] = v
    return out


# ----------------------------
# Routes (mirror your /gemini/* shape)
# ----------------------------

@app.get("/healthz")
def healthz():
    return jsonify(
        {
            "ok": True,
            "namespace": KUBE_NAMESPACE,
            "pod_selector": POD_SELECTOR,
            "pod_name_override": POD_NAME or None,
            "container": CONTAINER or None,
            "pod_local_target": f"http://{POD_LOCAL_PROXY_HOST}:{POD_LOCAL_PROXY_PORT}{POD_LOCAL_B64_PREFIX}",
            "platform": platform.system(),
        }
    )


@app.route("/gemini/<path:subpath>", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
def local_proxy_to_pod(subpath: str):
    """
    Accept normal (non-base64) Gemini request.
    Tunnel through kubectl exec to pod-local /geminib64/<subpath>.
    Return decoded normal response bytes.
    """
    try:
        pod = get_target_pod_name()
    except Exception as e:
        LOGGER.exception("Pod selection failed")
        return jsonify({"error": f"Pod selection failed: {str(e)}"}), 502

    # Build pod-local URL
    pod_url = f"http://{POD_LOCAL_PROXY_HOST}:{POD_LOCAL_PROXY_PORT}{POD_LOCAL_B64_PREFIX}/{subpath}"

    # Params + body
    params = request.args.to_dict(flat=False)
    body_bytes = request.get_data() or b""

    # Base64 encode request body
    body_b64 = base64.b64encode(body_bytes).decode("utf-8")

    # Forward headers (but do NOT forward Authorization; pod proxy will inject its own)
    hdrs: Dict[str, str] = {}
    for k, v in request.headers.items():
        lk = k.lower()
        if lk in ("host", "content-length", "authorization", "connection"):
            continue
        hdrs[k] = v

    # Build python code to run in pod
    py = build_python_exec_script(
        pod_url=pod_url,
        method=request.method,
        headers=hdrs,
        params=params,
        body_b64=body_b64,
    )

    if DEBUG_DUMP:
        LOGGER.info("Pod URL: %s", pod_url)
        LOGGER.info("Method: %s", request.method)
        LOGGER.info("Params: %s", params)
        LOGGER.info("Body bytes len: %d", len(body_bytes))
        LOGGER.info("Python snippet (head): %s", py[:200] + "...")

    # Exec into pod and run request
    try:
        stdout = kubectl_exec_python(pod, py)
        result = extract_json_from_stdout(stdout)
    except Exception as e:
        LOGGER.exception("kubectl exec request failed")
        return jsonify({"error": str(e)}), 502

    # Pod-level errors (proxy might return {"error": "..."} )
    if isinstance(result, dict) and result.get("error"):
        return jsonify({"error": result["error"], "pod": pod}), 502

    # Expecting pod's /geminib64 JSON envelope
    status_code = int(result.get("status_code", 502))
    pod_headers = result.get("headers") or {}
    body_b64_out = result.get("body_b64")

    if not body_b64_out:
        # Provide debug tail
        return jsonify(
            {
                "error": "Missing body_b64 in pod response",
                "pod": pod,
                "status_code": status_code,
                "raw_result": result,
            }
        ), 502

    # Decode response bytes
    try:
        resp_bytes = decode_b64_body(body_b64_out)
    except Exception as e:
        return jsonify({"error": f"Failed to decode response body_b64: {str(e)}"}), 502

    # Return "standard" response back to SDK/client
    resp = Response(
        resp_bytes,
        status=status_code,
        content_type=pod_headers.get("Content-Type", "application/json"),
    )

    # Optional header passthrough
    for k, v in safe_passthrough_headers(pod_headers).items():
        resp.headers[k] = v

    return resp

@app.get("/check-health-gemini")
def check_health_gemini():
    """
    Health check for Gemini via pod proxy.

    Flow:
      localhost:8081/check-health-gemini
        -> kubectl exec into pod
        -> curl http://127.0.0.1:8080/healthz
        -> parse stdout JSON
        -> return result
    """
    try:
        pod = get_target_pod_name()
    except Exception as e:
        LOGGER.exception("Pod selection failed")
        return jsonify(
            {
                "ok": False,
                "stage": "pod_selection",
                "error": str(e),
            }
        ), 502

    # Build a very small Python snippet to run inside pod
    py = r"""
    import json, requests, sys
    try:
        r = requests.get("http://127.0.0.1:8080/healthz", timeout=5)
        print(r.text)
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}))
    """.strip()

    try:
        stdout = kubectl_exec_python(pod, py)
        result = extract_json_from_stdout(stdout)
    except Exception as e:
        LOGGER.exception("Health check exec failed")
        return jsonify(
            {
                "ok": False,
                "stage": "kubectl_exec",
                "pod": pod,
                "error": str(e),
            }
        ), 502

    # Normalize response
    if not isinstance(result, dict):
        return jsonify(
            {
                "ok": False,
                "stage": "parse",
                "pod": pod,
                "raw": stdout,
            }
        ), 502

    return jsonify(
        {
            "ok": True,
            "pod": pod,
            "pod_health": result,
        }
    ), 200


if __name__ == "__main__":
    host = os.getenv("LOCAL_PROXY_HOST", "0.0.0.0")
    port = int(os.getenv("LOCAL_PROXY_PORT", "8081"))

    LOGGER.info("Starting local proxy-to-proxy on http://%s:%d", host, port)
    LOGGER.info("Target namespace=%s selector=%s pod_name=%s container=%s", KUBE_NAMESPACE, POD_SELECTOR, POD_NAME, CONTAINER)
    app.run(host=host, port=port, debug=False, threaded=True)














# Now this server 8080 will run in GKE pod. 

# Now write the proxy-to-proxy server in flask(8081) which simply route the request to the pod's b64 endpoint and decode the reponse and return in stand format. This 8081 server will run in my local machine only, it does not need any authentication for Gemini. It simply logs ( exec ) into any pods using subprocess + kubectl , build a python request request scipt) and runs the reqwust , and , finally parses the STDOUT of the pods return the encoded reponse .


# So , the flow is 

# genai-sdk/langchain -> (non encoded regular gemini req  ) -> localhost:8081 ( logs into the running pod + encodes regular gemini req + buid a python request script ( to the localhost:8080 within pod ) + run the scirpt in the pod's terminal + parses the stdout result + decode + return ) -> genai-sdk/langchain


# Write the local proxy-to-proxy server. It dynamically fetches the os env ( win or linux/mac ) and build subporicess command accordingly
