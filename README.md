# HolyVPN

<p align="center">
  <a href="/README.en.md"><img src="https://img.shields.io/badge/🇬🇧%20English-README-blue" alt="EN"></a>
  <a href="https://t.me/githoly"><img src="https://img.shields.io/badge/📬%20Telegram-@githoly-0088cc" alt="Telegram"></a>
</p>

**HolyVPN** — генератор прокси-подписок для Clash-клиентов. Собирает открытые прокси, проверяет их доступность, определяет страну и пинг, генерирует готовый YAML-конфиг.

---

## Подписка

```
https://raw.githubusercontent.com/Holy16rus/HolyVpn/gh-pages/HolyVPN.yaml
```

Используйте эту ссылку в **FLClash**, **Clash Meta** или любом другом Clash-совместимом клиенте как subscription URL. Конфигурация обновляется автоматически каждые 6 часов.

---

## Возможности

- **Сбор** прокси из GitHub-репозиториев и публичных API
- **Парсинг** всех популярных форматов: HTTP, SOCKS5, Shadowsocks, VMess, VLESS, Trojan, Hysteria2
- **Проверка** доступности и замер пинга (TCP handshake, до 200 одновременных)
- **Геолокация** через MaxMind GeoLite2 (локально) с fallback на ip-api.com
- **Генерация** Clash YAML с сортировкой по скорости и группировкой по странам
- **Интерфейс** — веб-панель с SSE-стримом, выбор режимов FULL / DATA, просмотр логов

---

## Локальный запуск

**Требования:** Python 3.11+, Git

```bash
git clone https://github.com/Holy16rus/HolyVpn.git
cd HolyVpn
pip install -r requirements.txt
python start.py
```

После запуска откройте `http://127.0.0.1:1488`.

---

## Автоматическая генерация (CI/CD)

Репозиторий автоматически перегенерирует подписку каждые 6 часов через GitHub Actions. Также доступен ручной запуск: **Actions → Generate Proxy Config → Run workflow**.

Для работы CI требуется [бесплатный ключ MaxMind](https://dev.maxmind.com/geoip/geolite2-free-geolocation-data), добавленный в секреты репозитория как `GEOIP_LICENSE_KEY`.

---

## Связь

По вопросам, предложениям и багам пишите в Telegram: [@githoly](https://t.me/githoly)
