import asyncio
import time

from backend.config import OUTPUT_FILE, load_sources
from backend.pipeline import run_pipeline, run_pipeline_from_nodes


class ProxyEngine:
    def __init__(self):
        self.cancel_event = asyncio.Event()
        self.status = "idle"
        self.metrics: dict = {
            "total_sources": 0, "current_source": 0,
            "candidates": 0, "deduped": 0,
            "checking_progress": 0, "checking_total": 0,
            "live": 0, "checker_rated": 0, "checker_filtered": 0,
            "geo_checked": 0, "selected": 0, "countries": 0,
        }
        self.events: asyncio.Queue = asyncio.Queue()

    def reset(self):
        self.cancel_event.clear()
        self.status = "running"
        self.metrics = {k: 0 for k in self.metrics}

    async def emit(self, event: str, data: dict | None = None):
        await self.events.put({"event": event, "data": data or {}, "time": time.time()})

    async def run(self, sources: list[str], local_files: list[str], opts: dict):
        self.reset()
        try:
            result = await run_pipeline(
                sources=sources,
                local_files=local_files,
                opts=opts,
                cancel_event=self.cancel_event,
                emit=self.emit,
            )

            self.status = result["status"]
            self.metrics.update(result["metrics"])

            if result["status"] == "done":
                await self.emit("status", {"status": "done", "message": result["message"]})
                await self.emit("done", {
                    "path": str(OUTPUT_FILE),
                    "count": result["metrics"]["selected"],
                })
            elif result["status"] == "cancelled":
                await self.emit("status", {"status": "cancelled", "message": "Отменено"})
            else:
                await self.emit("status", {"status": "error", "message": result["message"]})

        except Exception as e:
            self.status = "error"
            await self.emit("status", {"status": "error", "message": str(e)})
            await self.emit("log", {"level": "error", "text": f"Ошибка: {e}"})
        finally:
            # Гарантируем: статус никогда не застрянет в "running"
            if self.status == "running":
                self.status = "error"

    async def run_from_nodes(self, nodes: list[dict], opts: dict, source_label: str = "Proxy-Data"):
        self.reset()
        try:
            result = await run_pipeline_from_nodes(
                nodes=nodes,
                opts=opts,
                cancel_event=self.cancel_event,
                emit=self.emit,
                source_label=source_label,
            )

            self.status = result["status"]
            self.metrics.update(result["metrics"])

            if result["status"] == "done":
                await self.emit("status", {"status": "done", "message": result["message"]})
                await self.emit("done", {
                    "path": str(OUTPUT_FILE),
                    "count": result["metrics"]["selected"],
                })
            elif result["status"] == "cancelled":
                await self.emit("status", {"status": "cancelled", "message": "Отменено"})
            else:
                await self.emit("status", {"status": "error", "message": result["message"]})

        except Exception as e:
            self.status = "error"
            await self.emit("status", {"status": "error", "message": str(e)})
            await self.emit("log", {"level": "error", "text": f"Ошибка: {e}"})
        finally:
            if self.status == "running":
                self.status = "error"

    def cancel(self):
        self.cancel_event.set()

    @property
    def is_running(self) -> bool:
        return self.status == "running"
