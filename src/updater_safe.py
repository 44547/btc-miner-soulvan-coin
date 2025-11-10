import aiohttp
import asyncio
import os
import hashlib
import subprocess
import tempfile
from typing import Optional

GITHUB_API = "https://api.github.com/repos/{owner}/{repo}/releases/latest"

async def latest_release(owner: str, repo: str) -> Optional[dict]:
    url = GITHUB_API.format(owner=owner, repo=repo)
    async with aiohttp.ClientSession() as s:
        async with s.get(url, headers={"Accept": "application/vnd.github+json"}) as r:
            if r.status == 200:
                return await r.json()
            return None

async def download_url(url: str, dest_path: str):
    async with aiohttp.ClientSession() as s:
        async with s.get(url) as r:
            r.raise_for_status()
            with open(dest_path, "wb") as f:
                async for chunk in r.content.iter_chunked(1 << 20):
                    f.write(chunk)

def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def gpg_verify(sig_path: str, data_path: str, pubkey_path: Optional[str] = None) -> bool:
    try:
        if pubkey_path:
            subprocess.run(["gpg", "--import", pubkey_path], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        res = subprocess.run(["gpg", "--verify", sig_path, data_path], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return res.returncode == 0
    except Exception:
        return False

def open_in_host_browser(url: str):
    try:
        os.system(f'"$BROWSER" "{url}" &')
    except Exception:
        import webbrowser
        webbrowser.open(url)

async def download_and_verify_release_asset(owner: str, repo: str, asset_name_contains: str,
                                            pubkey_path: Optional[str] = None) -> Optional[str]:
    info = await latest_release(owner, repo)
    if not info:
        return None
    assets = info.get("assets", [])
    chosen = None
    sig_asset = None
    for a in assets:
        name = a.get("name", "")
        if asset_name_contains in name and chosen is None:
            chosen = a
        if name.endswith(".asc") or name.endswith(".sig"):
            if chosen and name.startswith(os.path.splitext(chosen.get("name", ""))[0]):
                sig_asset = a
    if not chosen:
        return None
    tmpdir = tempfile.mkdtemp(prefix="updater-")
    data_path = os.path.join(tmpdir, chosen["name"])
    await download_url(chosen["browser_download_url"], data_path)

    if sig_asset:
        sig_path = os.path.join(tmpdir, sig_asset["name"])
        await download_url(sig_asset["browser_download_url"], sig_path)
        ok = gpg_verify(sig_path, data_path, pubkey_path)
        if ok:
            return data_path
        else:
            open_in_host_browser(info.get("html_url", ""))
            return None

    h = sha256_of(data_path)
    print("Downloaded:", data_path)
    print("SHA256:", h)
    open_in_host_browser(info.get("html_url", ""))
    return None
