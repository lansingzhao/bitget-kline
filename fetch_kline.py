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

HEADERS = {
    "User-Agent": "bitget-kline-github-action/1.0",
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
            "limit": 40,
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
                "v3": "success",
                "v2": "not_needed",
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
            "limit": 40,
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
                "v3": v3_error,
                "v2": "success",
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
        "v3": v3_error,
        "v2": v2_error,
        "error": "v3 and v2 both failed",
    }


def main():
    results = []

    for symbol in SYMBOLS:
        for interval in INTERVALS:
            results.append(fetch_candles(symbol, interval))
            time.sleep(0.08)

    failures = [
        {
            "symbol": x["symbol"],
            "interval": x["interval"],
            "v3": x.get("v3"),
            "v2": x.get("v2"),
            "error": x.get("error"),
        }
        for x in results
        if not x["ok"]
    ]

    data = {}

    for r in results:
        data.setdefault(r["symbol"], {})[r["interval"]] = {
            "ok": r["ok"],
            "source": r["source"],
            "candles": r["candles"],
        }

    payload = {
        "source": "Bitget",
        "generatedAt": datetime.now(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),

        "complete": len(failures) == 0,

        "summary": {
            "expected": 21,
            "success": sum(1 for x in results if x["ok"]),
            "failed": len(failures),
        },

        "failures": failures,

        "data": data,
    }

    with open("kline.json", "w", encoding="utf-8") as f:
        json.dump(
            payload,
            f,
            ensure_ascii=False,
            separators=(",", ":"),
        )

    print(json.dumps(payload["summary"], ensure_ascii=False))

    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
