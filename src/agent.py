import asyncio
import subprocess
import os
import re
import logging
from typing import Optional, Dict
from fastapi import FastAPI, HTTPException
import psutil

from .backends import bitcoin, soulvan
from .updater import check_and_show_release
from .updater_safe import download_and_verify_release_asset
from .installer import atomic_install, validate_installed
from .hw_monitor import system_metrics
from . import notifications
import secrets

LOG = logging.getLogger("miner-agent")
logging.basicConfig(level=logging.INFO)

# Basic configuration - edit per your binaries/pools
CONFIG = {
    # Replace the placeholder paths below with your trusted miner binaries, signatures and pubkeys
    "bitcoin": {
        "binary": "/path/to/bitcoin-miner",
        "signature": "/path/to/bitcoin-miner.sig",
        "pool": "stratum+tcp://pool:3333",
        "user": "your_btc_wallet",
        "extra": ""
    },
    "soulvan": {
        "binary": "/path/to/soulvan-miner",
        "signature": "/path/to/soulvan-miner.sig",
        "pool": "stratum+tcp://soulvan-pool:4444",
        "user": "your_soulvan_wallet",
        "extra": ""
    },
    "policy": {
        "prefer": ["soulvan", "bitcoin"]
    },
    "secure": {
        "use_docker": True,
        # Path to the public key used to verify binaries and seccomp signatures
        "pubkey_path": "/path/to/miner_pubkey.asc",
        "image": "debian:bookworm-slim",
        "cpus": 0.5,
        "memory_mb": 512,
        "pids_limit": 200,
        # Optional seccomp profile and its signature (verify before use)
        "seccomp_path": "/path/to/seccomp.json",
        "seccomp_sig_path": "/path/to/seccomp.json.sig",
        # Optional AppArmor profile name (must be installed on host under /etc/apparmor.d/)
        "apparmor_profile": None,
        "extra_mounts": [
            "/etc/ssl/certs:/etc/ssl/certs:ro"
        ],
        # Auto-replace behavior: if True, after successful verification attempt install
        # If require_admin_confirmation is True, installation will create a pending token which must be confirmed
        "auto_replace": False,
        "require_admin_confirmation": True
    },
    # Notifications: webhook_url (or slack_webhook) and smtp settings
    "notifications": {
        "auto_send": False,
        "webhook_url": None,
        "smtp": {"enabled": False}
    }
}

APP = FastAPI()
CURRENT_PROC: Optional[subprocess.Popen] = None
LAST_HASH: Dict[str, float] = {"bitcoin": 0.0, "soulvan": 0.0}

HASH_RE = re.compile(r"([\d\.]+)\s*(H/s|KH/s|MH/s|GH/s|TH/s)", re.IGNORECASE)
MULT = {"h/s":1, "kh/s":1e3, "mh/s":1e6, "gh/s":1e9, "th/s":1e12}

def parse_hash_rate(line: str) -> Optional[float]:
    m = HASH_RE.search(line)
    if not m:
        return None
    val = float(m.group(1))
    unit = m.group(2).lower()
    for k in MULT:
        if k in unit:
            return val * MULT[k]
    return val

async def monitor_process(proc: subprocess.Popen, kind: str):
    LOG.info("Monitoring process for %s (pid=%s)", kind, getattr(proc, "pid", None))
    loop = asyncio.get_running_loop()
    while proc.poll() is None:
        line = await loop.run_in_executor(None, proc.stdout.readline)
        if not line:
            await asyncio.sleep(0.2)
            continue
        try:
            text = line.decode(errors="ignore").strip()
        except Exception:
            text = str(line)
        h = parse_hash_rate(text)
        if h:
            LAST_HASH[kind] = h
            LOG.info("%s hash rate: %.3f H/s", kind, h)
    LOG.info("Process %s ended", kind)

