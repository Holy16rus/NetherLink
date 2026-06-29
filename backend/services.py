import asyncio
import ipaddress
import json
from pathlib import Path

import httpx
import maxminddb

from backend.config import PROXYCHECK_KEY, ROOT

# Shared clients
_GEO_CLIENT: httpx.AsyncClient | None = None
_DOH_CLIENT: httpx.AsyncClient | None = None

# Local MaxMind GeoIP
_GEOIP_READER: maxminddb.Reader | None = None


def _load_geoip_db():
    global _GEOIP_READER
    if _GEOIP_READER is not None:
        return _GEOIP_READER

    import tempfile, shutil

    search = [
        ROOT / "GeoIP" / "GeoLite2-Country.mmdb",
        Path("GeoIP") / "GeoLite2-Country.mmdb",
    ]
    for p in search:
        if p.is_file():
            try:
                _GEOIP_READER = maxminddb.open_database(str(p))
            except (FileNotFoundError, OSError):
                # Windows + кириллица в пути: maxminddb C‑extension
                # не осиливает юникодные пути — копируем в temp
                tmp = Path(tempfile.gettempdir()) / "geolite2.mmdb"
                if not tmp.is_file() or tmp.stat().st_size != p.stat().st_size:
                    shutil.copy2(p, tmp)
                _GEOIP_READER = maxminddb.open_database(str(tmp))
            return _GEOIP_READER
    return None


def _get_geo_client() -> httpx.AsyncClient:
    global _GEO_CLIENT
    if _GEO_CLIENT is None or _GEO_CLIENT.is_closed:
        _GEO_CLIENT = httpx.AsyncClient(
            timeout=15,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
    return _GEO_CLIENT


def _get_doh_client() -> httpx.AsyncClient:
    global _DOH_CLIENT
    if _DOH_CLIENT is None or _DOH_CLIENT.is_closed:
        _DOH_CLIENT = httpx.AsyncClient(
            timeout=5,
            limits=httpx.Limits(max_connections=60, max_keepalive_connections=30),
            http2=True,  # DoH works well with HTTP/2 multiplexing
        )
    return _DOH_CLIENT


async def geoip_batch(ips, cancel_event):
    """
    Геолокация IP: сначала локальная база MaxMind (мгновенно),
    затем fallback на ip-api.com.
    """
    if not ips:
        return {}

    resolved = await resolve_hosts(ips, cancel_event)

    # host → IP маппинг
    by_ip: dict[str, list[str]] = {}
    for host in ips:
        ip = resolved.get(host, host)
        if ip:
            by_ip.setdefault(ip, []).append(host)

    result_map: dict[str, dict] = {}
    ip_list = list(by_ip.keys())

    # ── попытка 1: локальный MaxMind ──────────────────
    db = _load_geoip_db()
    if db is not None:
        missing: list[str] = []
        for ip in ip_list:
            try:
                data = db.get(ip)
                if data and data.get("country") and data["country"].get("iso_code"):
                    cc = data["country"]["iso_code"]
                    location = data.get("location", {})
                    for host in by_ip.get(ip, [ip]):
                        result_map[host] = {
                            "country": cc,
                            "ip": ip,
                            "lat": location.get("latitude"),
                            "lon": location.get("longitude"),
                        }
                    continue
            except Exception:
                pass
            missing.append(ip)

        # то, что не нашлось локально — пробуем через API
        if missing:
            api_results = await _geoip_api(missing, by_ip, cancel_event)
            result_map.update(api_results)
        return result_map

    # ── попытка 2: ip-api.com (нет локальной базы) ────
    return await _geoip_api(ip_list, by_ip, cancel_event)


async def _geoip_api(ip_list: list[str], by_ip: dict[str, list[str]], cancel_event) -> dict[str, dict]:
    """Fallback: ip-api.com batch (бесплатно, но с rate limit)."""
    result_map: dict[str, dict] = {}
    batch_size = 100
    client = _get_geo_client()
    for i in range(0, len(ip_list), batch_size):
        if cancel_event.is_set():
            break
        batch = ip_list[i:i + batch_size]
        try:
            payload = json.dumps(batch).encode("utf-8")
            resp = await client.post(
                "http://ip-api.com/batch?fields=status,countryCode,lat,lon,query",
                content=payload,
                headers={"Content-Type": "application/json"},
            )
            data = resp.json()
            for item in data:
                if isinstance(item, dict) and item.get("status") == "success":
                    ip = item.get("query", "")
                    cc = (item.get("countryCode") or "ZZ").upper()[:2]
                    if ip and cc != "ZZ":
                        for host in by_ip.get(ip, [ip]):
                            result_map[host] = {
                                "country": cc,
                                "ip": ip,
                                "lat": item.get("lat"),
                                "lon": item.get("lon"),
                            }
        except Exception:
            continue
    return result_map


def _is_ip(value):
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def _is_public_ip(value):
    try:
        return ipaddress.ip_address(value).is_global
    except ValueError:
        return False


async def resolve_hosts(hosts, cancel_event):
    results = {}
    sem = asyncio.Semaphore(80)  # increased from 50
    loop = asyncio.get_running_loop()

    async def resolve(host, client):
        if not host or cancel_event.is_set():
            return
        host = str(host).strip().rstrip(".")
        if _is_ip(host):
            if _is_public_ip(host):
                results[host] = host
            return
        try:
            async with sem:
                resp = await client.get(
                    "https://cloudflare-dns.com/dns-query",
                    params={"name": host, "type": "A"},
                    headers={"Accept": "application/dns-json"},
                    timeout=4,
                )
            data = resp.json()
            for answer in data.get("Answer", []):
                ip = answer.get("data", "")
                if answer.get("type") == 1 and _is_public_ip(ip):
                    results[host] = ip
                    return
        except Exception:
            pass

        try:
            async with sem:
                infos = await asyncio.wait_for(loop.getaddrinfo(host, 0, type=0), timeout=3)
            for family, _, _, _, sockaddr in infos:
                ip = sockaddr[0]
                if ":" not in ip and _is_public_ip(ip):
                    results[host] = ip
                    return
            if infos:
                ip = infos[0][4][0]
                if _is_public_ip(ip):
                    results[host] = ip
        except Exception:
            return

    client = _get_doh_client()
    await asyncio.gather(*(resolve(host, client) for host in hosts))
    return results


async def proxycheck_risk(ips, cancel_event):
    if not ips or not PROXYCHECK_KEY:
        return {}
    # Filter to only valid IPs — proxycheck.io doesn't accept hostnames in batch URL
    valid_ips = [ip for ip in ips if _is_ip(ip)]
    if not valid_ips:
        return {}
    result_map = {}
    client = _get_geo_client()
    for i in range(0, len(valid_ips), 100):
        if cancel_event.is_set():
            break
        batch = valid_ips[i:i + 100]
        try:
            resp = await client.get(
                f"https://proxycheck.io/v2/{','.join(batch)}",
                params={"key": PROXYCHECK_KEY, "vpn": 1, "asn": 1, "risk": 1},
            )
            data = resp.json()
            for ip, info in data.items():
                if isinstance(info, dict):
                    existing = result_map.get(ip, {})
                    if info.get("risk") is not None:
                        existing["risk"] = info.get("risk")
                    if info.get("proxy") is not None:
                        existing["proxy"] = info.get("proxy")
                    result_map[ip] = existing
        except Exception:
            continue
    return result_map

