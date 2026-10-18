# NetherLink

<p align="center">
  <img src="https://img.shields.io/badge/version-3.2-blue" alt="v3.2">
  <img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2FHoly16rus%2FNetherLink%2Fsubscription%2Fstatus.json&query=%24.main.count&label=проверено%20живых&color=brightgreen" alt="живых нод">
  <img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2FHoly16rus%2FNetherLink%2Fsubscription%2Fstatus.json&query=%24.updated_label&label=обновлено&color=yellow" alt="обновлено">
  <img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2FHoly16rus%2FNetherLink%2Fsubscription%2Fstatus.json&query=%24.verify.pass_rate&suffix=%25&label=прошло%20проверку&color=blue" alt="доля прошедших">
  <a href="https://github.com/Holy16rus/NetherLink/actions"><img src="https://custom-icon-badges.demolab.com/github/last-commit/Holy16rus/NetherLink?logo=history&logoColor=white&color=0e75b6&style=flat" alt="last commit"></a>
  <a href="https://t.me/githoly"><img src="https://img.shields.io/badge/Telegram-@githoly-0088cc" alt="Telegram"></a>
</p>

**🌐 [English](README.en.md) | Русский**

**NetherLink** — автоматический генератор прокси-подписок для обхода блокировок. Собирает открытые прокси из публичных репозиториев и Telegram-каналов, **проверяет каждую ноду настоящим ядром клиента (mihomo)** — данные должны реально пройти через ноду, — определяет страну по выходному IP и генерирует конфиги для VPN-клиентов. В подписку попадает только то, что прошло проверку. Полная пересборка — раз в **4 часа**, перепроверка всего пула — **каждый час**.

---

## 🚀 Подписки

Скопируй ссылку и вставь в клиент (долгий тап по ссылке → копировать):

### FLClash / Clash Meta (YAML)

```
https://raw.githubusercontent.com/Holy16rus/NetherLink/subscription/NetherLink-Clash.yaml
https://raw.githubusercontent.com/Holy16rus/NetherLink/subscription/NetherLink-100.yaml
https://raw.githubusercontent.com/Holy16rus/NetherLink/subscription/NetherLink-50.yaml
```

- **NetherLink-Clash.yaml** — основной список: все ноды, прошедшие проверку (число плавает — см. [status.json](https://raw.githubusercontent.com/Holy16rus/NetherLink/subscription/status.json); мы не добиваем список мёртвыми ради красивой цифры)
- **NetherLink-100.yaml** — отобранный топ-100
- **NetherLink-50.yaml** — топ-50 по скорости и стабильности, пересобирается каждый час
- В Clash-файлах есть группы **✈️ Telegram / ▶️ YouTube / 🤖 ИИ** — туда входят только ноды, у которых эти сервисы реально открылись при проверке; правила маршрутизации уже настроены на них

> Рекомендуемый клиент: [FLClash](https://github.com/chen08209/FlClash) (Android / Windows / macOS / Linux).

### Happ / Xray (только туннельные: vless/vmess/trojan/ss)

```
https://raw.githubusercontent.com/Holy16rus/NetherLink/subscription/NetherLink-Xray-100.txt
https://raw.githubusercontent.com/Holy16rus/NetherLink/subscription/NetherLink-Xray-50.txt
```

- **NetherLink-Xray-100.txt** — топ-100 туннельных
- **NetherLink-Xray-50.txt** — топ-50 туннельных

---

## 📊 Живые прокси (статистика)

Список всех живых прокси лежит в ветке `stats` — файл вида `{дата}-LiveProxy` (обновляется при каждой генерации):

```
https://raw.githubusercontent.com/Holy16rus/NetherLink/stats/13.08.26-LiveProxy
```

Смотреть все файлы: [ветка stats](https://github.com/Holy16rus/NetherLink/tree/stats)

---

## 🔧 Как это работает

1. **Сбор** — 50+ источников прокси (публичные репозитории, API, web-сервисы)
2. **Грубый экран** — TCP-подключение отсеивает заведомо мёртвое
3. **Строгая проверка ядром mihomo (как в клиенте)** — каждая нода получает свой локальный порт; через него проходит HTTPS-запрос с проверкой сертификата **и** закачка ≥200 КБ. Нода, которая «отвечает», но не гонит данные (HTTP-прокси без CONNECT, воркеры с мёртвым бэкендом, зависающие туннели), не проходит
4. **Расширенные тесты прошедших** — доступность Telegram, YouTube и ИИ-API, целостность plain-HTTP трафика (подменяющие ноды выкидываются), выходной IP и страна, скорость закачки
5. **Отбор** — история стабильности + скорость, дедуп по **выходному IP** (разные входы в один выход — это один канал), ограниченная доля CF-воркеров
6. **Резервный пул** — до 1500 проверенных нод хранится в ветке `stats`; каждый час весь пул перепроверяется и списки пересобираются из тех, кто жив прямо сейчас
7. **Самонастройка** — раз в неделю считается реальная отдача каждого источника, пустые отключаются автоматически
8. **Генерация** — конфиги в ветку `subscription` (вместе с `status.json`), пул и история — в ветку `stats`

**Протоколы:** VMess, VLESS (в т.ч. Reality), Trojan, Shadowsocks, Hysteria2, SOCKS5, HTTP

**Источники:** прямые raw-файлы агрегаторов (Free-v2ray-Configs и др.), публичные списки HTTP/SOCKS5 и публичные Telegram-каналы (`t.me/s/<канал>`)

### Почему прокси умирают?

Публичные прокси живут от минут до дней — они появляются и исчезают. Поэтому NetherLink:
- ⏱ Полная пересборка — каждые **4 часа**
- 🔁 **Каждый час** перепроверяется весь резервный пул (до 1500 нод), и подписки пересобираются из живых — а не просто «урезаются»
- ♻️ Ноды «мигают» (то живы, то нет): нода уходит из пула только после 3 проваленных проверок подряд
- 🧠 Помнит историю каждого прокси за **5 запусков**

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
**Ответ:** Автообновление раз в 1-2 часа. Списки пересобираются на GitHub каждый час, полная пересборка — раз в 4 часа.

**Вопрос:** Сколько прокси реально работает?
**Ответ:** Из сотен тысяч собранных ссылок данные реально проходят через считанные проценты — это нормально для публичных бесплатных источников. Мы показываем честную цифру: сколько нод проверено, сколько прошло, откуда проверяли — в [status.json](https://raw.githubusercontent.com/Holy16rus/NetherLink/subscription/status.json) и бейджах вверху. Подписки на «500» больше нет: размер основного списка — это число реально живых нод на момент проверки, а топ-100 и топ-50 — лучшие из них.

**Вопрос:** Откуда проверяли?
**Ответ:** Автоматическая проверка идёт с серверов GitHub Actions (США/Европа). Из России часть нод может вести себя иначе — если нода «прошла», но у тебя не работает, это нормально: выбирай другую из группы или топа.

---

## 📊 Статус

- [status.json — последняя проверка](https://raw.githubusercontent.com/Holy16rus/NetherLink/subscription/status.json)
- [Последний workflow](https://github.com/Holy16rus/NetherLink/actions)
- [Живые прокси (ветка stats)](https://github.com/Holy16rus/NetherLink/tree/stats)
- Telegram: [@githoly](https://t.me/githoly)

---

## ⚖️ Дисклеймер

Проект предназначен только для образовательных целей и тестирования. Автор не несёт ответственности за использование предоставленных конфигураций. Уважайте законы своей страны.
