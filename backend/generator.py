import json
import base64
from urllib.parse import quote

COUNTRY_NAMES_RU = {
    "AE": "ОАЭ", "AR": "Аргентина", "AT": "Австрия", "AU": "Австралия",
    "BE": "Бельгия", "BG": "Болгария", "BR": "Бразилия", "CA": "Канада",
    "CH": "Швейцария", "CL": "Чили", "CN": "Китай", "CO": "Колумбия",
    "CZ": "Чехия", "DE": "Германия", "DK": "Дания", "EE": "Эстония",
    "EG": "Египет", "ES": "Испания", "FI": "Финляндия", "FR": "Франция",
    "GB": "Великобритания", "GR": "Греция", "HK": "Гонконг", "HU": "Венгрия",
    "ID": "Индонезия", "IE": "Ирландия", "IL": "Израиль", "IN": "Индия",
    "IT": "Италия", "JP": "Япония", "KR": "Южная Корея", "LT": "Литва",
    "LV": "Латвия", "MX": "Мексика", "MY": "Малайзия", "NL": "Нидерланды",
    "NO": "Норвегия", "NZ": "Новая Зеландия", "PH": "Филиппины", "PL": "Польша",
    "PT": "Португалия", "RO": "Румыния", "RU": "Россия", "SE": "Швеция",
    "SG": "Сингапур", "SK": "Словакия", "TH": "Таиланд", "TR": "Турция",
    "TW": "Тайвань", "UA": "Украина", "US": "США", "VN": "Вьетнам",
    "ZA": "ЮАР", "ZZ": "Неизвестно",
    # ── дополнено: частые страны из реальных проверок ──
    "AZ": "Азербайджан", "AM": "Армения", "BD": "Бангладеш", "BY": "Беларусь",
    "GE": "Грузия", "IR": "Иран", "KZ": "Казахстан", "KE": "Кения",
    "MD": "Молдова", "NG": "Нигерия", "PK": "Пакистан", "SA": "Саудовская Аравия",
    "SY": "Сирия", "UZ": "Узбекистан", "RS": "Сербия", "HR": "Хорватия",
    "SI": "Словения", "BA": "Босния и Герцеговина", "MK": "Северная Македония",
    "AL": "Албания", "CY": "Кипр", "MT": "Мальта", "LU": "Люксембург",
    "IS": "Исландия", "LI": "Лихтенштейн", "MC": "Монако", "AD": "Андорра",
    "SM": "Сан-Марино", "VA": "Ватикан", "GI": "Гибралтар", "JE": "Джерси",
    "GG": "Гернси", "IM": "Остров Мэн", "FO": "Фарерские острова", "GL": "Гренландия",
    "PY": "Парагвай", "UY": "Уругвай", "BO": "Боливия", "EC": "Эквадор",
    "PE": "Перу", "VE": "Венесуэла", "CR": "Коста-Рика", "PA": "Панама",
    "DO": "Доминикана", "GT": "Гватемала", "HN": "Гондурас", "NI": "Никарагуа",
    "SV": "Сальвадор", "JM": "Ямайка", "CU": "Куба", "TT": "Тринидад и Тобаго",
    "PR": "Пуэрто-Рико", "BS": "Багамы", "BB": "Барбадос",
    "NP": "Непал", "LK": "Шри-Ланка", "MM": "Мьянма", "KH": "Камбоджа",
    "LA": "Лаос", "MN": "Монголия", "BD": "Бангладеш", "BT": "Бутан",
    "MV": "Мальдивы", "BN": "Бруней", "TL": "Восточный Тимор",
    "DZ": "Алжир", "MA": "Марокко", "TN": "Тунис", "LY": "Ливия",
    "SD": "Судан", "ET": "Эфиопия", "GH": "Гана", "CI": "Кот-д'Ивуар",
    "SN": "Сенегал", "CM": "Камерун", "UG": "Уганда", "TZ": "Танзания",
    "ZW": "Зимбабве", "MZ": "Мозамбик", "AO": "Ангола", "NA": "Намибия",
    "BW": "Ботсвана", "ZM": "Замбия", "MW": "Малави", "MG": "Мадагаскар",
    "MU": "Маврикий", "SC": "Сейшелы",
    "KZ": "Казахстан", "KG": "Киргизия", "TJ": "Таджикистан", "TM": "Туркменистан",
    "AF": "Афганистан", "IQ": "Ирак", "JO": "Иордания", "LB": "Ливан",
    "PS": "Палестина", "YE": "Йемен", "OM": "Оман", "QA": "Катар",
    "KW": "Кувейт", "BH": "Бахрейн",
}


