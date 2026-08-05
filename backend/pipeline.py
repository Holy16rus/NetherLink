"""
Pipeline: сбор и проверка идут параллельно через producer/consumer.

Схема:
  Producer: источники сканируются параллельно, распарсенные прокси
            кладутся в asyncio.Queue
  Consumer: читает из очереди, дедуплицирует, проверяет батчами

Это даёт ~40-60% выигрыша по времени — проверка начинается
сразу, не ожидая сбора всех источников.
"""
import asyncio
from datetime import datetime
import json
import re
from pathlib import Path
from typing import Callable, Awaitable

from backend.config import OUTPUT_FILE, CHECK_CONCURRENCY, ROOT
from backend.scraper import collect_local_files, discover_repo_files, fetch_and_parse
from backend.checker import check_node, speed_test_node, protocol_check
from backend.services import geoip_batch, dnsbl_check_batch
from backend.generator import select_nodes, generate_configs
from backend.web_sources import fetch_web_proxies
from backend.state import record_check_results, filter_stable, save_history

LIVE_PROXY_RE = re.compile(
    r"^(?P<proto>[a-z][a-z0-9]*)://(?:([^:@]+)(?::([^@]*))?@)?(?P<server>[^:]+):(?P<port>\d+)$"
)
_QUEUE_SENTINEL = None

EmitFn = Callable[[str, dict], Awaitable[None]]

PROTOCOL_CHECK_CONCURRENCY = 15
TCP_CONCURRENCY = CHECK_CONCURRENCY


async def _noop(event: str, data: dict) -> None:
    pass



async def _produce(
    sources: list[str],
    local_files: list[str],
    queue: asyncio.Queue,
    cancel_event: asyncio.Event,
    metrics: dict,
    emit: EmitFn,
    per_repo_limit: int = 80,
):
    local_nodes = await collect_local_files(local_files)
    if local_nodes:
        metrics["candidates"] += len(local_nodes)
        await queue.put(local_nodes)
        await emit("log", {"level": "info", "text": f"Локальные файлы: {len(local_nodes)} прокси"})

    if not sources:
        await queue.put(_QUEUE_SENTINEL)
        return

    total_sources = len(sources)
    metrics["total_sources"] = total_sources

    src_sem = asyncio.Semaphore(6)
    file_sem = asyncio.Semaphore(20)

    async def process_source(idx: int, source: str):
        if cancel_event.is_set():
            return
        async with src_sem:
            metrics["current_source"] = idx + 1
            await emit("status", {
                "status": "running",
                "message": f"[{idx+1}/{total_sources}] {source[:60]}...",
            })
            try:
                files = await discover_repo_files(source, per_repo_limit, cancel_event)
            except Exception as e:
                await emit("log", {"level": "warn", "text": f"Источник недоступен: {source[:50]} — {e}"})
                return

            async def process_file(item):
                if cancel_event.is_set():
                    return
                async with file_sem:
                    _, nodes = await fetch_and_parse(item, cancel_event)
                    if nodes:
                        metrics["candidates"] += len(nodes)
                        await queue.put(nodes)
                        await emit("log", {
                            "level": "info",
                            "text": f"+{len(nodes)} из {item['path'][:50]}",
                        })

            await asyncio.gather(*[process_file(f) for f in files])

    await asyncio.gather(*[process_source(i, src) for i, src in enumerate(sources)])
    await queue.put(_QUEUE_SENTINEL)



