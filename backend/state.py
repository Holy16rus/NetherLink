"""
Персистентная история прокси через git (ветка `state`).

Каждый запуск пайплайна:
1. Восстанавливает proxy-history.json из state-ветки
2. Обновляет счётчики success/fail для каждой ноды
3. В конце коммитит обратно в state-ветку

Ключ: sha256(protocol|server|port)[:16]
Скользящее окно: последние N_LAUNCHES запусков
Фильтр в финальный конфиг:
  - Laplace smoothing: (successes + 1) / (total + 2) >= 0.6
  - Минимум MIN_LAUNCHES=3 запусков в истории перед доверием
"""
import json
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HISTORY_FILE = ROOT / "proxy-history.json"
N_LAUNCHES = 5
MIN_LAUNCHES = 3
SUCCESS_RATE_THRESHOLD = 0.6

_loaded: dict | None = None


def _node_key(node: dict) -> str:
    proto = node.get("protocol", "").lower()
    server = str(node.get("server", "")).lower()
    port = str(node.get("port", 0))
    raw = f"{proto}|{server}|{port}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def load_history() -> dict:
    global _loaded
    if _loaded is not None:
        return _loaded
    if HISTORY_FILE.exists():
        try:
            _loaded = json.loads(HISTORY_FILE.read_text("utf-8"))
        except Exception:
            _loaded = {}
    else:
        _loaded = {}
    return _loaded


def save_history():
    data = load_history()
    HISTORY_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def record_check_results(live_nodes: list[dict], checked_nodes: list[dict]):
    """
    Записывает результаты текущего запуска: 1 для живых, 0 для не-живых.
    live_nodes — только живые.
    checked_nodes — все проверенные.
    """
    data = load_history()

    live_keys = {_node_key(n) for n in live_nodes}

    for n in checked_nodes:
        k = _node_key(n)
        if k not in data:
            data[k] = []
        data[k].append(1 if k in live_keys else 0)
        if len(data[k]) > N_LAUNCHES:
            data[k] = data[k][-N_LAUNCHES:]

    save_history()


def get_success_rate(node: dict) -> float:
    """
    Laplace smoothing: (successes + 1) / (total + 2).
    Новый прокси с 1/1 получает (1+1)/(1+2) = 0.67 (не 1.0).
    Прокси с 0/1 получает (0+1)/(1+2) = 0.33.
    Без данных вовсе → (0+1)/(0+2) = 0.5 (нейтрально).
    """
    data = load_history()
    key = _node_key(node)
    history = data.get(key, [])
    if not history:
        return 0.5
    successes = sum(history)
    total = len(history)
    return (successes + 1) / (total + 2)


def is_stable(node: dict) -> bool:
    """Стабилен если: минимум MIN_LAUNCHES запусков в истории И Laplace score >= THRESHOLD."""
    data = load_history()
    key = _node_key(node)
    history = data.get(key, [])
    if len(history) < MIN_LAUNCHES:
        return False
    return get_success_rate(node) >= SUCCESS_RATE_THRESHOLD


def filter_stable(nodes: list[dict]) -> list[dict]:
    return [n for n in nodes if is_stable(n)]