def flag_emoji(code):
    if not code or len(code) != 2 or not code.isalpha():
        return ""
    code = code.upper()
    return chr(ord(code[0]) + 127397) + chr(ord(code[1]) + 127397)


def yaml_quote(value):
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def latency_sort_key(node):
    raw = node.get("latency_ms")
    base = int(raw) if raw is not None else 999999999
    return (base, str(node.get("server", "")), int(node.get("port", 0)))


def select_nodes(nodes, limit, strategy="fastest"):
    if strategy == "fastest":
        return sorted(nodes, key=latency_sort_key)[:limit]
    by_country = {}
    for node in nodes:
        c = node.get("country", "ZZ")
        by_country.setdefault(c, []).append(node)
    selected = []
    for pool in by_country.values():
        pool.sort(key=latency_sort_key)
    countries = sorted(by_country.keys(), key=lambda c: latency_sort_key(by_country[c][0]))
    while countries and len(selected) < limit:
        next_round = []
        for c in countries:
            pool = by_country[c]
            if pool and len(selected) < limit:
                selected.append(pool.pop(0))
            if pool:
                next_round.append(c)
        countries = next_round
    return sorted(selected, key=latency_sort_key)


def node_name(node, used_names):
    # Готовое имя (напр. «🇺🇸 США 52ms» из пайплайна) уважаем — уникализируем
    existing = node.get("name")
    if existing and str(existing).strip():
        base = str(existing)
        name = base
        counter = 2
        while name in used_names:
            name = f"{base}-{counter}"
            counter += 1
        used_names.add(name)
        return name
    country = node.get("country") or "ZZ"
    cname = COUNTRY_NAMES_RU.get(country, "Неизвестно")
    flag = flag_emoji(country)
    latency = node.get("latency_ms")
    speed = f" {int(latency)}ms" if latency is not None else ""
    base = f"{flag + ' ' if flag else ''}{cname}{speed}"
    name = base
    counter = 2
    while name in used_names:
        name = f"{base}-{counter}"
        counter += 1
    used_names.add(name)
    return name


def clash_type(protocol):
    mapping = {"https": "http", "hy2": "hysteria2"}
    return mapping.get(protocol, protocol)


