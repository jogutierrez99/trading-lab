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


if not API_KEY or not API_SECRET or not PASSPHRASE:
    raise RuntimeError("Faltan OKX_API_KEY, OKX_API_SECRET o OKX_API_PASSPHRASE en el archivo .env")


def iso_timestamp():
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def sign_request(timestamp, method, request_path, body=""):
    message = timestamp + method.upper() + request_path + body

    signature = hmac.new(
        API_SECRET.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).digest()

    return base64.b64encode(signature).decode()


def private_get(request_path):
    timestamp = iso_timestamp()

    signature = sign_request(
        timestamp=timestamp,
        method="GET",
        request_path=request_path,
    )

    headers = {
        "OK-ACCESS-KEY": API_KEY,
        "OK-ACCESS-SIGN": signature,
        "OK-ACCESS-TIMESTAMP": timestamp,
        "OK-ACCESS-PASSPHRASE": PASSPHRASE,
        "x-simulated-trading": "1",
    }

    response = requests.get(
        BASE_URL + request_path,
        headers=headers,
        timeout=15,
    )

    return response


def public_get(request_path):
    return requests.get(
        BASE_URL + request_path,
        timeout=15,
    )


def print_response(title, response):
    print()
    print("=" * 70)
    print(title)
    print("=" * 70)
    print("HTTP:", response.status_code)

    try:
        data = response.json()
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return data
    except Exception:
        print(response.text)
        return None


print("OKX EU DEMO - TEST DE CONEXIÓN")
print("Endpoint:", BASE_URL)
print("Modo: DEMO")
print("NO SE ENVIARÁN ÓRDENES")


# ---------------------------------------------------------
# 1. Configuración de cuenta
# ---------------------------------------------------------

response = private_get("/api/v5/account/config")

config_data = print_response(
    "1. ACCOUNT CONFIG",
    response,
)


# ---------------------------------------------------------
# 2. Saldo
# ---------------------------------------------------------

response = private_get("/api/v5/account/balance")

balance_data = print_response(
    "2. ACCOUNT BALANCE",
    response,
)


# ---------------------------------------------------------
# 3. Instrumentos SPOT disponibles
# ---------------------------------------------------------

response = public_get("/api/v5/public/instruments?instType=SPOT")

spot_data = print_response(
    "3. SPOT INSTRUMENTS",
    response,
)


# ---------------------------------------------------------
# Resultado resumido
# ---------------------------------------------------------

print()
print("=" * 70)
print("RESULTADO")
print("=" * 70)

private_ok = (
    isinstance(config_data, dict)
    and config_data.get("code") == "0"
    and isinstance(balance_data, dict)
    and balance_data.get("code") == "0"
)

if private_ok:
    print("✅ Autenticación OKX Demo correcta.")
    print("✅ La API puede leer la cuenta.")
    print("✅ La API puede consultar el saldo.")
    print()
    print("Todavía NO se ha enviado ninguna orden.")
else:
    print("❌ La autenticación no se ha completado correctamente.")
    print("Revisa los mensajes anteriores.")
