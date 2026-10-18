"""NetherLink WhiteList builder.

Собирает конфиги для обхода белых списков РФ из публичных подборок
(igareck/vpn-configs-for-russia, whoahaow/rjsxrd, zieng2/wl), проверяет
TCP + протокол через sing-box и пишет файлы для ветки `whitelist`:
  NetherLink-WhiteList.txt   — все живые (универсальный импорт)
  NetherLink-WhiteList.yaml  — Clash-конфиг (FLClash), валиден для mihomo
  whitelist-meta.json        — статистика прогона

Run: python -m backend.whitelist_headless
Env:
  WHITELIST_MAX_PROTO  — cap на число protocol-проверок (default 1500)
  WHITELIST_EXTRA_DIRS — ':'-separated dirs: локальный поиск файлов источника
                         по basename (для тестов без сети)
"""
import asyncio
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from urllib.request import Request, urlopen

from backend.checker import protocol_check, tcp_check
from backend.generator import generate_config_clash
from backend.parser import parse_uri, try_decode_b64_subscription
from backend.verify import verify_nodes, find_mihomo

IGA = "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/"
RJS = "https://raw.githubusercontent.com/whoahaow/rjsxrd/refs/heads/main/githubmirror/bypass/"
ZIENG = "https://raw.githubusercontent.com/zieng2/wl/main/vless_universal.txt"
WLL = "https://raw.githubusercontent.com/wlunlocker/vpn-configs/main/"

SOURCES = [
    IGA + "Vless-Reality-White-Lists-Rus-Mobile.txt",
    IGA + "WHITE-SNI-RU-all.txt",
    IGA + "WHITE-CIDR-RU-checked.txt",
    IGA + "WHITE-CIDR-RU-all.txt",
    ZIENG,
    WLL + "whitelist_all.txt",
    WLL + "white_sni_ru.txt",
] + [RJS + f"bypass-{i}.txt" for i in range(1, 10)] + [RJS + "bypass-all.txt"]

URI_RE = re.compile(r"\b((?:vless|vmess|trojan|ss|hysteria2|hy2)://[^\s\"'<>]+)")


def fetch(url):
    base = url.rstrip("/").split("/")[-1]
    for d in (os.environ.get("WHITELIST_EXTRA_DIRS") or "").split(":"):
        if d:
            p = os.path.join(d, base)
            if os.path.exists(p):
                return open(p, encoding="utf-8", errors="replace").read()
    req = Request(url, headers={"User-Agent": "NetherLink-WhiteList/1.0"})
    with urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", errors="replace")


def parse_source(text, source):
    nodes = []
    for m in URI_RE.finditer(text):
        n = parse_uri(m.group(1).strip().rstrip(",;)]}"), "ZZ", source)
        if n:
            nodes.append(n)
    if not nodes:
        decoded = try_decode_b64_subscription(text)
        if decoded:
            for m in URI_RE.finditer(decoded):
                n = parse_uri(m.group(1).strip().rstrip(",;)]}"), "ZZ", source)
                if n:
                    nodes.append(n)
    return nodes


def priority(node):
    """reality → vless → hysteria2 → остальные."""
    if node.get("pbk"):
        return 0
    if node.get("protocol") == "vless":
        return 1
    if node.get("protocol") == "hysteria2":
        return 2
    return 3


