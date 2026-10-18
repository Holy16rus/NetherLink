"""status.json — честная шапка для README и бейджей.

Не обещаем «100% живых»: пишем, что именно и когда проверено, откуда проверяли
и какая доля кандидатов прошла. Читается shields.io (dynamic/json) прямо
с raw.githubusercontent.com из ветки `subscription`.
"""
import json
import statistics
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from backend.config import ROOT

STATUS_FILE = ROOT / "status.json"
VERIFIER = "mihomo: HTTPS-проба + закачка ≥200 КБ + сервисы + целостность"


def _is_tunnel(n: dict) -> bool:
    return str(n.get("protocol", "")).lower() not in ("http", "https", "socks5")


def _summ(nodes: list[dict]) -> dict:
    kb = [float(n["kbps"]) for n in nodes if n.get("kbps")]
    return {
        "count": len(nodes),
        "tunnels": sum(1 for n in nodes if _is_tunnel(n)),
        "http_socks": sum(1 for n in nodes if not _is_tunnel(n)),
        "reality": sum(1 for n in nodes if n.get("pbk")),
        "countries": len({n.get("country") for n in nodes if n.get("country") not in (None, "", "ZZ")}),
        "median_kbps": round(statistics.median(kb)) if kb else None,
    }


def build_status(*, kind: str, selected: list[dict], top_100: list[dict], top_50: list[dict],
                 checked: int, passed: int, pool_size: int | None = None,
                 tcp_live: int | None = None, candidates: int | None = None,
                 check_from: str = "GitHub Actions") -> dict:
    now = datetime.now(timezone.utc)
    svc = Counter(t for n in selected for t in (n.get("svc") or []))
    return {
        "updated_at": now.isoformat(timespec="seconds"),
        "updated_label": now.strftime("%d.%m %H:%M UTC"),
        "kind": kind,
        "verifier": VERIFIER,
        "check_from": check_from,
        "main": _summ(selected),
        "top100": _summ(top_100),
        "top50": _summ(top_50),
        "verify": {
            "checked": checked,
            "passed": passed,
            "pass_rate": round(100 * passed / checked, 1) if checked else None,
            "tcp_live": tcp_live,
            "candidates": candidates,
        },
        "pool": {"size": pool_size},
        "services": {"telegram": svc.get("tg", 0), "youtube": svc.get("yt", 0), "ai": svc.get("ai", 0)},
    }


def write_status(status: dict, path: Path | None = None) -> Path:
    p = Path(path) if path else STATUS_FILE
    p.write_text(json.dumps(status, ensure_ascii=False, indent=1), "utf-8")
    return p
