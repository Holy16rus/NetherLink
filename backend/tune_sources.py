#!/usr/bin/env python3
"""Самонастройка источников: раз в неделю считает РЕАЛЬНУЮ отдачу каждого источника
строгой проверкой и пишет `source-overrides.json` (ветка stats).

Правило (по каждому источнику с достаточной выборкой):
  - живых ноль на >= MIN_SAMPLE проверенных          -> disable
  - ранее отключённый, но на выборке есть живые      -> enable
Источники, по которым выборка мала, не трогаем (мало данных — не приговор).
Список источников — sources.json (с учётом прежних overrides); Telegram-каналы здесь НЕ
настраиваются (их список ведётся вручную в sources.json). overrides только включают/выключают,
сам sources.json не переписывается (его правит человек).

Запуск: python -m backend.tune_sources
Env: TUNE_SAMPLE (нод на источник, по умолчанию 250), TUNE_MIN_SAMPLE (по умолчанию 60)
"""
import asyncio
import json
import os
import random
import sys
import time
from collections import Counter
from datetime import datetime, timezone

from backend.checker import tcp_check
from backend.config import ROOT, load_sources
from backend.pool import node_key
from backend.scraper import discover_repo_files, fetch_and_parse
from backend.verify import verify_nodes, find_mihomo

OVERRIDES = ROOT / "source-overrides.json"
SAMPLE = int(os.environ.get("TUNE_SAMPLE", "250"))
MIN_SAMPLE = int(os.environ.get("TUNE_MIN_SAMPLE", "60"))
VERIFY_CAP = 200   # TCP-живых на источник, уходящих в строгую проверку


def _all_sources(cfg: dict) -> list[tuple[str, bool]]:
    out = []
    for s in cfg.get("sources", []):
        if isinstance(s, dict):
            out.append((s["url"], bool(s.get("enabled", True))))
        else:
            out.append((s, True))
    return out


ENABLE_MIN_CHECKED = 20     # меньше проверенных — выборка слишком мала для включения
ENABLE_MIN_ALIVE = 5        # минимум живых в выборке (2-3 живых — шум, не сигнал)
ENABLE_MIN_RATE = 0.08      # и доля живых >= 8%: иначе источник только тормозит сбор
ENABLE_MIN_NEW = 3          # и >= 3 живых, которых нет ни в одном УЖЕ включённом источнике


def decide_overrides(srcs, checked, alive, alive_keys, min_sample):
    """-> (disable, enable, new_alive{url: int}).

    disable: включён, проверено >= min_sample, живых 0.
    enable:  выключен и стабильно отдаёт живых И даёт НОВЫХ — тех, кого нет в живых
             включённых источников (выборки независимы, один и тот же узел жив в
             нескольких агрегаторах; источник полезен только своим вкладом).
    """
    enabled_alive: set = set()
    for url, en in srcs:
        if en:
            enabled_alive |= alive_keys.get(url, set())
    disable, enable, new_alive = [], [], {}
    for url, en in srcs:
        c, a = checked.get(url, 0), alive.get(url, 0)
        new = len(alive_keys.get(url, set()) - enabled_alive)
        new_alive[url] = new
        if en and c >= min_sample and a == 0:
            disable.append(url)
        elif (not en) and c >= ENABLE_MIN_CHECKED and a >= ENABLE_MIN_ALIVE \
                and a / c >= ENABLE_MIN_RATE and new >= ENABLE_MIN_NEW:
            enable.append(url)
    return disable, enable, new_alive


async def _collect(src: str, cancel: asyncio.Event) -> list[dict]:
    try:
        files = await discover_repo_files(src, 40, cancel)
    except Exception:
        return []
    sem = asyncio.Semaphore(8)

    async def one(it):
        async with sem:
            return (await fetch_and_parse(it, cancel))[1]

    res = await asyncio.gather(*(one(f) for f in files))
    return [n for r in res for n in r]


async def main():
    if not find_mihomo():
        print("[tune] mihomo не найден — самонастройка невозможна", flush=True)
        sys.exit(1)
    cfg = load_sources()
    srcs = _all_sources(cfg)
    cancel = asyncio.Event()
    random.seed(int(time.time()) // 86400)
    t0 = time.time()

    # собираем по источнику (включая выключенные — вдруг ожили)
    sem = asyncio.Semaphore(6)

    async def c(url):
        async with sem:
            return url, await _collect(url, cancel)

    got = await asyncio.gather(*(c(u) for u, _ in srcs))
    per: dict[str, dict] = {}
    seen = set()   # независимая выборка: дубликаты между источниками НЕ вычитаем из "чужих" выборок
    for url, nodes in got:
        uniq, local = [], set()
        for n in nodes:
            p = (n.get("protocol") or "").lower()
            if p == "socks4":
                continue
            k = (p, str(n["server"]).lower(), int(n["port"]), n.get("uuid") or n.get("password") or n.get("username") or "")
            if k in local:
                continue
            local.add(k)
            n["_src"] = url
            uniq.append(n)
        random.shuffle(uniq)
        per[url] = {"parsed": len(nodes), "nodes": uniq[:SAMPLE]}
    print(f"[tune] собрано {len(srcs)} источников за {time.time() - t0:.0f}с", flush=True)

    # TCP-экран
    tsem = asyncio.Semaphore(300)

    async def tc(n):
        async with tsem:
            n["_tcp"] = await tcp_check({"server": n["server"], "port": int(n["port"])}, 3.0)

    await asyncio.gather(*(tc(n) for d in per.values() for n in d["nodes"]))
    batch, tcp_rate = [], {}
    for url, d in per.items():
        alive = [n for n in d["nodes"] if n["_tcp"] is not None]
        tcp_rate[url] = len(alive) / max(1, len(d["nodes"]))
        batch.extend(alive[:VERIFY_CAP])
    random.shuffle(batch)
    print(f"[tune] к строгой проверке: {len(batch)} нод", flush=True)

    async def emit(ev, d):
        if ev == "log":
            print("  ", d.get("text"), flush=True)

    passed, checked = await verify_nodes(batch, cancel, conc=300, batch_size=450, emit=emit)
    ok = Counter(n["_src"] for n in passed)
    ch = Counter(n["_src"] for n in checked)
    alive_keys: dict[str, set] = {}
    for n in passed:
        alive_keys.setdefault(n["_src"], set()).add(node_key(n))

    disable, enable, new_alive = decide_overrides(srcs, ch, ok, alive_keys, MIN_SAMPLE)
    report = []
    for url, enabled in srcs:
        checked_n, alive_n = ch[url], ok[url]
        report.append({"src": url, "enabled": enabled, "parsed": per[url]["parsed"],
                       "tcp": round(tcp_rate.get(url, 0), 3), "checked": checked_n, "alive": alive_n,
                       "new_alive": new_alive.get(url),
                       "strict": round(alive_n / checked_n, 4) if checked_n else None})

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sample": SAMPLE, "min_sample": MIN_SAMPLE,
        "disable": sorted(disable), "enable": sorted(enable), "report": report,
    }
    OVERRIDES.write_text(json.dumps(out, ensure_ascii=False, indent=1), "utf-8")
    print(f"[tune] отключить {len(disable)}, включить {len(enable)}; отчёт -> {OVERRIDES.name}", flush=True)
    for r in sorted(report, key=lambda r: -(r["alive"] or 0))[:15]:
        print(f"   alive {r['alive']:>3}/{r['checked']:<4} tcp {100*r['tcp']:3.0f}%  {r['src'][:80]}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