def generate_config_clash(nodes):
    used_names = set()
    by_country = {}
    proxy_names = []
    lines = [
        "# Configuration: NetherLink",
        "# Generated by NetherLink",
        f"# Total proxies: {len(nodes)}",
        "",
        'name: "NetherLink"',
        "port: 7890",
        "socks-port: 7891",
        "allow-lan: true",
        "mode: Global",
        "log-level: info",
        "external-controller: 127.0.0.1:9090",
        "",
        "proxies:",
    ]
    for node in nodes:
        name = node_name(node, used_names)
        node["name"] = name
        proxy_names.append(name)
        c = node.get("country") or "ZZ"
        by_country.setdefault(c, []).append(name)
        lines.append(f"  - name: {yaml_quote(name)}")
        lines.append(f"    type: {clash_type(node['protocol'].lower())}")
        lines.append(f"    server: {node['server']}")
        lines.append(f"    port: {int(node['port'])}")
        protocol = node["protocol"].lower()
        if protocol in {"http", "https"}:
            if protocol == "https":
                lines.append("    tls: true")
            if node.get("username"):
                lines.append(f"    username: {yaml_quote(node['username'])}")
            if node.get("password"):
                lines.append(f"    password: {yaml_quote(node['password'])}")
        elif protocol == "socks5":
            if node.get("username"):
                lines.append(f"    username: {yaml_quote(node['username'])}")
            if node.get("password"):
                lines.append(f"    password: {yaml_quote(node['password'])}")
        elif protocol == "ss":
            lines.append(f"    cipher: {yaml_quote(node.get('cipher', ''))}")
            lines.append(f"    password: {yaml_quote(node.get('password', ''))}")
        elif protocol == "vmess":
            lines.append(f"    uuid: {yaml_quote(node.get('uuid', ''))}")
            lines.append(f"    alterId: {int(node.get('alterId', 0))}")
            lines.append(f"    cipher: {yaml_quote(node.get('cipher', 'auto'))}")
            lines.append(f"    network: {yaml_quote(node.get('network', 'tcp'))}")
            lines.append(f"    tls: {str(bool(node.get('tls'))).lower()}")
            if node.get("servername"):
                lines.append(f"    servername: {yaml_quote(node['servername'])}")
            if node.get("ws_path") or node.get("ws_host"):
                lines.append("    ws-opts:")
                if node.get("ws_path"):
                    lines.append(f"      path: {yaml_quote(node['ws_path'])}")
                if node.get("ws_host"):
                    lines.append("      headers:")
                    lines.append(f"        Host: {yaml_quote(node['ws_host'])}")
        elif protocol == "vless":
            lines.append(f"    uuid: {yaml_quote(node.get('uuid', ''))}")
            if node.get("flow"):
                lines.append(f"    flow: {yaml_quote(node['flow'])}")
            network = node.get("network", "tcp")
            lines.append(f"    network: {yaml_quote(network)}")
            lines.append(f"    tls: {str(bool(node.get('tls'))).lower()}")
            if node.get("servername"):
                lines.append(f"    servername: {yaml_quote(node['servername'])}")
            if network == "ws" and (node.get("ws_path") or node.get("ws_host")):
                lines.append("    ws-opts:")
                if node.get("ws_path"):
                    lines.append(f"      path: {yaml_quote(node['ws_path'])}")
                if node.get("ws_host"):
                    lines.append("      headers:")
                    lines.append(f"        Host: {yaml_quote(node['ws_host'])}")
            elif network in ("xhttp", "splithttp") and (node.get("ws_path") or node.get("ws_host")):
                lines.append("    ws-opts:")
                if node.get("ws_path"):
                    lines.append(f"      path: {yaml_quote(node['ws_path'])}")
                if node.get("ws_host"):
                    lines.append("      headers:")
                    lines.append(f"        Host: {yaml_quote(node['ws_host'])}")
            elif network == "grpc" and node.get("grpc_service_name"):
                lines.append("    grpc-opts:")
                lines.append(f"      grpc-service-name: {yaml_quote(node['grpc_service_name'])}")
        elif protocol == "trojan":
            lines.append(f"    password: {yaml_quote(node.get('password', ''))}")
            lines.append("    skip-cert-verify: true")
            if node.get("servername"):
                lines.append(f"    sni: {yaml_quote(node['servername'])}")
        elif protocol == "hysteria2":
            lines.append(f"    password: {yaml_quote(node.get('password', ''))}")
            lines.append("    skip-cert-verify: true")
            if node.get("servername"):
                lines.append(f"    sni: {yaml_quote(node['servername'])}")
        lines.append("")
    lines.extend([
        "proxy-groups:",
        "  - name: PROXY",
        "    type: select",
        "    proxies:",
        f"      - {yaml_quote('Auto-Смена')}",
    ])
    for c, names in sorted(by_country.items(), key=lambda x: (-len(x[1]), x[0])):
        cname = COUNTRY_NAMES_RU.get(c.upper() if c else c, "Неизвестно")
        flag = flag_emoji(c)
        group_name = f"{flag + ' ' if flag else ''}{cname}"
        lines.append(f"      - {yaml_quote(group_name)}")
    lines.append("      - DIRECT")
    lines.append("")
    lines.extend([
        f"  - name: {yaml_quote('Auto-Смена')}",
        "    type: url-test",
        "    url: http://www.gstatic.com/generate_204",
        "    interval: 300",
        "    tolerance: 50",
        "    proxies:",
    ])
    for name in proxy_names:
        lines.append(f"      - {yaml_quote(name)}")
    lines.append("")
    for c, names in sorted(by_country.items(), key=lambda x: (-len(x[1]), x[0])):
        cname = COUNTRY_NAMES_RU.get(c.upper() if c else c, "Неизвестно")
        flag = flag_emoji(c)
        group_name = f"{flag + ' ' if flag else ''}{cname}"
        lines.append(f"  - name: {yaml_quote(group_name)}")
        lines.append("    type: select")
        lines.append("    proxies:")
        for name in names:
            lines.append(f"      - {yaml_quote(name)}")
        lines.append("      - DIRECT")
        lines.append("")
    lines.extend([
        "rules:",
        "  - DOMAIN-SUFFIX,google.com,PROXY",
        "  - DOMAIN-SUFFIX,youtube.com,PROXY",
        "  - DOMAIN-SUFFIX,github.com,PROXY",
        "  - DOMAIN-SUFFIX,telegram.org,PROXY",
        "  - DOMAIN-SUFFIX,t.me,PROXY",
        "  - DOMAIN-KEYWORD,telegram,PROXY",
        "  - DOMAIN-SUFFIX,instagram.com,PROXY",
        "  - DOMAIN-SUFFIX,twitter.com,PROXY",
        "  - DOMAIN-SUFFIX,x.com,PROXY",
        "  - DOMAIN-SUFFIX,facebook.com,PROXY",
        "  - DOMAIN-SUFFIX,tiktok.com,PROXY",
        "  - DOMAIN-SUFFIX,netflix.com,PROXY",
        "  - DOMAIN-SUFFIX,spotify.com,PROXY",
        "  - DOMAIN-SUFFIX,openai.com,PROXY",
        "  - DOMAIN-SUFFIX,chatgpt.com,PROXY",
        "  - DOMAIN-SUFFIX,reddit.com,PROXY",
        "  - DOMAIN-SUFFIX,discord.com,PROXY",
        "  - MATCH,DIRECT",
        "",
    ])
    return "\n".join(lines)


