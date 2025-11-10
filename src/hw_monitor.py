import subprocess
import shutil
import psutil
from typing import Dict, Optional

def get_nvidia_smi() -> Optional[Dict]:
    if not shutil.which("nvidia-smi"):
        return None
    cmd = ["nvidia-smi", "--query-gpu=index,name,memory.total,memory.used,utilization.gpu,temperature.gpu", "--format=csv,noheader,nounits"]
    try:
        out = subprocess.check_output(cmd, text=True).strip().splitlines()
        gpus = []
        for line in out:
            idx, name, mem_total, mem_used, util, temp = [x.strip() for x in line.split(",")]
            gpus.append({
                "index": int(idx),
                "name": name,
                "memory_total_mb": int(mem_total),
                "memory_used_mb": int(mem_used),
                "util_percent": int(util),
                "temperature_c": int(temp),
            })
        return {"gpus": gpus}
    except Exception:
        return None

def system_metrics() -> Dict:
    mem = psutil.virtual_memory()
    cpu = psutil.cpu_percent(interval=0.1)
    metrics = {
        "cpu_percent": cpu,
        "mem_total_mb": int(mem.total / (1024*1024)),
        "mem_available_mb": int(mem.available / (1024*1024)),
    }
    gpu = get_nvidia_smi()
    if gpu:
        metrics.update(gpu)
    return metrics

def check_thresholds(metrics: Dict, thresholds: Optional[Dict] = None) -> Dict:
    """
    Given metrics and optional thresholds, return a dict of alerts.
    thresholds example: {"cpu_percent": 90, "temperature_c": 85}
    """
    if thresholds is None:
        thresholds = {"cpu_percent": 95}
    alerts = {}
    for k, thr in thresholds.items():
        # nested keys like GPU temperature may require special handling
        if k in metrics:
            try:
                val = float(metrics[k])
                if val >= thr:
                    alerts[k] = {"value": val, "threshold": thr}
            except Exception:
                continue
        else:
            # try GPU nested fields
            if "gpus" in metrics and k == "temperature_c":
                for g in metrics["gpus"]:
                    if g.get("temperature_c", 0) >= thr:
                        alerts.setdefault(k, []).append({"gpu": g.get("index"), "value": g.get("temperature_c")})
    return alerts

