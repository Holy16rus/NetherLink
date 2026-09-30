"""
Recheck headless: только проверка без сбора.
Запускается часто (каждый час) в отдельном workflow.

1. Парсит NetherLink-Clash.yaml (500), NetherLink-100.yaml, NetherLink-50.yaml через yaml.safe_load
2. Извлекает первые 200 прокси из main, дедуплицирует с top-100/50
3. Проверяет все ноды (TCP + protocol check для туннельных)
4. Записывает только живые обратно в YAML/JSON
5. Обновляет proxy-history.json
"""
import asyncio
import sys
import time
import json
from pathlib import Path

import yaml

from backend.checker import check_node, protocol_check
from backend.generator import generate_config_clash, generate_config_v2ray, generate_config_singbox
from backend.services import geoip_batch
from backend.state import record_check_results, save_history, get_success_rate
from backend.quality import select_quality, describe as describe_selection

ROOT = Path(__file__).resolve().parent.parent

PROTOCOL_CHECK_CONCURRENCY = 10
TCP_CONCURRENCY = 50
MAX_RECHECK_NODES = 320
MAX_RECHECK_TOTAL = 500


def parse_clash_yaml_nodes(path: Path) -> list[dict]:
    """Извлекает прокси из Clash YAML через yaml.safe_load."""
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    proxies = config.get("proxies", [])
    nodes = []
    for p in proxies:
        node = {
            "protocol": str(p.get("type", "")).lower(),
            "server": str(p.get("server", "")),
            "port": int(p.get("port", 0)),
        }
        name = p.get("name", "")
        if name:
            node["name"] = str(name)
        username = p.get("username")
        if username is not None:
            node["username"] = str(username)
        password = p.get("password")
        if password is not None:
            node["password"] = str(password)
        uuid_val = p.get("uuid")
        if uuid_val is not None:
            node["uuid"] = str(uuid_val)
        servername = p.get("servername") or p.get("sni")
        if servername:
            node["servername"] = str(servername)
        cipher = p.get("cipher")
        if cipher:
            node["cipher"] = str(cipher)
        network = p.get("network", "tcp")
        if network and network != "tcp":
            node["network"] = str(network)
        tls_val = p.get("tls")
        if tls_val is not None:
            node["tls"] = bool(tls_val)
        flow = p.get("flow")
        if flow:
            node["flow"] = str(flow)
        alter_id = p.get("alterId", 0)
        if alter_id:
            node["alterId"] = int(alter_id)
        ws = p.get("ws-opts") or {}
        if isinstance(ws, dict):
            if ws.get("path"):
                node["ws_path"] = str(ws["path"])
            hdrs = ws.get("headers") or {}
            if isinstance(hdrs, dict):
                host = hdrs.get("Host") or hdrs.get("host")
                if host:
                    node["ws_host"] = str(host)
        xh = p.get("xhttp-opts") or {}
        if isinstance(xh, dict):
            if xh.get("path") and not node.get("ws_path"):
                node["ws_path"] = str(xh["path"])
            if xh.get("host") and not node.get("ws_host"):
                node["ws_host"] = str(xh["host"])
        grpc = p.get("grpc-opts") or {}
        if isinstance(grpc, dict) and grpc.get("grpc-service-name"):
            node["grpc_service_name"] = str(grpc["grpc-service-name"])
        ro = p.get("reality-opts") or {}
        if isinstance(ro, dict):
            if ro.get("public-key"):
                node["pbk"] = str(ro["public-key"])
            if ro.get("short-id") is not None:
                node["sid"] = str(ro["short-id"])
        fp = p.get("client-fingerprint")
        if fp:
            node["fp"] = str(fp)
        sni = p.get("sni")
        if sni and not node.get("servername"):
            node["servername"] = str(sni)
        nodes.append(node)
    return nodes