def generate_config_v2ray(nodes):
    out = {}
    for node in nodes:
        proto = node["protocol"].lower()
        if proto in ("http", "https"):
            v = {"protocol": "http", "settings": {"servers": [{"address": node["server"], "port": int(node["port"])}]}}
            if node.get("username"):
                v["settings"]["servers"][0]["users"] = [{"user": node["username"], "pass": node.get("password", "")}]
            out[node.get("name", f"{node['server']}:{node['port']}")] = v
        elif proto == "socks5":
            v = {"protocol": "socks", "settings": {"servers": [{"address": node["server"], "port": int(node["port"])}]}}
            if node.get("username"):
                v["settings"]["servers"][0]["users"] = [{"user": node["username"], "pass": node.get("password", "")}]
            out[node.get("name", f"{node['server']}:{node['port']}")] = v
        elif proto == "vmess":
            v = {"protocol": "vmess", "settings": {"vnext": [{"address": node["server"], "port": int(node["port"]), "users": [{"id": node.get("uuid", ""), "alterId": int(node.get("alterId", 0)), "security": node.get("cipher", "auto")}]}]}}
            if node.get("network") and node["network"] != "tcp":
                v["streamSettings"] = {"network": node["network"]}
                if node.get("ws_path"):
                    v["streamSettings"]["wsSettings"] = {"path": node["ws_path"]}
                if node.get("tls"):
                    v["streamSettings"]["security"] = "tls"
                    if node.get("servername"):
                        v["streamSettings"]["tlsSettings"] = {"serverName": node["servername"]}
            out[node.get("name", f"{node['server']}:{node['port']}")] = v
        elif proto == "trojan":
            v = {"protocol": "trojan", "settings": {"servers": [{"address": node["server"], "port": int(node["port"]), "password": node.get("password", "")}]}}
            if node.get("servername"):
                v["streamSettings"] = {"security": "tls", "tlsSettings": {"serverName": node["servername"], "allowInsecure": True}}
            out[node.get("name", f"{node['server']}:{node['port']}")] = v
        elif proto == "vless":
            v = {"protocol": "vless", "settings": {"vnext": [{"address": node["server"], "port": int(node["port"]), "users": [{"id": node.get("uuid", ""), "encryption": "none", "flow": node.get("flow", "")}]}]}}
            network = node.get("network", "tcp")
            if network != "tcp":
                v["streamSettings"] = {"network": network}
                if network == "grpc" and node.get("grpc_service_name"):
                    v["streamSettings"]["grpcSettings"] = {"serviceName": node["grpc_service_name"]}
                if network == "ws":
                    v["streamSettings"]["wsSettings"] = {}
                    if node.get("ws_path"):
                        v["streamSettings"]["wsSettings"]["path"] = node["ws_path"]
                    if node.get("ws_host"):
                        v["streamSettings"]["wsSettings"]["headers"] = {"Host": node["ws_host"]}
            if node.get("tls"):
                v["streamSettings"] = v.get("streamSettings", {})
                v["streamSettings"]["security"] = "reality" if node.get("pbk") else "tls"
                tls_settings = {"serverName": node.get("servername", node["server"]), "allowInsecure": True}
                if node.get("pbk"):
                    tls_settings["realitySettings"] = {"publicKey": node["pbk"], "shortId": node.get("sid", ""), "fingerprint": node.get("fp") or "chrome"}
                v["streamSettings"]["tlsSettings"] = tls_settings
            out[node.get("name", f"{node['server']}:{node['port']}")] = v
        elif proto == "ss":
            v = {"protocol": "shadowsocks", "settings": {"servers": [{"address": node["server"], "port": int(node["port"]), "method": node.get("cipher", "aes-256-gcm"), "password": node.get("password", "")}]}}
            out[node.get("name", f"{node['server']}:{node['port']}")] = v
        elif proto in ("hysteria2", "hy2"):
            v = {"protocol": "hysteria2", "settings": {"servers": [{"address": node["server"], "port": int(node["port"]), "password": node.get("password", "")}]}}
            if node.get("servername"):
                v["settings"]["servers"][0]["tls"] = {"sni": node["servername"], "insecure": True}
            out[node.get("name", f"{node['server']}:{node['port']}")] = v
    return json.dumps(out, ensure_ascii=False, indent=2)