async def start_miner(kind: str) -> Optional[subprocess.Popen]:
    global CURRENT_PROC
    if CURRENT_PROC and CURRENT_PROC.poll() is None:
        LOG.warning("A miner is already running. Stop it first.")
        return None

    gen = bitcoin.generate_command if kind == "bitcoin" else soulvan.generate_command
    cmd_list = gen(CONFIG[kind])

    secure_cfg = CONFIG.get("secure", {})
    use_docker = secure_cfg.get("use_docker", False)

    if use_docker:
        from sandbox import run_miner_in_docker

        bin_path = CONFIG[kind].get("binary")
        sig_path = CONFIG[kind].get("signature")
        pubkey = secure_cfg.get("pubkey_path")

        if not bin_path or not sig_path:
            LOG.error("Secure docker mode requires 'binary' and 'signature' fields in CONFIG for %s", kind)
            return None

        binary = cmd_list[0]
        args = cmd_list[1:]

        try:
            proc = run_miner_in_docker(
                binary_path=binary,
                binary_args=args,
                sig_path=sig_path,
                pubkey_path=pubkey,
                image=secure_cfg.get("image"),
                cpu_quota=secure_cfg.get("cpus", 0.5),
                memory_mb=secure_cfg.get("memory_mb", 512),
                pids_limit=secure_cfg.get("pids_limit", 200),
                seccomp_path=secure_cfg.get("seccomp_path"),
                extra_mounts=secure_cfg.get("extra_mounts"),
                container_name=f"miner-{kind}"
            )
        except Exception as e:
            LOG.exception("Failed to start secure container: %s", e)
            return None

        CURRENT_PROC = proc
        asyncio.create_task(monitor_process(proc, kind))
        return proc

    cmd = cmd_list
    LOG.info("Starting %s miner with: %s", kind, " ".join(cmd))
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    CURRENT_PROC = proc
    asyncio.create_task(monitor_process(proc, kind))
    return proc

async def stop_miner():
    global CURRENT_PROC
    if not CURRENT_PROC:
        return
    try:
        LOG.info("Stopping miner pid=%s", CURRENT_PROC.pid)
        CURRENT_PROC.terminate()
        await asyncio.get_running_loop().run_in_executor(None, CURRENT_PROC.wait, 10)
    except Exception:
        try:
            CURRENT_PROC.kill()
        except Exception:
            pass
    CURRENT_PROC = None

def system_score() -> float:
    mem = psutil.virtual_memory()
    cpu = psutil.cpu_percent(interval=0.1)
    score = (mem.available / (1024*1024)) - (cpu * 10)
    return score

async def decide_and_run():
    pref = CONFIG["policy"]["prefer"]
    scores = {k: LAST_HASH.get(k, 0.0) for k in pref}
    chosen = max(scores, key=lambda k: scores[k] or 0.0)
    if scores[chosen] == 0.0:
        chosen = pref[0]
    await start_miner(chosen)

@APP.on_event("startup")
async def startup_event():
    version_path = os.path.join(os.path.dirname(__file__), "..", "VERSION")
    version = "0.0.0"
    try:
        with open(version_path, "r") as vf:
            version = vf.read().strip()
    except Exception:
        LOG.info("VERSION file not found; using default.")
    try:
        asyncio.create_task(check_and_show_release("example-owner", "example-miner-repo", version))
    except Exception as e:
        LOG.info("Update check failed: %s", e)
    asyncio.create_task(policy_loop())

async def policy_loop():
    while True:
        try:
            if not CURRENT_PROC or (CURRENT_PROC and CURRENT_PROC.poll() is not None):
                await decide_and_run()
        except Exception as e:
            LOG.exception("Policy loop error: %s", e)
        await asyncio.sleep(10)

@APP.post("/start/{kind}")
async def api_start(kind: str):
    if kind not in CONFIG:
        raise HTTPException(status_code=400, detail="unknown kind")
    proc = await start_miner(kind)
    return {"ok": proc is not None, "pid": getattr(proc, "pid", None)}

@APP.post("/stop")
async def api_stop():
    await stop_miner()
    return {"ok": True}

@APP.get("/status")
async def api_status():
    pid = getattr(CURRENT_PROC, "pid", None)
    return {"running_pid": pid, "last_hash": LAST_HASH, "system_score": system_score()}

@APP.get("/metrics")
async def api_metrics():
    try:
        metrics = system_metrics()
        return {"ok": True, "metrics": metrics}
    except Exception as e:
        LOG.exception("Failed to gather metrics: %s", e)
        raise HTTPException(status_code=500, detail="metrics error")


