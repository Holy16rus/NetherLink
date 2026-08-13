import asyncio
import json
import os
import mimetypes

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

from backend.config import OUTPUT_FILE, SOURCES_FILE, ROOT, load_sources, save_sources
from backend.engine import ProxyEngine
from backend.pipeline import parse_live_file

app = FastAPI(title="NetherLink")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

engine = ProxyEngine()


class SourcesPayload(BaseModel):
    sources: list = []
    local_files: list = []


class GeneratePayload(BaseModel):
    limit: int = 500
    max_checks: int = 10000
    timeout: float = 10
    selection: str = "fastest"


@app.get("/api/config")
async def get_config():
    config = load_sources()
    return {
        "sources": config.get("sources", []),
        "local_files": config.get("local_files", ["proxy.txt"]),
        "output": OUTPUT_FILE.name,
    }


@app.post("/api/config")
async def post_config(payload: SourcesPayload):
    data = {"sources": payload.sources, "local_files": payload.local_files or ["proxy.txt"]}
    save_sources(data)
    return {"ok": True}


@app.post("/api/generate")
async def start_generate(payload: GeneratePayload):
    if engine.is_running:
        raise HTTPException(409, "Генерация уже запущена")

    config = load_sources()
    sources = [s.get("url") if isinstance(s, dict) else s for s in config.get("sources", [])
               if not isinstance(s, dict) or s.get("enabled", True)]
    local_files = config.get("local_files", ["proxy.txt"])

    opts = {
        "limit": max(1, payload.limit),
        "max_checks": max(0, payload.max_checks),
        "timeout": max(1, payload.timeout),
        "selection": payload.selection if payload.selection in {"fastest", "balanced"} else "fastest",
    }

    asyncio.create_task(engine.run(sources, local_files, opts))
    return {"ok": True}


@app.post("/api/cancel")
async def cancel_generate():
    if engine.is_running:
        engine.cancel()
        return {"ok": True, "message": "Отменяем..."}
    return {"ok": False, "message": "Нет активной генерации"}


