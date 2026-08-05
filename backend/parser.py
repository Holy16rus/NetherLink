import base64
import json
import re
import urllib.parse

SUPPORTED_URI_SCHEMES = {"http", "https", "socks4", "socks5", "ss", "trojan", "vmess", "vless", "hysteria2", "hy2"}
TEXT_FILE_EXTENSIONS = (".txt", ".yaml", ".yml", ".json", ".csv", ".conf", ".list", ".sub", ".md")
SKIP_PATH_PARTS = (".git/", "node_modules/", "dist/", "build/", "vendor/", "__pycache__/")
COUNTRY_ALIASES = {
    "UNITED STATES": "US", "USA": "US", "US": "US", "США": "US", "АМЕРИКА": "US",
    "GERMANY": "DE", "DEUTSCHLAND": "DE", "DE": "DE", "ГЕРМАНИЯ": "DE",
    "FRANCE": "FR", "FR": "FR", "ФРАНЦИЯ": "FR",
    "NETHERLANDS": "NL", "HOLLAND": "NL", "NL": "NL", "НИДЕРЛАНДЫ": "NL", "ГОЛЛАНДИЯ": "NL",
    "UNITED KINGDOM": "GB", "UK": "GB", "GB": "GB", "BRITAIN": "GB", "ВЕЛИКОБРИТАНИЯ": "GB",
    "CANADA": "CA", "CA": "CA", "КАНАДА": "CA",
    "SINGAPORE": "SG", "SG": "SG", "СИНГАПУР": "SG",
    "JAPAN": "JP", "JP": "JP", "ЯПОНИЯ": "JP",
    "KOREA": "KR", "SOUTH KOREA": "KR", "KR": "KR", "КОРЕЯ": "KR", "ЮЖНАЯ КОРЕЯ": "KR",
    "HONG KONG": "HK", "HK": "HK", "ГОНКОНГ": "HK",
    "TURKEY": "TR", "TR": "TR", "ТУРЦИЯ": "TR",
    "POLAND": "PL", "PL": "PL", "ПОЛЬША": "PL",
    "SWEDEN": "SE", "SE": "SE", "ШВЕЦИЯ": "SE",
    "FINLAND": "FI", "FI": "FI", "ФИНЛЯНДИЯ": "FI",
    "SPAIN": "ES", "ES": "ES", "ИСПАНИЯ": "ES",
    "ITALY": "IT", "IT": "IT", "ИТАЛИЯ": "IT",
    "AUSTRIA": "AT", "AT": "AT", "АВСТРИЯ": "AT",
    "SWITZERLAND": "CH", "CH": "CH", "ШВЕЙЦАРИЯ": "CH",
    "RUSSIA": "RU", "RU": "RU", "РОССИЯ": "RU",
    "UKRAINE": "UA", "UA": "UA", "УКРАИНА": "UA",
    "AUSTRALIA": "AU", "AU": "AU", "АВСТРАЛИЯ": "AU",
    "BRAZIL": "BR", "BR": "BR", "БРАЗИЛИЯ": "BR",
    "INDIA": "IN", "IN": "IN", "ИНДИЯ": "IN",
    "INDONESIA": "ID", "ID": "ID", "ИНДОНЕЗИЯ": "ID",
    "VIETNAM": "VN", "VN": "VN", "ВЬЕТНАМ": "VN",
    "THAILAND": "TH", "TH": "TH", "ТАИЛАНД": "TH",
    "TAIWAN": "TW", "TW": "TW", "ТАЙВАНЬ": "TW",
    "CHINA": "CN", "CN": "CN", "КИТАЙ": "CN",
    "MALAYSIA": "MY", "MY": "MY", "МАЛАЙЗИЯ": "MY",
    "PHILIPPINES": "PH", "PH": "PH", "ФИЛИППИНЫ": "PH",
    "ROMANIA": "RO", "RO": "RO", "РУМЫНИЯ": "RO",
    "CZECH": "CZ", "CZECHIA": "CZ", "CZ": "CZ", "ЧЕХИЯ": "CZ",
    "LITHUANIA": "LT", "LT": "LT", "ЛИТВА": "LT",
    "LATVIA": "LV", "LV": "LV", "ЛАТВИЯ": "LV",
    "ESTONIA": "EE", "EE": "EE", "ЭСТОНИЯ": "EE",
    "NORWAY": "NO", "NO": "NO", "НОРВЕГИЯ": "NO",
    "DENMARK": "DK", "DK": "DK", "ДАНИЯ": "DK",
    "BELGIUM": "BE", "BE": "BE", "БЕЛЬГИЯ": "BE",
    "IRELAND": "IE", "IE": "IE", "ИРЛАНДИЯ": "IE",
    "ISRAEL": "IL", "IL": "IL", "ИЗРАИЛЬ": "IL",
    "MEXICO": "MX", "MX": "MX", "МЕКСИКА": "MX",
    "ARGENTINA": "AR", "AR": "AR", "АРГЕНТИНА": "AR",
    "UAE": "AE", "AE": "AE", "ОАЭ": "AE",
}


