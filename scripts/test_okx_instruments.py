import base64
import hashlib
import hmac
import json
import os
from datetime import UTC, datetime

import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("OKX_API_KEY")
API_SECRET = os.getenv("OKX_API_SECRET")
PASSPHRASE = os.getenv("OKX_API_PASSPHRASE")

BASE_URL = "https://eea.okx.com"

TARGET_COINS = {"BTC", "ETH"}


if not API_KEY or not API_SECRET or not PASSPHRASE:
    raise RuntimeError("Faltan OKX_API_KEY, OKX_API_SECRET o OKX_API_PASSPHRASE en .env")


def iso_timestamp():
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def sign_request(timestamp, method, request_path, body=""):
    message = timestamp + method.upper() + request_path + body

    signature = hmac.new(
        API_SECRET.encode(),
        message.encode(),
        hashlib.sha256,
    ).digest()

    return base64.b64encode(signature).decode()


def private_get(path):
    timestamp = iso_timestamp()

    headers = {
        "OK-ACCESS-KEY": API_KEY,
        "OK-ACCESS-SIGN": sign_request(
            timestamp,
            "GET",
            path,
        ),
        "OK-ACCESS-TIMESTAMP": timestamp,
        "OK-ACCESS-PASSPHRASE": PASSPHRASE,
        "x-simulated-trading": "1",
    }

    response = requests.get(
        BASE_URL + path,
        headers=headers,
        timeout=15,
    )

    response.raise_for_status()
    return response.json()


def get_instruments(inst_type):
    path = f"/api/v5/account/instruments?instType={inst_type}"

    return private_get(path)


def coin_matches(inst):
    fields = [
        inst.get("baseCcy", ""),
        inst.get("ctValCcy", ""),
        inst.get("instFamily", ""),
        inst.get("instId", ""),
    ]

    combined = " ".join(fields).upper()

    return any(coin in combined for coin in TARGET_COINS)


def print_instrument(inst):
    print("-" * 80)

    fields = {
        "instType": inst.get("instType"),
        "instId": inst.get("instId"),
        "instFamily": inst.get("instFamily"),
        "baseCcy": inst.get("baseCcy"),
        "quoteCcy": inst.get("quoteCcy"),
        "settleCcy": inst.get("settleCcy"),
        "ctType": inst.get("ctType"),
        "ctVal": inst.get("ctVal"),
        "ctValCcy": inst.get("ctValCcy"),
        "lotSz": inst.get("lotSz"),
        "minSz": inst.get("minSz"),
        "tickSz": inst.get("tickSz"),
        "lever": inst.get("lever"),
        "state": inst.get("state"),
        "ruleType": inst.get("ruleType"),
        "expTime": inst.get("expTime"),
    }

    for key, value in fields.items():
        print(f"{key:12}: {value}")


print()
print("=" * 80)
print("OKX EU DEMO - INSTRUMENT DISCOVERY")
print("=" * 80)

results = {}

for inst_type in ["SPOT", "SWAP", "FUTURES"]:
    print()
    print("=" * 80)
    print(inst_type)
    print("=" * 80)

    try:
        response = get_instruments(inst_type)

    except Exception as exc:
        print("ERROR:", exc)
        continue

    if response.get("code") != "0":
        print(
            json.dumps(
                response,
                indent=2,
                ensure_ascii=False,
            )
        )
        continue

    instruments = response.get("data", [])

    filtered = [inst for inst in instruments if coin_matches(inst)]

    results[inst_type] = filtered

    print(f"Instrumentos BTC/ETH encontrados: {len(filtered)}")

    for inst in filtered:
        print_instrument(inst)


print()
print("=" * 80)
print("X-PERPS DETECTADOS")
print("=" * 80)

xperps = [inst for inst in results.get("FUTURES", []) if inst.get("ruleType") == "xperp"]

if not xperps:
    print("❌ No se han encontrado FUTURES con ruleType=xperp para BTC/ETH.")

else:
    for inst in xperps:
        print()
        print("✅", inst.get("instId"))

        print("   Familia:", inst.get("instFamily"))

        print("   Contract size:", inst.get("ctVal"), inst.get("ctValCcy"))

        print("   Tick:", inst.get("tickSz"))

        print("   Lot:", inst.get("lotSz"))

        print("   Apalancamiento:", inst.get("lever"))

        print("   Estado:", inst.get("state"))


print()
print("=" * 80)
print("RESUMEN")
print("=" * 80)

print("SPOT BTC/ETH:", len(results.get("SPOT", [])))

print("SWAP BTC/ETH:", len(results.get("SWAP", [])))

print("FUTURES BTC/ETH:", len(results.get("FUTURES", [])))

print("X-PERPS BTC/ETH:", len(xperps))
