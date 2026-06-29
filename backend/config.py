import os
import json
from pathlib import Path

# Load .env if present (no dependency on python-dotenv)
_ROOT = Path(__file__).resolve().parent.parent
_env_file = _ROOT / ".env"
if _env_file.exists():
    for _line in _env_file.read_text("utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _key, _, _val = _line.partition("=")
            os.environ.setdefault(_key.strip(), _val.strip())

ROOT = _ROOT
SOURCES_FILE = ROOT / "sources.json"
OUTPUT_FILE = ROOT / "HolyVPN.yaml"
WEB_DIR = ROOT / "web"

# API keys — set via .env file (see .env.example)
PROXYCHECK_KEY: str = os.environ.get("PROXYCHECK_KEY", "")
GLOBALPING_KEY: str = os.environ.get("GLOBALPING_KEY", "")
CHECKER_NET_KEY: str = os.environ.get("CHECKER_NET_KEY", "")

# Concurrency / performance tuning
CHECK_CONCURRENCY = int(os.environ.get("CHECK_CONCURRENCY", "200"))  # было 100
CHECK_BATCH_SIZE = 1000
GLOBALPING_BATCH = 50
TIMEOUT = 15

COUNTRY_NAMES_RU = {
    "AE": "ОАЭ", "AR": "Аргентина", "AT": "Австрия", "AU": "Австралия",
    "BE": "Бельгия", "BG": "Болгария", "BR": "Бразилия", "CA": "Канада",
    "CH": "Швейцария", "CL": "Чили", "CN": "Китай", "CO": "Колумбия",
    "CZ": "Чехия", "DE": "Германия", "DK": "Дания", "EE": "Эстония",
    "EG": "Египет", "ES": "Испания", "FI": "Финляндия", "FR": "Франция",
    "GB": "Великобритания", "GR": "Греция", "HK": "Гонконг", "HU": "Венгрия",
    "ID": "Индонезия", "IE": "Ирландия", "IL": "Израиль", "IN": "Индия",
    "IT": "Италия", "JP": "Япония", "KR": "Южная Корея", "LT": "Литва",
    "LV": "Латвия", "MX": "Мексика", "MY": "Малайзия", "NL": "Нидерланды",
    "NO": "Норвегия", "NZ": "Новая Зеландия", "PH": "Филиппины", "PL": "Польша",
    "PT": "Португалия", "RO": "Румыния", "RU": "Россия", "SE": "Швеция",
    "SG": "Сингапур", "SK": "Словакия", "TH": "Таиланд", "TR": "Турция",
    "TW": "Тайвань", "UA": "Украина", "US": "США", "VN": "Вьетнам",
    "ZA": "ЮАР", "ZZ": "Неизвестно",
}


def load_sources():
    if not SOURCES_FILE.exists():
        # Fall back to example file so the app works out of the box
        example = ROOT / "sources.example.json"
        if example.exists():
            try:
                return json.loads(example.read_text("utf-8"))
            except Exception:
                pass
        return {"sources": [], "local_files": ["proxy.txt"]}
    try:
        data = json.loads(SOURCES_FILE.read_text("utf-8"))
        if isinstance(data, dict):
            return data
        if isinstance(data, list):
            return {"sources": data, "local_files": ["proxy.txt"]}
    except Exception:
        pass
    return {"sources": [], "local_files": ["proxy.txt"]}


def save_sources(data):
    SOURCES_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
