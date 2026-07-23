# NetherLink — Архитектура системы (v3)

## 1. Структура проекта

```
NetherLink/
├── backend/
│   ├── main.py                 # FastAPI: роуты, SSE, статика, авто-определение клиента
│   ├── engine.py               # ProxyEngine — синглтон
│   ├── pipeline.py             # Ядро: producer/consumer, protocol-check, GeoIP, speed-test, re-check
│   ├── generator.py            # Генерация конфигов: Clash YAML, V2Ray JSON, Sing-box JSON
│   ├── checker.py              # TCP check, HTTP check, SOCKS5 check, speed test, protocol check (sing-box)
│   ├── state.py                # Git-based персистентная история (state-ветка, success_rate >= 0.6)
│   ├── scraper.py              # Сборщик: GitHub API, raw-ссылки
│   ├── parser.py               # Парсер URI: vmess://, vless://, ss://, trojan://, hy2://, ip:port
│   ├── services.py             # GeoIP (MaxMind + ip-api.com), DNS (Cloudflare DoH)
│   ├── web_sources.py          # JSON API источники (proxyscrape, proxy-list.download, geonode, lumiproxy)
│   ├── config.py               # Конфиг, .env, load/save источников
│   ├── headless.py             # CLI для GitHub Actions (полный пайплайн)
│   ├── recheck_headless.py     # CLI для частого recheck (только проверка, без сбора)
│   ├── check_proxies.py        # Самостоятельный CLI-чекер proxy.txt
│   └── download_geoip.py       # Скачивание GeoLite2
├── frontend/                   # React + Vite + Tailwind
├── .github/workflows/
│   ├── generate.yml            # CI/CD — полная генерация каждые 10 часов
│   └── recheck.yml             # CI/CD — частая перепроверка топа каждый час
├── sources.json                # 50+ источников прокси
├── proxy-history.json          # История проверок (синхронизируется через state-ветку)
├── start.py                    # uvicorn 127.0.0.1:1488
└── requirements.txt            # fastapi, uvicorn, httpx, pydantic, maxminddb
```

## 2. Полный порядок проверки прокси (Pipeline v3)

### Этап 1: Web-источники (JSON API)
Сервисы: `proxyscrape.com`, `proxy-list.download`, `geonode.com`, `lumiproxy.com`, `free.redscrape.com`

### Этап 2: Producer (сбор из 50+ источников)
- Локальные файлы → парсинг
- Удалённые источники: GitHub API tree → path_score фильтрация → fetch_and_parse
- Параллельно: 6 репозиториев × 20 файлов
- **НОВОЕ: time-budget (producer_timeout=180s)** вместо early_stop по количеству
  - Producer форсируется через `asyncio.wait_for(producer_task, timeout=180)`
  - Если 180 сек истекли — сбор останавливается, consumer доедает очередь

### Этап 3: Consumer (TCP-дедупликация + проверка)
- Дедупликация: `(protocol, server.lower(), port, uuid|password|username)`
- TCP/HTTP/SOCKS5 проверка: `CHECK_CONCURRENCY=200`
- **НОВОЕ:** Сохраняет `all_checked` (все проверенные, и живые, и нет) для истории

### Этап 4: Сохранение истории (git-based)
**Файл:** `backend/state.py`
- Ключ: `sha256(protocol|server|port)[:16]`
- `record_check_results(live_nodes, checked_nodes)` — записывает 1 (success) или 0 (fail)
- Скользящее окно: 5 запусков
- `proxy-history.json` хранится в ветке `state`
- При запуске: `git fetch origin state && git show state:proxy-history.json`
- При завершении: коммит обратно в `state`-ветку

### Этап 5: Protocol check (sing-box для туннельных протоколов)
**НОВОЕ:** `checker.py` → `protocol_check()`
- Только для VMess/VLESS/Trojan/SS/Hysteria2 (уже прошедшие TCP)
- Запускает `sing-box run -c tmp.json` с SOCKS-листенером на случайном порту
- HTTP GET `/generate_204` через локальный SOCKS-листенер
- `PROTOCOL_CHECK_CONCURRENCY=15` (отдельный семафор, ниже чем TCP)
- На раннере GH Actions sing-box ставится через apt

### Этап 6-8: Сохранение → GeoIP → Speed test
(без изменений)

### Этап 9: Фильтрация по стабильности
**НОВОЕ:** `state.filter_stable(live_nodes)`
- Оставляет только ноды с `success_rate >= 0.6` за последние 5 запусков
- Если стабильных не хватает на лимит — fallback на все живые

