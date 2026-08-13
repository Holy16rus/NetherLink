# NetherLink

<p align="center">
  <a href="/README.md"><img src="https://img.shields.io/badge/🇷🇺%20Русский-README-orange" alt="RU"></a>
  <a href="https://t.me/githoly"><img src="https://img.shields.io/badge/📬%20Telegram-@githoly-0088cc" alt="Telegram"></a>
</p>

**NetherLink** — a proxy subscription generator. Scrapes public proxies, checks availability, measures speed, detects country and latency, and generates configs for **FLClash** and **Happ (Xray)**. Auto-updates every **10 hours**.

---

## Subscriptions

Copy a link and paste it into your client (long-press → copy):

### FLClash / Clash Meta (YAML)

```
https://raw.githubusercontent.com/Holy16rus/NetherLink/subscription/NetherLink-Clash.yaml
https://raw.githubusercontent.com/Holy16rus/NetherLink/subscription/NetherLink-100.yaml
https://raw.githubusercontent.com/Holy16rus/NetherLink/subscription/NetherLink-50.yaml
```

- **NetherLink-Clash.yaml** — full set (~500 proxies: ~250 tunnel + ~250 HTTP/SOCKS)
- **NetherLink-100.yaml** — selected top-100
- **NetherLink-50.yaml** — top-50, rechecked hourly

### Happ / Xray (tunnel-only: vless/vmess/trojan/ss)

```
https://raw.githubusercontent.com/Holy16rus/NetherLink/subscription/NetherLink-Xray-100.txt
https://raw.githubusercontent.com/Holy16rus/NetherLink/subscription/NetherLink-Xray-50.txt
```

- **NetherLink-Xray-100.txt** — top-100 tunnel proxies
- **NetherLink-Xray-50.txt** — top-50 tunnel proxies

---

## 📊 Live proxies (stats)

All live proxies are published to the `stats` branch as `{date}-LiveProxy` (updated on each generation):

```
https://raw.githubusercontent.com/Holy16rus/NetherLink/stats/13.08.26-LiveProxy
```

Browse all files: [stats branch](https://github.com/Holy16rus/NetherLink/tree/stats)

---

## Features

- **Scraping** from 50+ sources (GitHub repos, public APIs, Telegram channels)
- **Parsing** all formats: HTTP, HTTPS, SOCKS5, Shadowsocks, VMess, VLESS, Trojan, Hysteria2
- **Validation** with latency measurement (TCP/HTTP/SOCKS5, up to 200 concurrent)
- **Speed test** — bandwidth measurement via 1MB download
- **Re-check** — re-verify top-100 and top-50 proxies every hour
- **Geolocation** via MaxMind GeoLite2 (local) with ip-api.com fallback
- **Multi-format output**: Clash YAML, V2Ray JSON, Sing-box JSON
- **Web interface** with SSE streaming, FULL / DATA mode selection, live logs
- **Auto-update** every 10 hours via GitHub Actions

---

## Local Setup

**Requirements:** Python 3.11+, Git

```bash
git clone https://github.com/Holy16rus/NetherLink.git
cd NetherLink
pip install -r requirements.txt
python start.py
```

Open `http://127.0.0.1:1488` in your browser.

---

## Automated Generation (CI/CD)

The repository automatically regenerates all subscriptions every **10 hours** via GitHub Actions. Configs go to the `subscription` branch, live proxies to the `stats` branch.

A [free MaxMind license key](https://dev.maxmind.com/geoip/geolite2-free-geolocation-data) is required as `GEOIP_LICENSE_KEY` in repository secrets.

---

## Proxy Sources

50+ sources are scraped, including:
- `monosans/proxy-list`, `TheSpeedX/PROXY-List`, `jetkai/proxy-list`
- `proxifly/free-proxy-list`, `roosterkid/openproxylist`, `ShiftyTR/Proxy-List`
- `clarketm/proxy-list`, `ALIILAPRO/Proxy`, `hookzof/socks5_list`
- `RKPchannel/RKP_bypass_configs`, `luxxuria/harvester`, `HalyavusVPNUS/halyava-vpn-buy`
- `spys.me`, `ProxyScrape`, `proxy-list.download`, `free.redscrape.com`
- And dozens more

---

## Contact

For questions, suggestions, or bug reports: [@githoly](https://t.me/githoly)
