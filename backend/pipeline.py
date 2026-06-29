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
from backend.parser import dedupe
from backend.scraper import collect_local_files, discover_repo_files, fetch_and_parse
from backend.checker import check_node
from backend.services import geoip_batch
from backend.generator import select_nodes, generate_config
from backend.web_sources import fetch_web_proxies

LIVE_PROXY_RE = re.compile(
    r"^(?P<proto>[a-z][a-z0-9]*)://(?:([^:@]+)(?::([^@]*))?@)?(?P<server>[^:]+):(?P<port>\d+)$"
)
_QUEUE_SENTINEL = None  # сигнал завершения producer-а

EmitFn = Callable[[str, dict], Awaitable[None]]


async def _noop(event: str, data: dict) -> None:
    pass


# ──────────────────────────────────────────────────────────────────────────────
# Producer: сканирует источники, пушит ноды в очередь
# ──────────────────────────────────────────────────────────────────────────────

async def _produce(
    sources: list[str],
    local_files: list[str],
    queue: asyncio.Queue,
    cancel_event: asyncio.Event,
    metrics: dict,
    emit: EmitFn,
    per_repo_limit: int = 80,
):
    """Собирает прокси из всех источников и кладёт батчами в queue."""

    # Локальные файлы — быстро, делаем первыми
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

    # Семафор на параллельные HTTP-запросы к источникам
    src_sem = asyncio.Semaphore(6)   # 6 репозиториев одновременно
    file_sem = asyncio.Semaphore(20) # 20 файлов одновременно

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


# ──────────────────────────────────────────────────────────────────────────────
# Consumer: читает из очереди, дедуплицирует, проверяет
# ──────────────────────────────────────────────────────────────────────────────

