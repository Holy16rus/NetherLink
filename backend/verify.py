"""Строгая проверка нод — ядром, которое стоит в клиенте (mihomo = ядро FLClash).

Зачем: прежний чекер мерил TCP-коннект и HTTP 204 на gstatic по порту 80.
Так «живыми» считались HTTP-прокси без CONNECT/443, воркеры с мёртвым бэкендом,
туннели, что рукопожимаются, но не качают. Итог — ~85% мёртвых в подписке.

Нода живая только если через неё РЕАЛЬНО прошли данные по HTTPS с проверкой
сертификата (нода не может подменить трафик):
  1. проба  https://cp.cloudflare.com/generate_204 | https://www.gstatic.com/generate_204
  2. закачка >= 200 КБ  https://speed.cloudflare.com/__down?bytes=262144
                        | https://cachefly.cachefly.net/1mb.test
Достаточно любой цели из пары — IP выхода ноды может быть в бане у одного CDN.

Что проверили — то и отдали: нода превращается в Clash-прокси тем же
`generate_config_clash`, mihomo поднимает по отдельному локальному порту
(listeners → proxy) на каждую ноду, проба идёт SOCKS5 → CONNECT → TLS в чистом asyncio
(без curl на каждую ноду — это в 10 раз легче по CPU и позволяет сотни параллельно).

Ноды, которые mihomo не принимает при загрузке (`mihomo -t`), выкидываются по номеру
прокси из ошибки (иначе один плохой шифр/ключ убивает весь батч).
"""
import asyncio
import os
import re
import shutil
import socket
import ssl
import tempfile
import time
from pathlib import Path

from backend.generator import generate_config_clash

PROBE_TARGETS = (
    ("cp.cloudflare.com", "/generate_204"),
    ("www.gstatic.com", "/generate_204"),
)
DL_TARGETS = (
    ("speed.cloudflare.com", "/__down?bytes=262144"),
    ("cachefly.cachefly.net", "/1mb.test"),
)
DL_MIN_BYTES = 200_000
PROBE_TIMEOUT = float(os.environ.get("VERIFY_PROBE_TIMEOUT", "8"))
DL_TIMEOUT = float(os.environ.get("VERIFY_DL_TIMEOUT", "12"))

_PORT_BASE = 30000
_SSL_CTX: ssl.SSLContext | None = None


def _ssl_ctx() -> ssl.SSLContext:
    global _SSL_CTX
    if _SSL_CTX is None:
        _SSL_CTX = ssl.create_default_context()
    return _SSL_CTX


