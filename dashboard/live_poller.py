"""Health endpoint polling utilities for the live dashboard."""
from __future__ import annotations

from typing import Dict, Optional

import requests


def poll_health(url: str = "http://localhost:5001/health", timeout: float = 1.5) -> Optional[Dict]:
    try:
        resp = requests.get(url, timeout=timeout)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


def check_nodes_up(ports: tuple = (5001, 5002, 5003)) -> bool:
    for port in ports:
        try:
            resp = requests.get(f"http://localhost:{port}/health", timeout=1.0)
            if resp.status_code != 200:
                return False
        except Exception:
            return False
    return True
