import asyncio
import ssl
import time

from backend.config import CHECK_CONCURRENCY

HTTP_TEST_HOST = "www.gstatic.com"
HTTP_TEST_REQUEST = (
    f"GET http://{HTTP_TEST_HOST}/generate_204 HTTP/1.1\r\n"
    f"Host: {HTTP_TEST_HOST}\r\n"
    "User-Agent: HolyVPN-Proxy-Generator/2.0\r\n"
    "Proxy-Connection: close\r\n"
    "Connection: close\r\n\r\n"
).encode("ascii")

SOCKS5_INIT = b"\x05\x01\x00"
SOCKS5_AUTH = b"\x05\x01\x02"


async def tcp_check(node, timeout):
    started = time.perf_counter()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(node["server"], int(node["port"])), timeout=timeout
        )
        writer.close()
        await writer.wait_closed()
        return int((time.perf_counter() - started) * 1000)
    except Exception:
        return None


async def http_check(node, timeout):
    started = time.perf_counter()
    is_https = node.get("protocol", "").lower() == "https"
    try:
        if is_https:
            ctx = ssl._create_unverified_context()
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(node["server"], int(node["port"]), ssl=ctx),
                timeout=timeout,
            )
        else:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(node["server"], int(node["port"])),
                timeout=timeout,
            )
        writer.write(HTTP_TEST_REQUEST)
        await writer.drain()
        data = await asyncio.wait_for(reader.read(512), timeout=timeout)
        writer.close()
        await writer.wait_closed()
        if b"HTTP/" not in data[:16]:
            return None
        status_line = data.split(b"\r\n")[0]
        parts = status_line.split()
        if len(parts) < 2:
            return None
        status = int(parts[1])
        if status == 407:
            return None
        if status < 200 or status >= 400:
            return None
        return int((time.perf_counter() - started) * 1000)
    except Exception:
        return None


async def socks5_check(node, timeout):
    started = time.perf_counter()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(node["server"], int(node["port"])), timeout=timeout
        )

        # Auth negotiation
        username = node.get("username")
        if username:
            writer.write(SOCKS5_AUTH)
        else:
            writer.write(SOCKS5_INIT)
        await writer.drain()
        response = await asyncio.wait_for(reader.readexactly(2), timeout=timeout)
        if response[0] != 5 or response[1] == 255:
            raise Exception("bad SOCKS5")

        if response[1] == 2:
            ub = str(username).encode("utf-8")[:255]
            pb = str(node.get("password", "")).encode("utf-8")[:255]
            writer.write(bytes([1, len(ub)]) + ub + bytes([len(pb)]) + pb)
            await writer.drain()
            auth_resp = await asyncio.wait_for(reader.readexactly(2), timeout=timeout)
            if auth_resp != b"\x01\x00":
                raise Exception("SOCKS5 auth failed")

        target = HTTP_TEST_HOST.encode()
        writer.write(b"\x05\x01\x00\x03" + bytes([len(target)]) + target + (80).to_bytes(2, "big"))
        await writer.drain()
        connect_resp = await asyncio.wait_for(reader.readexactly(4), timeout=timeout)
        if connect_resp[0] != 5 or connect_resp[1] != 0:
            raise Exception("SOCKS5 connect failed")

        addr_type = connect_resp[3]
        if addr_type == 1:
            await asyncio.wait_for(reader.readexactly(4), timeout=timeout)
        elif addr_type == 3:
            addr_len = await asyncio.wait_for(reader.readexactly(1), timeout=timeout)
            await asyncio.wait_for(reader.readexactly(addr_len[0]), timeout=timeout)
        elif addr_type == 4:
            await asyncio.wait_for(reader.readexactly(16), timeout=timeout)
        await asyncio.wait_for(reader.readexactly(2), timeout=timeout)

        http_req = (
            f"GET /generate_204 HTTP/1.1\r\n"
            f"Host: {HTTP_TEST_HOST}\r\n"
            "User-Agent: HolyVPN-Proxy-Generator/2.0\r\n"
            "Connection: close\r\n\r\n"
        ).encode("ascii")
        writer.write(http_req)
        await writer.drain()
        data = await asyncio.wait_for(reader.read(512), timeout=timeout)
        writer.close()
        await writer.wait_closed()
        if b"HTTP/" not in data[:16]:
            return None
        status_line = data.split(b"\r\n")[0]
        status = int(status_line.split()[1])
        if status < 200 or status >= 400:
            return None
        return int((time.perf_counter() - started) * 1000)
    except Exception:
        return None


async def check_node(node, timeout, cancel_event):
    if cancel_event.is_set():
        return None
    protocol = node.get("protocol", "").lower()
    # Complex protocols (VMess/VLESS/Trojan/SS/Hysteria2) only get TCP check
    # — use a shorter timeout since we're just testing reachability
    effective_timeout = timeout if protocol in {"http", "https", "socks5"} else min(timeout, 5)
    try:
        if protocol in {"http", "https"}:
            latency = await http_check(node, effective_timeout)
        elif protocol == "socks5":
            latency = await socks5_check(node, effective_timeout)
        else:
            latency = await tcp_check(node, effective_timeout)
    except Exception:
        return None
    if latency is None:
        return None
    checked = dict(node)
    checked["latency_ms"] = latency
    return checked


async def check_batch(nodes, timeout, cancel_event, progress_cb=None):
    live = []
    total = len(nodes)
    sem = asyncio.Semaphore(CHECK_CONCURRENCY)

    async def check_one(node):
        if cancel_event.is_set():
            return None
        async with sem:
            return await check_node(node, timeout, cancel_event)

    tasks = [check_one(node) for node in nodes]
    for i, task in enumerate(asyncio.as_completed(tasks)):
        if cancel_event.is_set():
            break
        result = await task
        if result:
            live.append(result)
        if progress_cb and ((i + 1) % 50 == 0 or (i + 1) == total):
            await progress_cb(i + 1, total, len(live))

    live.sort(key=lambda n: n.get("latency_ms", 999999))
    return live
