
from __future__ import annotations

import re
import hashlib
from dataclasses import dataclass
from typing import List, Tuple, Set

from .logger import get_colorlogger
logger = get_colorlogger(__name__)

@dataclass(frozen=True)
class LSHEmbedding:
    """Output of LSH embedder."""
    signature: List[int]          # MinHash signature (length = num_hashes)
    band_keys: List[str]          # LSH bucket keys (length = num_bands)
    shingle_count: int            # number of unique shingles used




class LSHMinHashEmbedder:
    """
    MinHash + LSH banding embedder for near-duplicate detection / candidate generation.

    - Partial match support: character shingles (n-grams).
    - Vocabulary-free: uses hashing, no growing vocab table.
    - Persistent-friendly: `band_keys` are stable strings you can store (e.g., in Qdrant payload).

    Typical usage:
        emb = LSHMinHashEmbedder(shingle_size=5, num_hashes=128, bands=32, seed=42)
        out = emb.embed("raw log line ...")
        # candidate retrieval: find items that share any band_key
        # verification: recompute exact Jaccard of shingles (or other metric) vs candidates
    """

    def __init__(
        self,
        shingle_size: int,
        num_hashes: int,
        bands: int,
        seed: int,
        normalize: bool = True,
        lowercase: bool = True,
        collapse_whitespace: bool = True,
        stop_short_lines: int = 0,
    ):
        """
        Args:
            shingle_size: character n-gram size (5–7 is typical for logs)
            num_hashes: MinHash signature length (64–256 typical)
            bands: number of LSH bands. Must divide num_hashes exactly.
            seed: controls determinism of the hash family
            normalize: apply log normalization (uuid/ip/nums/timestamps masking)
            lowercase: lowercase before shingling
            collapse_whitespace: replace consecutive whitespace with single space
            stop_short_lines: if >0 and normalized text shorter than this, returns empty shingles/signature behavior
        """
        if shingle_size <= 0:
            raise ValueError("shingle_size must be > 0")
        if num_hashes <= 0:
            raise ValueError("num_hashes must be > 0")
        if bands <= 0 or (num_hashes % bands != 0):
            raise ValueError("bands must be > 0 and must divide num_hashes exactly")

        self.shingle_size = shingle_size
        self.num_hashes = num_hashes
        self.bands = bands
        self.rows_per_band = num_hashes // bands

        self.seed = seed
        self.normalize_enabled = normalize
        self.lowercase = lowercase
        self.collapse_whitespace = collapse_whitespace
        self.stop_short_lines = stop_short_lines

        # A large prime > 2^32 for modular hashing
        self._prime = 4294967311  # near 2^32, prime
        self._max_hash = (1 << 32) - 1

        # Pre-generate hash function parameters (a_i, b_i)
        # h_i(x) = (a_i * x + b_i) mod prime
        self._a, self._b = self._make_hash_params(num_hashes, seed)

    # ------------------------- Public API -------------------------

    def embed(self, text: str) -> LSHEmbedding:
        """Compute MinHash signature + LSH band keys for a single log line."""
        norm = self._preprocess(text)
        if self.stop_short_lines and len(norm) < self.stop_short_lines:
            sig = [self._max_hash] * self.num_hashes
            bands = self._signature_to_band_keys(sig)
            return LSHEmbedding(signature=sig, band_keys=bands, shingle_count=0)

        shingles = self._shingle(norm)
        sig = self._minhash_signature(shingles)
        bands = self._signature_to_band_keys(sig)
        return LSHEmbedding(signature=sig, band_keys=bands, shingle_count=len(shingles))

    def shingles(self, text: str) -> Set[int]:
        """Return hashed shingles (useful for exact Jaccard verification)."""
        return self._shingle(self._preprocess(text))

    @staticmethod
    def jaccard(shingles_a: Set[int], shingles_b: Set[int]) -> float:
        """Exact Jaccard similarity between two shingle sets."""
        if not shingles_a and not shingles_b:
            return 1.0
        if not shingles_a or not shingles_b:
            return 0.0
        inter = len(shingles_a & shingles_b)
        union = len(shingles_a | shingles_b)
        return inter / union

    # ------------------------- Preprocess -------------------------

    def _preprocess(self, text: str) -> str:
        lowercase = self.lowercase
        normalize_enabled = self.normalize_enabled
        collapse_whitespace = self.collapse_whitespace

        # --- Core patterns ---
        RE_UUID = re.compile(
            r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
            re.I,
        )
        RE_HEX_WORD = re.compile(r"\b0x[0-9a-f]+\b", re.I)
        RE_HEX_LONG = re.compile(r"\b[0-9a-f]{16,}\b", re.I)  # trace/span hashes etc.

        RE_IPv4 = re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b")
        RE_IPv6 = re.compile(r"\b(?:[0-9a-f]{1,4}:){2,7}[0-9a-f]{1,4}\b", re.I)

        RE_MAC = re.compile(r"\b(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}\b", re.I)

        # ISO-ish timestamps + common log forms
        RE_TS_ISO = re.compile(
            r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}"
            r"(?:\.\d{1,9})?"
            r"(?:Z|[+-]\d{2}:\d{2})?\b",
            re.I,
        )
        RE_TS_DATE = re.compile(r"\b\d{4}/\d{2}/\d{2}\b")            # 2026/01/19
        RE_TS_TIME = re.compile(r"\b\d{2}:\d{2}:\d{2}(?:\.\d+)?\b")  # 12:34:56.789

        # URLs / emails
        RE_URL = re.compile(r"\bhttps?://[^\s\"'<>]+", re.I)
        RE_EMAIL = re.compile(r"\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b", re.I)

        # AWS ARN
        RE_ARN = re.compile(r"\barn:aws[a-z-]*:[a-z0-9-]+:[a-z0-9-]*:\d{12}:[^\s\"']+\b", re.I)

        # JWT (header.payload.signature) base64url-ish
        RE_JWT = re.compile(r"\beyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\b")

        # base64-ish blobs (avoid masking short/normal words)
        RE_B64 = re.compile(r"\b(?:[A-Za-z0-9+/]{20,}={0,2})\b")

        # numbers (mask after timestamps/IP/ids to not break them)
        RE_NUM = re.compile(r"\b\d+\b")

        # key/value id fields: trace_id=..., requestId:..., span-id ..., etc.
        RE_KV_ID = re.compile(
            r"(?i)\b("
            r"trace[_-]?id|span[_-]?id|request[_-]?id|req[_-]?id|correlation[_-]?id|"
            r"session[_-]?id|event[_-]?id|message[_-]?id|msg[_-]?id|job[_-]?id|task[_-]?id|"
            r"txn[_-]?id|transaction[_-]?id|op[_-]?id|operation[_-]?id|run[_-]?id|"
            r"uid|user[_-]?id|account[_-]?id|customer[_-]?id|tenant[_-]?id|org[_-]?id"
            r")\s*([=:])\s*([A-Za-z0-9._:/+=-]{6,})\b"
        )

        # Generic "long token" heuristic:
        # - at least 12 chars
        # - contains BOTH letters and digits (most random ids do)
        # - limited charset (no spaces)
        RE_LONG_ALNUM = re.compile(r"\b(?=[A-Za-z0-9_-]{12,}\b)(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9_-]+\b")

        # Another heuristic for "mostly token-like" chunks often seen in logs:
        # e.g. "9f1c2a3b4d5e6f7a8b9c" (hex), "abc123def456ghi789"
        RE_MIXED_TOKEN = re.compile(r"\b[A-Za-z0-9]{18,}\b")

        def _mask_kv(m: re.Match) -> str:
            key, sep, val = m.group(1), m.group(2), m.group(3)
            # Keep key and separator for readability
            return f"{key}{sep}<id>"

        s = text
        if lowercase:
            s = s.lower()

        if normalize_enabled:
            # structured identifiers first
            s = RE_URL.sub("<url>", s)
            s = RE_EMAIL.sub("<url>", s)
            s = RE_ARN.sub("<url>", s)
            s = RE_JWT.sub("<url>", s)

            s = RE_UUID.sub("<id>", s)
            s = RE_IPv4.sub("<ip>", s)
            s = RE_IPv6.sub("<ip>", s)
            s = RE_MAC.sub("<ip>", s)

            # timestamps
            s = RE_TS_ISO.sub("<ts>", s)
            s = RE_TS_DATE.sub("<ts>", s)
            s = RE_TS_TIME.sub("<ts>", s)

            # key/value id fields (strong signal)
            s = RE_KV_ID.sub(_mask_kv, s)

            # hex / base64 blobs
            s = RE_HEX_WORD.sub("<hex>", s)
            s = RE_HEX_LONG.sub("<hex>", s)
            s = RE_B64.sub("<hex>", s)

            # generic long alnum tokens (request ids etc.)
            s = RE_LONG_ALNUM.sub("<id>", s)
            s = RE_MIXED_TOKEN.sub("<id>", s)

            # finally numbers (so we don't destroy ids before we detect them)
            s = RE_NUM.sub("<id>", s)

        if collapse_whitespace:
            s = re.sub(r"\s+", " ", s).strip()

        return s

    # ------------------------- Shingling -------------------------

    def _shingle(self, s: str) -> Set[int]:
        """
        Character n-gram shingling -> set of 32-bit ints (stable).
        Using a stable hash (blake2b) for shingles to avoid Python hash randomization.
        """
        n = self.shingle_size
        if len(s) < n:
            return set()

        out: Set[int] = set()
        # sliding window
        for i in range(0, len(s) - n + 1):
            gram = s[i : i + n]
            out.add(self._stable_u32(gram))
        return out

    # ------------------------- MinHash -------------------------

    def _minhash_signature(self, shingles: Set[int]) -> List[int]:
        """
        Compute MinHash signature over hashed shingles.
        If shingles empty: return max_hash vector so that it won't spuriously match.
        """
        if not shingles:
            return [self._max_hash] * self.num_hashes

        sig = [self._max_hash] * self.num_hashes
        p = self._prime

        # For each shingle x, update all hash functions:
        # sig[i] = min(sig[i], (a[i]*x + b[i]) % p)
        # (This is O(num_hashes * num_shingles). For very long lines, consider sampling shingles.)
        for x in shingles:
            for i in range(self.num_hashes):
                hx = (self._a[i] * x + self._b[i]) % p
                if hx < sig[i]:
                    sig[i] = hx

        # Convert modulo prime values into 32-bit range for compactness
        # (still deterministic; helps if you want to pack)
        return [v & self._max_hash for v in sig]

    def _signature_to_band_keys(self, sig: List[int]) -> List[str]:
        """
        Convert signature to LSH band keys.
        Band key is a stable string: "lsh:{band_index}:{hex_digest}".
        """
        keys: List[str] = []
        r = self.rows_per_band
        for b in range(self.bands):
            chunk = sig[b * r : (b + 1) * r]
            # Stable digest of the chunk
            digest = hashlib.blake2b(
                (",".join(map(str, chunk))).encode("utf-8"),
                digest_size=8  # 64-bit digest -> short key
            ).hexdigest()
            keys.append(f"lsh:{b}:{digest}")
        return keys

    # ------------------------- Hash utilities -------------------------

    @staticmethod
    def _make_hash_params(k: int, seed: int) -> Tuple[List[int], List[int]]:
        """
        Deterministically generate (a_i, b_i) pairs for k hash functions.
        We derive them from blake2b(seed||i) so results are stable across runs.
        """
        a: List[int] = []
        b: List[int] = []
        for i in range(k):
            h = hashlib.blake2b(f"{seed}:{i}".encode("utf-8"), digest_size=16).digest()
            # 64-bit a and b, then clamp into [1, prime-1] / [0, prime-1]
            ai = int.from_bytes(h[:8], "little") | 1  # make it odd / non-zero-ish
            bi = int.from_bytes(h[8:], "little")
            a.append(ai)
            b.append(bi)
        return a, b

    @staticmethod
    def _stable_u32(s: str) -> int:
        """Stable 32-bit unsigned hash for a string."""
        # blake2b is fast and stable; digest_size=4 gives 32-bit
        return int.from_bytes(hashlib.blake2b(s.encode("utf-8"), digest_size=4).digest(), "little")