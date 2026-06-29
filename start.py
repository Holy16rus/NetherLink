#!/usr/bin/env python3
"""HolyVPN Proxy Generator v2 — FastAPI + React"""
import os
import signal
import uvicorn

_force_exit = False

def _on_signal(signum, frame):
    global _force_exit
    if _force_exit:
        os._exit(0)
    _force_exit = True

if hasattr(signal, "SIGINT"):
    signal.signal(signal.SIGINT, _on_signal)
if hasattr(signal, "SIGTERM"):
    signal.signal(signal.SIGTERM, _on_signal)

# Windows: SelectorEventLoop вместо Proactor — убирает спам ConnectionResetError
if os.name == "nt":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


if __name__ == "__main__":
    config = uvicorn.Config(
        "backend.main:app",
        host="127.0.0.1",
        port=1488,
        reload=False,
        log_level="info",
        timeout_graceful_shutdown=3,
    )
    server = uvicorn.Server(config)
    try:
        server.run()
    except KeyboardInterrupt:
        pass