def flag_emoji(code):
    if not code or len(code) != 2 or not code.isalpha() or code == "ZZ":
        return ""
    return chr(ord(code[0]) + 127397) + chr(ord(code[1]) + 127397)


def country_from_flag(text):
    for idx, char in enumerate(text):
        codepoint = ord(char)
        if 127462 <= codepoint <= 127487 and idx + 1 < len(text):
            next_codepoint = ord(text[idx + 1])
            if 127462 <= next_codepoint <= 127487:
                return chr(codepoint - 127397) + chr(next_codepoint - 127397)
    return "ZZ"


def infer_country_hint(*values):
    text = " ".join(str(v or "") for v in values)
    flagged = country_from_flag(text)
    if flagged != "ZZ":
        return flagged

    normalized = urllib.parse.unquote(text).upper()
    normalized = re.sub(r"[^A-ZА-ЯЁ]+", " ", normalized)
    padded = f" {normalized} "
    for name in sorted(COUNTRY_ALIASES, key=len, reverse=True):
        if f" {name} " in padded:
            return COUNTRY_ALIASES[name]
    return "ZZ"


def b64_decode_padded(text):
    text = text.strip().replace("-", "+").replace("_", "/")
    text += "=" * ((4 - len(text) % 4) % 4)
    return base64.b64decode(text).decode("utf-8", errors="replace")


def parse_http_like_uri(uri, country, source):
    parsed = urllib.parse.urlparse(uri)
    hint = infer_country_hint(parsed.fragment, source)
    country = hint if hint != "ZZ" else country
    user = urllib.parse.unquote(parsed.username or "") or None
    password = urllib.parse.unquote(parsed.password or "") or None
    if not parsed.hostname or not parsed.port:
        return None
    return {"protocol": parsed.scheme.lower(), "server": parsed.hostname, "port": parsed.port,
            "username": user, "password": password, "country": country, "source": source, "raw": uri}


def parse_vless_uri(uri, country, source):
    parsed = urllib.parse.urlparse(uri)
    if not parsed.username or not parsed.hostname or not parsed.port:
        return None
    params = urllib.parse.parse_qs(parsed.query)
    hint = infer_country_hint(parsed.fragment, source)
    country = hint if hint != "ZZ" else country
    return {"protocol": "vless", "server": parsed.hostname, "port": parsed.port,
            "uuid": parsed.username, "network": params.get("type", ["tcp"])[0],
            "tls": params.get("security", [""])[0] in {"tls", "reality"},
            "servername": params.get("sni", params.get("host", [""]))[0],
            "ws_path": params.get("path", [""])[0], "ws_host": params.get("host", [""])[0],
            "flow": params.get("flow", [""])[0],
            "pbk": params.get("pbk", [""])[0], "sid": params.get("sid", [""])[0],
            "fp": params.get("fp", [""])[0],
            "grpc_service_name": params.get("serviceName", params.get("service_name", [""]))[0],
            "country": country, "source": source, "raw": uri}