async def _consume(
    queue: asyncio.Queue,
    cancel_event: asyncio.Event,
    opts: dict,
    metrics: dict,
    emit: EmitFn,
) -> tuple[list[dict], list[dict]]:
    """Возвращает (live_nodes, all_checked_nodes)."""
    timeout = opts.get("timeout", 10)
    max_checks = opts.get("max_checks", 0)
    limit = opts.get("limit", 100)
    early_stop = limit * 3 if limit > 0 else 0

    # Туннельные протоколы имеют приоритет: когда бюджет max_checks
    # исчерпан, http/socks5 обрезаются, а vmess/vless/trojan/ss/hy2
    # проходят ВСЕГДА (в счёт общего бюджета). Так жирные http-источники
    # не вытесняют туннельные из проверки.
    TUNNEL_PROTOCOLS = ("vmess", "vless", "trojan", "ss", "hysteria2", "hy2")
    tunnel_checked = 0  # для лога

    seen_keys: set = set()
    live_nodes: list[dict] = []
    all_checked: list[dict] = []

    check_sem = asyncio.Semaphore(TCP_CONCURRENCY)
    pending_nodes: list[dict] = []

    async def flush_pending():
        nonlocal pending_nodes, tunnel_checked
        if not pending_nodes or cancel_event.is_set():
            pending_nodes = []
            return
        batch = pending_nodes
        pending_nodes = []

        # Приоритет туннельных: при исчерпании бюджета обрезаем
        # только http/socks5, туннельные проходят всегда.
        remaining = max_checks - metrics["checking_total"] if max_checks > 0 else None
        if remaining is not None and remaining <= 0:
            # Бюджет исчерпан — проверяем только туннельные (если есть).
            batch = [n for n in batch if n.get("protocol", "").lower() in TUNNEL_PROTOCOLS]
        elif remaining is not None and len(batch) > remaining:
            # Часть бюджета осталась — сначала туннельные, потом http/socks.
            tunnel_part = [n for n in batch if n.get("protocol", "").lower() in TUNNEL_PROTOCOLS]
            other_part = [n for n in batch if n.get("protocol", "").lower() not in TUNNEL_PROTOCOLS]
            other_part = other_part[:max(0, remaining - len(tunnel_part))]
            batch = tunnel_part + other_part

        if not batch:
            return
        tunnel_checked += len([n for n in batch if n.get("protocol", "").lower() in TUNNEL_PROTOCOLS])
        metrics["checking_total"] += len(batch)

        async def check_one(node):
            if cancel_event.is_set():
                return None
            async with check_sem:
                return await check_node(node, timeout, cancel_event)

        tasks = [asyncio.create_task(check_one(n)) for n in batch]
        for coro in asyncio.as_completed(tasks):
            if cancel_event.is_set():
                for t in tasks:
                    t.cancel()
                break
            result = await coro
            if result:
                live_nodes.append(result)
            metrics["checking_progress"] += 1
            metrics["live"] = len(live_nodes)
            await emit("metrics", dict(metrics))
            if early_stop > 0 and len(live_nodes) >= early_stop:
                for t in tasks:
                    t.cancel()
                break

    FLUSH_BATCH = 150

    await emit("log", {"level": "info", "text": f"Consumer: max_checks={max_checks}, limit={opts.get('limit', '?')}"})

    while True:
        try:
            batch = await asyncio.wait_for(queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            if len(pending_nodes) >= FLUSH_BATCH // 2:
                await flush_pending()
            if max_checks > 0 and metrics["checking_total"] >= max_checks:
                await flush_pending()
                await emit("log", {"level": "info", "text": f"Достигнут max_checks={max_checks}, проверено {metrics['checking_total']} (туннельных: {tunnel_checked})"})
                break
            continue

        if batch is _QUEUE_SENTINEL:
            await flush_pending()
            break

        if cancel_event.is_set():
            break

        new_nodes = []
        for node in batch:
            proto = node.get("protocol", "").lower()
            if proto == "socks4":
                continue
            key = (
                proto,
                str(node.get("server", "")).lower(),
                int(node.get("port", 0)),
                node.get("uuid") or node.get("password") or node.get("username") or "",
            )
            if not key[1] or not key[2] or key in seen_keys:
                continue
            seen_keys.add(key)
            new_nodes.append(node)

        all_checked.extend(new_nodes)
        metrics["deduped"] = len(seen_keys)
        pending_nodes.extend(new_nodes)

        if len(pending_nodes) >= FLUSH_BATCH:
            if max_checks > 0 and metrics["checking_total"] >= max_checks:
                await emit("log", {"level": "info", "text": f"max_checks={max_checks} достигнут, выход"})
                break
            else:
                await flush_pending()

    return live_nodes, all_checked


async def _protocol_check_batch(nodes, timeout, cancel_event, emit):
    """Проверяет туннельные протоколы (VMess/VLESS/Trojan/SS/Hy2) через sing-box.
    Только для нод, уже прошедших TCP-фильтр. Низкая конкурентность (15-20).
    """
    candidates = [n for n in nodes if n.get("protocol", "").lower() in ("vmess", "vless", "trojan", "ss", "hysteria2", "hy2")]
    non_tunnel = [n for n in nodes if n.get("protocol", "").lower() in ("http", "https", "socks5")]
    if not candidates:
        await emit("log", {"level": "info", "text": "Нет туннельных прокси для протокольной проверки"})
        return nodes

    await emit("log", {"level": "info", "text": f"Protocol check: {len(candidates)} туннельных (sing-box), {PROTOCOL_CHECK_CONCURRENCY} параллельно..."})

    sem = asyncio.Semaphore(PROTOCOL_CHECK_CONCURRENCY)
    passed = []

    async def check_one(node):
        if cancel_event.is_set():
            return None
        async with sem:
            latency = await protocol_check(node, timeout, cancel_event)
            if latency is not None:
                node["latency_ms"] = latency
                return node
            return None

    tasks = [asyncio.create_task(check_one(n)) for n in candidates]
    for coro in asyncio.as_completed(tasks):
        if cancel_event.is_set():
            for t in tasks:
                t.cancel()
            break
        result = await coro
        if result:
            passed.append(result)

    await emit("log", {"level": "info", "text": f"Protocol check: {len(passed)}/{len(candidates)} прошли sing-box"})
    return non_tunnel + passed


async def _speed_test_batch(nodes, timeout, cancel_event, emit):
    if not nodes:
        return nodes
    testable = [n for n in nodes if n.get("protocol", "").lower() in ("http", "https", "socks5")]
    if not testable:
        return nodes

    await emit("log", {"level": "info", "text": f"Speed test: {len(testable)} прокси..."})

    sem = asyncio.Semaphore(50)
    checked = 0

    async def test_one(node):
        nonlocal checked
        if cancel_event.is_set():
            return None
        async with sem:
            result = await speed_test_node(node, timeout, cancel_event)
            checked += 1
            if checked % 10 == 0:
                await emit("log", {"level": "info", "text": f"Speed test: {checked}/{len(testable)}"})
            return result

    tasks = [test_one(n) for n in testable]
    results = await asyncio.gather(*tasks)
    speed_map = {id(n): r for n, r in zip(testable, results) if r is not None}

    for node in nodes:
        sid = id(node)
        if sid in speed_map:
            node["speed_mbps"] = speed_map[sid]

    fast = sum(1 for n in nodes if n.get("speed_mbps") is not None and n["speed_mbps"] > 0)
    await emit("log", {"level": "info", "text": f"Speed test: {fast}/{len(testable)} имеют скорость"})
    return nodes


async def _recheck_top_nodes(nodes, limit, timeout, cancel_event, emit):
    if not nodes or limit <= 0:
        return nodes

    top = sorted(nodes, key=lambda n: (
        -(n.get("speed_mbps") or 0),
        n.get("latency_ms") or 999999
    ))[:limit]

    await emit("log", {"level": "info", "text": f"Re-check: перепроверка топ-{len(top)} прокси..."})

    sem = asyncio.Semaphore(30)
    rechecked = []

    async def recheck_one(node):
        if cancel_event.is_set():
            return None
        async with sem:
            result = await check_node(node, timeout, cancel_event)
            if result:
                speed = await speed_test_node(result, timeout, cancel_event)
                if speed is not None:
                    result["speed_mbps"] = speed
                return result
            return None

    tasks = [asyncio.create_task(recheck_one(n)) for n in top]
    for coro in asyncio.as_completed(tasks):
        if cancel_event.is_set():
            for t in tasks:
                t.cancel()
            break
        result = await coro
        if result:
            rechecked.append(result)

    await emit("log", {"level": "info", "text": f"Re-check: {len(rechecked)}/{len(top)} живы после перепроверки"})
    return rechecked


async def run_pipeline(
    sources: list[str],
    local_files: list[str],
    opts: dict,
    cancel_event: asyncio.Event,
    emit: EmitFn = _noop,
) -> dict:
    metrics = {
        "total_sources": 0,
        "current_source": 0,
        "candidates": 0,
        "deduped": 0,
        "checking_progress": 0,
        "checking_total": 0,
        "live": 0,
        "checker_rated": 0,
        "checker_filtered": 0,
        "geo_checked": 0,
        "selected": 0,
        "countries": 0,
    }

    await emit("status", {"status": "running", "message": "Параллельный сбор и проверка прокси..."})

    queue: asyncio.Queue = asyncio.Queue(maxsize=50)

    # Сортируем источники: туннельные протоколы (v2ray/vless/trojan/hysteria/ss)
    # идут первыми в очередь. Иначе жирные http-источники (checker.net,
    # proxyscrape и т.п.) съедают весь max_checks-бюджет ещё до того, как
    # producer доберётся до туннельных — и protocol_check получает пустоту.
    def _is_tunnel_source(url: str) -> bool:
        u = url.lower()
        return any(k in u for k in ("v2ray", "vless", "vmess", "trojan", "hysteria", "hy2", "vpn-config", "clashx"))

    sources = sorted(sources, key=lambda s: 0 if _is_tunnel_source(s) else 1)

    producer_task = asyncio.create_task(
        _produce(sources, local_files, queue, cancel_event, metrics, emit)
    )

    async def _feed_web_sources():
        if not opts.get("use_web_sources", True):
            return
        await emit("status", {"status": "running", "message": "Сбор прокси с web-источников..."})
        try:
            web_nodes = await fetch_web_proxies(cancel_event)
            if web_nodes:
                metrics["candidates"] += len(web_nodes)
                # Кладём небольшими чанками, а НЕ одним огромным батчем.
                # Один batch из 3000+ http-нод займёт весь ранний max_checks
                # раньше, чем producer успеет докинуть туннельные источники.
                # Запускается КОНКУРЕНТНО с _produce (см. ниже) — не блокирует
                # старт сбора туннельных источников.
                CHUNK = 150
                for i in range(0, len(web_nodes), CHUNK):
                    await queue.put(web_nodes[i:i + CHUNK])
                await emit("log", {"level": "info", "text": f"Web-источники: +{len(web_nodes)} прокси"})
        except Exception as e:
            await emit("log", {"level": "warn", "text": f"Web-источники ошибка: {e}"})

    web_task = asyncio.create_task(_feed_web_sources())

    producer_time_budget = opts.get("producer_timeout", 180)
    producer_limited = asyncio.ensure_future(
        asyncio.wait_for(producer_task, timeout=producer_time_budget)
    )

    consumer_task = asyncio.create_task(
        _consume(queue, cancel_event, opts, metrics, emit)
    )

    live_nodes: list[dict] = []
    all_checked: list[dict] = []
    was_cancelled = cancel_event.is_set()
    try:
        live_nodes, all_checked = await consumer_task
    finally:
        if not producer_limited.done():
            try:
                cancel_event.set()
                producer_limited.cancel()
                await producer_limited
            except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                pass
        if not web_task.done():
            web_task.cancel()
        try:
            await web_task
        except (asyncio.CancelledError, Exception):
            pass
        if not was_cancelled:
            cancel_event.clear()

    if was_cancelled:
        return {"status": "cancelled", "message": "Отменено", "selected": [], "metrics": metrics}

    metrics["live"] = len(live_nodes)
    await emit("metrics", dict(metrics))
    await emit("log", {"level": "info",
                       "text": f"Живых прокси после TCP: {len(live_nodes)} / {metrics['checking_total']} проверено"})

    if not live_nodes:
        return {"status": "error", "message": "Нет живых прокси", "selected": [], "metrics": metrics}

    if all_checked:
        record_check_results(live_nodes, all_checked)
        await emit("log", {"level": "info", "text": "История сохранена в proxy-history.json"})

    timeout = opts.get("timeout", 10)
    live_nodes = await _protocol_check_batch(live_nodes, timeout, cancel_event, emit)

    if not live_nodes:
        return {"status": "error", "message": "Нет живых после протокольной проверки", "selected": [], "metrics": metrics}

    now = datetime.now()
    ts_dir = now.strftime("%H-%M_%d.%m.%y")
    history_dir = ROOT / "Proxy-Data" / ts_dir

    lines = []
    for n in live_nodes:
        proto = n.get("protocol", "http").lower()
        server = n.get("server", "")
        port = n.get("port", 0)
        user = n.get("username")
        password = n.get("password")
        if user and password:
            lines.append(f"{proto}://{user}:{password}@{server}:{port}")
        elif user:
            lines.append(f"{proto}://{user}@{server}:{port}")
        else:
            lines.append(f"{proto}://{server}:{port}")

    text = "\n".join(lines)

    try:
        (ROOT / "liveproxy.txt").write_text(text, "utf-8")
        await emit("log", {"level": "info", "text": f"liveproxy.txt → {len(lines)} шт."})
    except Exception as e:
        await emit("log", {"level": "warn", "text": f"liveproxy.txt: {e}"})

    try:
        history_dir.mkdir(parents=True, exist_ok=True)
        (history_dir / "live.txt").write_text(text, "utf-8")

        saved_nodes = []
        for n in live_nodes:
            sn = {
                "protocol": n.get("protocol", "http").lower(),
                "server": n.get("server", ""),
                "port": int(n.get("port", 0)),
            }
            if n.get("username"):
                sn["username"] = n["username"]
            if n.get("password"):
                sn["password"] = n["password"]
            if n.get("latency_ms") is not None:
                sn["latency_ms"] = n["latency_ms"]
            if n.get("speed_mbps") is not None:
                sn["speed_mbps"] = n["speed_mbps"]
            saved_nodes.append(sn)
        (history_dir / "nodes.json").write_text(
            json.dumps(saved_nodes, ensure_ascii=False), "utf-8")

        meta = {
            "timestamp": now.isoformat(),
            "live": len(live_nodes),
            "checked": metrics.get("checking_total", 0),
            "candidates": metrics.get("candidates", 0),
            "sources": metrics.get("total_sources", 0),
            "checker_rated": metrics.get("checker_rated", 0),
            "geoip_success": metrics.get("geoip", 0),
        }
        (history_dir / "meta.json").write_text(
            json.dumps(meta, indent=2, ensure_ascii=False), "utf-8")

        await emit("log", {"level": "info", "text": f"Proxy-Data/{ts_dir}/ → {len(lines)} шт."})
    except Exception as e:
        await emit("log", {"level": "warn", "text": f"Proxy-Data: {e}"})

    if cancel_event.is_set():
        return {"status": "cancelled", "message": "Отменено", "selected": [], "metrics": metrics}

    use_local = (ROOT / "GeoIP" / "GeoLite2-Country.mmdb").is_file()
    await emit("status", {"status": "running", "message": f"GeoIP ({len(live_nodes)} прокси, {'локально' if use_local else 'ip-api.com'})..."})

    unique_ips = list(dict.fromkeys(n.get("server", "") for n in live_nodes if n.get("server")))
    geo_data = await geoip_batch(unique_ips, cancel_event)

    metrics["geo_checked"] = len(geo_data)
    await emit("metrics", dict(metrics))

    for node in live_nodes:
        ip = node.get("server", "")
        if ip in geo_data:
            info = geo_data[ip]
            if node.get("country", "ZZ") == "ZZ":
                node["country"] = info.get("country", "ZZ")
            if info.get("lat") is not None and info.get("lon") is not None:
                node["lat"] = info["lat"]
                node["lon"] = info["lon"]

    known = sum(1 for n in live_nodes if n.get("country") != "ZZ")
    await emit("log", {"level": "info", "text": f"GeoIP: {known}/{len(live_nodes)} определено"})

    # ── DNSBL-фильтр спам-баз (бесплатно, без ключей) ────────────────
    # Отсекаем прокси, замеченные в спаме/абузе (SpamCop/Spamhaus/SORBS).
    # host → IP берём из geo_data (там уже есть резолв доменов).
    spam_hosts = {}
    for node in live_nodes:
        host = node.get("server", "")
        if not host:
            continue
        ip = geo_data.get(host, {}).get("ip") or host
        if ip:
            spam_hosts[host] = ip
    if spam_hosts:
        spam_map = await dnsbl_check_batch(spam_hosts, cancel_event)
        spam_count = sum(1 for h, bad in spam_map.items() if bad)
        if spam_count:
            clean_nodes = [n for n in live_nodes if not spam_map.get(n.get("server", ""), False)]
            await emit("log", {"level": "info",
                               "text": f"DNSBL: {spam_count} прокси в спам-базах отсечено ({len(live_nodes)} → {len(clean_nodes)})"})
            live_nodes = clean_nodes
        else:
            await emit("log", {"level": "info", "text": "DNSBL: все прокси чистые (0 в спам-базах)"})

    geo_points = [
        {"lat": n["lat"], "lon": n["lon"], "country": n.get("country", "ZZ"), "latency_ms": n.get("latency_ms")}
        for n in live_nodes if n.get("lat") is not None and n.get("lon") is not None
    ]
    await emit("geo_points", {"points": geo_points})

    await emit("status", {"status": "running", "message": "Speed test всех живых прокси..."})
    live_nodes = await _speed_test_batch(live_nodes, timeout, cancel_event, emit)

    stable_nodes = filter_stable(live_nodes)
    await emit("log", {"level": "info", "text": f"История: {len(stable_nodes)}/{len(live_nodes)} стабильны (success_rate >= 0.6 за последние 5 запусков)"})

    await emit("status", {"status": "running", "message": "Финальный отбор..."})

    limit = opts.get("limit", 100)
    strategy = opts.get("selection", "fastest")

    # Для 500-прокси подписки (NetherLink.yaml) берём ВСЕ живые по скорости,
    # а не только стабильные. Стабильный фильтр — для топ-100 и топ-50.
    if limit >= 500:
        selected = select_nodes(live_nodes, limit, strategy)
    else:
        selected = select_nodes(stable_nodes, limit, strategy)
        if len(selected) < limit:
            selected = select_nodes(live_nodes, limit, strategy)

    countries = {n.get("country", "ZZ") for n in selected}
    metrics["selected"] = len(selected)
    metrics["countries"] = len(countries)

    socks5 = sum(1 for n in selected if n.get("protocol", "").lower() == "socks5")
    http   = sum(1 for n in selected if n.get("protocol", "").lower() in ("http", "https"))
    other  = len(selected) - socks5 - http
    await emit("log", {"level": "info",
                       "text": f"Отобрано: {len(selected)} (SOCKS5:{socks5} HTTP:{http} др:{other})"})
    await emit("metrics", dict(metrics))

    await emit("status", {"status": "running", "message": "Формирование топ-100 и топ-50..."})

    fast_nodes = sorted(stable_nodes, key=lambda n: (
        0 if n.get("speed_mbps") is not None and n["speed_mbps"] > 0 else 1,
        -(n.get("speed_mbps") or 0),
        n.get("latency_ms") or 999999,
    ))
    if len(fast_nodes) < 100:
        fast_nodes = sorted(live_nodes, key=lambda n: (
            0 if n.get("speed_mbps") is not None and n["speed_mbps"] > 0 else 1,
            -(n.get("speed_mbps") or 0),
            n.get("latency_ms") or 999999,
        ))

    top_100 = select_nodes(fast_nodes, min(100, len(fast_nodes)), strategy)
    top_50 = select_nodes(fast_nodes, min(50, len(fast_nodes)), strategy)

    top_100_rechecked = await _recheck_top_nodes(top_100, len(top_100), timeout, cancel_event, emit)
    top_50_rechecked = await _recheck_top_nodes(top_50, len(top_50), timeout, cancel_event, emit)

    configs = generate_configs(selected, top_nodes_100=top_100_rechecked, top_nodes_50=top_50_rechecked, all_live_nodes=live_nodes)

    for name, content in configs.items():
        file_path = ROOT / name
        file_path.write_text(content, "utf-8")
        await emit("log", {"level": "info", "text": f"{name} → {len(content)} байт"})

    return {
        "status": "done",
        "message": f"Готово: {len(selected)} прокси, {len(countries)} стран, configs: {', '.join(configs.keys())}",
        "selected": selected,
        "top_100": top_100_rechecked,
        "top_50": top_50_rechecked,
        "metrics": metrics,
        "configs": list(configs.keys()),
    }


def parse_live_file(path: Path) -> list[dict]:
    nodes_json = path.parent / "nodes.json" if path.name == "live.txt" else None
    if nodes_json and nodes_json.is_file():
        try:
            return json.loads(nodes_json.read_text("utf-8"))
        except Exception:
            pass

    nodes = []
    for line in path.read_text("utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        m = LIVE_PROXY_RE.match(line)
        if not m:
            continue
        proto = m.group("proto").lower()
        server = m.group("server")
        port = int(m.group("port"))
        username = m.group(2)
        password = m.group(3)
        node: dict = {"protocol": proto, "server": server, "port": port}
        if username:
            node["username"] = username
        if password:
            node["password"] = password
        nodes.append(node)
    return nodes


async def run_pipeline_from_nodes(
    nodes: list[dict],
    opts: dict,
    cancel_event: asyncio.Event,
    emit: EmitFn = _noop,
    source_label: str = "Proxy-Data",
) -> dict:
    metrics = {
        "total_sources": 0,
        "current_source": 0,
        "candidates": len(nodes),
        "deduped": len(nodes),
        "checking_progress": len(nodes),
        "checking_total": len(nodes),
        "live": len(nodes),
        "checker_rated": 0,
        "checker_filtered": 0,
        "geo_checked": 0,
        "selected": 0,
        "countries": 0,
    }

    live_nodes = nodes
    await emit("status", {"status": "running", "message": f"Загружено {len(nodes)} прокси из {source_label}"})
    await emit("log", {"level": "info", "text": f"Загружено: {len(nodes)} прокси из {source_label}"})
    await emit("metrics", dict(metrics))

    if cancel_event.is_set():
        return {"status": "cancelled", "message": "Отменено", "selected": [], "metrics": metrics}

    use_local = (ROOT / "GeoIP" / "GeoLite2-Country.mmdb").is_file()
    await emit("status", {"status": "running", "message": f"GeoIP ({len(live_nodes)} прокси, {'MaxMind локально' if use_local else 'ip-api.com'})..."})

    unique_ips = list(dict.fromkeys(n.get("server", "") for n in live_nodes if n.get("server")))
    geo_data = await geoip_batch(unique_ips, cancel_event)

    metrics["geo_checked"] = len(geo_data)
    await emit("metrics", dict(metrics))

    for node in live_nodes:
        ip = node.get("server", "")
        if ip in geo_data:
            info = geo_data[ip]
            if node.get("country", "ZZ") == "ZZ":
                node["country"] = info.get("country", "ZZ")
            if info.get("lat") is not None and info.get("lon") is not None:
                node["lat"] = info["lat"]
                node["lon"] = info["lon"]

    known = sum(1 for n in live_nodes if n.get("country") != "ZZ")
    await emit("log", {"level": "info", "text": f"GeoIP: {known}/{len(live_nodes)} определено"})
    geo_points = [
        {"lat": n["lat"], "lon": n["lon"], "country": n.get("country", "ZZ"), "latency_ms": n.get("latency_ms")}
        for n in live_nodes if n.get("lat") is not None and n.get("lon") is not None
    ]
    await emit("geo_points", {"points": geo_points})

    timeout = opts.get("timeout", 10)
    live_nodes = await _speed_test_batch(live_nodes, timeout, cancel_event, emit)

    stable_nodes = filter_stable(live_nodes)
    await emit("log", {"level": "info", "text": f"История: {len(stable_nodes)}/{len(live_nodes)} стабильны"})

    await emit("status", {"status": "running", "message": "Финальный отбор..."})

    limit = opts.get("limit", 100)
    strategy = opts.get("selection", "fastest")
    selected = select_nodes(stable_nodes, limit, strategy)
    if len(selected) < limit:
        selected = select_nodes(live_nodes, limit, strategy)

    countries = {n.get("country", "ZZ") for n in selected}
    metrics["selected"] = len(selected)
    metrics["countries"] = len(countries)

    socks5 = sum(1 for n in selected if n.get("protocol", "").lower() == "socks5")
    http   = sum(1 for n in selected if n.get("protocol", "").lower() in ("http", "https"))
    other  = len(selected) - socks5 - http
    await emit("log", {"level": "info",
                       "text": f"Отобрано: {len(selected)} (SOCKS5:{socks5} HTTP:{http} др:{other})"})

    fast_nodes = sorted(stable_nodes if len(stable_nodes) >= 100 else live_nodes, key=lambda n: (
        0 if n.get("speed_mbps") is not None and n["speed_mbps"] > 0 else 1,
        -(n.get("speed_mbps") or 0),
        n.get("latency_ms") or 999999,
    ))
    top_100 = select_nodes(fast_nodes, min(100, len(fast_nodes)), strategy)
    top_50 = select_nodes(fast_nodes, min(50, len(fast_nodes)), strategy)

    top_100_rechecked = await _recheck_top_nodes(top_100, len(top_100), timeout, cancel_event, emit)
    top_50_rechecked = await _recheck_top_nodes(top_50, len(top_50), timeout, cancel_event, emit)

    configs = generate_configs(selected, top_nodes_100=top_100_rechecked, top_nodes_50=top_50_rechecked, all_live_nodes=live_nodes)

    for name, content in configs.items():
        file_path = ROOT / name
        file_path.write_text(content, "utf-8")
        await emit("log", {"level": "info", "text": f"{name} → {len(content)} байт"})

    return {
        "status": "done",
        "message": f"Готово: {len(selected)} прокси, {len(countries)} стран",
        "selected": selected,
        "top_100": top_100_rechecked,
        "top_50": top_50_rechecked,
        "metrics": metrics,
        "configs": list(configs.keys()),
    }
