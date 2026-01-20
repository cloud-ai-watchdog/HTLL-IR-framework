import hashlib

from .logger import get_colorlogger
logger = get_colorlogger(__name__)

def get_time():
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")

def hash_text_to_string(text: str) -> str:
    """Generate a SHA-256 hash of the given text and return it as a hexadecimal string."""
    res = hashlib.md5(text.encode('utf-8')).hexdigest()
    return res

def hash_text_to_int(text: str) -> int:
    """Generate a SHA-256 hash of the given text and return it as an integer."""
    res = hashlib.md5(text.encode('utf-8')).hexdigest()
    res = int.from_bytes(bytes.fromhex(res), 'big')
    return res