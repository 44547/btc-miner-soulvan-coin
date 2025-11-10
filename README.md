# BTC Miner - Soulvan Coin Agent

This repository contains a secure mining agent prototype that can run trusted miner binaries inside a hardened Docker sandbox, monitor hardware metrics, and help safely check/download releases.

Key files:
- `src/agent.py` - FastAPI agent that manages miners and implements a small policy loop.
- `src/sandbox.py` - Hardened Docker runner that enforces 0755 on binaries, read-only mounts, seccomp, and GPG verification.
- `src/updater_safe.py` - Safe release downloader with optional GPG verification.
- `contrib/` - systemd service/slice and example seccomp profile.

Notes:
- You must supply miner binaries and signatures and place them under `bin/` and a public key under `keys/`.
- The secure sandbox refuses to run unverified binaries.
