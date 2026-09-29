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

MS = {
    "15m": 900000,
    "1H": 3600000,
    "4H": 14400000,
}

# Bitget V2 fallback granularity mapping
V2 = {
    "15m": "15min",
    "1H": "1h",
    "4H": "4h",
}

HEADERS = {
    "User-Agent": "bitget-kline-action/3.1",
    "Accept": "application/json",
}


def get_json(url):
    req = urllib.request.Request(url, headers=HEADERS)

    with urllib.request.urlopen(req, timeout=20) as r:
        body = r.read().decode("utf-8")
        return r.status, json.loads(body)


def fetch(symbol, interval):
    """
    Prefer Bitget V3 spot market candles.
    Fall back to V2 spot candles if V3 fails.
    """

    # ---------- V3 ----------
    q = urllib.parse.urlencode({
        "category": "SPOT",
        "symbol": symbol,
        "interval": interval,
        "type": "market",
        "limit": 60,
    })

    v3_url = (
        "https://api.bitget.com/api/v3/market/candles?"
        + q
    )

    try:
        status, data = get_json(v3_url)

        if (
            status == 200
            and data.get("code") == "00000"
            and data.get("data")
        ):
            return data["data"]

    except Exception:
        pass

    # ---------- V2 fallback ----------
    q = urllib.parse.urlencode({
        "symbol": symbol,
        "granularity": V2[interval],
        "limit": 60,
    })

    v2_url = (
        "https://api.bitget.com/api/v2/spot/market/candles?"
        + q
    )

    status, data = get_json(v2_url)

    if (
        status == 200
        and data.get("code") == "00000"
        and data.get("data")
    ):
        return data["data"]

    raise RuntimeError(
        f"{symbol} {interval} fetch failed"
    )


def closed_rows(raw, interval):
    """
    Convert raw Bitget candles into normalized rows
    and remove the currently unfinished candle.
    """

    now = int(time.time() * 1000)

    rows = []

    for x in raw:
        try:
            rows.append({
                "ts": int(x[0]),
                "o": float(x[1]),
                "h": float(x[2]),
                "l": float(x[3]),
                "c": float(x[4]),
            })

        except Exception:
            pass

    rows.sort(key=lambda x: x["ts"])

    return [
        x
        for x in rows
        if x["ts"] + MS[interval] <= now
    ]


def piv_lows(rows):
    return [
        (i, rows[i]["l"])
        for i in range(1, len(rows) - 1)
        if (
            rows[i]["l"] < rows[i - 1]["l"]
            and rows[i]["l"] <= rows[i + 1]["l"]
        )
    ]


def piv_highs(rows):
    return [
        (i, rows[i]["h"])
        for i in range(1, len(rows) - 1)
        if (
            rows[i]["h"] > rows[i - 1]["h"]
            and rows[i]["h"] >= rows[i + 1]["h"]
        )
    ]


def pct(a, b):
    if not a:
        return 0.0

    return round(
        (b / a - 1) * 100,
        3,
    )


def abc15(rows):
    """
    Detect a simplified A -> B -> C structure:

    A = swing low
    B = rebound swing high
    C = later higher low

    breakout = a later closed candle closes above B
    """

    rows = rows[-18:]

    lows = piv_lows(rows)
    highs = piv_highs(rows)

    best = None

    for ai, av in lows:

        for bi, bv in highs:

            if bi <= ai:
                continue

            for ci, cv in lows:

                if ci <= bi:
                    continue

                if cv <= av:
                    continue

                best = {
                    "A": round(av, 8),
                    "B": round(bv, 8),
                    "C": round(cv, 8),
                    "breakout": any(
                        x["c"] > bv
                        for x in rows[ci + 1:]
                    ),
                }

    return best


def summarize(raw, interval):
    rows = closed_rows(raw, interval)

    if len(rows) < 12:
        raise RuntimeError(
            f"{interval} closed candles < 12"
        )

    rows = rows[-24:]

    closes = [
        x["c"]
        for x in rows
    ]

    lows = [
        value
        for _, value in piv_lows(rows)
    ]

    highs = [
        value
        for _, value in piv_highs(rows)
    ]

    out = {
        "close": round(
            rows[-1]["c"],
            8,
        ),

        "lastClosedTs":
            rows[-1]["ts"],

        "ret3Pct": pct(
            closes[-4],
            closes[-1],
        ),

        "ret8Pct": pct(
            closes[-9],
            closes[-1],
        ),

        "low12": round(
            min(
                x["l"]
                for x in rows[-12:]
            ),
            8,
        ),

        "high12": round(
            max(
                x["h"]
                for x in rows[-12:]
            ),
            8,
        ),

        "higherLow":
            len(lows) >= 2
            and lows[-1] > lows[-2],

        "lowerLow":
            len(lows) >= 2
            and lows[-1] < lows[-2],

        "higherHigh":
            len(highs) >= 2
            and highs[-1] > highs[-2],

        "lowerHigh":
            len(highs) >= 2
            and highs[-1] < highs[-2],

        "last4Closes": [
            round(x, 8)
            for x in closes[-4:]
        ],
    }

    if interval == "15m":
        out["abc"] = abc15(rows)

    return out


def main():
    market = {}
    failures = []

    expected = len(SYMBOLS) * len(INTERVALS)

    for symbol in SYMBOLS:

        market[symbol] = {}

        for interval in INTERVALS:

            try:
                raw = fetch(
                    symbol,
                    interval,
                )

                market[symbol][interval] = summarize(
                    raw,
                    interval,
                )

            except Exception as e:

                failures.append({
                    "symbol": symbol,
                    "interval": interval,
                    "reason": str(e),
                })

            # Avoid unnecessary burst requests
            time.sleep(0.08)

    # ---------- relative strength ----------
    relative_strength = []

    for symbol in SYMBOLS:

        frames = market.get(
            symbol,
            {},
        )

        if all(
            interval in frames
            for interval in INTERVALS
        ):

            score = (
                frames["15m"]["ret8Pct"] * 0.25
                + frames["1H"]["ret8Pct"] * 0.35
                + frames["4H"]["ret3Pct"] * 0.40
            )

            relative_strength.append({
                "symbol": symbol,
                "score": round(
                    score,
                    4,
                ),
            })

    relative_strength.sort(
        key=lambda x: x["score"],
        reverse=True,
    )

    success = expected - len(failures)

    payload = {
        "source": "Bitget",
        "schema": "compact-v1",

        "generatedAt":
            datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),

        "complete":
            len(failures) == 0,

        "summary": {
            "expected": expected,
            "success": success,
            "failed": len(failures),
        },

        "failures":
            failures,

        "relativeStrength":
            relative_strength,

        "market":
            market,
    }

    with open(
        "kline.json",
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            payload,
            f,
            ensure_ascii=False,
            separators=(",", ":"),
        )

    print(
        json.dumps({
            "generatedAt":
                payload["generatedAt"],

            "complete":
                payload["complete"],

            "summary":
                payload["summary"],
        })
    )

    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
