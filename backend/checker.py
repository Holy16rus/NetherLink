import asyncio
import json
import os
import ssl
import tempfile
import time
from pathlib import Path

from backend.config import CHECK_CONCURRENCY

HTTP_TEST_HOST = "www.gstatic.com"
HTTP_TEST_REQUEST = (
    f"GET http://{HTTP_TEST_HOST}/generate_204 HTTP/1.1\r\n"
    f"Host: {HTTP_TEST_HOST}\r\n"
    "User-Agent: NetherLink/2.0\r\n"
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
            "User-Agent: NetherLink/2.0\r\n"
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


async def speed_test_node(node, timeout, cancel_event):
    """Измеряет пропускную способность прокси (скорость скачивания).
    Скачивает небольшой файл через прокси и замеряет скорость в Mbps.
    """
    protocol = node.get("protocol", "").lower()
    if protocol not in ("http", "https", "socks5"):
        return None
    if cancel_event.is_set():
        return None
    started = time.perf_counter()
    try:
        test_host = "speedtest.tele2.net"
        request = (
            f"GET /1MB.zip HTTP/1.1\r\n"
            f"Host: {test_host}\r\n"
            "User-Agent: NetherLink/3.0\r\n"
            "Connection: close\r\n\r\n"
        ).encode("ascii")
        total = 0
        if protocol in ("http", "https"):
            is_https = protocol == "https"
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
            writer.write(request)
            await writer.drain()
            while True:
                try:
                    chunk = await asyncio.wait_for(reader.read(65536), timeout=min(timeout, 5))
                    if not chunk:
                        break
                    total += len(chunk)
                except asyncio.TimeoutError:
                    break
                except Exception:
                    break
            writer.close()
            await writer.wait_closed()
        elif protocol == "socks5":
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(node["server"], int(node["port"])), timeout=timeout
            )
            username = node.get("username")
            if username:
                writer.write(b"\x05\x01\x02")
            else:
                writer.write(b"\x05\x01\x00")
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
            target = test_host.encode()
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
                f"GET /1MB.zip HTTP/1.1\r\n"
                f"Host: {test_host}\r\n"
                "User-Agent: NetherLink/3.0\r\n"
                "Connection: close\r\n\r\n"
            ).encode("ascii")
            writer.write(http_req)
            await writer.drain()
            while True:
                try:
                    chunk = await asyncio.wait_for(reader.read(65536), timeout=min(timeout, 5))
                    if not chunk:
                        break
                    total += len(chunk)
                except asyncio.TimeoutError:
                    break
                except Exception:
                    break
            writer.close()
            await writer.wait_closed()
        elapsed = time.perf_counter() - started
        if elapsed <= 0 or total < 10240:
            return None
        mbps = (total * 8) / (elapsed * 1_000_000)
        return round(mbps, 1)
    except Exception:
        return None


SING_BOX_BINARY = "/usr/local/bin/sing-box"