def generate_config_singbox(nodes):
    out_obfs = {}
    for node in nodes:
        proto = node["protocol"].lower()
        tag = node.get("name", f"{node['server']}:{node['port']}")
        if proto in ("http", "https"):
            v = {"type": "http", "server": node["server"], "server_port": int(node["port"])}
            if node.get("username"):
                v["username"] = node["username"]
                v["password"] = node.get("password", "")
            out_obfs[tag] = v
        elif proto == "socks5":
            v = {"type": "socks", "server": node["server"], "server_port": int(node["port"])}
            if node.get("username"):
                v["username"] = node["username"]
                v["password"] = node.get("password", "")
            out_obfs[tag] = v
        elif proto == "vmess":
            v = {"type": "vmess", "server": node["server"], "server_port": int(node["port"]), "uuid": node.get("uuid", ""), "alter_id": int(node.get("alterId", 0)), "security": node.get("cipher", "auto")}
            if node.get("tls"):
                v["tls"] = {"enabled": True, "server_name": node.get("servername", node["server"]), "insecure": True}
            out_obfs[tag] = v
        elif proto == "trojan":
            v = {"type": "trojan", "server": node["server"], "server_port": int(node["port"]), "password": node.get("password", ""), "tls": {"enabled": True, "server_name": node.get("servername", node["server"]), "insecure": True}}
            out_obfs[tag] = v
        elif proto == "vless":
            v = {"type": "vless", "server": node["server"], "server_port": int(node["port"]), "uuid": node.get("uuid", "")}
            if node.get("flow"):
                v["flow"] = node["flow"]
            network = node.get("network", "tcp")
            if network == "grpc":
                v["transport"] = {"type": "grpc"}
                if node.get("grpc_service_name"):
                    v["transport"]["service_name"] = node["grpc_service_name"]
            elif network != "tcp":
                v["transport"] = {"type": network}
                if node.get("ws_path"):
                    v["transport"]["path"] = node["ws_path"]
                if node.get("ws_host"):
                    v["transport"]["headers"] = {"Host": node["ws_host"]}
            tls_fields = {}
            if node.get("tls"):
                tls_fields["enabled"] = True
                tls_fields["server_name"] = node.get("servername", node["server"])
                tls_fields["insecure"] = True
            if node.get("pbk"):
                tls_fields["enabled"] = True
                tls_fields["reality"] = {"enabled": True, "public_key": node["pbk"], "short_id": node.get("sid", "")}
                tls_fields["server_name"] = node.get("servername", node.get("sni", node["server"]))
                tls_fields["utls"] = {"enabled": True, "fingerprint": node.get("fp") or "chrome"}
            if tls_fields:
                v["tls"] = tls_fields
            out_obfs[tag] = v
        elif proto == "ss":
            v = {"type": "shadowsocks", "server": node["server"], "server_port": int(node["port"]), "method": node.get("cipher", "aes-256-gcm"), "password": node.get("password", "")}
            out_obfs[tag] = v
        elif proto in ("hysteria2", "hy2"):
            v = {"type": "hysteria2", "server": node["server"], "server_port": int(node["port"]), "password": node.get("password", ""), "tls": {"enabled": True, "server_name": node.get("servername", node["server"]), "insecure": True}}
            out_obfs[tag] = v
    return json.dumps(out_obfs, ensure_ascii=False, indent=2)


