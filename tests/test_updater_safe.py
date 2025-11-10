import tempfile
import os
from src.updater_safe import sha256_of, gpg_verify

def test_sha256_of_tmpfile():
    tf = tempfile.NamedTemporaryFile(delete=False)
    try:
        tf.write(b"hello world")
        tf.flush()
        tf.close()
        h = sha256_of(tf.name)
        assert isinstance(h, str) and len(h) == 64
    finally:
        os.unlink(tf.name)

def test_gpg_verify_fails_on_invalid_files():
    fdata = tempfile.NamedTemporaryFile(delete=False)
    fsig = tempfile.NamedTemporaryFile(delete=False)
    try:
        fdata.write(b"data")
        fdata.flush()
        fsig.write(b"sig")
        fsig.flush()
        fdata.close()
        fsig.close()
        ok = gpg_verify(fsig.name, fdata.name, pubkey_path=None)
        assert ok is False
    finally:
        os.unlink(fdata.name)
        os.unlink(fsig.name)
