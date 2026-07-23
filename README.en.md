# NetherLink

<p align="center">
  <a href="/README.md"><img src="https://img.shields.io/badge/🇷🇺%20Русский-README-orange" alt="RU"></a>
  <a href="https://t.me/githoly"><img src="https://img.shields.io/badge/📬%20Telegram-@githoly-0088cc" alt="Telegram"></a>
</p>

**NetherLink** — a proxy subscription generator. Scrapes public proxies, checks availability, measures speed, detects country and latency, and generates configs for **FLClash**, **V2rayTun**, and **HiddifyApp**.

---

## Subscriptions

### 500 proxies (FLClash only)
```
https://raw.githubusercontent.com/Holy16rus/NetherLink/gh-pages/NetherLink.yaml
```
> `/sub/500` — for Clash-compatible clients only. Other clients can't handle that many proxies.

### 100 proxies (auto-detect client)
```
https://your-server/sub/100
```
Client auto-detected by User-Agent:
- **FLClash / Clash Meta** → YAML
- **V2rayTun / V2RayNG** → JSON
- **HiddifyApp / Sing-box** → JSON

Force format: `/sub/100?format=clash|v2ray|singbox`

### 50 proxies (auto-detect client)
```
https://your-server/sub/50
```
Same as `/sub/100`, but only the best of the best — rechecked and speed-tested.

### Raw files on gh-pages

| File | Description |
|------|-------------|
| `NetherLink.yaml` | FLClash, 500 proxies |
| `NetherLink-100.yaml` | FLClash, top-100 |
| `NetherLink-50.yaml` | FLClash, top-50 |
| `NetherLink-v2ray.json` | V2Ray, all live |
| `NetherLink-100-v2ray.json` | V2Ray, top-100 |
| `NetherLink-50-v2ray.json` | V2Ray, top-50 |
| `NetherLink-singbox.json` | Sing-box, all live |
| `NetherLink-100-singbox.json` | Sing-box, top-100 |
| `NetherLink-50-singbox.json` | Sing-box, top-50 |
| `live.txt` | All live proxies (plain text) |

Base URL: `https://raw.githubusercontent.com/Holy16rus/NetherLink/gh-pages/`

---

## Features

- **Scraping** from 50+ sources (GitHub repos, public APIs, Telegram channels)
- **Parsing** all formats: HTTP, HTTPS, SOCKS5, Shadowsocks, VMess, VLESS, Trojan, Hysteria2
- **Validation** with latency measurement (TCP/HTTP/SOCKS5, up to 200 concurrent)
- **Speed test** — bandwidth measurement via 1MB download (10 min cycle)
- **Re-check** — re-verify top-100 and top-50 proxies
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

The repository automatically regenerates all subscriptions every **10 hours** via GitHub Actions. All configs and `live.txt` are published to `gh-pages`.

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
