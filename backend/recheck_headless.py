"""
Recheck headless: только проверка без сбора.
Запускается часто (каждый час) в отдельном workflow.

1. Парсит NetherLink.yaml (500), NetherLink-100.yaml, NetherLink-50.yaml через yaml.safe_load
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
from backend.state import record_check_results, save_history

ROOT = Path(__file__).resolve().parent.parent

PROTOCOL_CHECK_CONCURRENCY = 10
TCP_CONCURRENCY = 50
MAX_RECHECK_NODES = 300


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

    for config_name in ["NetherLink.yaml", "NetherLink-100.yaml", "NetherLink-50.yaml"]:
        fp = ROOT / config_name
        if fp.exists():
            nodes = parse_clash_yaml_nodes(fp)
            limit = MAX_RECHECK_NODES if "NetherLink.yaml" == config_name else None
            for n in nodes:
                key = (n["protocol"], n["server"], n["port"])
                if key not in seen:
                    seen.add(key)
                    all_nodes.append(n)
                if limit and len(all_nodes) >= limit:
                    break
            print(f"  [*] Parsed {len(nodes)} from {config_name}")

    if not all_nodes:
        print("  [!] No nodes found in configs")
        return

    all_nodes = all_nodes[:MAX_RECHECK_NODES]
    print(f"  [*] Total unique (capped at {MAX_RECHECK_NODES}): {len(all_nodes)}")

    live_nodes = await check_nodes(all_nodes, timeout, cancel)

    if not live_nodes:
        print("  [!] All nodes dead, keeping existing configs")
        return

    print(f"  [+] Live after recheck: {len(live_nodes)}")

    record_check_results(live_nodes, all_nodes)

    for n in live_nodes:
        if not n.get("name"):
            n["name"] = f"{n['server']}:{n['port']}"

    if len(live_nodes) >= 50:
        gen_50 = generate_config_clash(live_nodes[:50])
        (ROOT / "NetherLink-50.yaml").write_text(gen_50, "utf-8")
        gen_50_v2r = generate_config_v2ray(live_nodes[:50])
        (ROOT / "NetherLink-50-v2ray.json").write_text(gen_50_v2r, "utf-8")
        gen_50_sb = generate_config_singbox(live_nodes[:50])
        (ROOT / "NetherLink-50-singbox.json").write_text(gen_50_sb, "utf-8")

    if len(live_nodes) >= 100:
        gen_100 = generate_config_clash(live_nodes[:100])
        (ROOT / "NetherLink-100.yaml").write_text(gen_100, "utf-8")
        gen_100_v2r = generate_config_v2ray(live_nodes[:100])
        (ROOT / "NetherLink-100-v2ray.json").write_text(gen_100_v2r, "utf-8")
        gen_100_sb = generate_config_singbox(live_nodes[:100])
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
