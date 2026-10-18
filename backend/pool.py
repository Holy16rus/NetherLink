"""Резервный пул проверенных нод.

Зачем: полная генерация раз в несколько часов находит ~300 живых нод, а за час
часть из них умирает. Часовой recheck раньше лишь выбивал мёртвых — списки худели
до следующей генерации. Пул хранит ВСЕ когда-либо прошедшие строгую проверку ноды
(до MAX_POOL), recheck перепроверяет весь пул и собирает списки из тех, кто жив
прямо сейчас. Ноды «мигают» (то живы, то нет), поэтому объединение прогонов
даёт списки длиннее, чем один проход, — и без добивки мёртвыми.

Нода покидает пул после MAX_MISS подряд проваленных проверок (одна неудача — не приговор).
Файл pool.json живёт в ветке `stats` (в рабочем дереве игнорируется git'ом).
"""
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from backend.config import ROOT

POOL_FILE = ROOT / "pool.json"
MAX_POOL = 1500
MAX_MISS = 3

# служебные поля, которые не должны попадать в файл
_EPHEMERAL = {"name", "_ip", "_src", "_tcp", "tampered", "lat", "lon"}


def node_key(n: dict) -> tuple:
    return (
        str(n.get("protocol", "")).lower(),
        str(n.get("server", "")).lower(),
        int(n.get("port", 0) or 0),
        str(n.get("uuid") or n.get("password") or n.get("username") or "").lower(),
    )


def _clean(n: dict) -> dict:
    return {k: v for k, v in n.items() if k not in _EPHEMERAL}


def load_pool(path: Path | None = None) -> list[dict]:
    p = Path(path) if path else POOL_FILE
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text("utf-8"))
        nodes = data.get("nodes", []) if isinstance(data, dict) else data
        return [n for n in nodes if isinstance(n, dict) and n.get("server") and n.get("port")]
    except Exception:
        return []


def merge_pool(existing: list[dict], passed: list[dict], attempted: list[dict],
               max_size: int = MAX_POOL, max_miss: int = MAX_MISS) -> list[dict]:
    """Склеивает пул с результатом прогона.

    passed    — прошли проверку сейчас (miss=0, поля обновляются);
    attempted — реально участвовали в проверке (в т.ч. провалившиеся);
    остальные (не дошли до проверки из-за дедлайна) остаются как были.
    """
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    passed_map = {node_key(n): n for n in passed}
    attempted_keys = {node_key(n) for n in attempted}
    out: dict[tuple, dict] = {}

    for old in existing:
        k = node_key(old)
        if k in passed_map:
            continue  # обновим ниже свежим словарём
        if k in attempted_keys:
            miss = int(old.get("miss", 0)) + 1
            if miss >= max_miss:
                continue
            kept = _clean(old)
            kept["miss"] = miss
            out[k] = kept
        else:
            out[k] = _clean(old)

    prev = {node_key(o): o for o in existing}
    for k, n in passed_map.items():
        fresh = _clean(n)
        fresh["miss"] = 0
        fresh["seen_ok"] = now
        fresh["first_seen"] = (prev.get(k) or {}).get("first_seen") or now
        out[k] = fresh

    nodes = list(out.values())
    nodes.sort(key=lambda n: (int(n.get("miss", 0)), -(float(n.get("kbps") or 0)),
                              int(n.get("latency_ms") or 99999)))
    return nodes[:max_size]


def save_pool(nodes: list[dict], path: Path | None = None) -> Path:
    p = Path(path) if path else POOL_FILE
    payload = {
        "version": 1,
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(nodes),
        "nodes": nodes,
    }
    p.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), "utf-8")
    return p


def pool_candidates(path: Path | None = None) -> list[dict]:
    """Ноды пула как кандидаты на проверку (свежие словари, без служебных полей)."""
    return [_clean(n) | {"miss": int(n.get("miss", 0))} for n in load_pool(path)]
