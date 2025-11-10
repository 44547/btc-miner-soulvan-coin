#!/usr/bin/env python3
"""
Simple CLI for common tasks:
- run-agent         : start the FastAPI agent (uvicorn)
- update-check      : open release page if newer release exists
- update-download   : download & verify a release asset (does not install)
"""
import argparse
import asyncio
import os
import sys
import subprocess

from updater import check_and_show_release
from updater_safe import download_and_verify_release_asset

def run_agent():
    subprocess.run([sys.executable, "src/agent.py"])

async def do_update_check(owner: str, repo: str):
    version_path = os.path.join(os.path.dirname(__file__), "..", "VERSION")
    version = "0.0.0"
    try:
        with open(version_path, "r") as vf:
            version = vf.read().strip()
    except Exception:
        pass
    changed = await check_and_show_release(owner, repo, version)
    if changed:
        print("Update available. Opened release page in host browser.")
    else:
        print("No update detected or check failed.")

async def do_update_download(owner: str, repo: str, asset_contains: str, pubkey: str = None):
    path = await download_and_verify_release_asset(owner, repo, asset_contains, pubkey_path=pubkey)
    if path:
        print("Verified asset downloaded to:", path)
    else:
        print("No verified asset downloaded; opened release page for manual review (if available).")

def main():
    p = argparse.ArgumentParser(prog="agent-cli")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("run-agent", help="Run the FastAPI agent (foreground)")

    ccheck = sub.add_parser("update-check", help="Check repo releases and open browser if newer")
    ccheck.add_argument("owner")
    ccheck.add_argument("repo")

    cdl = sub.add_parser("update-download", help="Download + verify a release asset (no auto-install)")
    cdl.add_argument("owner")
    cdl.add_argument("repo")
    cdl.add_argument("asset_contains", help="substring to match asset name (e.g. linux-amd64)")
    cdl.add_argument("--pubkey", help="optional path to GPG public key to import for verification", default=None)

    cinst = sub.add_parser("update-install", help="Download + verify + install a release asset (atomic)")
    cinst.add_argument("owner")
    cinst.add_argument("repo")
    cinst.add_argument("asset_contains")
    cinst.add_argument("install_path", help="destination path for the installed binary")
    cinst.add_argument("--pubkey", help="optional path to GPG public key to import for verification", default=None)

    args = p.parse_args()

    if args.cmd == "run-agent":
        run_agent()
        return

    if args.cmd == "update-check":
        asyncio.run(do_update_check(args.owner, args.repo))
        return

    if args.cmd == "update-download":
        asyncio.run(do_update_download(args.owner, args.repo, args.asset_contains, pubkey=args.pubkey))
        return

    if args.cmd == "update-install":
        # perform download+verify and atomic install
        # This CLI performs a local download+verify and then asks to install locally.
        path = asyncio.run(download_and_verify_release_asset(args.owner, args.repo, args.asset_contains, pubkey_path=args.pubkey))
        if not path:
            print("No verified asset downloaded; release page opened for manual review (if available).")
            return
        # ask for confirmation
        resp = input(f"Install {path} -> {args.install_path}? [y/N]: ").strip().lower()
        if resp != "y":
            print("Install aborted by user.")
            return
        # import installer lazily
        from installer import atomic_install
        try:
            final = atomic_install(path, args.install_path)
            print("Installed to:", final)
        except Exception as e:
            print("Install failed:", e)
        return

    if args.cmd == "confirm-install":
        # Confirm a pending install token on a running agent (HTTP POST)
        import urllib.parse, urllib.request
        token = args.token
        url = f"http://localhost:8000/update/confirm_install?token={urllib.parse.quote(token)}"
        try:
            req = urllib.request.Request(url, method="POST")
            with urllib.request.urlopen(req, timeout=10) as resp:
                print(resp.read().decode())
        except Exception as e:
            print("Confirm install failed:", e)
        return

if __name__ == "__main__":
    main()