async def _emit(event: str, data: dict):
    if event == "log":
        level = data.get("level", "info")
        prefix = {"error": "[!]", "warn": "[~]"}.get(level, "   ")
        print(f"  {prefix} {data.get('text', '')}")
    elif event == "status":
        print(f"  [*] {data.get('message', '')}")


async def check_nodes(nodes: list[dict], timeout: int, cancel: asyncio.Event) -> list[dict]:
    sem = asyncio.Semaphore(TCP_CONCURRENCY)
    live = []

    async def check_one(node):
        if cancel.is_set():
            return None
        async with sem:
            return await check_node(node, timeout, cancel)

    print(f"  [*] TCP check: {len(nodes)} прокси, {TCP_CONCURRENCY} parallel")
    tasks = [asyncio.create_task(check_one(n)) for n in nodes]
    for coro in asyncio.as_completed(tasks):
        if cancel.is_set():
            for t in tasks:
                t.cancel()
            break
        result = await coro
        if result:
            live.append(result)

    print(f"  [+] TCP pass: {len(live)}/{len(nodes)}")

    if not live:
        return []

    tunnel = [n for n in live if n.get("protocol", "").lower() in ("vmess", "vless", "trojan", "ss", "hysteria2", "hy2")]
    non_tunnel = [n for n in live if n["protocol"].lower() in ("http", "https", "socks5")]

    if tunnel:
        protocol_sem = asyncio.Semaphore(PROTOCOL_CHECK_CONCURRENCY)
        protocol_live = []

        async def protocol_check_one(node):
            if cancel.is_set():
                return None
            async with protocol_sem:
                latency = await protocol_check(node, timeout, cancel)
                if latency is not None:
                    node["latency_ms"] = latency
                    return node
                return None

        print(f"  [*] Protocol check: {len(tunnel)} туннельных, {PROTOCOL_CHECK_CONCURRENCY} parallel")
        p_tasks = [asyncio.create_task(protocol_check_one(n)) for n in tunnel]
        for coro in asyncio.as_completed(p_tasks):
            if cancel.is_set():
                break
            result = await coro
            if result:
                protocol_live.append(result)

        print(f"  [+] Protocol pass: {len(protocol_live)}/{len(tunnel)}")
        live = non_tunnel + protocol_live

    return live


