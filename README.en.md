# HolyVPN

<p align="center">
  <a href="/README.md"><img src="https://img.shields.io/badge/🇷🇺%20Русский-README-orange" alt="RU"></a>
  <a href="https://t.me/githoly"><img src="https://img.shields.io/badge/📬%20Telegram-@githoly-0088cc" alt="Telegram"></a>
</p>

**HolyVPN** — a proxy subscription generator for Clash clients. It scrapes public proxies, checks their availability, detects country and latency, and produces a ready-to-use YAML configuration.

---

## Subscription URL

```
https://raw.githubusercontent.com/Holy16rus/HolyVpn/gh-pages/HolyVPN.yaml
```

Use this link in **FLClash**, **Clash Meta**, or any other Clash-compatible client as a subscription URL. The configuration is automatically regenerated every 6 hours.

---

## Features

- **Scraping** proxies from GitHub repositories and public APIs
- **Parsing** all major formats: HTTP, SOCKS5, Shadowsocks, VMess, VLESS, Trojan, Hysteria2
- **Validation** with latency measurement (TCP handshake, up to 200 concurrent)
- **Geolocation** via MaxMind GeoLite2 (local) with ip-api.com fallback
- **Generation** of Clash YAML with speed-based sorting and country grouping
- **Web interface** with SSE streaming, FULL / DATA mode selection, and live logs

---

## Local Setup

**Requirements:** Python 3.11+, Git

```bash
git clone https://github.com/Holy16rus/HolyVpn.git
cd HolyVpn
pip install -r requirements.txt
python start.py
```

Open `http://127.0.0.1:1488` in your browser.

---

## Automated Generation (CI/CD)

The repository automatically regenerates the subscription every 6 hours via GitHub Actions. Manual trigger is also available: **Actions → Generate Proxy Config → Run workflow**.

For CI to work, a [free MaxMind license key](https://dev.maxmind.com/geoip/geolite2-free-geolocation-data) must be added to the repository secrets as `GEOIP_LICENSE_KEY`.

---

## Contact

For questions, suggestions, or bug reports, reach out on Telegram: [@githoly](https://t.me/githoly)
