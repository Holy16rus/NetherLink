# NetherLink

<p align="center">
  <img src="https://img.shields.io/badge/version-3.2-blue" alt="v3.2">
  <img src="https://img.shields.io/badge/proxies-500%2B-brightgreen" alt="500+">
  <img src="https://img.shields.io/badge/updated-every_10h-yellow" alt="10h">
  <a href="https://github.com/Holy16rus/NetherLink/actions"><img src="https://custom-icon-badges.demolab.com/github/last-commit/Holy16rus/NetherLink?logo=history&logoColor=white&color=0e75b6&style=flat" alt="last commit"></a>
  <a href="https://t.me/githoly"><img src="https://img.shields.io/badge/Telegram-@githoly-0088cc" alt="Telegram"></a>
</p>

**🌐 [English](README.en.md) | Русский**

**NetherLink** — автоматический генератор прокси-подписок для обхода блокировок. Собирает открытые прокси из **50+ источников**, проверяет доступность, стабильность и скорость, определяет страну и генерирует конфиги для VPN-клиентов. Обновляется автоматически каждые **10 часов**, мертвые и медленные сервера отсеиваются.

---

## 🚀 Быстрый старт

| Что нужно | Ссылка |
|-----------|--------|
| **500 прокси** — полный набор | [NetherLink.yaml](https://raw.githubusercontent.com/Holy16rus/NetherLink/gh-pages/NetherLink.yaml) |
| **100 прокси** — отобранный топ | [NetherLink-100.yaml](https://raw.githubusercontent.com/Holy16rus/NetherLink/gh-pages/NetherLink-100.yaml) |
| **50 прокси** — топ с перепроверкой каждый час | [NetherLink-50.yaml](https://raw.githubusercontent.com/Holy16rus/NetherLink/gh-pages/NetherLink-50.yaml) |

> 💡 Формат — **Clash YAML**. Рекомендуемый клиент: [FLClash](https://github.com/chen08209/FlClash) (Android / Windows / macOS / Linux).

### Как добавить подписку (3 шага)

1. Скопируй ссылку из таблицы выше (нужна именно **RAW**-ссылка)
2. В FLClash: «Профили» → «Добавить из буфера» / вставь ссылку в поле подписки
3. Готово — клиент сам подтянет и будет обновлять конфиг

---

## 🔧 Как это работает

1. **Сбор** — 50+ источников прокси (публичные репозитории, API, web-сервисы)
2. **Проверка** — TCP-подключение, HTTP/SOCKS5 handshake, protocol-check через sing-box для туннельных протоколов
3. **Фильтрация** — удаление спам-прокси (DNSBL), проверка стабильности по истории (5 запусков, success_rate ≥ 0.6)
4. **Геолокация** — определение страны через MaxMind GeoLite2 + ip-api.com
5. **Speed test** — замер скорости через скачивание 1MB
6. **Генерация** — конфиги, деплой на GitHub Pages

**Протоколы:** HTTP, HTTPS, SOCKS5, VMess, VLESS, Trojan, Shadowsocks, Hysteria2

### Почему прокси умирают?

Публичные прокси живут от минут до дней — они появляются и исчезают. Поэтому NetherLink:
- ⏱ Обновляет подписки каждые **10 часов** (полный пайплайн)
- 🔁 Перепроверяет топ-50 **каждый час** (быстрый recheck)
- 🧠 Помнит историю каждого прокси за **5 запусков** и отсеивает нестабильных (success_rate < 0.6)

Включи автообновление подписки в клиенте (раз в 1-2 часа) — и у тебя всегда свежий список рабочих серверов.

---

## 💻 Локальный запуск

```bash
git clone https://github.com/Holy16rus/NetherLink.git
cd NetherLink
pip install -r requirements.txt
python start.py
```

Откройте http://127.0.0.1:1488

---

## 📚 FAQ

**Вопрос:** Сервера есть, но не подключается — почему?
**Ответ:** Проверь в клиенте «Реальную задержку» (Real delay / Latency), а не TCP ping — TCP ping не показывает доступность VPN-сервера. Выбирай сервера с наименьшей задержкой. Иногда помогает обновить подписку и проверить ещё раз.

**Вопрос:** Как часто обновлять?
**Ответ:** Автообновление раз в 1-2 часа. Подписки сами обновляются на GitHub каждые 10 часов.

**Вопрос:** Сколько прокси реально работает?
**Ответ:** Из 500+ собранных стабильно живут обычно 100-200. Поэтому есть подписки на 500 (все), 100 (отбор) и 50 (топ с почасовой перепроверкой).

---

## 📊 Статус

- [Последний workflow](https://github.com/Holy16rus/NetherLink/actions)
- [Все прокси (live.txt)](https://raw.githubusercontent.com/Holy16rus/NetherLink/gh-pages/live.txt)
- Telegram: [@githoly](https://t.me/githoly)

---

## ⚖️ Дисклеймер

Проект предназначен только для образовательных целей и тестирования. Автор не несёт ответственности за использование предоставленных конфигураций. Уважайте законы своей страны.
