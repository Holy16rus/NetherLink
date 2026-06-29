import asyncio
import json
import urllib.parse
from pathlib import Path

import httpx

from backend.parser import extract_proxies, path_score, SKIP_PATH_PARTS, TEXT_FILE_EXTENSIONS

TIMEOUT = 25

# Shared clients — reuse TCP connections across all requests
_GITHUB_CLIENT: httpx.AsyncClient | None = None
_GENERAL_CLIENT: httpx.AsyncClient | None = None


def _get_github_client() -> httpx.AsyncClient:
    global _GITHUB_CLIENT
    if _GITHUB_CLIENT is None or _GITHUB_CLIENT.is_closed:
        _GITHUB_CLIENT = httpx.AsyncClient(
            timeout=TIMEOUT,
            follow_redirects=True,
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
            headers={"User-Agent": "HolyVPN-Proxy-Generator/2.0"},
        )
    return _GITHUB_CLIENT


def _get_general_client() -> httpx.AsyncClient:
    global _GENERAL_CLIENT
    if _GENERAL_CLIENT is None or _GENERAL_CLIENT.is_closed:
        _GENERAL_CLIENT = httpx.AsyncClient(
            timeout=TIMEOUT,
            follow_redirects=True,
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=40),
            headers={"User-Agent": "HolyVPN-Proxy-Generator/2.0"},
        )
    return _GENERAL_CLIENT


async def fetch_url(url: str, timeout: float = TIMEOUT) -> str:
    client = _get_general_client()
    resp = await client.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.text


async def fetch_json(url: str, timeout: float = TIMEOUT):
    return json.loads(await fetch_url(url, timeout))


async def _default_branch(owner: str, repo: str) -> str:
    """Try main and master in parallel — return whichever tree responds first."""
    client = _get_github_client()

    async def try_branch(branch: str) -> str | None:
        try:
            url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
            resp = await client.head(url, timeout=5)
            if resp.status_code < 400:
                return branch
        except Exception:
            pass
        return None

    results = await asyncio.gather(try_branch("main"), try_branch("master"))
    for r in results:
        if r:
            return r
    return "main"


def common_repo_candidates(owner: str, repo: str, source: str, per_repo_limit: int) -> list[dict]:
    paths = [
        "http.txt", "https.txt", "socks5.txt", "socks4.txt",
        "proxy.txt", "proxies.txt", "all.txt", "README.md",
        "data/http.txt", "data/https.txt", "data/socks5.txt", "data/proxies.txt",
        "proxies/http.txt", "proxies/https.txt", "proxies/socks5.txt", "proxies/all.txt",
    ]
    candidates = []
    for branch in ("main", "master"):
        for path in paths:
            candidates.append({
                "url": f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}",
                "path": path,
                "source": source,
                "score": path_score(path),
            })
            if len(candidates) >= per_repo_limit:
                return candidates
    return candidates


async def discover_repo_files(source: str, per_repo_limit: int, cancel_event: asyncio.Event) -> list[dict]:
    """Возвращает список файлов для скачивания из источника."""
    parsed = urllib.parse.urlparse(source.strip())
    host = parsed.netloc.lower()
    parts = parsed.path.strip("/").split("/")

    # Уже прямая raw-ссылка
    if host == "raw.githubusercontent.com" and len(parts) >= 4:
        return [{"url": source, "path": "/".join(parts[3:]), "source": source}]

    # Не GitHub — пробуем как прямой URL
    if host not in {"github.com", "www.github.com"} or len(parts) < 2:
        return [{"url": source, "path": source, "source": source}]

    owner, repo = parts[0], parts[1].removesuffix(".git")

    # Прямая ссылка на файл
    if len(parts) >= 5 and parts[2] in {"blob", "raw"}:
        branch = parts[3]
        file_path = "/".join(parts[4:])
        raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{file_path}"
        return [{"url": raw_url, "path": file_path, "source": source}]

    branch = (
        parts[3] if len(parts) >= 5 and parts[2] == "tree"
        else await _default_branch(owner, repo)
    )
    prefix = "/".join(parts[4:]).strip("/") if len(parts) >= 5 and parts[2] == "tree" else ""

    if cancel_event.is_set():
        return []

    client = _get_github_client()
    try:
        tree_url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
        resp = await client.get(tree_url, timeout=20)
        resp.raise_for_status()
        tree = resp.json().get("tree", [])
    except Exception:
        return common_repo_candidates(owner, repo, source, per_repo_limit)

    candidates = []
    for item in tree:
        if cancel_event.is_set():
            return []
        path = item.get("path", "")
        if item.get("type") != "blob":
            continue
        if prefix and not path.startswith(prefix.rstrip("/") + "/") and path != prefix:
            continue
        score = path_score(path)
        if score < 0:
            continue
        raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"
        candidates.append({"url": raw_url, "path": path, "source": source, "score": score})

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[:per_repo_limit]


async def fetch_and_parse(item: dict, cancel_event: asyncio.Event) -> tuple[dict, list[dict]]:
    """Скачивает и парсит один файл. Возвращает (item, nodes)."""
    if cancel_event.is_set():
        return item, []
    try:
        client = _get_general_client()
        resp = await client.get(item["url"], timeout=20)
        resp.raise_for_status()
        content = resp.text
        nodes = extract_proxies(content, item["path"], item["source"])
        return item, nodes
    except Exception:
        return item, []


async def collect_local_files(files: list[str]) -> list[dict]:
    """Читает локальные файлы и парсит прокси из них."""
    root = Path(__file__).resolve().parent.parent
    all_nodes = []
    for path in files:
        full = root / path
        if not full.exists():
            continue
        try:
            content = full.read_text("utf-8", errors="replace")
        except Exception:
            continue
        nodes = extract_proxies(content, str(full), str(full))
        all_nodes.extend(nodes)
    return all_nodes


async def collect_from_sources(
    sources: list[str],
    per_repo_limit: int,
    cancel_event: asyncio.Event,
    progress_cb=None,
) -> list[dict]:
    """
    Устаревший последовательный сборщик — оставлен для обратной совместимости.
    В pipeline.py используется параллельный _produce().
    """
    all_nodes: list[dict] = []
    total_sources = len(sources)

    for idx, source in enumerate(sources):
        if cancel_event.is_set():
            break
        if progress_cb:
            await progress_cb("source", {"current": idx + 1, "total": total_sources, "url": source})

        try:
            files = await discover_repo_files(source, per_repo_limit, cancel_event)
        except Exception as e:
            if progress_cb:
                await progress_cb("error", {"msg": f"Source failed: {source}", "error": str(e)})
            continue

        sem = asyncio.Semaphore(10)

        async def process_file(item, _source=source):
            if cancel_event.is_set():
                return []
            async with sem:
                _, nodes = await fetch_and_parse(item, cancel_event)
                if nodes and progress_cb:
                    await progress_cb("parsed", {"count": len(nodes), "path": item["path"], "source": _source})
                return nodes

        for task in asyncio.as_completed([process_file(f) for f in files]):
            if cancel_event.is_set():
                break
            nodes = await task
            all_nodes.extend(nodes)

    return all_nodes