def _build_singbox_config(node: dict, socks_port: int) -> dict:
    """Строит минимальный sing-box конфиг с одним outbound на проверяемый прокси."""
    proto = node.get("protocol", "").lower()
    tag = f"test-{proto}"
    outbound = {"type": proto, "tag": tag, "server": node["server"], "server_port": int(node["port"])}

    if proto == "vmess":
        outbound["uuid"] = node.get("uuid", "")
        outbound["security"] = node.get("cipher", "auto")
        outbound["alter_id"] = int(node.get("alterId", 0))
        if node.get("tls"):
            outbound["tls"] = {"enabled": True, "server_name": node.get("servername", node["server"]), "insecure": True}
        if node.get("network") and node["network"] != "tcp":
            outbound["transport"] = {"type": node["network"]}
            if node.get("ws_path"):
                outbound["transport"]["path"] = node["ws_path"]
            if node.get("ws_host"):
                outbound["transport"]["headers"] = {"Host": node["ws_host"]}

    elif proto == "vless":
        outbound["uuid"] = node.get("uuid", "")
        flow = node.get("flow", "")
        if flow:
            outbound["flow"] = flow
        network = node.get("network", "tcp")
        if network != "tcp":
            outbound["transport"] = {"type": network}
        tls_fields = {}
        if node.get("tls"):
            tls_fields["enabled"] = True
            tls_fields["server_name"] = node.get("servername", node["server"])
            tls_fields["insecure"] = True
        if node.get("pbk"):
            tls_fields["enabled"] = True
            tls_fields["reality"] = {"enabled": True, "public_key": node["pbk"], "short_id": node.get("sid", "")}
            tls_fields["server_name"] = node.get("servername", node.get("sni", node["server"]))
        if tls_fields:
            outbound["tls"] = tls_fields

    elif proto == "trojan":
        outbound["password"] = node.get("password", "")
        outbound["tls"] = {"enabled": True, "server_name": node.get("servername", node.get("sni", node["server"])), "insecure": True}

    elif proto == "ss":
        outbound["method"] = node.get("cipher", "aes-256-gcm")
        outbound["password"] = node.get("password", "")

    elif proto == "hysteria2":
        outbound["password"] = node.get("password", "")
        outbound["tls"] = {"enabled": True, "server_name": node.get("servername", node.get("sni", node["server"])), "insecure": True}

    return {
        "log": {"level": "error"},
        "inbounds": [{"type": "socks", "listen": "127.0.0.1", "listen_port": socks_port, "tag": "socks-in"}],
        "outbounds": [outbound, {"type": "direct", "tag": "direct"}],
        "route": {"rules": [{"inbound": "socks-in", "outbound": tag}]},
    }


async def protocol_check(node, timeout, cancel_event):
    """Проверяет туннельный протокол через sing-box.
    Жёсткий таймаут: весь subprocess + HTTP запрос форсируется через asyncio.wait_for.
    """
    protocol = node.get("protocol", "").lower()
    if protocol in ("http", "https", "socks5"):
        return None
    if cancel_event.is_set():
        return None
    if not os.path.exists(SING_BOX_BINARY):
        return None

    socks_port = 0
    try:
        import socket as sock_lib
        s = sock_lib.socket(sock_lib.AF_INET, sock_lib.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        socks_port = s.getsockname()[1]
        s.close()
    except Exception:
        return None

    config = _build_singbox_config(node, socks_port)
    tmp_path = None
    process = None

    async def _inner():
        nonlocal process, tmp_path
        try:
            tmp_fd, tmp_path = tempfile.mkstemp(suffix=".json", prefix="singbox-")
            os.close(tmp_fd)
            Path(tmp_path).write_text(json.dumps(config, ensure_ascii=False), "utf-8")

            process = await asyncio.create_subprocess_exec(
                SING_BOX_BINARY, "run", "-c", tmp_path,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )

            started = time.perf_counter()
            deadline = started + timeout
            while time.perf_counter() < deadline:
                await asyncio.sleep(0.1)
                try:
                    reader, writer = await asyncio.wait_for(
                        asyncio.open_connection("127.0.0.1", socks_port),
                        timeout=1.0,
                    )
                    request = (
                        "GET /generate_204 HTTP/1.1\r\n"
                        "Host: www.gstatic.com\r\n"
                        "User-Agent: NetherLink/3.1\r\n"
                        "Connection: close\r\n\r\n"
                    ).encode("ascii")
                    writer.write(request)
                    await writer.drain()
                    data = await asyncio.wait_for(reader.read(512), timeout=3.0)
                    writer.close()
                    await writer.wait_closed()
                    if b"HTTP/" in data[:16]:
                        parts = data.split(b"\r\n")[0].split()
                        if len(parts) >= 2:
                            status = int(parts[1])
                            if 200 <= status < 400:
                                return int((time.perf_counter() - started) * 1000)
                    break
                except (asyncio.TimeoutError, ConnectionRefusedError, OSError, Exception):
                    pass
            return None
        finally:
            if process is not None and process.returncode is None:
                try:
                    process.terminate()
                except Exception:
                    pass
                try:
                    await asyncio.wait_for(process.wait(), timeout=3)
                except (asyncio.TimeoutError, Exception):
                    try:
                        process.kill()
                    except Exception:
                        pass
                    try:
                        await asyncio.wait_for(process.wait(), timeout=2)
                    except Exception:
                        pass
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

    try:
        return await asyncio.wait_for(_inner(), timeout=timeout + 5)
    except asyncio.TimeoutError:
        return None
    except Exception:
        return None