def parse_trojan_uri(uri, country, source):
    parsed = urllib.parse.urlparse(uri)
    if not parsed.username or not parsed.hostname or not parsed.port:
        return None
    params = urllib.parse.parse_qs(parsed.query)
    hint = infer_country_hint(parsed.fragment, source)
    country = hint if hint != "ZZ" else country
    return {"protocol": "trojan", "server": parsed.hostname, "port": parsed.port,
            "password": urllib.parse.unquote(parsed.username),
            "servername": params.get("sni", params.get("peer", [""]))[0],
            "country": country, "source": source, "raw": uri}


def parse_vmess_uri(uri, country, source):
    payload = uri.split("://", 1)[1].split("#", 1)[0]
    try:
        data = json.loads(b64_decode_padded(payload))
    except Exception:
        return None
    server = data.get("add") or data.get("server")
    port = data.get("port")
    uuid = data.get("id")
    if not server or not port or not uuid:
        return None
    hint = infer_country_hint(data.get("ps"), source)
    country = hint if hint != "ZZ" else country
    return {"protocol": "vmess", "server": server, "port": int(port), "uuid": uuid,
            "alterId": int(data.get("aid") or 0), "cipher": data.get("scy") or "auto",
            "network": data.get("net") or "tcp", "tls": str(data.get("tls") or "").lower() == "tls",
            "servername": data.get("sni") or data.get("host") or "",
            "ws_path": data.get("path") or "", "ws_host": data.get("host") or "",
            "country": country, "source": source, "raw": uri}


def parse_ss_uri(uri, country, source):
    value = uri.split("://", 1)[1].split("#", 1)[0].split("?", 1)[0]
    fragment = uri.split("#", 1)[1] if "#" in uri else ""
    try:
        if "@" not in value:
            value = b64_decode_padded(value)
        userinfo, address = value.rsplit("@", 1)
        if ":" not in userinfo:
            userinfo = b64_decode_padded(userinfo)
        method, password = userinfo.split(":", 1)
        server, port = address.rsplit(":", 1)
    except Exception:
        return None
    hint = infer_country_hint(fragment, source)
    country = hint if hint != "ZZ" else country
    return {"protocol": "ss", "server": server.strip("[]"), "port": int(port),
            "cipher": method, "password": urllib.parse.unquote(password),
            "country": country, "source": source, "raw": uri}


def parse_hysteria2_uri(uri, country, source):
    parsed = urllib.parse.urlparse(uri.replace("hy2://", "hysteria2://", 1))
    if not parsed.hostname or not parsed.port:
        return None
    params = urllib.parse.parse_qs(parsed.query)
    hint = infer_country_hint(parsed.fragment, source)
    country = hint if hint != "ZZ" else country
    return {"protocol": "hysteria2", "server": parsed.hostname, "port": parsed.port,
            "password": urllib.parse.unquote(parsed.username or ""),
            "servername": params.get("sni", [""])[0],
            "country": country, "source": source, "raw": uri}


def parse_uri(uri, country, source):
    scheme = uri.split("://", 1)[0].lower()
    try:
        if scheme in {"http", "https", "socks4", "socks5"}:
            return parse_http_like_uri(uri, country, source)
        if scheme == "vless":
            return parse_vless_uri(uri, country, source)
        if scheme == "trojan":
            return parse_trojan_uri(uri, country, source)
        if scheme == "vmess":
            return parse_vmess_uri(uri, country, source)
        if scheme == "ss":
            return parse_ss_uri(uri, country, source)
        if scheme in {"hysteria2", "hy2"}:
            return parse_hysteria2_uri(uri, country, source)
    except Exception:
        return None
    return None


def infer_protocol_from_path(path):
    lowered = path.lower()
    if "socks5" in lowered:
        return "socks5"
    if "socks4" in lowered:
        return "socks4"
    if "https" in lowered:
        return "https"
    if "http" in lowered:
        return "http"
    return "http"