async def run():
    nodes = []
    for src in SOURCES:
        try:
            text = fetch(src)
        except Exception as exc:  # noqa: BLE001
            print(f"[src] SKIP {src}: {exc}", flush=True)
            continue
        found = parse_source(text, src)
        nodes += found
        print(f"[src] {src.split('/')[-1]:42s} +{len(found):5d}  (накоплено {len(nodes)})", flush=True)

    uniq = {}
    for n in nodes:
        uniq.setdefault(n["raw"], n)
    nodes = list(uniq.values())
    print(f"[parse] уникальных конфигов: {len(nodes)}", flush=True)

    # ── TCP ──
    hosts = sorted({(n["server"], int(n["port"])) for n in nodes})
    sem = asyncio.Semaphore(120)
    t0 = time.time()

    async def tcp_one(hp):
        async with sem:
            lat = await tcp_check({"server": hp[0], "port": hp[1]}, 3.0)
        return hp, lat

    res = await asyncio.gather(*(tcp_one(hp) for hp in hosts))
    live = {f"{h}:{p}" for (h, p), lat in res if lat is not None}
    print(f"[tcp] живых host:port {len(live)}/{len(hosts)} ({time.time() - t0:.0f}s)", flush=True)

    # ── protocol check ──
    cand = [n for n in nodes if f"{n['server']}:{n['port']}" in live]
    cand.sort(key=priority)
    cap = int(os.environ.get("WHITELIST_MAX_PROTO", "2000"))
    cand = cand[:cap]
    strict = find_mihomo() is not None and os.environ.get("STRICT_VERIFY", "1") != "0"
    live_nodes = []

    if strict:
        # Строгая проверка ядром клиента (mihomo): HTTPS-проба + закачка >=200 КБ.
        # Белые списки РФ режут «зависшие» TCP-сессии после ~16-20 КБ — проба одним
        # generate_204 такие ноды пропускает, закачка 200 КБ — нет.
        print(f"[verify] строгая проверка {len(cand)} (cap {cap})", flush=True)

        async def emit(ev, d):
            if ev == "log":
                print("   ", d.get("text"), flush=True)

        passed, checked = await verify_nodes(
            cand, None, conc=300, batch_size=450,
            deadline=time.monotonic() + float(os.environ.get("WHITELIST_VERIFY_BUDGET", "1500")),
            emit=emit)
        print(f"[verify] живых: {len(passed)}/{len(checked)}", flush=True)
        for n in passed:
            m = dict(n)
            live_nodes.append(m)
    else:
        print(f"[proto] проверяю {len(cand)} (cap {cap}) — sing-box, прежний режим", flush=True)
        sem = asyncio.Semaphore(15)
        cancel = asyncio.Event()
        done = 0

        async def proto_one(n):
            nonlocal done
            async with sem:
                lat = await protocol_check(n, 8.0, cancel)
            done += 1
            if done % 100 == 0:
                print(f"[proto] {done}/{len(cand)} ({time.time() - t0:.0f}s)", flush=True)
            return n, lat

        for n, lat in await asyncio.gather(*(proto_one(n) for n in cand)):
            if lat is not None:
                m = dict(n)
                m["latency_ms"] = lat
                live_nodes.append(m)
        print(f"[proto] живых: {len(live_nodes)}/{len(cand)}", flush=True)

    best = {}
    for n in live_nodes:
        key = (n["server"], n["port"])
        if key not in best or n["latency_ms"] < best[key]["latency_ms"]:
            best[key] = n
    final = sorted(best.values(), key=lambda n: n["latency_ms"])
    if len(final) < 10:
        print(f"[fatal] слишком мало живых ({len(final)}), не публикую", flush=True)
        sys.exit(1)

    # Геолокация для человекочитаемых имён: генератор назовёт ноды
    # «🇩🇪 Германия 123ms» (по country + latency_ms), как в основной подписке.
    from backend.services import geoip_batch

    geo_cancel = asyncio.Event()
    try:
        geo = await geoip_batch([n["server"] for n in final], geo_cancel)
    except Exception as exc:  # noqa: BLE001
        print(f"[geo] fail: {exc}", flush=True)
        geo = {}
    for n in final:
        info = geo.get(n["server"]) or {}
        # страна ВЫХОДА (CF trace из проверки) точнее GeoIP по IP сервера; GeoIP — запасной путь
        n["country"] = (n.get("exit_loc") or info.get("country") or "ZZ").upper()

    open("NetherLink-WhiteList.txt", "w").write("\n".join(n["raw"] for n in final) + "\n")
    open("NetherLink-WhiteList.yaml", "w").write(generate_config_clash([dict(n) for n in final]))

    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": [s.split("/")[-1] for s in SOURCES],
        "parsed": len(nodes),
        "tcp_alive": len(live),
        "proto_checked": len(cand),
        "live_configs": len(live_nodes),
        "unique_servers": len(final),
        "protocols": dict(Counter(n["protocol"] for n in final)),
        "reality": sum(1 for n in final if n.get("pbk")),
        "verifier": "mihomo: HTTPS-проба + закачка ≥200 КБ" if strict else "sing-box: generate_204",
        "services": {"telegram": sum(1 for n in final if "tg" in (n.get("svc") or [])),
                     "youtube": sum(1 for n in final if "yt" in (n.get("svc") or [])),
                     "ai": sum(1 for n in final if "ai" in (n.get("svc") or []))},
    }
    json.dump(meta, open("whitelist-meta.json", "w"), ensure_ascii=False, indent=1)
    print(json.dumps(meta, ensure_ascii=False, indent=1), flush=True)
    print("[done]", flush=True)


if __name__ == "__main__":
    asyncio.run(run())