### Этап 10: Re-check топ-100/топ-50 + генерация конфигов
(без изменений, но топ формируется из стабильных нод)

## 3. Два CI/CD workflow

### generate.yml (каждые 10 часов)
- Установка sing-box через apt
- `git fetch origin state` → восстановление истории
- `python -m backend.headless` (полный пайплайн)
- Деплой на `gh-pages` + коммит истории в `state`

### recheck.yml (каждый час)
- Установка sing-box
- Скачивание `NetherLink-50.yaml` / `NetherLink-100.yaml` из `gh-pages`
- `python -m backend.recheck_headless` — **только проверка**, без сбора источников
- TCP check + protocol check для туннельных
- Обновление `gh-pages` + `state`
- Занимает секунды, мало жрёт лимит Actions

## 4. Checker: все методы проверки

| Метод | Протоколы | Что делает | Конкурентность |
|-------|-----------|------------|----------------|
| `tcp_check()` | Все | TCP connect, latency ms | — |
| `http_check()` | HTTP/HTTPS | TCP → HTTP GET /generate_204 | — |
| `socks5_check()` | SOCKS5 | SOCKS5 handshake → HTTP GET | — |
| `check_node()` | Все | Диспетчер: HTTP→http, SOCKS5→socks5, остальные→tcp | 200 |
| `protocol_check()` | VMess/VLESS/Trojan/SS/Hy2 | sing-box subprocess → SOCKS proxy → HTTP GET | 15 |
| `speed_test_node()` | HTTP/HTTPS/SOCKS5 | Скачивание 1MB.zip → Mbps | 50 |

## 5. Персистентная история (state.py)

```
proxy-history.json = {
  "a1b2c3d4e5f6a7b8": [1, 1, 0, 1, 1],   # 4/5 = 0.8 — стабилен
  "b2c3d4e5f6a7b8c9": [0, 0, 0, 1, 0],   # 1/5 = 0.2 — нестабилен
  "c3d4e5f6a7b8c9d0": [1, 1],             # 2/2 = 1.0 — стабилен (мало данных)
  ...                                      # ~10K-50K записей, ~1-5 MB JSON
}
```

Фильтр: `success_rate = sum(history) / len(history) >= 0.6` → включаем в конфиг

## 6. Auto-детект клиента для подписок

| User-Agent | Определяется | Формат |
|-----------|-------------|--------|
| clash, meta, mihomo, stash | clash | YAML |
| v2ray, v2rayng, v2raytun | v2ray | V2Ray JSON |
| hiddify, hiddifynext, singbox, sing-box | singbox | Sing-box JSON |
| default | clash | YAML |

## 7. Concurrency параметры

| Параметр | Значение | Где |
|----------|---------|-----|
| `CHECK_CONCURRENCY` (TCP/HTTP) | 200 | pipeline consumer |
| `PROTOCOL_CHECK_CONCURRENCY` | 15 | protocol check (sing-box) |
| `src_sem` | 6 | параллельные репозитории |
| `file_sem` | 20 | параллельные файлы |
| `FLUSH_BATCH` | 150 | размер батча TCP-проверки |
| Speed test semaphore | 50 | параллельный speed-test |
| Re-check semaphore | 30 | перепроверка топа |
| `producer_timeout` | 180s | time-budget на сбор |
| `N_LAUNCHES` (история) | 5 | скользящее окно |
| `N_LAUNCHES` (история) | 5 | скользящее окно |
| `SUCCESS_RATE_THRESHOLD` | 0.6 | минимальный Laplace-сглаженный success_rate |
| `MIN_LAUNCHES` | 3 | минимум запусков перед доверием к прокси |

## 8. Фикс багов (v3.1)

### Cold-start bias
Laplace smoothing: `(successes + 1) / (total + 2)`. Новый прокси с `[1,1]` → 0.67 (не 1.0). Плюс `MIN_LAUNCHES=3` — пока не накоплено 3 запуска, прокси не считается стабильным вообще.

### Гонка за state-ветку
Retry-цикл на 3 попытки с `git fetch` перед каждым коммитом, слияние JSON через python, force-push орфан-коммит.

### State-ветка не пухнет
`git checkout --orphan state-new` → force-push. Всегда ровно 1 коммит, как `gh-pages`.

### sing-box жёсткий таймаут
`asyncio.wait_for(_inner(), timeout+5)` + `process.terminate()` → `wait(3)` → `process.kill()` → `wait(2)`.

### Кеш sing-box
`actions/cache@v4` по хэшу workflow-файлов. Установка только при cache-miss.