@app.get("/api/proxy-data")
async def list_proxy_data():
    """Список сохранённых слепков Proxy-Data."""
    data_dir = ROOT / "Proxy-Data"
    if not data_dir.is_dir():
        return {"entries": []}
    entries = []
    for d in sorted(data_dir.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        meta = {}
        meta_file = d / "meta.json"
        if meta_file.is_file():
            try:
                meta = json.loads(meta_file.read_text("utf-8"))
            except Exception:
                pass
        entries.append({
            "name": d.name,
            "live": meta.get("live", 0),
            "checked": meta.get("checked", 0),
            "candidates": meta.get("candidates", 0),
            "sources": meta.get("sources", 0),
            "timestamp": meta.get("timestamp", ""),
        })
    return {"entries": entries}


class GenerateFromDataPayload(BaseModel):
    datasets: list[str]
    limit: int = 500
    selection: str = "fastest"


@app.post("/api/generate-from-data")
async def start_generate_from_data(payload: GenerateFromDataPayload):
    if engine.is_running:
        raise HTTPException(409, "Генерация уже запущена")

    if not payload.datasets:
        raise HTTPException(400, "Не выбрано ни одного датасета")

    all_nodes: list[dict] = []
    seen = set()
    for ds in payload.datasets:
        dataset_dir = ROOT / "Proxy-Data" / ds
        if not dataset_dir.is_dir():
            raise HTTPException(404, f"Датасет не найден: {ds}")

        live_file = dataset_dir / "live.txt"
        if not live_file.is_file():
            raise HTTPException(404, f"live.txt не найден: {ds}")

        nodes = parse_live_file(live_file)
        for n in nodes:
            key = (n.get("protocol"), n.get("server"), n.get("port"))
            if key not in seen:
                seen.add(key)
                all_nodes.append(n)

    if not all_nodes:
        raise HTTPException(400, "Датасеты пусты")

    label = ", ".join(payload.datasets[:3])
    if len(payload.datasets) > 3:
        label += f" +{len(payload.datasets) - 3}"

    opts = {
        "limit": max(1, payload.limit),
        "selection": payload.selection if payload.selection in {"fastest", "balanced"} else "fastest",
    }

    asyncio.create_task(engine.run_from_nodes(all_nodes, opts, source_label=label))
    return {"ok": True, "loaded": len(all_nodes)}


@app.get("/api/stream")
async def stream_events():
    async def event_generator():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(engine.events.get(), timeout=30)
                    yield f"event: {event['event']}\ndata: {json.dumps(event['data'], ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    if engine.status == "idle":
                        yield f"event: heartbeat\ndata: {json.dumps({'status': 'idle'})}\n\n"
                        continue
                    yield f"event: heartbeat\ndata: {json.dumps({'status': engine.status, 'metrics': engine.metrics})}\n\n"
        except asyncio.CancelledError:
            pass
        except GeneratorExit:
            pass

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/status")
async def get_status():
    return {
        "status": engine.status,
        "metrics": engine.metrics,
    }


@app.get("/api/configs")
async def list_configs():
    configs = []
    patterns = ["NetherLink-Clash.yaml", "NetherLink-100.yaml", "NetherLink-50.yaml",
                "NetherLink-v2ray.json", "NetherLink-100-v2ray.json", "NetherLink-50-v2ray.json",
                "NetherLink-singbox.json", "NetherLink-100-singbox.json", "NetherLink-50-singbox.json",
                "NetherLink-Xray-100.txt", "NetherLink-Xray-50.txt",
                "live.txt"]
    for name in patterns:
        fp = ROOT / name
        if fp.exists():
            configs.append({"name": name, "size": fp.stat().st_size, "type": "clash" if name.endswith(".yaml") else "xray" if "Xray" in name else "v2ray" if "v2ray" in name else "singbox" if "singbox" in name else "txt"})
    return {"configs": configs}


@app.get("/api/download")
async def download_config():
    if not OUTPUT_FILE.exists():
        raise HTTPException(404, "Конфиг ещё не сгенерирован")
    return FileResponse(
        path=str(OUTPUT_FILE),
        filename=OUTPUT_FILE.name,
        media_type="application/yaml",
    )


@app.get("/api/download/{config_name}")
async def download_named_config(config_name: str):
    allowed = ["NetherLink-Clash.yaml", "NetherLink-100.yaml", "NetherLink-50.yaml",
               "NetherLink-v2ray.json", "NetherLink-100-v2ray.json", "NetherLink-50-v2ray.json",
               "NetherLink-singbox.json", "NetherLink-100-singbox.json", "NetherLink-50-singbox.json",
               "NetherLink-Xray-100.txt", "NetherLink-Xray-50.txt",
               "live.txt"]
    if config_name not in allowed:
        raise HTTPException(404, "Неизвестный конфиг")
    fp = ROOT / config_name
    if not fp.exists():
        raise HTTPException(404, "Конфиг ещё не сгенерирован")
    mime = "application/yaml" if config_name.endswith(".yaml") else "application/json" if config_name.endswith(".json") else "text/plain"
    return FileResponse(path=str(fp), filename=config_name, media_type=mime)


CLIENT_MAP = {
    "clash": ("yaml", "application/yaml"),
    "meta": ("yaml", "application/yaml"),
    "mihomo": ("yaml", "application/yaml"),
    "stash": ("yaml", "application/yaml"),
    "v2ray": ("json", "application/json"),
    "v2raytun": ("json", "application/json"),
    "v2rayng": ("json", "application/json"),
    "v2box": ("json", "application/json"),
    "hiddify": ("json", "application/json"),
    "hiddifynext": ("json", "application/json"),
    "singbox": ("json", "application/json"),
    "sing-box": ("json", "application/json"),
    "happ": ("txt", "text/plain"),
    "hap": ("txt", "text/plain"),
}


def _detect_client(user_agent: str) -> str:
    ua = user_agent.lower()
    if any(x in ua for x in ("happ", "hap/", "xray")):
        return "happ"
    if any(x in ua for x in ("hiddify", "hiddifynext")):
        return "hiddify"
    if any(x in ua for x in ("sing-box", "singbox")):
        return "singbox"
    if any(x in ua for x in ("v2ray", "v2rayn", "v2raytun")):
        return "v2ray"
    if any(x in ua for x in ("clash", "meta", "mihomo", "stash", "cfw")):
        return "clash"
    return "clash"


def _pick_config(client: str, size: str):
    if client == "happ":
        # Полный Xray (500) убрали — у туннельных только топ-100/50
        return f"NetherLink-Xray-{size}.txt" if size else "NetherLink-Xray-100.txt"
    if client in ("v2ray", "v2raytun", "v2rayng", "v2box"):
        return f"NetherLink-{size}-v2ray.json" if size else "NetherLink-v2ray.json"
    if client in ("hiddify", "hiddifynext", "singbox", "sing-box"):
        return f"NetherLink-{size}-singbox.json" if size else "NetherLink-singbox.json"
    if size:
        return f"NetherLink-{size}.yaml"
    return "NetherLink-Clash.yaml"


@app.get("/sub")
@app.get("/subscription")
async def subscription(format: str = ""):
    if not OUTPUT_FILE.exists():
        raise HTTPException(404, "Конфиг ещё не сгенерирован")
    return FileResponse(
        path=str(OUTPUT_FILE),
        filename=OUTPUT_FILE.name,
        media_type="application/yaml",
        headers={
            "Content-Disposition": f"inline; filename={OUTPUT_FILE.name}",
            "Cache-Control": "no-store",
        },
    )


@app.get("/sub/500")
@app.get("/subscription/500")
async def subscription_500(request: Request, format: str = ""):
    """500 прокси — авто-определение клиента: FLClash (YAML), Happ (URI-txt),
    sing-box/v2ray (JSON)."""
    client = _detect_client(request.headers.get("user-agent", ""))
    if format:
        client = {"clash": "clash", "v2ray": "v2ray", "singbox": "singbox", "happ": "happ"}.get(format.lower(), client)
    config_name = _pick_config(client, "")
    fp = ROOT / config_name
    if not fp.exists():
        fp = ROOT / "NetherLink-Clash.yaml"
        config_name = "NetherLink-Clash.yaml"
    mime = "application/yaml" if config_name.endswith(".yaml") else "text/plain" if config_name.endswith(".txt") else "application/json"
    return FileResponse(
        path=str(fp), filename=config_name, media_type=mime,
        headers={"Content-Disposition": f"inline; filename={config_name}", "Cache-Control": "no-store"},
    )


@app.get("/sub/100")
@app.get("/subscription/100")
async def subscription_100(request: Request, format: str = ""):
    """100 прокси — авто-определение клиента."""
    client = _detect_client(request.headers.get("user-agent", ""))
    if format:
        client = {"clash": "clash", "v2ray": "v2ray", "singbox": "singbox", "happ": "happ"}.get(format.lower(), client)
    config_name = _pick_config(client, "100")
    fp = ROOT / config_name
    if not fp.exists():
        fp = ROOT / "NetherLink-100.yaml"
        config_name = "NetherLink-100.yaml"
        if not fp.exists():
            raise HTTPException(404, "Конфиг 100 ещё не сгенерирован")
    ext = config_name.split(".")[-1]
    mime = "application/json" if ext == "json" else "application/yaml"
    return FileResponse(
        path=str(fp), filename=config_name,
        media_type=mime,
        headers={"Content-Disposition": f"inline; filename={config_name}", "Cache-Control": "no-store"},
    )


@app.get("/sub/50")
@app.get("/subscription/50")
async def subscription_50(request: Request, format: str = ""):
    """50 прокси — авто-определение клиента."""
    client = _detect_client(request.headers.get("user-agent", ""))
    if format:
        client = {"clash": "clash", "v2ray": "v2ray", "singbox": "singbox"}.get(format.lower(), client)
    config_name = _pick_config(client, "50")
    fp = ROOT / config_name
    if not fp.exists():
        fp = ROOT / "NetherLink-50.yaml"
        config_name = "NetherLink-50.yaml"
        if not fp.exists():
            raise HTTPException(404, "Конфиг 50 ещё не сгенерирован")
    ext = config_name.split(".")[-1]
    mime = "application/json" if ext == "json" else "application/yaml"
    return FileResponse(
        path=str(fp), filename=config_name,
        media_type=mime,
        headers={"Content-Disposition": f"inline; filename={config_name}", "Cache-Control": "no-store"},
    )


FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "dist")


def _serve_static(path: str):
    file_path = os.path.join(FRONTEND_DIR, path.lstrip("/"))
    if os.path.isfile(file_path):
        content_type, _ = mimetypes.guess_type(file_path)
        return FileResponse(file_path, media_type=content_type or "application/octet-stream")
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.isfile(index_path):
        return FileResponse(index_path, media_type="text/html")
    raise HTTPException(404)


@app.get("/")
async def serve_root():
    return _serve_static("index.html")


@app.get("/assets/{file_path:path}")
async def serve_assets(file_path: str):
    return _serve_static(f"assets/{file_path}")


@app.get("/{file_name}.{ext}")
async def serve_with_ext(file_name: str, ext: str):
    full = f"{file_name}.{ext}"
    if full.startswith("api"):
        raise HTTPException(404)
    return _serve_static(full)
