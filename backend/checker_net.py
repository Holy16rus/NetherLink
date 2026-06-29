import asyncio
import json
import uuid
import httpx

API_BASE = "https://api.checker.net/v1/check"


def format_dsn(node):
    protocol = node.get("protocol", "http").lower()
    server = node.get("server", "")
    port = node.get("port", 0)
    username = node.get("username")
    password = node.get("password")
    if not server or not port:
        return None
    if username and password:
        return f"{protocol}://{username}:{password}@{server}:{port}"
    if username:
        return f"{protocol}://{username}@{server}:{port}"
    return f"{protocol}://{server}:{port}"


def normalize_dsn(dsn):
    if "://" in dsn:
        dsn = dsn.split("://", 1)[1]
    if "@" in dsn:
        dsn = dsn.split("@", 1)[1]
    return dsn


async def send_proxies(nodes, api_key, cancel_event):
    proxies = []
    for i, node in enumerate(nodes):
        dsn = format_dsn(node)
        if dsn:
            proxies.append({"id": str(i), "dsn": dsn})

    if not proxies:
        return None

    request_id = str(uuid.uuid4())
    protocols_set = set()
    for node in nodes:
        p = node.get("protocol", "http").lower()
        if p == "socks5":
            protocols_set.add("socks5")
        elif p in ("http", "https"):
            protocols_set.add("http")

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{API_BASE}/api",
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
            },
            json={
                "results": {"callbackUrl": None},
                "params": {
                    "requestId": request_id,
                    "proxies": proxies,
                    "default": True,
                    "protocols": list(protocols_set) or ["http", "socks5"],
                    "needBlackLists": True,
                    "needScore": True,
                    "services": ["google"],
                    "timeout": 10,
                },
            },
        )
        data = resp.json()
        if not data.get("success"):
            msg = data.get("message", "unknown")
            errors = data.get("errors")
            detail = f" ({errors})" if errors else ""
            raise Exception(f"Checker.net API error: {msg}{detail}")
        check_id = data.get("data", {}).get("checkId")
        if not check_id:
            raise Exception("No checkId in checker.net response: " + json.dumps(data, ensure_ascii=False))
        return check_id, len(proxies)


async def poll_results(check_id, api_key, cancel_event, expected_count, progress_cb=None):
    """Опрашивает GET /get пока не получит все результаты.
    Использует адаптивные интервалы: начинает с 5с, растёт до 15с.
    Выходит досрочно если 3 опроса подряд без новых результатов."""
    ratings = {}
    interval = 5  # start fast, back off as we wait longer
    stale_streak = 0
    last_count = 0

    async with httpx.AsyncClient(timeout=30) as client:
        for attempt in range(80):  # до ~10 минут максимум
            if cancel_event.is_set():
                break
            await asyncio.sleep(interval)
            # Back off: 5 → 8 → 10 → 12 → 15 → 15 → ...
            interval = min(interval + 1, 15)

            try:
                resp = await client.get(
                    f"{API_BASE}/result/{check_id}/get",
                    headers={"Content-Type": "application/json", "x-api-key": api_key},
                    params={"perPage": 500},
                )
                data = resp.json()
                items = (data.get("data") or {}).get("items") or []
                meta = data.get("data") or {}

                for item in items:
                    dsn = item.get("dsn", "")
                    if not dsn:
                        continue
                    key = normalize_dsn(dsn)
                    score = item.get("score")
                    if score is not None:
                        ratings[key] = float(score)  # score уже 0-5

                current_count = len(ratings)
                total = meta.get("meta", {}).get("totalCount", 0)
                if progress_cb:
                    await progress_cb(current_count, expected_count, 0,
                                      f"Checker.net: получено {current_count}/{expected_count} результатов (опрос {attempt + 1})")
                # Early exit if we got all results or 90% (some may fail)
                if total >= expected_count or (expected_count > 0 and current_count >= expected_count * 0.9):
                    break

                # Early exit: 3 опроса подряд без новых результатов
                if current_count == last_count:
                    stale_streak += 1
                    if stale_streak >= 3:
                        if progress_cb:
                            await progress_cb(current_count, expected_count, 0,
                                              f"Checker.net: нет новых результатов, остановка на {current_count}/{expected_count}")
                        break
                else:
                    stale_streak = 0
                last_count = current_count

            except Exception:
                if progress_cb:
                    await progress_cb(len(ratings), expected_count, 0,
                                      f"Checker.net: опрос {attempt + 1}, получено {len(ratings)}/{expected_count}")
                continue

    return ratings


async def check_with_rating(nodes, api_key, cancel_event, progress_cb=None):
    if not nodes:
        return [], {}

    if progress_cb:
        await progress_cb(0, 1, 0, "Отправка в checker.net...")

    check_id, expected = await send_proxies(nodes, api_key, cancel_event)

    if cancel_event.is_set():
        return [], {}

    if progress_cb:
        await progress_cb(0, 1, 0, f"Ожидание результатов ({expected} прокси)...")

    ratings = await poll_results(check_id, api_key, cancel_event, expected, progress_cb)

    if cancel_event.is_set():
        return [], {}

    rated_nodes = []
    for node in nodes:
        dsn = format_dsn(node)
        if not dsn:
            continue
        key = normalize_dsn(dsn)
        rating = ratings.get(key)
        if rating is not None:
            node["checker_rating"] = rating
            rated_nodes.append(node)

    return rated_nodes, ratings
