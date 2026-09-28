import hashlib
import hmac
import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("BYBIT_API_KEY")
API_SECRET = os.getenv("BYBIT_API_SECRET")

if not API_KEY or not API_SECRET:
    raise RuntimeError("Faltan BYBIT_API_KEY o BYBIT_API_SECRET en .env")

BASE_URL = "https://api.bybit.eu"

recv_window = "5000"
timestamp = str(int(time.time() * 1000))

query_string = ""

payload = timestamp + API_KEY + recv_window + query_string

signature = hmac.new(
    API_SECRET.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
).hexdigest()

headers = {
    "X-BAPI-API-KEY": API_KEY,
    "X-BAPI-SIGN": signature,
    "X-BAPI-SIGN-TYPE": "2",
    "X-BAPI-TIMESTAMP": timestamp,
    "X-BAPI-RECV-WINDOW": recv_window,
}

url = BASE_URL + "/v5/user/query-api"

print("Probando:")
print(url)
print()

response = requests.get(
    url,
    headers=headers,
    timeout=10,
)

print("HTTP:", response.status_code)
print(response.text)
