import os
import shutil
import stat
import subprocess
import logging
from typing import List, Optional

from .updater_safe import gpg_verify

LOG = logging.getLogger("miner-sandbox")
logging.basicConfig(level=logging.INFO)

DEFAULT_IMAGE = "debian:bookworm-slim"

def _ensure_docker_available():
    if not shutil.which("docker"):
        raise RuntimeError("docker not found on PATH. Install Docker to use the sandbox runner.")

def _ensure_executable_and_mode(path: str):
    if not os.path.exists(path):
        raise FileNotFoundError(f"binary not found: {path}")
    st = os.stat(path)
    mode = stat.S_IMODE(st.st_mode)
    if mode != 0o755:
        raise PermissionError(f"binary permissions must be 0755 (found {oct(mode)}): {path}")
    if not stat.S_ISREG(st.st_mode):
        raise PermissionError(f"binary is not a regular file: {path}")

def _reject_writable_mounts(mounts: List[str]):
    for m in mounts:
        parts = m.split(":")
        host = parts[0]
        mode = parts[2] if len(parts) >= 3 else None
        if mode and mode != "ro":
            raise PermissionError(f"Writable mount mode not allowed: {m}")
        if not mode:
            raise PermissionError(f"Mount mode must be explicit and read-only (add ':ro'): {m}")
        if not os.path.exists(host):
            raise FileNotFoundError(f"Mount host path does not exist: {host}")
        st = os.stat(host)
        if st.st_mode & stat.S_IWUSR or st.st_mode & stat.S_IWGRP or st.st_mode & stat.S_IWOTH:
            raise PermissionError(f"Host mount path must not be writable: {host}")

def run_miner_in_docker(
    binary_path: str,
    binary_args: List[str],
    sig_path: Optional[str] = None,
    pubkey_path: Optional[str] = None,
    image: str = DEFAULT_IMAGE,
    cpu_quota: float = 0.5,
    memory_mb: int = 512,
    pids_limit: int = 200,
    container_name: Optional[str] = None,
    seccomp_path: Optional[str] = None,
    seccomp_sig_path: Optional[str] = None,
    apparmor_profile: Optional[str] = None,
    extra_mounts: Optional[List[str]] = None,
) -> subprocess.Popen:
    _ensure_docker_available()
    _ensure_executable_and_mode(binary_path)

    if sig_path:
        LOG.info("Verifying binary with provided signature...")
        ok = gpg_verify(sig_path, binary_path, pubkey_path)
        if not ok:
            raise RuntimeError("GPG verification failed. Refusing to run unverified binary.")
        LOG.info("GPG verification succeeded.")
    else:
        raise RuntimeError("Signature required: provide sig_path to verify binary before running.")

    name = container_name or f"miner-{os.getpid()}"
    memory_arg = f"{memory_mb}m"
    cpus_arg = str(cpu_quota)

    mounts = [
        f"{os.path.abspath(binary_path)}:/opt/miner:ro",
        "/etc/ssl/certs:/etc/ssl/certs:ro",
    ]
    if extra_mounts:
        mounts += extra_mounts

    _reject_writable_mounts(mounts)

    docker_cmd = [
        "docker", "run", "--rm",
        "--name", name,
        "--cap-drop=ALL",
        "--security-opt", "no-new-privileges",
        "--read-only",
        "--pids-limit", str(pids_limit),
        "--memory", memory_arg,
        "--cpus", cpus_arg,
        "--tmpfs", "/tmp:rw,size=100m",
    ]

    if seccomp_path:
        if not os.path.exists(seccomp_path):
            raise FileNotFoundError(f"seccomp profile not found: {seccomp_path}")
        # if signature provided, verify seccomp profile before using
        if seccomp_sig_path:
            if not os.path.exists(seccomp_sig_path):
                raise FileNotFoundError(f"seccomp signature not found: {seccomp_sig_path}")
            # verify signature of seccomp file
            ok = gpg_verify(seccomp_sig_path, seccomp_path, pubkey_path)
            if not ok:
                raise RuntimeError("Seccomp profile signature verification failed")
        docker_cmd += ["--security-opt", f"seccomp={seccomp_path}"]

    # AppArmor support (profile name). Ensure host has the profile installed under /etc/apparmor.d/
    if apparmor_profile:
        profile_path = f"/etc/apparmor.d/{apparmor_profile}"
        if not os.path.exists(profile_path):
            raise FileNotFoundError(f"AppArmor profile not found on host: {profile_path}")
        docker_cmd += ["--security-opt", f"apparmor={apparmor_profile}"]

    for m in mounts:
        docker_cmd += ["-v", m]

    docker_cmd += ["--user", "65534:65534"]

    docker_cmd += [image, "/opt/miner"] + binary_args

    LOG.info("Running hardened container: %s", " ".join(docker_cmd))
    proc = subprocess.Popen(docker_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return proc
