# NetherLink

<p align="center">
  <img src="https://img.shields.io/badge/version-3.2-blue" alt="v3.2">
  <img src="https://img.shields.io/badge/proxies-500%2B-brightgreen" alt="500+">
  <img src="https://img.shields.io/badge/formats-Clash_|_V2Ray_|_Singbox-orange" alt="formats">
  <img src="https://img.shields.io/badge/updated-every_10h-yellow" alt="10h">
  <a href="https://t.me/githoly"><img src="https://img.shields.io/badge/Telegram-@githoly-0088cc" alt="Telegram"></a>
</p>

**NetherLink** — автоматический генератор прокси-подписок. Собирает открытые прокси из 50+ источников, проверяет доступность, замеряет скорость, определяет страну и генерирует конфиги для популярных VPN-клиентов. Работает полностью автоматически через GitHub Actions, обновляется каждые 10 часов.

---

## Подписки

### 500 прокси — FLClash / Clash Meta
```
https://raw.githubusercontent.com/Holy16rus/NetherLink/gh-pages/NetherLink.yaml
```
Полный набор, 500 прокси. Только для Clash-совместимых клиентов.

### 100 прокси — любой клиент
| Клиент | Ссылка |
|--------|--------|
| FLClash / Clash Meta | https://raw.githubusercontent.com/Holy16rus/NetherLink/gh-pages/NetherLink-100.yaml |
| V2rayTun / V2RayNG | https://raw.githubusercontent.com/Holy16rus/NetherLink/gh-pages/NetherLink-100-v2ray.json |
| HiddifyApp / Sing-box | https://raw.githubusercontent.com/Holy16rus/NetherLink/gh-pages/NetherLink-100-singbox.json |

### 50 прокси — топ с перепроверкой
| Клиент | Ссылка |
|--------|--------|
| FLClash / Clash Meta | https://raw.githubusercontent.com/Holy16rus/NetherLink/gh-pages/NetherLink-50.yaml |
| V2rayTun / V2RayNG | https://raw.githubusercontent.com/Holy16rus/NetherLink/gh-pages/NetherLink-50-v2ray.json |
| HiddifyApp / Sing-box | https://raw.githubusercontent.com/Holy16rus/NetherLink/gh-pages/NetherLink-50-singbox.json |

> 🔥 Авто-определение клиента по User-Agent (`/sub/100`) доступно при локальном запуске: `python start.py`

---

## Как использовать

1. Скопируйте ссылку под свой клиент из таблицы выше
2. Вставьте её в настройки VPN-клиента в поле «Подписка» или «Subscription URL»
3. Клиент сам подтянет конфигурацию и будет обновлять её

**Поддерживаемые клиенты:**
- [FLClash](https://github.com/chen08209/FlClash) — Android
- [Clash Meta](https://github.com/MetaCubeX/Clash.Meta) — универсальный
- [V2rayTun](https://github.com/ssrlive/v2raytun) — Android
- [V2RayNG](https://github.com/2dust/v2rayNG) — Android
- [HiddifyApp](https://github.com/hiddify/hiddify-app) — кроссплатформенный
- [Sing-box](https://github.com/SagerNet/sing-box) — универсальный

---

## Как это работает

1. **Сбор** — 50+ источников прокси (публичные репозитории, API, web-сервисы)
2. **Проверка** — TCP-подключение, HTTP/SOCKS5 handshake, protocol-check через sing-box для туннельных протоколов
3. **Фильтрация** — удаление спам-прокси (DNSBL), проверка стабильности по истории (5 запусков)
4. **Геолокация** — определение страны через MaxMind GeoLite2 + ip-api.com
5. **Speed test** — замер скорости через скачивание 1MB
6. **Генерация** — конфиги в 3 форматах, деплой на GitHub Pages

**Протоколы:** HTTP, HTTPS, SOCKS5, VMess, VLESS, Trojan, Shadowsocks, Hysteria2

---

## Локальный запуск

> 💡 При локальном запуске работает авто-определение клиента через `/sub/100`

```bash
git clone https://github.com/Holy16rus/NetherLink.git
cd NetherLink
pip install -r requirements.txt
python start.py
```

Откройте http://127.0.0.1:1488

---

## Обновление

Подписки обновляются автоматически каждые **10 часов** через GitHub Actions. Никаких действий от пользователя не требуется — клиент сам подтягивает свежий конфиг при обновлении подписки.

---

## Ссылки

- [Последний workflow](https://github.com/Holy16rus/NetherLink/actions)
- [Все прокси (live.txt)](https://raw.githubusercontent.com/Holy16rus/NetherLink/gh-pages/live.txt)
- Telegram: [@githoly](https://t.me/githoly)
