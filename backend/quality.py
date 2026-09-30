"""Качество отбора нод: классы, ранжирование, дедуп по бэкенду, разнообразие.

Зачем этот модуль:
  старый отбор сортировал по пингу, замеренному на CI-раннере.
  Cloudflare Workers (edge в паре мс от раннера) забивали топ, а один и тот же
  воркер, доступный через десятки edge-IP, занимал десятки слотов.
  Здесь: классификация нод, счёт по истории успехов, схлопывание клонов бэкенда
  и жадный отбор с лимитами на подсеть / бэкенд / долю «воркерных».
"""
import ipaddress
import math
import re

# ── Cloudflare edge (anycast) — по ним ловим «воркерные» прокси ──
CF_PREFIXES = (
    "103.21.244.0/22", "103.22.200.0/22", "103.31.4.0/22", "104.16.0.0/13",
    "104.24.0.0/14", "108.162.192.0/18", "131.0.72.0/22", "141.101.64.0/18",
    "162.158.0.0/15", "172.64.0.0/13", "173.245.48.0/20", "188.114.96.0/20",
    "190.93.240.0/20", "197.234.240.0/22", "198.41.128.0/17",
)
_CF_NETS = tuple(ipaddress.ip_network(p) for p in CF_PREFIXES)

# Домены/сервисы, по которым узнаётся CF-воркер (в т.ч. кастомные фронты)
WORKER_HOST_RX = re.compile(
    r"(workers\.dev|pages\.dev|\.kdns\.|\.vavava\.|\.cfdns\.|trycloudflare)", re.I)
WORKER_PATH_RX = re.compile(r"(proxyip|cmliussss)", re.I)

HTTP_PROTOS = ("http", "https", "socks5")


def _as_ip(host):
    try:
        return ipaddress.ip_address(str(host).strip().strip("[]"))
    except ValueError:
        return None


def ip_in_cf(host) -> bool:
    ip = _as_ip(host)
    if ip is None or ip.version != 4:
        return False
    return any(ip in net for net in _CF_NETS)


def is_http_like(node) -> bool:
    return str(node.get("protocol", "")).lower() in HTTP_PROTOS


def is_worker_like(node) -> bool:
    """«Воркерный» класс: vless/vmess через CF-домен или ws на CF-IP.

    Это рабочие, но перегруженные каналы: их не выкидываем, но ограничиваем
    долю в списках и опускаем в ранге относительно сопоставимых «прямых» нод.
    """
    proto = str(node.get("protocol", "")).lower()
    if proto not in ("vless", "vmess"):
        return False
    ws_host = str(node.get("ws_host") or "")
    if ws_host and WORKER_HOST_RX.search(ws_host):
        return True
    srv_name = str(node.get("servername") or "")
    if srv_name and WORKER_HOST_RX.search(srv_name):
        return True
    path = str(node.get("ws_path") or "")
    if path and WORKER_PATH_RX.search(path):
        return True
    if str(node.get("network", "")).lower() == "ws" and ip_in_cf(node.get("server", "")):
        return True
    return False


def backend_key(node):
    """Идентичность бэкенда: один воркер/сервер = один ключ.

    Для ws-туннелей с доменом-хостом (воркеры и любые фронты) ключ — по хосту,
    иначе — по server:port. Так десятки edge-IP одного воркера дают один ключ.
    """
    proto = str(node.get("protocol", "")).lower()
    cred = str(node.get("uuid") or node.get("password") or node.get("username") or "").lower()
    ws_host = str(node.get("ws_host") or "").lower().strip()
    if proto in ("vless", "vmess") and ws_host and _as_ip(ws_host) is None:
        return (proto, cred, "wshost:" + ws_host)
    return (proto, str(node.get("server", "")).lower(), int(node.get("port", 0) or 0), cred)


def subnet_key(node) -> str:
    """Ключ «/24-подсети»: по резолвнутому IP, если он есть, иначе по server."""
    ip = _as_ip(node.get("_ip") or node.get("server", ""))
    if ip is not None and ip.version == 4:
        return ".".join(str(ip).split(".")[:3])
    return "host:" + str(node.get("server", "")).lower()


def collapse_backends(nodes, rate_fn):
    """Схлопывает дубли одного бэкенда, оставляя лучший вход (по рангу).

    Один воркер через 100 edge-IP — это один и тот же канал, а не 100 нод.
    """
    best = {}
    for n in nodes:
        k = backend_key(n)
        cur = best.get(k)
        if cur is None or rank_key(n, rate_fn) < rank_key(cur, rate_fn):
            best[k] = n
    return list(best.values())


