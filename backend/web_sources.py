"""
HTTP/HTTPS proxy collection from public JSON APIs.
"""
import asyncio
from datetime import date, timedelta

import httpx


WEB_SOURCES = [
    # proxyscrape.com — бесплатный JSON API
    "https://api.proxyscrape.com/v4/free-proxy-list/get?request=displayproxies&protocol=http&country=all&anonymity=elite&timeout=10000&proxy_format=ipport&format=json",
    "https://api.proxyscrape.com/v4/free-proxy-list/get?request=displayproxies&protocol=https&country=all&anonymity=elite&timeout=10000&proxy_format=ipport&format=json",
    # proxy-list.download — JSON API
    "https://www.proxy-list.download/api/v2/get?l=en&t=http",
    "https://www.proxy-list.download/api/v2/get?l=en&t=https",
    # geonode.com — JSON API (500 за раз)
    "https://proxylist.geonode.com/api/proxy-list?protocols=http,https&filterLastChecked=5&speed=fast&limit=500&page=1&sort_by=lastChecked&sort_type=desc",
    # lumiproxy.com — JSON API
    "https://api.lumiproxy.com/web_v1/free-proxy/list?page_size=2000&page=1&language=en-us",
]

# checker.net — архив свежих проверенных прокси по датам.
# JSON: {"data": {"date": "2026-08-05", "proxyList": ["host:port", ...]}}
CHECKER_NET_BASE = "https://checker.net/v1/landing/archive"


def _checker_net_dates() -> list[str]:
    """Сегодня и вчера (UTC). Если сегодняшнего архива ещё нет — возьмём вчерашний."""
    today = date.today()
    return [today.isoformat(), (today - timedelta(days=1)).isoformat()]


async def _fetch_checker_net(client: httpx.AsyncClient) -> dict | None:
    """Качает свежайший доступный архив checker.net (сегодня → вчера)."""
    for day in _checker_net_dates():
        try:
            resp = await client.get(f"{CHECKER_NET_BASE}/{day}", timeout=15)
            if resp.status_code != 200:
                continue
            data = resp.json()
            proxy_list = data.get("data", {}).get("proxyList", [])
            if proxy_list:
                return {"date": day, "proxyList": proxy_list}
        except Exception:
            continue
    return None


async def _fetch_json(client: httpx.AsyncClient, url: str) -> dict | None:
    try:
        resp = await client.get(url, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


async def fetch_web_proxies(cancel_event: asyncio.Event | None = None) -> list[dict]:
    """Собирает прокси со всех web-источников, возвращает список нод."""
    nodes: list[dict] = []
    seen = set()

    limits = httpx.Limits(max_connections=10, max_keepalive_connections=5)
    async with httpx.AsyncClient(timeout=15, limits=limits) as client:
        tasks = [_fetch_json(client, url) for url in WEB_SOURCES]
        # checker.net — отдельно: свой парсер и авто-дата
        checker_task = _fetch_checker_net(client)
        all_tasks = tasks + [checker_task]
        results = await asyncio.gather(*all_tasks, return_exceptions=True)

        # checker.net — последний индекс
        checker_idx = len(WEB_SOURCES)
        checker_result = results[checker_idx]
        if checker_result and not isinstance(checker_result, Exception):
            try:
                before = len(nodes)
                for item in checker_result.get("proxyList", []):
                    host, _, port = str(item).partition(":")
                    if not host or not port:
                        continue
                    try:
                        port = int(port)
                    except ValueError:
                        continue
                    key = ("http", host, port, "")
                    if key[1] and key not in seen:
                        seen.add(key)
                        nodes.append({"protocol": "http", "server": host, "port": port})
                if len(nodes) > before:
                    print(f"  [checker.net] {checker_result.get('date')}: +{len(nodes) - before} прокси")
            except Exception:
                pass

        for i, result in enumerate(results[:len(WEB_SOURCES)]):
            if cancel_event and cancel_event.is_set():
                break
            if result is None or isinstance(result, Exception):
                continue

            try:
                _parse_source(i, result, nodes, seen)
            except Exception:
                continue

    return nodes


def _parse_source(idx: int, data: dict, nodes: list[dict], seen: set):
    """Разбирает ответ от конкретного источника (по индексу в WEB_SOURCES)."""
    if idx in (0, 1):  # proxyscrape.com
        for p in data.get("proxies", []):
            if not p.get("alive"):
                continue
            ip = p.get("proxy", "")
            key = ("http", ip, 0, "")
            if key[1] and key not in seen:
                seen.add(key)
                host, _, port = ip.partition(":")
                nodes.append({
                    "protocol": p.get("protocol", "http").lower(),
                    "server": host or ip,
                    "port": int(port) if port else 0,
                })

    elif idx in (2, 3):  # proxy-list.download
        for p in data.get("LISTA", []):
            ip = p.get("IP", "")
            port = int(p.get("PORT", 0))
            key = ("http", ip, port, "")
            if ip and key not in seen:
                seen.add(key)
                nodes.append({"protocol": "http", "server": ip, "port": port})

    elif idx == 4:  # geonode.com
        for p in data.get("data", []):
            ip = p.get("ip", "")
            port = int(p.get("port", 0))
            proto = (p.get("protocols") or ["http"])[0].lower()
            key = (proto, ip, port, "")
            if ip and key not in seen:
                seen.add(key)
                nodes.append({"protocol": proto, "server": ip, "port": port})

    elif idx == 5:  # lumiproxy.com
        for p in data.get("data", {}).get("list", []):
            ip = p.get("ip", "")
            port = int(p.get("port", 0))
            proto_num = p.get("protocol", 0)
            proto = "https" if proto_num == 2 else "http"
            key = (proto, ip, port, "")
            if ip and key not in seen:
                seen.add(key)
                nodes.append({"protocol": proto, "server": ip, "port": port})
