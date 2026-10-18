"""
Headless-режим: запуск pipeline без FastAPI (для GitHub Actions / CLI).
"""
import asyncio
import os
import sys
import time

from backend.config import OUTPUT_FILE, ROOT, load_sources
from backend.pipeline import run_pipeline


async def _emit(event: str, data: dict) -> None:
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
        pass
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
        "limit": config.get("limit", 500),
        "max_checks": config.get("max_checks", 50000),
        "timeout": config.get("timeout", 8),
        "selection": config.get("selection", "fastest"),
        "producer_timeout": config.get("producer_timeout", 300),
        "per_repo_limit": config.get("per_repo_limit", 40),
        # Строгая проверка ядром клиента (mihomo): данные реально прошли через ноду.
        # Параметры — в sources.json; STRICT_VERIFY=0 в окружении выключает режим.
        "strict_verify": bool(config.get("strict_verify", True)) and os.environ.get("STRICT_VERIFY", "1") != "0",
        "verify_budget": config.get("verify_budget", 1500),
        "verify_target": config.get("verify_target"),
        "verify_conc": config.get("verify_conc", 300),
        "verify_batch": config.get("verify_batch", 450),
        "tunnel_checks": config.get("tunnel_checks"),
        "http_checks": config.get("http_checks"),
        "early_stop": config.get("early_stop", 0),
        "telegram_channels": config.get("telegram_channels", []),
        "telegram_pages": config.get("telegram_pages", 6),
        "use_pool": config.get("use_pool", True),
        "collapse_exit": config.get("collapse_exit", True),
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
        configs = result.get("configs", [])
        print(f"\n[+] Done: {selected} proxies, {countries} countries")
        print(f"[+] Generated configs: {', '.join(configs)}")
        for name in configs:
            fp = ROOT / name
            if fp.exists():
                print(f"    - {name} ({fp.stat().st_size} bytes)")
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
