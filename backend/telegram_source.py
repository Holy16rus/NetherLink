"""Telegram-каналы как источник нод (публичный веб-просмотр t.me/s/<канал>).

Ноды из каналов свежее, чем файлы агрегаторов: их постят по мере появления,
а мёртвые уходят вниз ленты. Берём последние страницы канала (по ~20 постов,
листаем назад через ?before=<id>), вытаскиваем URI vless/vmess/trojan/ss/hy2.

Доступ: с раннера GitHub t.me открыт напрямую. С российского сервера t.me
режется — тогда нужен прокси (env TG_PROXY, напр. socks5h://127.0.0.1:1080 —
наш ssh-туннель); с прокси идём через curl (httpx[socks] не тянем).
"""
import asyncio
import html
import os
import re
import shutil

import httpx

from backend.parser import parse_uri

URI_RE = re.compile(r"(?:vless|vmess|trojan|ss|hysteria2|hy2)://[^\s\"'<>`]+", re.I)
POST_RE = re.compile(r'data-post="[^"/]+/(\d+)"')
BR_RE = re.compile(r"<br\s*/?>", re.I)

DEFAULT_PAGES = 6        # ~120 последних постов на канал
CHANNEL_CONC = 4         # t.me не любит шквал — по 4 канала одновременно


def _proxy() -> str:
    return os.environ.get("TG_PROXY", "").strip()


async def _get_page(client: httpx.AsyncClient | None, channel: str, before: int | None,
                    proxy: str) -> str:
    url = f"https://t.me/s/{channel}" + (f"?before={before}" if before else "")
    if proxy:
        curl = shutil.which("curl")
        if not curl:
            return ""
        proc = await asyncio.create_subprocess_exec(
            curl, "-s", "--max-time", "25", "-x", proxy, "-A", "Mozilla/5.0", url,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            return ""
        return out.decode("utf-8", "replace")
    try:
        resp = await client.get(url, timeout=25, headers={"User-Agent": "Mozilla/5.0"}) if client else None
        return resp.text if resp is not None and resp.status_code == 200 else ""
    except Exception:
        return ""


def _extract(text: str, channel: str) -> list[dict]:
    """HTML страницы -> ноды (br -> перенос строки, html-сущности раскрыты)."""
    text = html.unescape(BR_RE.sub("\n", text))
    nodes = []
    for m in URI_RE.finditer(text):
        uri = m.group(0).strip().rstrip(".,;)]}")
        n = parse_uri(uri, "ZZ", f"tg:{channel}")
        if n:
            n["_src"] = f"tg:{channel}"
            nodes.append(n)
    return nodes


async def fetch_channel(client: httpx.AsyncClient | None, channel: str, pages: int,
                        proxy: str) -> list[dict]:
    channel = channel.lstrip("@")
    nodes: list[dict] = []
    before = None
    for _ in range(max(1, pages)):
        page = await _get_page(client, channel, before, proxy)
        if not page:
            break
        ids = [int(x) for x in POST_RE.findall(page)]
        nodes.extend(_extract(page, channel))
        if not ids or min(ids) <= 1:
            break
        before = min(ids)
    return nodes


async def fetch_telegram_nodes(channels: list[str], pages: int = DEFAULT_PAGES,
                               cancel_event: asyncio.Event | None = None,
                               on_channel=None) -> tuple[list[dict], dict]:
    """-> (ноды, {канал: сколько нод}).

    on_channel(channel, nodes) — корутина, вызывается СРАЗУ по готовности канала: так
    ноды уходят в очередь проверки по мере поступления, а не пачкой в конце (иначе
    отмена по таймауту сбора теряет всё, что уже скачано)."""
    proxy = _proxy()
    sem = asyncio.Semaphore(CHANNEL_CONC)
    per: dict[str, int] = {}
    out: list[dict] = []
    client = None if proxy else httpx.AsyncClient(follow_redirects=True)

    async def one(ch):
        if cancel_event is not None and cancel_event.is_set():
            return
        async with sem:
            nodes = await fetch_channel(client, ch, pages, proxy)
        per[ch.lstrip("@")] = len(nodes)
        out.extend(nodes)
        if on_channel is not None and nodes:
            await on_channel(ch.lstrip("@"), nodes)

    try:
        await asyncio.gather(*(one(c) for c in channels))
    finally:
        if client is not None:
            await client.aclose()
    return out, per