async def _consume(
    queue: asyncio.Queue,
    cancel_event: asyncio.Event,
    opts: dict,
    metrics: dict,
    emit: EmitFn,
) -> list[dict]:
    """Читает батчи из очереди, дедуплицирует и проверяет каждый батч."""

    timeout = opts.get("timeout", 10)
    max_checks = opts.get("max_checks", 0)
    limit = opts.get("limit", 100)
    # Stop checking early once we have 3× the requested limit — plenty to select from
    early_stop = limit * 3 if limit > 0 else 0

    seen_keys: set = set()      # для инкрементной дедупликации
    live_nodes: list[dict] = []

    # Семафор для check_node — разделяем с producer-ом
    check_sem = asyncio.Semaphore(CHECK_CONCURRENCY)

    pending_nodes: list[dict] = []  # буфер перед проверкой

    async def flush_pending():
        """Проверяет накопленный буфер."""
        nonlocal pending_nodes
        if not pending_nodes or cancel_event.is_set():
            pending_nodes = []
            return

        batch = pending_nodes
        pending_nodes = []

        # Обрезаем батч до max_checks если лимит задан
        remaining = max_checks - metrics["checking_total"] if max_checks > 0 else None
        if remaining is not None and len(batch) > remaining:
            batch = batch[:remaining]

        if not batch:
            return

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
            # Early stop: we have enough live nodes
            if early_stop > 0 and len(live_nodes) >= early_stop:
                for t in tasks:
                    t.cancel()
                break

    FLUSH_BATCH = 150  # было 500 — начинаем проверять раньше

    await emit("log", {"level": "info", "text": f"Consumer: max_checks={max_checks}, limit={opts.get('limit', '?')}"})

    while True:
        try:
            batch = await asyncio.wait_for(queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            # producer ещё работает, проверим буфер если накопился
            if len(pending_nodes) >= FLUSH_BATCH // 2:
                await flush_pending()
            # Если лимит достигнут — выходим
            if max_checks > 0 and metrics["checking_total"] >= max_checks:
                await flush_pending()
                await emit("log", {"level": "info", "text": f"Достигнут max_checks={max_checks}, проверено {metrics['checking_total']}"})
                break
            continue

        if batch is _QUEUE_SENTINEL:
            # Producer закончил — сливаем остаток
            await flush_pending()
            break

        if cancel_event.is_set():
            break

        # Инкрементная дедупликация
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

        metrics["deduped"] = len(seen_keys)
        pending_nodes.extend(new_nodes)

        # Проверяем батч как только накопили FLUSH_BATCH уникальных
        if len(pending_nodes) >= FLUSH_BATCH:
            # Уважаем max_checks
            if max_checks > 0 and metrics["checking_total"] >= max_checks:
                await emit("log", {"level": "info", "text": f"max_checks={max_checks} достигнут, выход"})
                break
            else:
                await flush_pending()

    return live_nodes


# ──────────────────────────────────────────────────────────────────────────────
# Основной pipeline
# ──────────────────────────────────────────────────────────────────────────────

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

    # Очередь между producer и consumer
    queue: asyncio.Queue = asyncio.Queue(maxsize=50)

    # ── Web-источники (JSON API) — быстро, делаем до основных источников ──
    if opts.get("use_web_sources", True):
        await emit("status", {"status": "running", "message": "Сбор прокси с web-источников..."})
        try:
            web_nodes = await fetch_web_proxies(cancel_event)
            if web_nodes:
                metrics["candidates"] += len(web_nodes)
                await queue.put(web_nodes)
                await emit("log", {"level": "info", "text": f"Web-источники: +{len(web_nodes)} прокси"})
        except Exception as e:
            await emit("log", {"level": "warn", "text": f"Web-источники ошибка: {e}"})

    # Запускаем producer и consumer параллельно
    producer_task = asyncio.create_task(
        _produce(sources, local_files, queue, cancel_event, metrics, emit)
    )
    consumer_task = asyncio.create_task(
        _consume(queue, cancel_event, opts, metrics, emit)
    )

    # Ждём consumer (завершится первым при max_checks), затем гасим producer
    live_nodes: list[dict] = []
    was_cancelled = cancel_event.is_set()
    try:
        live_nodes = await consumer_task
    finally:
        if not producer_task.done():
            cancel_event.set()
            producer_task.cancel()
            try:
                await producer_task
            except (asyncio.CancelledError, Exception):
                pass
        if not was_cancelled:
            cancel_event.clear()

    if was_cancelled:
        return {"status": "cancelled", "message": "Отменено", "selected": [], "metrics": metrics}

    metrics["live"] = len(live_nodes)
    await emit("metrics", dict(metrics))
    await emit("log", {"level": "info",
                       "text": f"Живых прокси: {len(live_nodes)} / {metrics['checking_total']} проверено"})

    if not live_nodes:
        return {"status": "error", "message": "Нет живых прокси", "selected": [], "metrics": metrics}

    # ── Сохраняем живые прокси ─────────────────────────────────────────────
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

    # liveproxy.txt — всегда последний снимок
    try:
        (ROOT / "liveproxy.txt").write_text(text, "utf-8")
        await emit("log", {"level": "info",
                           "text": f"liveproxy.txt → {len(lines)} шт."})
    except Exception as e:
        await emit("log", {"level": "warn",
                           "text": f"liveproxy.txt: {e}"})

    # Proxy-Data/ЧЧ-ММ_ДД.ММ.ГГ/live.txt + meta.json + nodes.json — история
    try:
        history_dir.mkdir(parents=True, exist_ok=True)
        (history_dir / "live.txt").write_text(text, "utf-8")

        # Сохраняем полные ноды (с latency_ms) для быстрой перезагрузки
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

        await emit("log", {"level": "info",
                           "text": f"Proxy-Data/{ts_dir}/ → {len(lines)} шт."})
    except Exception as e:
        await emit("log", {"level": "warn",
                           "text": f"Proxy-Data: {e}"})

    if cancel_event.is_set():
        return {"status": "cancelled", "message": "Отменено", "selected": [], "metrics": metrics}

    # ── GeoIP ────────────────────────────────────────────────────────────────
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

    geo_points = [
        {"lat": n["lat"], "lon": n["lon"], "country": n.get("country", "ZZ"), "latency_ms": n.get("latency_ms")}
        for n in live_nodes if n.get("lat") is not None and n.get("lon") is not None
    ]
    await emit("geo_points", {"points": geo_points})

    # ── Финальный отбор ────────────────────────────────────────────────────────
    await emit("status", {"status": "running", "message": "Финальный отбор..."})

    limit = opts.get("limit", 100)
    strategy = opts.get("selection", "fastest")
    prefer_socks = opts.get("prefer_socks5", True)
    selected = select_nodes(live_nodes, limit, strategy, prefer_socks=prefer_socks)

    countries = {n.get("country", "ZZ") for n in selected}
    metrics["selected"] = len(selected)
    metrics["countries"] = len(countries)

    socks5 = sum(1 for n in selected if n.get("protocol", "").lower() == "socks5")
    http   = sum(1 for n in selected if n.get("protocol", "").lower() in ("http", "https"))
    other  = len(selected) - socks5 - http
    await emit("log", {"level": "info",
                       "text": f"Отобрано: {len(selected)} (SOCKS5:{socks5} HTTP:{http} др:{other})"})
    await emit("metrics", dict(metrics))

    # ── Сохранение ─────────────────────────────────────────────────────────────
    OUTPUT_FILE.write_text(generate_config(selected), "utf-8")

    return {
        "status": "done",
        "message": f"Готово: {len(selected)} прокси, {len(countries)} стран",
        "selected": selected,
        "metrics": metrics,
    }


def parse_live_file(path: Path) -> list[dict]:
    """Парсит live.txt (или nodes.json если есть) обратно в список proxy-нод."""
    # Предпочитаем nodes.json — там сохранены latency_ms
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
    """Запускает pipeline начиная с GeoIP на готовых нодах (пропускает сбор и проверку)."""
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

    # ── GeoIP ───────────────────────────────────────────────────────────────
    use_local = (ROOT / "GeoIP" / "GeoLite2-Country.mmdb").is_file()
    await emit("status", {"status": "running", "message": f"GeoIP ({len(live_nodes)} прокси, {'MaxMind локально' if use_local else 'ip-api.com'})..."})
    await emit("log", {"level": "info", "text": f"GeoIP: {'MaxMind (локально)' if use_local else 'ip-api.com (API)'}"})

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

    # ── Финальный отбор ────────────────────────────────────────────────────
    await emit("status", {"status": "running", "message": "Финальный отбор..."})

    limit = opts.get("limit", 100)
    strategy = opts.get("selection", "fastest")
    prefer_socks = opts.get("prefer_socks5", True)
    selected = select_nodes(live_nodes, limit, strategy, prefer_socks=prefer_socks)

    countries = {n.get("country", "ZZ") for n in selected}
    metrics["selected"] = len(selected)
    metrics["countries"] = len(countries)

    socks5 = sum(1 for n in selected if n.get("protocol", "").lower() == "socks5")
    http   = sum(1 for n in selected if n.get("protocol", "").lower() in ("http", "https"))
    other  = len(selected) - socks5 - http
    await emit("log", {"level": "info",
                       "text": f"Отобрано: {len(selected)} (SOCKS5:{socks5} HTTP:{http} др:{other})"})
    await emit("metrics", dict(metrics))

    OUTPUT_FILE.write_text(generate_config(selected), "utf-8")

    return {
        "status": "done",
        "message": f"Готово: {len(selected)} прокси, {len(countries)} стран",
        "selected": selected,
        "metrics": metrics,
    }
