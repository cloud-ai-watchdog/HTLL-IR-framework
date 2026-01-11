
import fcntl
import json
from typing import Dict, Any

class NdJsonHandler:
    @staticmethod
    def write(entity: Dict[str, Any], file_path: str):
        line = json.dumps(entity, separators=(",", ":"), ensure_ascii=False)
        with open(file_path, "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.write(line + "\n")
                f.flush()
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    @staticmethod
    def read(file_path: str):
        with open(file_path, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    yield json.loads(line)