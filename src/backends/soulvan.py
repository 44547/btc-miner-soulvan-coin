import shlex
from typing import List, Dict

def generate_command(config: Dict) -> List[str]:
    """
    Return command line list for a Soulvan coin miner.
    IMPORTANT: Replace the binary path in CONFIG with your trusted miner binary.
    """
    binary = config.get("binary", "/usr/local/bin/soulvan-miner")
    pool = config.get("pool", "stratum+tcp://soulvan-pool.example:4444")
    user = config.get("user", "soulvan_wallet")
    extra = config.get("extra", "")
    cmd = f"{binary} --pool {pool} --user {user} {extra}"
    return shlex.split(cmd)