# ── ранжирование ─────────────────────────────────────────────────────────
WORKER_PENALTY = 0.15   # воркерные отстают от «прямых» при равной истории
HTTP_PENALTY = 0.06     # публичные http/socks5 чуть ниже туннелей при равенстве


def rank_score(node, rate_fn) -> float:
    try:
        rate = float(rate_fn(node))
    except Exception:
        rate = 0.5
    score = rate
    if is_worker_like(node):
        score -= WORKER_PENALTY
    if is_http_like(node):
        score -= HTTP_PENALTY
    return score


def rank_key(node, rate_fn):
    lat = node.get("latency_ms")
    try:
        lat = int(lat)
    except (TypeError, ValueError):
        lat = 99999
    return (
        -round(rank_score(node, rate_fn), 4),
        lat,
        str(node.get("server", "")).lower(),
        int(node.get("port", 0) or 0),
    )


# ── отбор с лимитами ─────────────────────────────────────────────────────

def _caps_for(limit: int):
    """Базовые лимиты (масштабируются при нехватке пула)."""
    if limit <= 60:
        subnet_cap, backend_cap = 3, 1
    elif limit <= 150:
        subnet_cap, backend_cap = 4, 1
    else:
        subnet_cap, backend_cap = 8, 2
    worker_cap = max(5, int(limit * 0.30))
    return subnet_cap, backend_cap, worker_cap


def select_quality(nodes, limit, rate_fn, http_share=0.5):
    """Жадный отбор: ранжирование + гарантия доли http/socks5 + лимиты.

    Возвращает список длиной <= limit, отсортированный по рангу.
    """
    if limit <= 0 or not nodes:
        return []

    ranked = sorted(nodes, key=lambda n: rank_key(n, rate_fn))
    http_pool = [n for n in ranked if is_http_like(n)]
    tun_pool = [n for n in ranked if not is_http_like(n)]
    want_http = min(len(http_pool), int(math.ceil(limit * http_share)))

    base_subnet, base_backend, base_worker = _caps_for(limit)
    picked = []
    picked_ids = set()
    subnets = {}
    backends = {}
    workers = 0
    http_count = 0

    def try_pick(n, subnet_cap, backend_cap, worker_cap):
        nonlocal workers, http_count
        nid = id(n)
        if nid in picked_ids:
            return
        sk = subnet_key(n)
        bk = backend_key(n)
        if subnets.get(sk, 0) >= subnet_cap:
            return
        if backends.get(bk, 0) >= backend_cap:
            return
        worker = is_worker_like(n)
        if worker and workers >= worker_cap:
            return
        picked_ids.add(nid)
        subnets[sk] = subnets.get(sk, 0) + 1
        backends[bk] = backends.get(bk, 0) + 1
        if worker:
            workers += 1
        if is_http_like(n):
            http_count += 1
        picked.append(n)

    for scale in (1, 2, 4):
        subnet_cap = base_subnet * scale
        backend_cap = base_backend * scale
        worker_cap = int(base_worker * (scale if scale > 1 else 1.35))
        # фаза 1: http/socks5 до целевой доли
        for n in http_pool:
            if http_count >= want_http:
                break
            if len(picked) >= limit:
                break
            try_pick(n, subnet_cap, backend_cap, worker_cap)
        # фаза 2: туннели до заполнения
        for n in tun_pool:
            if len(picked) >= limit:
                break
            try_pick(n, subnet_cap, backend_cap, worker_cap)
        if len(picked) >= limit:
            break

    # добор без лимитов — короткий список хуже, чем «сверхлимит по подсети»
    if len(picked) < limit:
        for n in ranked:
            if len(picked) >= limit:
                break
            if id(n) not in picked_ids:
                picked_ids.add(id(n))
                picked.append(n)

    return sorted(picked, key=lambda n: rank_key(n, rate_fn))


def describe(nodes) -> dict:
    """Сводка по отобранному списку — для логов."""
    subnets = {}
    backends = {}
    workers = 0
    http = 0
    for n in nodes:
        sk = subnet_key(n)
        backends[backend_key(n)] = backends.get(backend_key(n), 0) + 1
        subnets[sk] = subnets.get(sk, 0) + 1
        if is_worker_like(n):
            workers += 1
        if is_http_like(n):
            http += 1
    return {
        "count": len(nodes),
        "workers": workers,
        "http": http,
        "tunnels": len(nodes) - http,
        "unique_backends": len(backends),
        "max_per_subnet": max(subnets.values()) if subnets else 0,
    }
