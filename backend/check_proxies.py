"""
Проверка прокси из proxy.txt: базовая проверка + checker.net рейтинг >= 4.
Запуск: python -m backend.check_proxies
"""
import asyncio
import sys
import time
from pathlib import Path

from backend.config import CHECKER_NET_KEY
from backend.parser import extract_proxies
from backend.checker import check_batch
from backend.checker_net import check_with_rating
from backend.generator import select_nodes, generate_config

ROOT = Path(__file__).resolve().parent.parent
PROXY_FILE = ROOT / "proxy.txt"
OUTPUT_FILE = ROOT / "HolyVPN.yaml"
RATING_THRESHOLD = 3.6


async def main():
    if not PROXY_FILE.exists():
        print(f"[!] Файл не найден: {PROXY_FILE}")
        sys.exit(1)

    cancel = asyncio.Event()

    # 1. Парсим proxy.txt
    content = PROXY_FILE.read_text("utf-8", errors="replace")
    nodes = extract_proxies(content, str(PROXY_FILE), str(PROXY_FILE))
    print(f"[*] Загружено прокси: {len(nodes)}")
    print(f"    SOCKS5: {sum(1 for n in nodes if n.get('protocol') == 'socks5')}")
    print(f"    HTTP:   {sum(1 for n in nodes if n.get('protocol') in ('http', 'https'))}")

    if not nodes:
        print("[!] Нет прокси для проверки")
        sys.exit(1)

    # 2. Базовая проверка
    print(f"\n[*] Проверка {len(nodes)} прокси...")
    start = time.time()

    async def check_progress(checked, total, live):
        elapsed = time.time() - start
        pct = f"{checked}/{total}"
        print(f"  [{pct}] живых: {live} ({elapsed:.0f}s)", end="\r" if checked < total else "\n")

    live_nodes = await check_batch(nodes, timeout=10, cancel_event=cancel, progress_cb=check_progress)
    print(f"\n[+] Живых: {len(live_nodes)}/{len(nodes)}")

    if not live_nodes:
        print("[!] Нет живых прокси")
        sys.exit(1)

    # 3. Checker.net рейтинг
    if CHECKER_NET_KEY:
        print(f"\n[*] Проверка через checker.net ({len(live_nodes)} прокси)...")
        try:
            rated_nodes, ratings = await check_with_rating(live_nodes, CHECKER_NET_KEY, cancel)
            print(f"  [+] Получен рейтинг для: {len(rated_nodes)} прокси")

            before = len(rated_nodes)
            rated_nodes = [n for n in rated_nodes if n.get("checker_rating", 0) >= RATING_THRESHOLD]
            filtered = before - len(rated_nodes)
            print(f"  [+] Рейтинг >= {RATING_THRESHOLD}: {len(rated_nodes)} (отсеяно {filtered})")

            if rated_nodes:
                live_nodes = rated_nodes
            else:
                print("  [!] Нет прокси с рейтингом >= 4, использую исходные")
        except Exception as e:
            print(f"  [!] Ошибка checker.net: {e}")
    else:
        print("[!] CHECKER_NET_KEY не задан")

    # 4. Отбор (SOCKS5 приоритет)
    print(f"\n[*] Отбор прокси...")
    selected = select_nodes(live_nodes, limit=len(live_nodes), strategy="fastest", prefer_socks=True)

    socks5_count = sum(1 for n in selected if n.get("protocol", "").lower() == "socks5")
    http_count = sum(1 for n in selected if n.get("protocol", "").lower() in ("http", "https"))
    print(f"  [+] Отобрано: {len(selected)}")
    print(f"      SOCKS5: {socks5_count}")
    print(f"      HTTP:   {http_count}")

    # 5. Вывод результатов
    print(f"\n{'='*60}")
    print(f"ТОП-10 прокси (по скорости):")
    print(f"{'='*60}")
    for i, n in enumerate(selected[:10]):
        proto = n.get("protocol", "?")
        server = n.get("server", "?")
        port = n.get("port", "?")
        lat = n.get("latency_ms", "?")
        rating = n.get("checker_rating", "?")
        print(f"  {i+1}. {proto}://{server}:{port}  {lat}ms  рейтинг={rating}")

    # 6. Сохраняем в YAML (опционально)
    yaml = generate_config(selected)
    OUTPUT_FILE.write_text(yaml, "utf-8")
    print(f"\n[+] Конфиг сохранён: {OUTPUT_FILE}")
    print(f"[+] Всего: {len(selected)} прокси")


if __name__ == "__main__":
    asyncio.run(main())