async def run():
    cancel = asyncio.Event()
    timeout = 8
    all_nodes: list[dict] = []
    seen = set()

    for config_name in ["NetherLink-Clash.yaml", "NetherLink-100.yaml", "NetherLink-50.yaml"]:
        fp = ROOT / config_name
        if fp.exists():
            nodes = parse_clash_yaml_nodes(fp)
            limit = MAX_RECHECK_NODES if "NetherLink-Clash.yaml" == config_name else None
            for n in nodes:
                key = (n["protocol"], n["server"], n["port"])
                if key not in seen:
                    seen.add(key)
                    all_nodes.append(n)
                if limit and len(all_nodes) >= limit:
                    break
            print(f"  [*] Parsed {len(nodes)} from {config_name}")

    # Подмешиваем свежие HTTP-прокси из web-источников —
    # иначе HTTP вымирают из конфигов и recheck их не возвращает.
    MAX_FRESH_HTTP = 100
    existing_http = sum(1 for n in all_nodes if n.get("protocol", "").lower() in ("http", "https", "socks5"))
    if existing_http < 30:
        print("  [*] HTTP мало в конфигах, добавляю свежие из web-источников...")
        try:
            from backend.web_sources import fetch_web_proxies
            fresh = await fetch_web_proxies(cancel)
            http_fresh = [n for n in fresh if n.get("protocol", "").lower() in ("http", "https")]
            added = 0
            for n in http_fresh:
                key = (n["protocol"], n["server"], n["port"])
                if key not in seen:
                    seen.add(key)
                    all_nodes.append(n)
                    added += 1
                    if added >= MAX_FRESH_HTTP:
                        break
            if added:
                print(f"  [+] Добавлено {added} свежих HTTP из web-источников")
        except Exception as e:
            print(f"  [~] Web-источники недоступны: {e}")

    if not all_nodes:
        print("  [!] No nodes found in configs")
        return

    all_nodes = all_nodes[:MAX_RECHECK_TOTAL + MAX_FRESH_HTTP]
    print(f"  [*] Total unique (capped at {MAX_RECHECK_TOTAL + MAX_FRESH_HTTP}): {len(all_nodes)}")

    # ── GeoIP: определяем страны ДО генерации, иначе имена будут «Неизвестно» ──
    # У нод из YAML country отсутствует (в YAML страна только в имени), а у свежих
    # web-прокси его нет вообще. Без этого шага все прокси получают флаг 🇿🇿.
    geo_ips = list(dict.fromkeys(n.get("server", "") for n in all_nodes if n.get("server")))
    if geo_ips:
        print(f"  [*] GeoIP: {len(geo_ips)} уникальных IP...")
        try:
            geo_data = await geoip_batch(geo_ips, cancel)
            for n in all_nodes:
                info = geo_data.get(n.get("server", ""))
                if info:
                    n["_ip"] = info.get("ip") or n.get("server", "")
                    if n.get("country", "ZZ") == "ZZ":
                        n["country"] = info.get("country", "ZZ")
            known = sum(1 for n in all_nodes if n.get("country") not in (None, "", "ZZ"))
            print(f"  [+] GeoIP: {known}/{len(all_nodes)} определено")
        except Exception as e:
            print(f"  [~] GeoIP недоступен: {e}")

    live_nodes = await check_nodes(all_nodes, timeout, cancel)

    if not live_nodes:
        print("  [!] All nodes dead, keeping existing configs")
        return

    print(f"  [+] Live after recheck: {len(live_nodes)}")

    record_check_results(live_nodes, all_nodes)

    # Имена пересоберём из свежих стран/пингов (в YAML лежали старые)
    for n in live_nodes:
        n.pop("name", None)

    top_50 = select_quality(live_nodes, 50, get_success_rate)
    top_100 = select_quality(live_nodes, 100, get_success_rate)
    d50 = describe_selection(top_50)
    print(f"  [+] Отбор топ-50: воркерных {d50['workers']}, бэкендов {d50['unique_backends']}, "
          f"макс/подсеть {d50['max_per_subnet']}, http/socks {d50['http']}")

    if len(top_50) >= 50:
        gen_50 = generate_config_clash(top_50)
        (ROOT / "NetherLink-50.yaml").write_text(gen_50, "utf-8")
        gen_50_v2r = generate_config_v2ray(top_50)
        (ROOT / "NetherLink-50-v2ray.json").write_text(gen_50_v2r, "utf-8")
        gen_50_sb = generate_config_singbox(top_50)
        (ROOT / "NetherLink-50-singbox.json").write_text(gen_50_sb, "utf-8")

    if len(top_100) >= 100:
        gen_100 = generate_config_clash(top_100)
        (ROOT / "NetherLink-100.yaml").write_text(gen_100, "utf-8")
        gen_100_v2r = generate_config_v2ray(top_100)
        (ROOT / "NetherLink-100-v2ray.json").write_text(gen_100_v2r, "utf-8")
        gen_100_sb = generate_config_singbox(top_100)
        (ROOT / "NetherLink-100-singbox.json").write_text(gen_100_sb, "utf-8")

    live_txt = "\n".join(
        f"{n['protocol']}://{n['server']}:{n['port']}"
        for n in live_nodes
    )
    (ROOT / "live-top.txt").write_text(live_txt, "utf-8")

    print(f"\n[+] Done: {len(live_nodes)} live (was {len(all_nodes)})")
    print(f"    Updated: NetherLink-50.yaml, NetherLink-100.yaml + v2ray/singbox variants")


if __name__ == "__main__":
    start = time.time()
    asyncio.run(run())
    print(f"\n[+] Total time: {time.time() - start:.1f}s")