def find_mihomo() -> str | None:
    home = os.path.expanduser("~")
    candidates = [
        os.environ.get("MIHOMO_BINARY", ""),
        "/usr/local/bin/mihomo",
        os.path.join(home, "bin", "mihomo"),
        "/usr/bin/mihomo",
        shutil.which("mihomo") or "",
    ]
    for path in candidates:
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def _port_free(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _pick_base_port(slot: int, count: int) -> int:
    """Диапазон локальных портов под батч (проверяем, что он свободен)."""
    base = _PORT_BASE + slot * 1000
    for shift in range(0, 30000, 1000 * 4):
        b = base + shift
        if _port_free(b) and _port_free(b + count - 1):
            return b
    return base


def build_verify_config(batch: list[dict], base_port: int) -> str:
    """Clash-конфиг: прокси (как в подписке) + по listener-порту на каждый."""
    saved = [n.get("name") for n in batch]
    for i, n in enumerate(batch):
        n["name"] = f"v{i}"
    try:
        text = generate_config_clash(batch)
    finally:
        for n, old in zip(batch, saved):
            if old is None:
                n.pop("name", None)
            else:
                n["name"] = old
    a = text.index("\nproxies:")
    b = text.find("\nproxy-groups:")
    proxies_block = text[a:b] if b > a else text[a:]
    listeners = "".join(
        f"  - name: l{i}\n    type: mixed\n    listen: 127.0.0.1\n"
        f"    port: {base_port + i}\n    proxy: v{i}\n"
        for i in range(len(batch))
    )
    return (
        "allow-lan: false\nmode: rule\nlog-level: error\nipv6: false\n"
        + proxies_block.rstrip() + "\n\nlisteners:\n" + listeners
        + "\nrules:\n  - MATCH,DIRECT\n"
    )


async def _mihomo_test_cfg(mihomo: str, cfg_path: str, workdir: str) -> tuple[bool, str]:
    proc = await asyncio.create_subprocess_exec(
        mihomo, "-t", "-f", cfg_path, "-d", workdir,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=90)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        return False, "timeout"
    return proc.returncode == 0, out.decode("utf-8", "replace")


async def prune_invalid(mihomo: str, batch: list[dict], workdir: str, base_port: int) -> list[dict]:
    """Выкидывает ноды, на которых mihomo -t падает (по номеру из ошибки / бисекцией)."""
    cfg_path = os.path.join(workdir, "validate.yaml")
    current = list(batch)
    for _ in range(80):
        if not current:
            return []
        Path(cfg_path).write_text(build_verify_config(current, base_port), "utf-8")
        ok, out = await _mihomo_test_cfg(mihomo, cfg_path, workdir)
        if ok:
            return current
        m = re.search(r"proxy (\d+)\b", out)
        if m and int(m.group(1)) < len(current):
            del current[int(m.group(1))]
            continue
        break
    if len(current) <= 1:
        return []
    mid = len(current) // 2
    return (await prune_invalid(mihomo, current[:mid], workdir, base_port)
            + await prune_invalid(mihomo, current[mid:], workdir, base_port))


async def _socks_tls_get(port: int, host: str, path: str, timeout: float,
                         want_bytes: int = 0) -> tuple[int, int] | None | str:
    """GET https://host/path через локальный SOCKS5-listener -> (http_status, body_bytes).

    Возвращает None при явной ошибке (отказ SOCKS, не-HTTP ответ, обрыв) и строку
    "timeout" при таймауте: по таймауту нода, скорее всего, мертва, и пробовать
    вторую цель смысла нет (экономит ×2 времени на мёртвых).

    want_bytes > 0: читаем тело, пока не наберём want_bytes (или EOF/таймаут).
    """
    writer = None
    try:
        async def _run():
            nonlocal writer
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(b"\x05\x01\x00")
            await writer.drain()
            if await reader.readexactly(2) != b"\x05\x00":
                return None
            hb = host.encode()
            writer.write(b"\x05\x01\x00\x03" + bytes([len(hb)]) + hb + (443).to_bytes(2, "big"))
            await writer.drain()
            resp = await reader.readexactly(4)
            if resp[1] != 0:
                return None
            atyp = resp[3]
            if atyp == 1:
                await reader.readexactly(4 + 2)
            elif atyp == 3:
                ln = (await reader.readexactly(1))[0]
                await reader.readexactly(ln + 2)
            elif atyp == 4:
                await reader.readexactly(16 + 2)
            await writer.start_tls(_ssl_ctx(), server_hostname=host)
            writer.write(
                (f"GET {path} HTTP/1.1\r\nHost: {host}\r\nUser-Agent: NetherLink-verify/1\r\n"
                 "Accept: */*\r\nAccept-Encoding: identity\r\nConnection: close\r\n\r\n").encode())
            await writer.drain()
            buf = b""
            while b"\r\n\r\n" not in buf:
                chunk = await reader.read(4096)
                if not chunk:
                    return None
                buf += chunk
                if len(buf) > 65536:
                    return None
            head, _, body = buf.partition(b"\r\n\r\n")
            parts = head.split(b"\r\n", 1)[0].split()
            if len(parts) < 2 or not parts[0].startswith(b"HTTP/"):
                return None
            status = int(parts[1])
            got = len(body)
            while want_bytes and got < want_bytes:
                chunk = await reader.read(65536)
                if not chunk:
                    break
                got += len(chunk)
            return status, got
        return await asyncio.wait_for(_run(), timeout=timeout)
    except asyncio.TimeoutError:
        return "timeout"
    except Exception:
        return None
    finally:
        if writer is not None:
            try:
                writer.close()
            except Exception:
                pass


async def _check_port(port: int, sem: asyncio.Semaphore) -> dict | None:
    async with sem:
        probe_ms = None
        for host, path in PROBE_TARGETS:
            t0 = time.perf_counter()
            r = await _socks_tls_get(port, host, path, PROBE_TIMEOUT)
            if isinstance(r, tuple) and r[0] in (200, 204):
                probe_ms = max(1, int((time.perf_counter() - t0) * 1000))
                break
            if r == "timeout":
                break  # мертва/зависла — вторая цель не поможет
        if probe_ms is None:
            return None
        for host, path in DL_TARGETS:
            t0 = time.perf_counter()
            r = await _socks_tls_get(port, host, path, DL_TIMEOUT, want_bytes=DL_MIN_BYTES)
            if isinstance(r, tuple) and r[0] in (200, 206) and r[1] >= DL_MIN_BYTES:
                el = max(0.001, time.perf_counter() - t0)
                return {"latency_ms": probe_ms, "kbps": round(r[1] / 1024 / el, 1)}
            if r == "timeout":
                break
        return None


async def _fetch(port: int, host: str, path: str, timeout: float, *, tls: bool = True,
                 dport: int | None = None, max_body: int = 0, headers: dict | None = None,
                 http10: bool = False) -> tuple[int, bytes] | None:
    """GET через локальный SOCKS5-listener -> (http_status, body[:max_body]) | None.

    Универсальный вариант `_socks_tls_get`: умеет обычный HTTP (tls=False, порт 80)
    и возвращает тело — нужно для trace, проверки целостности и сервисных проб.
    http10=True — без chunked в ответе (ровный хеш тела).
    """
    writer = None
    try:
        async def _run():
            nonlocal writer
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(b"\x05\x01\x00")
            await writer.drain()
            if await reader.readexactly(2) != b"\x05\x00":
                return None
            hb = host.encode()
            target_port = dport or (443 if tls else 80)
            writer.write(b"\x05\x01\x00\x03" + bytes([len(hb)]) + hb + target_port.to_bytes(2, "big"))
            await writer.drain()
            resp = await reader.readexactly(4)
            if resp[1] != 0:
                return None
            atyp = resp[3]
            if atyp == 1:
                await reader.readexactly(4 + 2)
            elif atyp == 3:
                ln = (await reader.readexactly(1))[0]
                await reader.readexactly(ln + 2)
            elif atyp == 4:
                await reader.readexactly(16 + 2)
            if tls:
                await writer.start_tls(_ssl_ctx(), server_hostname=host)
            extra = "".join(f"{k}: {v}\r\n" for k, v in (headers or {}).items())
            ver = "1.0" if http10 else "1.1"
            writer.write((f"GET {path} HTTP/{ver}\r\nHost: {host}\r\nUser-Agent: NetherLink-verify/1\r\n"
                          f"Accept: */*\r\nAccept-Encoding: identity\r\n{extra}Connection: close\r\n\r\n").encode())
            await writer.drain()
            buf = b""
            while b"\r\n\r\n" not in buf:
                chunk = await reader.read(4096)
                if not chunk:
                    return None
                buf += chunk
                if len(buf) > 65536:
                    return None
            head, _, body = buf.partition(b"\r\n\r\n")
            parts = head.split(b"\r\n", 1)[0].split()
            if len(parts) < 2 or not parts[0].startswith(b"HTTP/"):
                return None
            status = int(parts[1])
            body = bytearray(body)
            while max_body and len(body) < max_body:
                chunk = await reader.read(65536)
                if not chunk:
                    break
                body += chunk
            return status, bytes(body[:max_body]) if max_body else b""
        return await asyncio.wait_for(_run(), timeout=timeout)
    except Exception:
        return None
    finally:
        if writer is not None:
            try:
                writer.close()
            except Exception:
                pass


# ── расширенные проверки: проходят ТОЛЬКО ноды, уже прошедшие базовую проверку ──
# Сервисы: нода может качать с CDN и всё равно не открывать Telegram/YouTube/ИИ
# (выходной IP в бане у сервиса). Ожидаемые статусы подобраны по замерам.
SERVICES = {
    "tg": ("api.telegram.org", "/", {200, 301, 302, 404}),
    "yt": ("www.youtube.com", "/generate_204", {204}),
    "ai": ("api.openai.com", "/v1/models", {401}),   # 401 = регион принят; 403 = блок
}
INTEGRITY_HOST = "cachefly.cachefly.net"
INTEGRITY_PATH = "/1mb.test"
INTEGRITY_BYTES = 262144
EXTRAS_ON = os.environ.get("VERIFY_EXTRAS", "1") != "0"


def reference_hash() -> str | None:
    """Эталонный sha256 первых 256 КБ тестового файла — прямым HTTPS-запросом (с раннера).

    Не хардкод: если CDN сменит файл, эталон обновится сам. Нет эталона — проверка
    целостности пропускается (не отбрасываем ноды вслепую)."""
    import hashlib
    import urllib.request
    try:
        req = urllib.request.Request(
            f"https://{INTEGRITY_HOST}{INTEGRITY_PATH}",
            headers={"Range": f"bytes=0-{INTEGRITY_BYTES - 1}", "User-Agent": "NetherLink-verify/1"})
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read(INTEGRITY_BYTES)
        return hashlib.sha256(body).hexdigest() if len(body) >= INTEGRITY_BYTES else None
    except Exception:
        return None


async def _node_extras(port: int, ref_hash: str | None) -> dict:
    """Выходной IP/страна (CF trace), доступность сервисов, целостность plain-HTTP."""
    import hashlib
    info: dict = {}
    trace, *svc_res = await asyncio.gather(
        _fetch(port, "cloudflare.com", "/cdn-cgi/trace", 8, max_body=4096),
        *(_fetch(port, h, p, 8) for h, p, _ in SERVICES.values()),
    )
    if trace and trace[0] == 200:
        txt = trace[1].decode("utf-8", "replace")
        m = re.search(r"(?m)^ip=(\S+)", txt)
        if m:
            info["exit_ip"] = m.group(1)
        m = re.search(r"(?m)^loc=([A-Za-z]{2})\b", txt)
        if m and m.group(1).upper() not in ("XX", "T1"):
            info["exit_loc"] = m.group(1).upper()
    info["svc"] = [key for (key, (_, _, ok)), r in zip(SERVICES.items(), svc_res) if r and r[0] in ok]
    if ref_hash:
        r = await _fetch(port, INTEGRITY_HOST, INTEGRITY_PATH, 15, tls=False,
                         max_body=INTEGRITY_BYTES, http10=True,
                         headers={"Range": f"bytes=0-{INTEGRITY_BYTES - 1}"})
        if r and r[0] in (200, 206) and len(r[1]) >= INTEGRITY_BYTES:
            info["integrity"] = hashlib.sha256(r[1][:INTEGRITY_BYTES]).hexdigest() == ref_hash
    return info


async def _wait_listener(port: int, deadline_s: float = 20.0) -> bool:
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < deadline_s:
        try:
            _, w = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", port), 0.8)
            w.close()
            await w.wait_closed()
            return True
        except Exception:
            await asyncio.sleep(0.2)
    return False


async def verify_batch(mihomo: str, batch: list[dict], slot: int, conc: int,
                       cancel_event: asyncio.Event | None = None,
                       ref_hash: str | None = None) -> tuple[list[dict], list[dict]]:
    """Возвращает (прошедшие, проверенные). Прошедшие дополнены latency_ms/kbps/verified
    и (если EXTRAS_ON) exit_ip/exit_loc/svc/integrity. Подменяющие трафик ноды отбрасываются."""
    workdir = tempfile.mkdtemp(prefix="nl-verify-")
    proc = None
    try:
        base = _pick_base_port(slot, len(batch))
        valid = await prune_invalid(mihomo, batch, workdir, base)
        if not valid:
            return [], []
        cfg_path = os.path.join(workdir, "run.yaml")
        Path(cfg_path).write_text(build_verify_config(valid, base), "utf-8")
        proc = await asyncio.create_subprocess_exec(
            mihomo, "-f", cfg_path, "-d", workdir,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        if not await _wait_listener(base + len(valid) - 1):
            return [], valid
        sem = asyncio.Semaphore(conc)
        xsem = asyncio.Semaphore(100)

        async def one(i: int, node: dict) -> dict | None:
            if cancel_event is not None and cancel_event.is_set():
                return None
            res = await _check_port(base + i, sem)
            if res is None:
                return None
            node["latency_ms"] = res["latency_ms"]
            node["kbps"] = res["kbps"]
            node["verified"] = True
            if EXTRAS_ON:
                async with xsem:
                    info = await _node_extras(base + i, ref_hash)
                node["exit_ip"] = info.get("exit_ip")
                node["exit_loc"] = info.get("exit_loc")
                node["svc"] = info.get("svc", [])
                node["integrity"] = info.get("integrity")
                if info.get("integrity") is False:
                    node["tampered"] = True
                    return None          # подменяет трафик — в подписку нельзя
                if info.get("exit_loc"):
                    node["country"] = info["exit_loc"]   # страна ВЫХОДА, а не метка источника
            return node

        results = await asyncio.gather(*(one(i, n) for i, n in enumerate(valid)))
        passed = [n for n in results if n is not None]

        # Честная задержка: основная проверка шла под нагрузкой (сотни параллельно) —
        # там latency раздута очередью. Для имён нод и ранга перемеряем у прошедших
        # низкой конкурентностью, лучшая из двух попыток.
        idx_of = {id(n): i for i, n in enumerate(valid)}
        lsem = asyncio.Semaphore(30)

        async def relat(n):
            async with lsem:
                best = None
                for _ in range(2):
                    t0 = time.perf_counter()
                    r = await _fetch(base + idx_of[id(n)], PROBE_TARGETS[0][0], PROBE_TARGETS[0][1], 6)
                    if r and r[0] in (200, 204):
                        ms = max(1, int((time.perf_counter() - t0) * 1000))
                        best = ms if best is None else min(best, ms)
                if best is not None:
                    n["latency_ms"] = best

        await asyncio.gather(*(relat(n) for n in passed))
        return passed, valid
    finally:
        if proc is not None and proc.returncode is None:
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=4)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        shutil.rmtree(workdir, ignore_errors=True)


async def verify_nodes(nodes: list[dict], cancel_event: asyncio.Event | None = None, *,
                       conc: int = 300, batch_size: int = 400, parallel: int = 1,
                       deadline: float | None = None, target: int | None = None,
                       emit=None) -> tuple[list[dict], list[dict]]:
    """Проверяет ноды батчами в заданном порядке. Возвращает (прошедшие, реально проверенные).

    deadline — time.monotonic()-метка: после неё новые батчи не стартуют.
    target   — остановиться, когда набрано столько прошедших.
    """
    mihomo = find_mihomo()
    if not mihomo:
        raise RuntimeError("mihomo не найден (MIHOMO_BINARY / ~/bin/mihomo / PATH)")
    ref_hash = await asyncio.to_thread(reference_hash) if EXTRAS_ON else None
    if emit is not None and EXTRAS_ON:
        await emit("log", {"level": "info",
                           "text": "Verify: эталон целостности " + ("получен" if ref_hash else "недоступен — проверка целостности пропущена")})
    batches = [nodes[i:i + batch_size] for i in range(0, len(nodes), batch_size)]
    passed_all: list[dict] = []
    checked_all: list[dict] = []
    queue: asyncio.Queue = asyncio.Queue()
    for idx, b in enumerate(batches):
        queue.put_nowait((idx, b))
    t0 = time.monotonic()

    async def log(text):
        if emit is not None:
            await emit("log", {"level": "info", "text": text})

    async def worker(slot: int):
        while True:
            if cancel_event is not None and cancel_event.is_set():
                return
            if deadline is not None and time.monotonic() >= deadline:
                return
            if target is not None and len(passed_all) >= target:
                return
            try:
                idx, b = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                passed, checked = await verify_batch(mihomo, b, slot, conc, cancel_event, ref_hash)
            except Exception as e:  # сбойный батч не должен валить прогон
                await log(f"Verify: батч {idx + 1}/{len(batches)} сбой: {type(e).__name__}: {e}")
                continue
            passed_all.extend(passed)
            checked_all.extend(checked)
            tampered = sum(1 for n in checked if n.get("tampered"))
            await log(f"Verify: батч {idx + 1}/{len(batches)} — живых {len(passed)}/{len(checked)}"
                      + (f", подмена трафика: {tampered}" if tampered else "")
                      + f"; итого {len(passed_all)}/{len(checked_all)} ({time.monotonic() - t0:.0f}с)")

    await asyncio.gather(*(worker(s) for s in range(max(1, parallel))))
    return passed_all, checked_all
