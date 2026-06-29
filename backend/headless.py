"""
Headless-режим: запуск pipeline без FastAPI (для GitHub Actions / CLI).
"""
import asyncio
import sys
import time

from backend.config import OUTPUT_FILE, load_sources
from backend.pipeline import run_pipeline


async def _emit(event: str, data: dict) -> None:
    """Простой stdout-вывод вместо SSE."""
    if event == "status":
        msg = data.get("message", "")
        status = data.get("status", "")
        prefix = {"running": "[>]", "done": "[+]", "error": "[!]", "cancelled": "[x]"}.get(status, "[*]")
        print(f"  {prefix} {msg}")
    elif event == "log":
        level = data.get("level", "info")
        prefix = {"error": "[!]", "warn": "[~]"}.get(level, "   ")
        print(f"  {prefix} {data.get('text', '')}")
    elif event == "metrics":
        pass  # headless не нужен real-time метрик в stdout
    elif event == "geo_points":
        pts = len(data.get("points", []))
        if pts:
            print(f"  [+] Geo points: {pts}")


async def run():
    config = load_sources()
    sources = [
        s.get("url") if isinstance(s, dict) else s
        for s in config.get("sources", [])
        if not isinstance(s, dict) or s.get("enabled", True)
    ]
    local_files = config.get("local_files", ["proxy.txt"])

    print(f"[*] Sources: {len(sources)} remote, {len(local_files)} local")

    opts = {
        "limit": 500,
        "max_checks": 10000,
        "timeout": 8,
        "selection": "fastest",
        "prefer_socks5": True,
    }

    cancel = asyncio.Event()

    result = await run_pipeline(
        sources=sources,
        local_files=local_files,
        opts=opts,
        cancel_event=cancel,
        emit=_emit,
    )

    status = result["status"]
    m = result["metrics"]

    if status == "done":
        countries = m.get("countries", 0)
        selected = m.get("selected", 0)
        print(f"\n[+] Done: {selected} proxies, {countries} countries")
        print(f"[+] Config saved: {OUTPUT_FILE}")
    elif status == "error":
        print(f"\n[!] Failed: {result['message']}", file=sys.stderr)
        sys.exit(1)
    elif status == "cancelled":
        print("\n[x] Cancelled", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    start = time.time()
    asyncio.run(run())
    print(f"\n[+] Total time: {time.time() - start:.1f}s")