@APP.get("/alerts")
async def api_alerts(cpu_threshold: Optional[int] = 95, temp_threshold: Optional[int] = 85):
    try:
        metrics = system_metrics()
        thresholds = {"cpu_percent": cpu_threshold, "temperature_c": temp_threshold}
        from .hw_monitor import check_thresholds
        alerts = check_thresholds(metrics, thresholds)
        # auto-send notifications if configured
        if alerts and CONFIG.get("notifications", {}).get("auto_send"):
            ncfg = CONFIG.get("notifications", {})
            res = notifications.notify_alerts(alerts, ncfg)
            return {"ok": True, "alerts": alerts, "notified": res}
        return {"ok": True, "alerts": alerts}
    except Exception as e:
        LOG.exception("Failed to gather alerts: %s", e)
        raise HTTPException(status_code=500, detail="alerts error")

@APP.post("/update/check")
async def api_update_check(owner: str, repo: str):
    version_path = os.path.join(os.path.dirname(__file__), "..", "VERSION")
    version = "0.0.0"
    try:
        with open(version_path, "r") as vf:
            version = vf.read().strip()
    except Exception:
        pass
    try:
        changed = await check_and_show_release(owner, repo, version)
        return {"ok": True, "update_available": changed}
    except Exception as e:
        LOG.exception("update check failed: %s", e)
        raise HTTPException(status_code=500, detail="update check failed")

@APP.post("/update/download")
async def api_update_download(owner: str, repo: str, asset_contains: str, pubkey_path: Optional[str] = None):
    try:
        path = await download_and_verify_release_asset(owner, repo, asset_contains, pubkey_path=pubkey_path)
        if path:
            return {"ok": True, "downloaded_path": path}
        return {"ok": False, "message": "no verified asset downloaded; release page opened for manual review"}
    except Exception as e:
        LOG.exception("download failed: %s", e)
        raise HTTPException(status_code=500, detail="download failed")


@APP.post("/update/install")
async def api_update_install(owner: str, repo: str, asset_contains: str, install_path: str, pubkey_path: Optional[str] = None):
    """
    Downloads and verifies a release asset, then atomically installs it to `install_path`.
    This endpoint does NOT auto-execute the installed binary. It requires explicit install_path.
    """
    try:
        path = await download_and_verify_release_asset(owner, repo, asset_contains, pubkey_path=pubkey_path)
        if not path:
            return {"ok": False, "message": "no verified asset downloaded; release page opened for manual review"}
        # If auto_replace in config is enabled, perform install or create pending token depending on confirmation flag
        secure_cfg = CONFIG.get("secure", {})
        auto_replace = secure_cfg.get("auto_replace", False)
        require_confirm = secure_cfg.get("require_admin_confirmation", True)

        if not auto_replace:
            return {"ok": False, "message": "auto_replace disabled in configuration; manual install required"}

        # If admin confirmation required, create a pending install token and return it
        if require_confirm:
            token = secrets.token_urlsafe(16)
            PENDING_INSTALLS[token] = {
                "owner": owner,
                "repo": repo,
                "asset_contains": asset_contains,
                "downloaded_path": path,
                "install_path": install_path
            }
            return {"ok": True, "pending": True, "token": token, "message": "Confirm install with /update/confirm_install?token=<token>"}

        # else perform install immediately
        final = atomic_install(path, install_path)
        ok = validate_installed(final)
        return {"ok": ok, "installed_path": final}
    except Exception as e:
        LOG.exception("install failed: %s", e)
        raise HTTPException(status_code=500, detail=f"install failed: {e}")

def run_api():
    import uvicorn
    uvicorn.run("src.agent:APP", host="0.0.0.0", port=8000, reload=False)


# In-memory store for pending installs (token -> info)
PENDING_INSTALLS: Dict[str, Dict] = {}


@APP.post("/update/confirm_install")
async def api_confirm_install(token: str):
    info = PENDING_INSTALLS.get(token)
    if not info:
        raise HTTPException(status_code=404, detail="pending token not found")
    try:
        final = atomic_install(info["downloaded_path"], info["install_path"])
        ok = validate_installed(final)
        # remove pending
        del PENDING_INSTALLS[token]
        return {"ok": ok, "installed_path": final}
    except Exception as e:
        LOG.exception("confirm install failed: %s", e)
        raise HTTPException(status_code=500, detail=f"confirm install failed: {e}")

if __name__ == "__main__":
    run_api()
