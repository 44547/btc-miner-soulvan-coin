import tempfile
import os
import stat
from src.installer import atomic_install, validate_installed

def test_atomic_install_and_validate(tmp_path):
    src = tmp_path / "srcbin"
    src.write_bytes(b"binary")
    dest_dir = tmp_path / "dest"
    dest_dir.mkdir()
    dest = dest_dir / "binprog"

    final = atomic_install(str(src), str(dest))
    assert os.path.exists(final)
    assert validate_installed(final)
    st = os.stat(final)
    assert stat.S_IMODE(st.st_mode) == 0o755
