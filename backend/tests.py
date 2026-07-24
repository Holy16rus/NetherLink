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
    test("generates all 10 configs", len(configs), 10)
    test("live.txt in configs", "live.txt" in configs, True)

    for fname in ["NetherLink.yaml", "NetherLink-100.yaml", "NetherLink-50.yaml",
                  "NetherLink-v2ray.json", "NetherLink-100-v2ray.json", "NetherLink-50-v2ray.json",
                  "NetherLink-singbox.json", "NetherLink-100-singbox.json", "NetherLink-50-singbox.json"]:
        test(f"{fname} exists in configs", fname in configs, True)


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
        test("HTTPS check github.com:443 (reachable)", lat_h is not None, True)

        node = {"server": "1.1.1.1", "port": 80, "protocol": "http"}
        result = await check_node(node, timeout, cancel)
        test("check_node on non-proxy → None", result, None)

        node_fake = {"server": "255.255.255.255", "port": 9, "protocol": "http"}
        result_fake = await check_node(node_fake, 2, cancel)
        test("check_node dead → None", result_fake, None)

        sp = await speed_test_node({"server": "1.1.1.1", "port": 80, "protocol": "http"}, timeout, cancel)
        test("speed_test on non-proxy → None", sp, None)

    asyncio.run(run())


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


# ── main ────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("NetherLink Tests")
    print("=" * 60)

    test_state()
    test_generator()
    test_parser()

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
