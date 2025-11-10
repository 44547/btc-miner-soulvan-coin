import os
import shutil
import stat
import tempfile
import logging
from typing import Optional

LOG = logging.getLogger("miner-installer")

def atomic_install(src_path: str, dest_path: str, mode: int = 0o755) -> str:
    """
    Atomically install a verified binary from `src_path` to `dest_path`.
    - Writes to a temp file in the destination directory then renames it.
    - Sets file mode to `mode` (default 0755).
    - Ensures destination directory exists.
    Returns the final path on success.
    Raises on error.
    """
    if not os.path.exists(src_path):
        raise FileNotFoundError(f"source does not exist: {src_path}")

    d = os.path.dirname(os.path.abspath(dest_path))
    os.makedirs(d, exist_ok=True)

    # Use tempfile in destination dir to ensure same-filesystem atomic rename
    fd, tmp = tempfile.mkstemp(dir=d)
    os.close(fd)
    try:
        shutil.copy2(src_path, tmp)
        os.chmod(tmp, mode)
        # atomic move
        os.replace(tmp, dest_path)
        LOG.info("Installed %s -> %s", src_path, dest_path)
        return dest_path
    except Exception:
        # cleanup temp file on failure
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise

def remove_if_exists(path: str):
    if os.path.exists(path):
        os.remove(path)

def validate_installed(path: str, expected_mode: int = 0o755) -> bool:
    st = os.stat(path)
    mode = stat.S_IMODE(st.st_mode)
    return mode == expected_mode and stat.S_ISREG(st.st_mode)
