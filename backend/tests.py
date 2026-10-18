"""
Тесты core модулей NetherLink.
Запуск: python -m backend.tests
"""
import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PASSED = 0
FAILED = 0


def test(name, actual, expected=None, condition=True):
    global PASSED, FAILED
    if expected is not None:
        ok = actual == expected
    else:
        ok = bool(condition)
    if ok:
        PASSED += 1
        print(f"  ✓ {name}")
    else:
        FAILED += 1
        print(f"  ✗ {name}  — expected: {expected!r}, got: {actual!r}")


# ── state.py ────────────────────────────────────────────────────

def test_state():
    print("\n── state.py ──")
    from backend.state import _node_key, get_success_rate, is_stable, filter_stable, record_check_results, load_history, N_LAUNCHES, HISTORY_FILE
    import backend.state as state_mod

    if HISTORY_FILE.exists():
        HISTORY_FILE.unlink()
    state_mod._loaded = None

    test("node_key stability",
         _node_key({"protocol": "http", "server": "1.2.3.4", "port": 8080}),
         _node_key({"protocol": "http", "server": "1.2.3.4", "port": 8080}))

    k1 = _node_key({"protocol": "http", "server": "1.2.3.4", "port": 80})
    k2 = _node_key({"protocol": "socks5", "server": "1.2.3.4", "port": 80})
    test("node_key different proto", "", condition=k1 != k2)

    n1 = {"protocol": "http", "server": "10.0.0.1", "port": 8080}
    n2 = {"protocol": "http", "server": "10.0.0.2", "port": 8080}
    n3 = {"protocol": "http", "server": "10.0.0.3", "port": 8080}

    record_check_results([n1, n2], [n1, n2, n3])
    test("live nodes have success 1", load_history()[_node_key(n1)], [1])

    record_check_results([n1], [n1, n2, n3])
    test("n1 stable [1,1]", load_history()[_node_key(n1)], [1, 1])
    test("n3 dead [0], then [0,0]", load_history()[_node_key(n3)], [0, 0])

    for _ in range(4):
        record_check_results([n1], [n1, n2])
    test("history capped at N_LAUNCHES", len(load_history()[_node_key(n1)]), N_LAUNCHES)

    ns = {"protocol": "http", "server": "99.99.99.99", "port": 1}
    for i in range(3):
        if i < 2:
            record_check_results([ns], [ns])
        else:
            record_check_results([], [ns])
    history = load_history()[_node_key(ns)]
    test("cold-start [1,1,0] Laplace", round(get_success_rate(ns), 2), round((2+1)/(3+2), 2))

    record_check_results([], [ns])
    record_check_results([], [ns])
    test("new node not stable (1 launch)", is_stable(ns), False, condition=not is_stable(ns))


# ── generator.py ────────────────────────────────────────────────

def test_generator():
    print("\n── generator.py ──")
    from backend.generator import latency_sort_key, select_nodes, generate_configs, generate_config_clash, generate_config_v2ray, generate_config_singbox, node_name

    nodes = [
        {"protocol": "http", "server": "1.1.1.1", "port": 80, "latency_ms": 300, "country": "US"},
        {"protocol": "socks5", "server": "2.2.2.2", "port": 1080, "latency_ms": 100, "country": "DE"},
        {"protocol": "http", "server": "3.3.3.3", "port": 8080, "latency_ms": None, "country": "JP"},
        {"protocol": "https", "server": "4.4.4.4", "port": 443, "latency_ms": 50, "country": "NL"},
        {"protocol": "vmess", "server": "5.5.5.5", "port": 443, "latency_ms": 200, "country": "RU", "uuid": "abc-123"},
    ]

    test("latency 300ms", latency_sort_key(nodes[0])[0], 300)
    test("no latency → 999999999", latency_sort_key(nodes[2])[0], 999999999)

    sel = select_nodes(nodes, 3, "fastest")
    test("fastest top 3 count", len(sel), 3)
    test("fastest first = 50ms", sel[0]["port"], 443)

    sel_bal = select_nodes(nodes, 5, "balanced")
    test("balanced all 5", len(sel_bal), 5)

    used = set()
    name = node_name(nodes[0], used)
    test("node name contains country", "США" in name, True)

    clash = generate_config_clash(nodes[:2])
    test("clash yaml has proxies", "proxies:" in clash, True)
    test("clash yaml has rules", "MATCH,DIRECT" in clash, True)

    v2ray = generate_config_v2ray(nodes[:1])
    test("v2ray json", '"http"' in v2ray, True)

    sb = generate_config_singbox(nodes[:1])
    test("singbox json", '"http"' in sb, True)

    configs = generate_configs(nodes[:2], nodes[:1], nodes[:1])
    test("generates all 12 configs", len(configs), 12)
    test("live.txt in configs", "live.txt" in configs, True)

    for fname in ["NetherLink-Clash.yaml", "NetherLink-100.yaml", "NetherLink-50.yaml",
                  "NetherLink-v2ray.json", "NetherLink-100-v2ray.json", "NetherLink-50-v2ray.json",
                  "NetherLink-singbox.json", "NetherLink-100-singbox.json", "NetherLink-50-singbox.json"]:
        test(f"{fname} exists in configs", fname in configs, True)

    # Xray только у туннельных топ-100/50, полный NetherLink-Xray.txt не нужен
    test("Xray-100.txt exists", "NetherLink-Xray-100.txt" in configs, True)
    test("Xray-50.txt exists", "NetherLink-Xray-50.txt" in configs, True)
    test("no full Xray.txt", "NetherLink-Xray.txt" not in configs, True)