def extract_from_text(text, country, source):
    found = []
    protocol_hint = infer_protocol_from_path(source)
    cleaned = text

    uri_pattern = re.compile(r"\b([a-zA-Z0-9+.-]+://[^\s\"'<>]+)")
    for match in uri_pattern.finditer(text):
        uri = match.group(1).strip().rstrip(",;)]}")
        scheme = uri.split("://", 1)[0].lower()
        if scheme in SUPPORTED_URI_SCHEMES:
            parsed = parse_uri(uri, country, source)
            if parsed:
                found.append(parsed)
            cleaned = cleaned.replace(match.group(1), " ")

    ip_port = re.compile(r"(?<![\w./:-])((?:\d{1,3}\.){3}\d{1,3}):(\d{2,5})(?![\w.-])")
    for host, port in ip_port.findall(cleaned):
        if all(0 <= int(p) <= 255 for p in host.split(".")) and 0 < int(port) <= 65535:
            found.append({"protocol": protocol_hint, "server": host, "port": int(port),
                          "country": country, "source": source, "raw": f"{host}:{port}"})

    host_port = re.compile(r"(?<![\w./:-])([a-zA-Z0-9][a-zA-Z0-9.-]+\.[a-zA-Z]{2,}):(\d{2,5})(?![\w.-])")
    for host, port in host_port.findall(cleaned):
        found.append({"protocol": protocol_hint, "server": host, "port": int(port),
                      "country": country, "source": source, "raw": f"{host}:{port}"})

    return found


def walk_json(value, country, source):
    found = []
    if isinstance(value, dict):
        parsed = normalize_proxy_obj(value, country, source)
        if parsed:
            found.append(parsed)
        for child in value.values():
            found.extend(walk_json(child, country, source))
    elif isinstance(value, list):
        for child in value:
            found.extend(walk_json(child, country, source))
    elif isinstance(value, str):
        found.extend(extract_from_text(value, country, source))
    return found


def normalize_proxy_obj(obj, country, source):
    hint = infer_country_hint(obj.get("country"), obj.get("countryCode"), obj.get("cc"), obj.get("name"), obj.get("remarks"), source)
    if hint != "ZZ":
        country = hint
    proxy_text = obj.get("proxy") or obj.get("url") or obj.get("link")
    if proxy_text and isinstance(proxy_text, str) and "://" in proxy_text:
        return parse_uri(proxy_text, country, source)
    protocol = str(obj.get("protocol") or infer_protocol_from_path(source)).lower()
    server = obj.get("ip") or obj.get("address") or obj.get("host") or obj.get("server")
    port = obj.get("port")
    if not server or not port:
        return None
    return {"protocol": protocol, "server": server, "port": int(port),
            "country": country, "source": source, "raw": proxy_text or f"{server}:{port}"}


def extract_proxies(content, path, source):
    country = infer_country_hint(path, source)
    stripped = content.lstrip()
    if path.lower().endswith(".json") or "format=json" in path.lower() or stripped.startswith(("[", "{")):
        try:
            return walk_json(json.loads(content), country, path)
        except Exception:
            pass
    return extract_from_text(content, country, path)


def dedupe(nodes):
    seen = set()
    result = []
    for node in nodes:
        protocol = node.get("protocol", "").lower()
        if protocol == "socks4":
            continue
        key = (protocol, str(node.get("server", "")).lower(), int(node.get("port", 0)),
               node.get("uuid") or node.get("password") or node.get("username") or "")
        if not key[1] or not key[2] or key in seen:
            continue
        seen.add(key)
        result.append(node)
    return result


def path_score(path):
    lowered = path.lower()
    if any(part in lowered for part in SKIP_PATH_PARTS):
        return -100
    if not lowered.endswith(TEXT_FILE_EXTENSIONS):
        return -100
    score = 0
    for word in ("proxy", "proxies", "free", "clash", "v2ray", "sub", "http", "socks", "list"):
        if word in lowered:
            score += 2
    if lowered.endswith((".txt", ".yaml", ".yml", ".json")):
        score += 1
    return score
