import shlex
from typing import List, Dict

def generate_command(config: Dict) -> List[str]:
    """
    Return command line list for a Bitcoin miner.
    IMPORTANT: Replace the binary path in CONFIG with your trusted miner binary.
    """
    binary = config.get("binary", "/usr/local/bin/bitcoin-miner")
    pool = config.get("pool", "stratum+tcp://pool.example:3333")
    user = config.get("user", "wallet_address")
    extra = config.get("extra", "")
    cmd = f"{binary} -o {pool} -u {user} {extra}"
    return shlex.split(cmd)
