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
import os
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
from backend.verify import verify_nodes, find_mihomo

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


def strict_enabled() -> bool:
    """Строгая проверка ядром клиента (mihomo) — по умолчанию вкл., если mihomo найден."""
    return find_mihomo() is not None and os.environ.get("STRICT_VERIFY", "1") != "0"


async def check_nodes(nodes: list[dict], timeout: int, cancel: asyncio.Event) -> list[dict]:
    if strict_enabled():
        # Те же критерии, что и при генерации: данные реально прошли через ноду
        # (HTTPS-проба + закачка >=200 КБ), а не просто TCP/порт 80. Иначе часовой
        # recheck разбавлял бы топы «живыми на бумаге».
        print(f"  [*] Strict verify (mihomo): {len(nodes)} нод")

        async def _emit_log(event, data):
            if event == "log":
                print(f"     {data.get('text', '')}")

        passed, _checked = await verify_nodes(
            nodes, cancel, conc=300, batch_size=450,
            deadline=time.monotonic() + 600, emit=_emit_log)
        print(f"  [+] Strict pass: {len(passed)}/{len(nodes)}")
        return passed

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


async def run_legacy():
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
    strict = strict_enabled()
    existing_http = sum(1 for n in all_nodes if n.get("protocol", "").lower() in ("http", "https", "socks5"))
    if existing_http < 30 and not strict:
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

    hs = 0 if strict else 0.5   # строгий режим: квоты на тип нет, берём лучших по рангу
    top_50 = select_quality(live_nodes, 50, get_success_rate, http_share=hs)
    top_100 = select_quality(live_nodes, 100, get_success_rate, http_share=hs)
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


MIN_MAIN = 50      # меньше — не перезаписываем основной список (сбой раннера/сети ≠ «все умерли»)
MIN_TOP100 = 30
MIN_TOP50 = 20
STRICT_DEADLINE_S = 780


async def run_strict():
    """Часовой recheck в строгом режиме.

    Кандидаты = текущие списки подписки ∪ резервный пул (до 1500 нод, накоплен
    прошлыми прогонами). Всё проверяется ядром клиента (mihomo), списки
    пересобираются ИЗ ЖИВЫХ — основной, топ-100/50 и Xray — а не просто
    урезаются. Пул обновляется (miss-счётчики), мёртвые вылетают после 3 провалов.
    """
    from backend import pool as node_pool
    from backend.generator import generate_configs
    from backend.quality import collapse_backends, collapse_exit
    from backend.status import build_status

    cancel = asyncio.Event()
    cands: dict[tuple, dict] = {}

    for n in node_pool.pool_candidates():
        cands[node_pool.node_key(n)] = n
    from_pool = len(cands)

    from_lists = 0
    for config_name in ["NetherLink-Clash.yaml", "NetherLink-100.yaml", "NetherLink-50.yaml"]:
        fp = ROOT / config_name
        if not fp.exists():
            continue
        nodes = parse_clash_yaml_nodes(fp)
        added = 0
        for n in nodes:
            k = node_pool.node_key(n)
            if k not in cands:      # версия из пула богаче (reality/ws/svc) — её не затираем
                cands[k] = n
                added += 1
        from_lists += added
        print(f"  [*] Parsed {len(nodes)} from {config_name} (новых к пулу: {added})")

    all_nodes = list(cands.values())
    if not all_nodes:
        print("  [!] No nodes found in configs/pool")
        return
    print(f"  [*] Кандидатов: {len(all_nodes)} (пул {from_pool}, из списков +{from_lists})")

    async def _emit_log(event, data):
        if event == "log":
            print(f"     {data.get('text', '')}")

    passed, attempted = await verify_nodes(
        all_nodes, cancel, conc=300, batch_size=450,
        deadline=time.monotonic() + STRICT_DEADLINE_S, emit=_emit_log)
    print(f"  [+] Strict pass: {len(passed)}/{len(attempted)} проверено (из {len(all_nodes)})")

    if not passed:
        print("  [!] Ни одна нода не прошла — подписки не трогаем (вероятно, сбой сети раннера)")
        return

    # пул — всегда обновляем (и miss-счётчики тоже)
    merged = node_pool.merge_pool(node_pool.load_pool(), passed, attempted)
    node_pool.save_pool(merged)
    print(f"  [+] Пул: {len(merged)} нод")
    record_check_results(passed, attempted)

    # страна: у большинства уже есть (выходной IP); остальным — GeoIP
    need_geo = [n for n in passed if n.get("country") in (None, "", "ZZ")]
    if need_geo:
        try:
            ips = list(dict.fromkeys(n["server"] for n in need_geo))
            geo = await geoip_batch(ips, cancel)
            for n in need_geo:
                info = geo.get(n["server"])
                if info:
                    n["_ip"] = info.get("ip") or n["server"]
                    n["country"] = info.get("country", "ZZ")
        except Exception as e:
            print(f"  [~] GeoIP недоступен: {e}")

    for n in passed:
        n.pop("name", None)     # имена из свежих страны/пинга

    live = collapse_backends(passed, get_success_rate)
    live = collapse_exit(live, get_success_rate)
    selected = select_quality(live, 500, get_success_rate, http_share=0)
    top_100 = select_quality(selected, 100, get_success_rate, http_share=0)
    top_50 = select_quality(top_100, 50, get_success_rate, http_share=0)
    print(f"  [+] Списки: main {len(selected)}, top-100 {len(top_100)}, top-50 {len(top_50)}")

    configs = generate_configs(selected, top_nodes_100=top_100, top_nodes_50=top_50, all_live_nodes=live)
    write_all = len(selected) >= MIN_MAIN
    for name, content in configs.items():
        is_main = name in ("NetherLink-Clash.yaml", "NetherLink-v2ray.json", "NetherLink-singbox.json")
        is_100 = "100" in name
        is_50 = "-50" in name
        if is_main and len(selected) < MIN_MAIN:
            continue
        if is_100 and len(top_100) < MIN_TOP100:
            continue
        if is_50 and len(top_50) < MIN_TOP50:
            continue
        (ROOT / name).write_text(content, "utf-8")
    if not write_all:
        print(f"  [~] Основной список короче {MIN_MAIN} — main-файлы не перезаписаны")

    try:
        st = build_status(kind="recheck", selected=selected, top_100=top_100, top_50=top_50,
                          checked=len(attempted), passed=len(passed), pool_size=len(merged),
                          check_from=os.environ.get("CHECK_FROM", "GitHub Actions"))
        (ROOT / "status.json").write_text(json.dumps(st, ensure_ascii=False, indent=1), "utf-8")
    except Exception as e:
        print(f"  [~] status.json: {e}")

    print(f"\n[+] Done: {len(passed)} живых из {len(attempted)} проверенных; "
          f"main {len(selected)} / top-100 {len(top_100)} / top-50 {len(top_50)} / пул {len(merged)}")


async def run():
    if strict_enabled():
        await run_strict()
    else:
        await run_legacy()


if __name__ == "__main__":
    start = time.time()
    asyncio.run(run())
    print(f"\n[+] Total time: {time.time() - start:.1f}s")
