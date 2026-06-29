"""
Скачивает GeoLite2-Country.mmdb для локального GeoIP.
Требуется бесплатный лицензионный ключ MaxMind:
  1. Зарегистрируйтесь на https://dev.maxmind.com/geoip/geolite2-free-geolocation-data
  2. Создайте ключ в разделе "Manage License Keys"
  3. Установите переменную окружения GEOIP_LICENSE_KEY или передайте ключ аргументом

Использование:
  python -m backend.download_geoip
  python -m backend.download_geoip --key YOUR_KEY
"""
import argparse
import os
import sys
import tarfile
import tempfile
from pathlib import Path

import httpx

# Корень проекта (родитель backend/)
ROOT = Path(__file__).resolve().parent.parent
GEODIR = ROOT / "GeoIP"
GEOFILE = GEODIR / "GeoLite2-Country.mmdb"

MAXMIND_URL = "https://download.maxmind.com/app/geoip_download"
EDITION_ID = "GeoLite2-Country"
SUFFIX = "tar.gz"


def main():
    parser = argparse.ArgumentParser(description="Скачать GeoLite2-Country.mmdb")
    parser.add_argument("--key", help="Лицензионный ключ MaxMind")
    args = parser.parse_args()

    key = args.key or os.environ.get("GEOIP_LICENSE_KEY")
    if not key:
        print("❌ Укажите ключ через --key или переменную GEOIP_LICENSE_KEY")
        print("   Получить ключ: https://dev.maxmind.com/geoip/geolite2-free-geolocation-data")
        sys.exit(1)

    if GEOFILE.exists():
        print(f"📁 База уже существует: {GEOFILE}")
        print(f"   Размер: {GEOFILE.stat().st_size / 1024 / 1024:.1f} MB")
        return

    GEODIR.mkdir(parents=True, exist_ok=True)

    url = f"{MAXMIND_URL}?edition_id={EDITION_ID}&license_key={key}&suffix={SUFFIX}"
    print(f"⬇️  Скачивание GeoLite2-Country...")

    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
        with httpx.stream("GET", url, follow_redirects=True, timeout=60) as resp:
            resp.raise_for_status()
            for chunk in resp.iter_bytes(1024 * 1024):
                tmp.write(chunk)
        tmp_path = Path(tmp.name)

    try:
        with tarfile.open(tmp_path, "r:gz") as tar:
            for member in tar.getmembers():
                if member.name.endswith(".mmdb"):
                    member.name = GEOFILE.name
                    tar.extract(member, GEODIR, filter="data")
                    print(f"✅ Сохранено: {GEOFILE} ({GEOFILE.stat().st_size / 1024 / 1024:.1f} MB)")
                    break
            else:
                print("❌ .mmdb не найден в архиве")
    finally:
        tmp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