def _b64url(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")


def _uri_frag(name: str) -> str:
    return quote(name, safe="!~*'()")


def _node_uri(node: dict, name: str) -> str | None:
    """Собирает URI ноды для Happ/v2ray-подписки. Все протоколы, включая
    http/https/socks5 (Xray поддерживает их outbounds; Happ распознает схемы
    http:// и socks5:// — неподдерживаемые просто проигнорит)."""
    proto = node["protocol"].lower()
    server = node["server"]
    port = int(node["port"])
    frag = _uri_frag(name)
    try:
        if proto in ("http", "https"):
            scheme = "https" if proto == "https" else "http"
            auth = ""
            if node.get("username"):
                auth = f"{quote(node['username'], safe='')}:{quote(node.get('password', ''), safe='')}@"
            return f"{scheme}://{auth}{server}:{port}#{frag}"
        if proto == "socks5":
            auth = ""
            if node.get("username"):
                auth = f"{quote(node['username'], safe='')}:{quote(node.get('password', ''), safe='')}@"
            return f"socks5://{auth}{server}:{port}#{frag}"
        if proto == "vmess":
            vm = {
                "v": "2",
                "ps": name,
                "add": server,
                "port": str(port),
                "id": node.get("uuid", ""),
                "aid": str(int(node.get("alterId", 0))),
                "scy": node.get("cipher", "auto"),
                "net": node.get("network", "tcp"),
                "type": "grpc" if node.get("network") == "grpc" else "none",
                "host": node.get("ws_host", "") or "",
                "path": node.get("grpc_service_name", "") if node.get("network") == "grpc" else (node.get("ws_path", "") or ""),
                "tls": "tls" if node.get("tls") else "",
                "sni": node.get("servername", "") or "",
                "alpn": "",
                "fp": node.get("fp", "") or "",
            }
            return f"vmess://{_b64url(json.dumps(vm, ensure_ascii=False))}#{frag}"
        if proto == "vless":
            params = ["encryption=none"]
            network = node.get("network", "tcp")
            params.append(f"type={network}")
            if network in ("ws", "xhttp", "splithttp"):
                if node.get("ws_path"):
                    params.append(f"path={quote(node['ws_path'], safe='/:')}")
                if node.get("ws_host"):
                    params.append(f"host={quote(node['ws_host'], safe='/:.')}")
            elif network == "grpc":
                if node.get("grpc_service_name"):
                    params.append(f"serviceName={quote(node['grpc_service_name'], safe='/')}")
            if node.get("tls") or node.get("pbk"):
                params.append("security=reality" if node.get("pbk") else "security=tls")
                if node.get("pbk"):
                    params.append(f"pbk={quote(node['pbk'], safe='')}")
                if node.get("sid"):
                    params.append(f"sid={quote(node['sid'], safe='')}")
                params.append(f"fp={quote(node.get('fp') or 'chrome', safe='')}")
            sni = node.get("servername") or node.get("sni") or server
            if node.get("tls") or node.get("pbk"):
                params.append(f"sni={quote(sni, safe=':.')}")
            if node.get("flow"):
                params.append(f"flow={quote(node['flow'], safe='')}")
            return f"vless://{node.get('uuid', '')}@{server}:{port}?{'&'.join(params)}#{frag}"
        if proto == "ss":
            method = node.get("cipher", "aes-256-gcm")
            password = node.get("password", "")
            return f"ss://{_b64url(f'{method}:{password}')}@{server}:{port}#{frag}"
        if proto == "trojan":
            sni = node.get("servername") or server
            return f"trojan://{node.get('password', '')}@{server}:{port}?security=tls&sni={quote(sni, safe=':.')}#{frag}"
        if proto in ("hysteria2", "hy2"):
            sni = node.get("servername") or server
            return f"hy2://{node.get('password', '')}@{server}:{port}?sni={quote(sni, safe=':.')}&insecure=1#{frag}"
    except Exception:
        return None
    return None


def _xray_outbound(node: dict, name: str) -> dict:
    """Xray outbound сервер (для JSON-подписки). Включает http/socks5 —
    Xray core поддерживает их как outbounds."""
    proto = node["protocol"].lower()
    tag = name
    if proto in ("http", "https"):
        v = {"protocol": "http", "settings": {"servers": [{"address": node["server"], "port": int(node["port"])}]}}
        if node.get("username"):
            v["settings"]["servers"][0]["users"] = [{"user": node["username"], "pass": node.get("password", "")}]
        v["tag"] = tag
        return v
    if proto == "socks5":
        v = {"protocol": "socks", "settings": {"servers": [{"address": node["server"], "port": int(node["port"])}]}}
        if node.get("username"):
            v["settings"]["servers"][0]["users"] = [{"user": node["username"], "pass": node.get("password", "")}]
        v["tag"] = tag
        return v
    if proto == "vmess":
        v = {"protocol": "vmess", "settings": {"vnext": [{"address": node["server"], "port": int(node["port"]), "users": [{"id": node.get("uuid", ""), "alterId": int(node.get("alterId", 0)), "security": node.get("cipher", "auto")}]}]}}
        if node.get("network") and node["network"] != "tcp":
            v["streamSettings"] = {"network": node["network"]}
            if node.get("ws_path"):
                v["streamSettings"]["wsSettings"] = {"path": node["ws_path"]}
            if node.get("tls"):
                v["streamSettings"]["security"] = "tls"
                if node.get("servername"):
                    v["streamSettings"]["tlsSettings"] = {"serverName": node["servername"], "allowInsecure": True}
        v["tag"] = tag
        return v
    if proto == "trojan":
        v = {"protocol": "trojan", "settings": {"servers": [{"address": node["server"], "port": int(node["port"]), "password": node.get("password", "")}]}}
        if node.get("servername"):
            v["streamSettings"] = {"security": "tls", "tlsSettings": {"serverName": node["servername"], "allowInsecure": True}}
        v["tag"] = tag
        return v
    if proto == "vless":
        v = {"protocol": "vless", "settings": {"vnext": [{"address": node["server"], "port": int(node["port"]), "users": [{"id": node.get("uuid", ""), "encryption": "none", "flow": node.get("flow", "")}]}]}}
        network = node.get("network", "tcp")
        if network != "tcp":
            v["streamSettings"] = {"network": network}
            if network == "grpc" and node.get("grpc_service_name"):
                v["streamSettings"]["grpcSettings"] = {"serviceName": node["grpc_service_name"]}
            if network == "ws":
                v["streamSettings"]["wsSettings"] = {}
                if node.get("ws_path"):
                    v["streamSettings"]["wsSettings"]["path"] = node["ws_path"]
                if node.get("ws_host"):
                    v["streamSettings"]["wsSettings"]["headers"] = {"Host": node["ws_host"]}
        if node.get("tls") or node.get("pbk"):
            v["streamSettings"] = v.get("streamSettings", {})
            v["streamSettings"]["security"] = "reality" if node.get("pbk") else "tls"
            tls_settings = {"serverName": node.get("servername", node["server"]), "allowInsecure": True}
            if node.get("pbk"):
                tls_settings["realitySettings"] = {"publicKey": node["pbk"], "shortId": node.get("sid", ""), "fingerprint": node.get("fp") or "chrome"}
            v["streamSettings"]["tlsSettings"] = tls_settings
        v["tag"] = tag
        return v
    if proto == "ss":
        v = {"protocol": "shadowsocks", "settings": {"servers": [{"address": node["server"], "port": int(node["port"]), "method": node.get("cipher", "aes-256-gcm"), "password": node.get("password", "")}]}}
        v["tag"] = tag
        return v
    if proto in ("hysteria2", "hy2"):
        # Xray core не поддерживает hysteria2 — в Xray-JSON подписку не включаем
        return None
    return None


def generate_config_xray(nodes):
    """Xray-JSON подписка (XTLS соглашение, Happ его понимает):
    массив ПОЛНЫХ Xray-конфигов — каждый сервер это изолированное
    подключение с remarks/inbounds/outbounds/routing. Happ передаёт
    такой конфиг ядру 1:1 (http/socks5 тоже поддерживаются)."""
    used_names = set()
    out = []
    for node in nodes:
        name = node_name(node, used_names)
        ob = _xray_outbound(node, name)
        if not ob:
            continue
        ob["tag"] = "proxy"
        out.append({
            "remarks": name,
            "meta": {"serverDescription": "NetherLink @githoly"},
            "inbounds": [
                {"listen": "127.0.0.1", "port": 10808, "protocol": "socks"},
                {"listen": "127.0.0.1", "port": 10809, "protocol": "http"},
            ],
            "outbounds": [
                ob,
                {"tag": "direct", "protocol": "freedom"},
            ],
            "routing": {
                "rules": [
                    {"type": "field", "outboundTag": "direct", "ip": ["geoip:private"]},
                    {"type": "field", "outboundTag": "direct", "domain": ["geosite:cn"]},
                ]
            },
        })
    return json.dumps(out, ensure_ascii=False, indent=2)


def generate_config_happ(nodes, title="NetherLink | @githoly"):
    """Xray-подписка (txt, URI): только туннельные (vless/vmess/ss/trojan) +
    мета-заголовки в теле. Happ (Xray core) принимает именно URI-формат;
    http/socks5/hy2 не включаем — Happ их не поддерживает как outbounds."""
    used_names = set()
    allowed = ("vless", "vmess", "ss", "trojan")
    tunnel = [n for n in nodes if n.get("protocol", "").lower() in allowed]
    lines = [
        f"# profile-title: {title}",
        "# profile-update-interval: 2",
        "#announce: 🟢 NetherLink · туннельные прокси (vless/vmess/trojan/ss) · топ обновляется каждый час",
        f"# Количество: {len(tunnel)}",
        "",
    ]
    for node in tunnel:
        name = node_name(node, used_names)
        uri = _node_uri(node, name)
        if uri:
            lines.append(uri)
    return "\n".join(lines)


def generate_configs(nodes, top_nodes_100=None, top_nodes_50=None, all_live_nodes=None):
    configs = {}
    configs["NetherLink-Clash.yaml"] = generate_config_clash(nodes)
    if top_nodes_100:
        configs["NetherLink-100.yaml"] = generate_config_clash(top_nodes_100)
    if top_nodes_50:
        configs["NetherLink-50.yaml"] = generate_config_clash(top_nodes_50)

    configs["NetherLink-v2ray.json"] = generate_config_v2ray(nodes)
    if top_nodes_100:
        configs["NetherLink-100-v2ray.json"] = generate_config_v2ray(top_nodes_100)
    if top_nodes_50:
        configs["NetherLink-50-v2ray.json"] = generate_config_v2ray(top_nodes_50)

    configs["NetherLink-singbox.json"] = generate_config_singbox(nodes)
    if top_nodes_100:
        configs["NetherLink-100-singbox.json"] = generate_config_singbox(top_nodes_100)
    if top_nodes_50:
        configs["NetherLink-50-singbox.json"] = generate_config_singbox(top_nodes_50)

    # Xray-подписка (txt, URI): только туннельные — Happ-совместимая.
    # Полный Xray (500) не нужен — брат хочет Xray только у туннельных топ-100/50.
    if top_nodes_100:
        configs["NetherLink-Xray-100.txt"] = generate_config_happ(top_nodes_100)
    if top_nodes_50:
        configs["NetherLink-Xray-50.txt"] = generate_config_happ(top_nodes_50)

    live_source = all_live_nodes if all_live_nodes else nodes
    live_lines = []
    for n in live_source:
        if not n.get("server") or not n.get("port"):
            continue
        proto = n.get("protocol", "http").lower()
        server = n["server"]
        port = n["port"]
        user = n.get("username")
        password = n.get("password")
        if user and password:
            live_lines.append(f"{proto}://{user}:{password}@{server}:{port}")
        elif user:
            live_lines.append(f"{proto}://{user}@{server}:{port}")
        else:
            live_lines.append(f"{proto}://{server}:{port}")
    configs["live.txt"] = "\n".join(live_lines)

    return configs
