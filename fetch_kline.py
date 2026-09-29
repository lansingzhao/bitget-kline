import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

SYMBOLS = [
    "SOLUSDT",
    "TAOUSDT",
    "NEARUSDT",
    "UNIUSDT",
    "LINKUSDT",
    "XRPUSDT",
    "HYPEUSDT",
]

INTERVALS = ["15m", "1H", "4H"]

V2_GRANULARITY = {
    "15m": "15min",
    "1H": "1h",
    "4H": "4h",
}

INTERVAL_MS = {
    "15m": 15 * 60 * 1000,
    "1H": 60 * 60 * 1000,
    "4H": 4 * 60 * 60 * 1000,
}

HEADERS = {
    "User-Agent": "bitget-kline-github-action/2.0",
    "Accept": "application/json",
}


def get_json(url, timeout=20):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def fetch_candles(symbol, interval):
    v3_error = ""

    try:
        q = urllib.parse.urlencode({
            "category": "SPOT",
            "symbol": symbol,
            "interval": interval,
            "limit": 60,
        })
        status, body = get_json(
            f"https://api.bitget.com/api/v3/market/candles?{q}"
        )

        if (
            status == 200
            and body.get("code") == "00000"
            and isinstance(body.get("data"), list)
            and body["data"]
        ):
            return {
                "symbol": symbol,
                "interval": interval,
                "ok": True,
                "source": "v3",
                "candles": body["data"],
            }

        v3_error = (
            f'HTTP {status} | '
            f'{body.get("code", "")} | '
            f'{body.get("msg", "")}'
        )

    except Exception as e:
        v3_error = str(e)

    try:
        q = urllib.parse.urlencode({
            "symbol": symbol,
            "granularity": V2_GRANULARITY[interval],
            "limit": 60,
        })
        status, body = get_json(
            f"https://api.bitget.com/api/v2/spot/market/candles?{q}"
        )

        if (
            status == 200
            and body.get("code") == "00000"
            and isinstance(body.get("data"), list)
            and body["data"]
        ):
            return {
                "symbol": symbol,
                "interval": interval,
                "ok": True,
                "source": "v2",
                "candles": body["data"],
            }

        v2_error = (
            f'HTTP {status} | '
            f'{body.get("code", "")} | '
            f'{body.get("msg", "")}'
        )

    except Exception as e:
        v2_error = str(e)

    return {
        "symbol": symbol,
        "interval": interval,
        "ok": False,
        "source": None,
        "candles": [],
        "error": {
            "v3": v3_error,
            "v2": v2_error,
        },
    }


def normalize_closed(raw, interval):
    now_ms = int(time.time() * 1000)
    rows = []
