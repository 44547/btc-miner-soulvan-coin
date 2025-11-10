import os
import tempfile
import stat
import pytest
from src import sandbox

def test_ensure_executable_and_mode_rejects_nonexistent():
    with pytest.raises(FileNotFoundError):
        sandbox._ensure_executable_and_mode("/nonexistent/path/does/not/exist")

def test_ensure_executable_and_mode_requires_0755(tmp_path):
    f = tmp_path / "binfile"
    f.write_bytes(b"#!/bin/sh\necho hi\n")
    os.chmod(f, 0o644)
    with pytest.raises(PermissionError):
        sandbox._ensure_executable_and_mode(str(f))
    os.chmod(f, 0o755)
    sandbox._ensure_executable_and_mode(str(f))

def test_reject_writable_mounts_requires_ro_and_nonwritable_host(tmp_path):
    host = tmp_path / "writable"
    host.mkdir()
    os.chmod(host, 0o700)
    mount = f"{host}:/opt/data:ro"
    with pytest.raises(PermissionError):
        sandbox._reject_writable_mounts([mount])
    host2 = tmp_path / "readonly"
    host2.mkdir()
    os.chmod(host2, 0o555)
    mount2 = f"{host2}:/opt/data:ro"
    sandbox._reject_writable_mounts([mount2])

def test_reject_writable_mounts_rejects_missing_mode(tmp_path):
    host = tmp_path / "h"
    host.mkdir()
    with pytest.raises(PermissionError):
        sandbox._reject_writable_mounts([f"{host}:/opt/data"])