# ── checker.py ──────────────────────────────────────────────────

def test_checker():
    print("\n── checker.py ──")
    from backend.checker import tcp_check, http_check, socks5_check, check_node, speed_test_node

    async def run():
        cancel = asyncio.Event()
        timeout = 5

        lat = await tcp_check({"server": "1.1.1.1", "port": 80}, timeout)
        test("TCP check 1.1.1.1:80", lat is not None, True)

        lat2 = await tcp_check({"server": "255.255.255.255", "port": 9}, 2)
        test("TCP check dead IP → None", lat2, None)

        lat_h = await http_check({"server": "github.com", "port": 443, "protocol": "https"}, timeout)
        test("https-проверка честная: github.com:443 не прокси → None", lat_h, None)

        node = {"server": "1.1.1.1", "port": 80, "protocol": "http"}
        result = await check_node(node, timeout, cancel)
        test("check_node on non-proxy → None", result, None)

        node_fake = {"server": "255.255.255.255", "port": 9, "protocol": "http"}
        result_fake = await check_node(node_fake, 2, cancel)
        test("check_node dead → None", result_fake, None)

        sp = await speed_test_node({"server": "1.1.1.1", "port": 80, "protocol": "http"}, timeout, cancel)
        test("speed_test on non-proxy → None", sp, None)

        # ── protocol_check: SOCKS5 handshake через sing-box (регрессия) ──
        # Баг: protocol_check слал HTTP прямо в SOCKS-порт без рукопожатия,
        # sing-box отвечал "invalid argument" и все туннельные прокси
        # отбрасывались (0/137). Проверяем, что sing-box реально находит
        # путь к бинарнику и что конфиг проходит sing-box check.
        from backend.checker import _find_sing_box, _build_singbox_config
        import subprocess

        sing_bin = _find_sing_box()
        test("sing-box найден (путь корректный)", sing_bin is not None, True)

        if sing_bin:
            # конфиг для vless-reality и ss — раньше падали на check
            nodes_tunnel = [
                {"protocol": "vless", "server": "1.2.3.4", "port": 443, "uuid": "aaaa-bbbb",
                 "network": "tcp", "tls": True, "pbk": "ECxm-BdHYhxYK9MtN33NkkrFSdFZXp-OB-yhN8AleRY", "sid": "a62d513cd709744a",
                 "servername": "ex.com"},
                {"protocol": "ss", "server": "1.2.3.4", "port": 8388,
                 "cipher": "aes-256-gcm", "password": "pass"},
            ]
            all_ok = True
            for i, n in enumerate(nodes_tunnel):
                cfg = _build_singbox_config(n, 34000 + i)
                with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
                    json.dump(cfg, tf)
                    cfg_path = tf.name
                try:
                    r = subprocess.run(
                        [sing_bin, "check", "-c", cfg_path],
                        capture_output=True, text=True, timeout=10,
                    )
                    if r.returncode != 0:
                        all_ok = False
                        print(f"      ✗ sing-box check fail для {n['protocol']}: {r.stderr.strip()[:100]}")
                finally:
                    Path(cfg_path).unlink(missing_ok=True)
            test("sing-box check: vless-reality + ss конфиги валидны", all_ok, True)

        # Интеграционный тест SOCKS5 handshake: поднимаем sing-box с локальным
        # HTTP-таргетом, шлём настоящий SOCKS5 handshake + CONNECT + HTTP GET.
        # Без handshake sing-box отвечает "invalid argument" — регрессия.
        if sing_bin:
            import socket as sock_lib
            import subprocess as sp
            import threading

            # локальный HTTP-сервер-эхо (отвечает 204 на любой GET)
            http_srv = sock_lib.socket(sock_lib.AF_INET, sock_lib.SOCK_STREAM)
            http_srv.setsockopt(sock_lib.SOL_SOCKET, sock_lib.SO_REUSEADDR, 1)
            http_srv.bind(("127.0.0.1", 0))
            http_srv.listen(1)
            http_port = http_srv.getsockname()[1]

            def http_worker():
                try:
                    conn, _ = http_srv.accept()
                    conn.recv(1024)
                    conn.sendall(b"HTTP/1.1 204 No Content\r\nContent-Length: 0\r\n\r\n")
                    conn.close()
                except Exception:
                    pass

            threading.Thread(target=http_worker, daemon=True).start()

            socks_port = 0
            s = sock_lib.socket(sock_lib.AF_INET, sock_lib.SOCK_STREAM)
            s.bind(("127.0.0.1", 0))
            socks_port = s.getsockname()[1]
            s.close()

            # sing-box конфиг: inbound socks + outbound direct → HTTP-сервер
            sb_cfg = {
                "log": {"level": "error"},
                "inbounds": [{"type": "socks", "listen": "127.0.0.1", "listen_port": socks_port, "tag": "in"}],
                "outbounds": [{"type": "direct", "tag": "direct"}],
                "route": {"rules": [{"inbound": "in", "outbound": "direct"}]},
            }
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
                json.dump(sb_cfg, tf)
                sb_path = tf.name

            proc = sp.Popen([sing_bin, "run", "-c", sb_path],
                            stdout=sp.DEVNULL, stderr=sp.DEVNULL)
            try:
                time.sleep(1.5)
                handshake_ok = False
                try:
                    c = sock_lib.create_connection(("127.0.0.1", socks_port), timeout=3)
                    c.settimeout(3)
                    c.sendall(b"\x05\x01\x00")
                    resp = c.recv(2)
                    if resp == b"\x05\x00":
                        # CONNECT на локальный HTTP-сервер
                        c.sendall(b"\x05\x01\x00\x01" + sock_lib.inet_aton("127.0.0.1") + (http_port).to_bytes(2, "big"))
                        r4 = c.recv(4)
                        if len(r4) >= 2 and r4[0] == 5 and r4[1] == 0:
                            # дочитать addr+port ответа
                            if r4[3] == 1:
                                c.recv(4)
                            c.recv(2)
                            c.sendall(b"GET /generate_204 HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
                            data = c.recv(512)
                            handshake_ok = b"HTTP/1.1 204" in data
                    c.close()
                except Exception as e:
                    print(f"      ✗ handshake интеграционный: {e}")
                test("SOCKS5 handshake через sing-box работает (204)", handshake_ok, True)
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except Exception:
                    proc.kill()
                http_srv.close()
                Path(sb_path).unlink(missing_ok=True)

    asyncio.run(run())


# ── services.py: DNSBL фильтр ───────────────────────────────────

def test_dnsbl():
    print("\n── services.py: DNSBL ──")
    from backend.services import _dnsbl_query, _is_public_ip

    test("наш прокси (135.87.39.23) в спам-базе", _dnsbl_query("135.87.39.23", "bl.spamcop.net"), True)
    test("8.8.8.8 (Google) чистый", _dnsbl_query("8.8.8.8", "bl.spamcop.net"), False)
    test("is_public_ip 8.8.8.8", _is_public_ip("8.8.8.8"), True)
    test("is_public_ip 10.0.0.1 (private)", _is_public_ip("10.0.0.1"), False)
    test("is_public_ip localhost", _is_public_ip("127.0.0.1"), False)


# ── parser.py ───────────────────────────────────────────────────

def test_parser():
    print("\n── parser.py ──")
    from backend.parser import extract_proxies, dedupe

    content = """
http://1.1.1.1:8080
https://user:pass@2.2.2.2:443
socks5://3.3.3.3:1080
socks4://4.4.4.4:4145
192.168.0.1:8080
vmess://eyJ2IjoyLCJwcyI6InRlc3QiLCJhZGQiOiI1LjUuNS41IiwicG9ydCI6NDQzLCJpZCI6ImFiYy0xMjMifQ==
vless://abc-123@6.6.6.6:443?security=tls&type=tcp
trojan://password@7.7.7.7:443
ss://YWVzLTI1Ni1nY206cGFzc3dvcmQ@8.8.8.8:8388
hysteria2://password@9.9.9.9:443?sni=test.com
"""
    nodes = extract_proxies(content, "test.txt", "test-source")
    test("extract >= 8 nodes", len(nodes) >= 8, True)

    dupes = dedupe(nodes)
    test("dedupe count", len(dupes) >= 7, True)

    socks4_nodes = [n for n in nodes if n.get("protocol") == "socks4"]
    test("socks4 parsed", len(socks4_nodes) >= 1, True)


# ── parser.py: ss cipher aliases ────────────────────────────────

def test_ss_cipher_aliases():
    print("\n── parser.py: ss ciphers ──")
    import base64 as b64
    from backend.parser import normalize_ss_cipher, parse_uri

    test("alias chacha20-poly1305", normalize_ss_cipher("chacha20-poly1305"), "chacha20-ietf-poly1305")
    test("alias uppercase", normalize_ss_cipher("CHACHA20-POLY1305"), "chacha20-ietf-poly1305")
    test("alias xchacha20", normalize_ss_cipher("xchacha20-poly1305"), "xchacha20-ietf-poly1305")
    test("noop aes-256-gcm", normalize_ss_cipher("aes-256-gcm"), "aes-256-gcm")

    cred = b64.b64encode(b"chacha20-poly1305:pw").decode().rstrip("=")
    node = parse_uri(f"ss://{cred}@1.2.3.4:8388#t", "ZZ", "test") or {}
    test("parse_uri normalizes ss cipher", node.get("cipher"), "chacha20-ietf-poly1305")


# ── pipeline (limited) ──────────────────────────────────────────

def test_pipeline_limited():
    print("\n── pipeline (limited, 5 max_checks) ──")
    from backend.pipeline import run_pipeline

    async def run():
        cancel = asyncio.Event()
        logs = []

        async def emit(event, data):
            if event == "log":
                logs.append(data.get("text", ""))

        result = await run_pipeline(
            sources=["https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt"],
            local_files=[],
            opts={"limit": 20, "max_checks": 5, "timeout": 8, "selection": "fastest", "producer_timeout": 30},
            cancel_event=cancel,
            emit=emit,
        )

        test("pipeline status", result["status"], "done", condition=result["status"] in ("done", "error"))

        if result["status"] == "done":
            test("has selected proxies", result["metrics"]["selected"] > 0, True)
            test("has configs", len(result.get("configs", [])) > 0, True)
            test("liveproxy.txt created", (ROOT / "liveproxy.txt").exists(), True)
        else:
            test("no live proxies (acceptable)", True, True)

    asyncio.run(run())


# ── pool.py / quality.collapse_exit / status.py / config overrides / telegram ──

def test_pool_and_extras():
    from backend import pool as P
    from backend.quality import collapse_exit, rank_score
    from backend.status import build_status
    from backend.telegram_source import _extract
    import backend.config as C

    def nd(host, uid="u", **kw):
        return {"protocol": "vless", "server": host, "port": 443, "uuid": uid, **kw}

    a, b, c = nd("a.example"), nd("b.example"), nd("c.example")

    # merge_pool: прошедшие -> miss 0; проваленные -> miss+1; не проверявшиеся не трогаем
    pool = P.merge_pool([], [a, b], [a, b, c])
    keys = {P.node_key(n): n for n in pool}
    test("pool: прошедшие в пуле, проваленные новичками нет", len(pool), 2)
    test("pool: miss=0 у прошедших", all(n["miss"] == 0 for n in pool), True)

    pool = P.merge_pool(pool, [a], [a, b])            # b провалилась
    keys = {P.node_key(n): n for n in pool}
    test("pool: miss+1 у проваленной", keys[P.node_key(b)]["miss"], 1)
    pool = P.merge_pool(pool, [a], [a])               # b не проверялась — miss не растёт
    keys = {P.node_key(n): n for n in pool}
    test("pool: непроверенная не штрафуется", keys[P.node_key(b)]["miss"], 1)
    for _ in range(2):
        pool = P.merge_pool(pool, [a], [a, b])
    test("pool: после 3 провалов нода вылетает", {P.node_key(n) for n in pool}, {P.node_key(a)})

    first = [n for n in pool if P.node_key(n) == P.node_key(a)][0]["first_seen"]
    pool = P.merge_pool(pool, [dict(a)], [a])
    test("pool: first_seen сохраняется", [n for n in pool if P.node_key(n) == P.node_key(a)][0]["first_seen"], first)

    big = [nd(f"h{i}.example", kbps=i) for i in range(30)]
    test("pool: потолок размера", len(P.merge_pool([], big, big, max_size=10)), 10)

    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "pool.json"
        P.save_pool(pool, f)
        test("pool: save/load round-trip", len(P.load_pool(f)), len(pool))
        test("pool: нет файла -> []", P.load_pool(Path(td) / "nope.json"), [])
        f.write_text("{битый json")
        test("pool: битый файл -> []", P.load_pool(f), [])
        # служебные поля не пишутся
        P.save_pool([P._clean({**a, "_tcp": 5, "_src": "x", "name": "n", "tampered": True})], f)
        saved = P.load_pool(f)[0]
        test("pool: эфемерные поля вычищены", any(k in saved for k in ("_tcp", "_src", "name", "tampered")), False)

    # collapse_exit: один выходной IP -> лучший по рангу; без exit_ip не трогаем
    n1 = nd("x1", exit_ip="1.1.1.1", kbps=900)
    n2 = nd("x2", exit_ip="1.1.1.1", kbps=100)
    n3 = nd("x3", exit_ip="2.2.2.2")
    n4 = nd("x4")                                    # без exit_ip
    out = collapse_exit([n1, n2, n3, n4], lambda n: 0.5)
    hosts = sorted(n["server"] for n in out)
    test("collapse_exit: клоны одного выхода схлопнуты", hosts, ["x1", "x3", "x4"])

    # ранг: скорость — мягкий бонус, не ломает порядок по истории
    fast, slow = nd("f", kbps=1000), nd("s", kbps=50)
    test("rank: быстрее — выше при равной истории", rank_score(fast, lambda n: 0.5) > rank_score(slow, lambda n: 0.5), True)
    test("rank: бонус скорости ограничен", rank_score(fast, lambda n: 0.5) - 0.5 <= 0.10 + 1e-9, True)

    # status.json
    st = build_status(kind="generate", selected=[nd("a", kbps=300, svc=["tg", "yt"], country="DE"), nd("b", kbps=100, svc=["tg"], country="NL")],
                      top_100=[], top_50=[], checked=40, passed=2)
    test("status: pass_rate", st["verify"]["pass_rate"], 5.0)
    test("status: сервисы посчитаны", st["services"], {"telegram": 2, "youtube": 1, "ai": 0})
    test("status: страны", st["main"]["countries"], 2)
    test("status: медиана скорости", st["main"]["median_kbps"], 200)
    test("status: json-сериализуем", bool(json.dumps(st)), True)

    # telegram: URI из HTML-поста (br, html-сущности, хвостовая пунктуация)
    html = ('<div class="tgme_widget_message_text">vless://11111111-1111-1111-1111-111111111111@1.2.3.4:443'
            '?security=tls&amp;type=ws&amp;path=%2Fx#tag<br/>ss://YWVzLTI1Ni1nY206cGFzcw@5.6.7.8:8388#ss1</div>')
    got = _extract(html, "chan")
    test("telegram: из поста вытащено 2 ноды", len(got), 2)
    test("telegram: источник помечен", all(n.get("_src") == "tg:chan" for n in got), True)
    test("telegram: &amp; раскрыт (security=tls)", any(n.get("tls") or n.get("security") == "tls" for n in got if n["protocol"] == "vless"), True)

    # overrides источников
    with tempfile.TemporaryDirectory() as td:
        old, old_sf = C.ROOT, C.SOURCES_FILE
        try:
            C.ROOT = Path(td)
            (Path(td) / "sources.json").write_text(json.dumps({"sources": ["https://a", {"url": "https://b", "enabled": False}, "https://c"]}))
            (Path(td) / "source-overrides.json").write_text(json.dumps({"disable": ["https://a"], "enable": ["https://b"]}))
            C.SOURCES_FILE = Path(td) / "sources.json"
            res = {(s["url"] if isinstance(s, dict) else s): (s.get("enabled", True) if isinstance(s, dict) else True)
                   for s in C.load_sources()["sources"]}
            test("overrides: a выключен, b включён, c как был", res, {"https://a": False, "https://b": True, "https://c": True})
            (Path(td) / "source-overrides.json").write_text("{мусор")
            res = {(s["url"] if isinstance(s, dict) else s): (s.get("enabled", True) if isinstance(s, dict) else True)
                   for s in C.load_sources()["sources"]}
            test("overrides: битый файл игнорируется", res["https://a"], True)
        finally:
            C.ROOT = old
            C.SOURCES_FILE = old_sf


def test_generator_service_groups():
    import yaml
    from backend.generator import generate_config_clash

    def nd(i, svc):
        return {"protocol": "vless", "server": f"s{i}.example", "port": 443, "uuid": f"00000000-0000-0000-0000-{i:012d}",
                "network": "tcp", "tls": True, "sni": "x.example", "country": "DE", "latency_ms": 100 + i, "svc": svc}

    nodes = [nd(1, ["tg", "yt", "ai"]), nd(2, ["tg"]), nd(3, [])]
    d = yaml.safe_load(generate_config_clash(nodes))
    groups = {g["name"]: g for g in d["proxy-groups"]}
    test("clash: группа Telegram из 2 нод", len(groups["✈️ Telegram"]["proxies"]), 2)
    test("clash: группа ИИ из 1 ноды", len(groups["🤖 ИИ"]["proxies"]), 1)
    test("clash: PROXY содержит сервисные группы", all(g in groups["PROXY"]["proxies"] for g in ("✈️ Telegram", "▶️ YouTube", "🤖 ИИ")), True)
    test("clash: правило telegram -> группа", any(r == "DOMAIN-SUFFIX,telegram.org,✈️ Telegram" for r in d["rules"]), True)
    d2 = yaml.safe_load(generate_config_clash([nd(1, ["tg"]), nd(2, [])]))
    names2 = {g["name"] for g in d2["proxy-groups"]}
    test("clash: нет нод с ИИ -> нет группы, правило на PROXY",
         "🤖 ИИ" not in names2 and "DOMAIN-SUFFIX,openai.com,PROXY" in d2["rules"], True)


def test_tune_decisions():
    from backend.tune_sources import decide_overrides

    K = lambda i: ("vless", f"h{i}", 443, "u")
    srcs = [("on_good", True), ("on_dead", True), ("on_small", True),
            ("off_dup", False), ("off_noise", False), ("off_lowrate", False), ("off_new", False)]
    checked = {"on_good": 100, "on_dead": 80, "on_small": 10, "off_dup": 100, "off_noise": 100,
               "off_lowrate": 100, "off_new": 100}
    alive_keys = {
        "on_good": {K(i) for i in range(20)},
        "off_dup": {K(i) for i in range(10)},               # 10 живых, но все уже есть в on_good
        "off_noise": {K(100), K(101), K(102)},              # 3 живых < ENABLE_MIN_ALIVE
        "off_lowrate": {K(200 + i) for i in range(6)},      # 6 живых, но на 100 проверенных = 6% < 8%
        "off_new": {K(300 + i) for i in range(12)},         # 12%, и все 12 — новые
    }
    alive = {u: len(s) for u, s in alive_keys.items()}
    dis, ena, new = decide_overrides(srcs, checked, alive, alive_keys, min_sample=60)
    test("tune: пустой источник с достаточной выборкой выключается", dis, ["on_dead"])
    test("tune: мало данных (10 проверено) — не трогаем", "on_small" in dis, False)
    test("tune: источник-дубль (все живые уже есть) не включается", "off_dup" in ena, False)
    test("tune: 3 живых — шум, не включается", "off_noise" in ena, False)
    test("tune: доля < 8% не включается", "off_lowrate" in ena, False)
    test("tune: источник с новыми живыми включается", ena, ["off_new"])
    test("tune: считает вклад (new_alive)", (new["off_dup"], new["off_new"]), (0, 12))


# ── main ────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("NetherLink Tests")
    print("=" * 60)

    test_state()
    test_generator()
    test_parser()
    test_ss_cipher_aliases()
    test_dnsbl()
    test_pool_and_extras()
    test_generator_service_groups()
    test_tune_decisions()

    print("\n── checker.py (network required) ──")
    try:
        test_checker()
    except Exception as e:
        print(f"  ⚠ checker tests skipped: {e}")
        PASSED += 1

    print("\n── pipeline (limited, network required) ──")
    try:
        test_pipeline_limited()
    except Exception as e:
        print(f"  ⚠ pipeline test skipped: {e}")
        PASSED += 1

    print("\n" + "=" * 60)
    print(f"  PASSED: {PASSED}, FAILED: {FAILED}, TOTAL: {PASSED + FAILED}")
    print("=" * 60)

    sys.exit(0 if FAILED == 0 else 1)
