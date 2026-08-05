# NetherLink

<p align="center">
  <a href="/README.en.md"><img src="https://img.shields.io/badge/🇬🇧%20English-README-blue" alt="EN"></a>
  <a href="https://t.me/githoly"><img src="https://img.shields.io/badge/📬%20Telegram-@githoly-0088cc" alt="Telegram"></a>
</p>

**NetherLink** — генератор прокси-подписок. Собирает открытые прокси, проверяет их доступность, замеряет скорость, определяет страну и пинг, генерирует конфиги для **FLClash**, **V2rayTun** и **HiddifyApp**.

---

## Подписки

### 500 прокси (только FLClash)
```
https://raw.githubusercontent.com/Holy16rus/NetherLink/gh-pages/NetherLink.yaml
```
> `/sub/500` — для Clash-совместимых клиентов. Другие клиенты не тянут столько прокси.

### 100 прокси (выберите формат под свой клиент)
```
FLClash / Clash Meta:  https://raw.githubusercontent.com/Holy16rus/NetherLink/gh-pages/NetherLink-100.yaml
V2rayTun / V2RayNG:    https://raw.githubusercontent.com/Holy16rus/NetherLink/gh-pages/NetherLink-100-v2ray.json
HiddifyApp / Sing-box: https://raw.githubusercontent.com/Holy16rus/NetherLink/gh-pages/NetherLink-100-singbox.json
```
> Авто-определение по User-Agent (`/sub/100`) работает только при **локальном запуске** сервера
> (`python start.py`) — GitHub Pages отдаёт статику и не умеет читать заголовки запроса.
> Поэтому для gh-pages нужно вручную выбрать ссылку под свой клиент.

### 50 прокси (топ, с перепроверкой)
```
FLClash / Clash Meta:  https://raw.githubusercontent.com/Holy16rus/NetherLink/gh-pages/NetherLink-50.yaml
V2rayTun / V2RayNG:    https://raw.githubusercontent.com/Holy16rus/NetherLink/gh-pages/NetherLink-50-v2ray.json
HiddifyApp / Sing-box: https://raw.githubusercontent.com/Holy16rus/NetherLink/gh-pages/NetherLink-50-singbox.json
```
Аналогично топ-100, но только лучшие из лучших — с перепроверкой и замером скорости.

### Прямые ссылки на raw (gh-pages)

| Файл | Описание |
|------|----------|
| `NetherLink.yaml` | FLClash, 500 прокси |
| `NetherLink-100.yaml` | FLClash, топ-100 |
| `NetherLink-50.yaml` | FLClash, топ-50 |
| `NetherLink-v2ray.json` | V2Ray, все живые |
| `NetherLink-100-v2ray.json` | V2Ray, топ-100 |
| `NetherLink-50-v2ray.json` | V2Ray, топ-50 |
| `NetherLink-singbox.json` | Sing-box, все живые |
| `NetherLink-100-singbox.json` | Sing-box, топ-100 |
| `NetherLink-50-singbox.json` | Sing-box, топ-50 |
| `live.txt` | Все живые прокси (plain text) |

Базовый URL: `https://raw.githubusercontent.com/Holy16rus/NetherLink/gh-pages/`

---

## Возможности

- **Сбор** прокси из 50+ источников (GitHub-репозитории, публичные API, Telegram-каналы)
- **Парсинг** всех форматов: HTTP, HTTPS, SOCKS5, Shadowsocks, VMess, VLESS, Trojan, Hysteria2
- **Проверка** доступности и замер пинга (TCP/HTTP/SOCKS5 handshake, до 200 одновременных)
- **Speed test** — замер пропускной способности через скачивание 1MB (10 мин цикл)
- **Re-check** — повторная перепроверка топ-100 и топ-50 прокси
- **Геолокация** через MaxMind GeoLite2 (локально) с fallback на ip-api.com
- **Генерация** в 3 формата: Clash YAML, V2Ray JSON, Sing-box JSON
- **Интерфейс** — веб-панель с SSE-стримом, выбор режимов FULL / DATA, просмотр логов
- **Авто-обновление** раз в 10 часов через GitHub Actions

---

## Локальный запуск

**Требования:** Python 3.11+, Git

```bash
git clone https://github.com/Holy16rus/NetherLink.git
cd NetherLink
pip install -r requirements.txt
python start.py
```

После запуска откройте `http://127.0.0.1:1488`.

---

## Автоматическая генерация (CI/CD)

Репозиторий автоматически перегенерирует подписку каждые **10 часов** через GitHub Actions. В `gh-pages` публикуются все конфиги и `live.txt`.

Для работы CI требуется [бесплатный ключ MaxMind](https://dev.maxmind.com/geoip/geolite2-free-geolocation-data), добавленный в секреты репозитория как `GEOIP_LICENSE_KEY`.

---

## Источники прокси

Парсятся 50+ источников, включая:
- `monosans/proxy-list`, `TheSpeedX/PROXY-List`, `jetkai/proxy-list`
- `proxifly/free-proxy-list`, `roosterkid/openproxylist`, `ShiftyTR/Proxy-List`
- `clarketm/proxy-list`, `ALIILAPRO/Proxy`, `hookzof/socks5_list`
- `RKPchannel/RKP_bypass_configs` (чёрные списки РосКомПозор)
- `luxxuria/harvester`, `HalyavusVPNUS/halyava-vpn-buy`
- `spys.me`, `ProxyScrape`, `proxy-list.download`, `free.redscrape.com`
- И десятки других

---

## Связь

По вопросам, предложениям и багам пишите в Telegram: [@githoly](https://t.me/githoly)
