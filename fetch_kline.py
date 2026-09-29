def summarize(rows, interval):
    if len(rows) < 12:
        return {"ok": False, "reason": "closed_candles_lt_12"}

    r = rows[-24:]
    closes = [x["c"] for x in r]

    pls = pivot_lows(r)
    phs = pivot_highs(r)

    last_two_lows = [v for _, v in pls[-2:]]
    last_two_highs = [v for _, v in phs[-2:]]

    higher_low = (
        len(last_two_lows) == 2
        and last_two_lows[-1] > last_two_lows[-2]
    )
    lower_low = (
        len(last_two_lows) == 2
        and last_two_lows[-1] < last_two_lows[-2]
    )
    higher_high = (
        len(last_two_highs) == 2
        and last_two_highs[-1] > last_two_highs[-2]
    )
    lower_high = (
        len(last_two_highs) == 2
        and last_two_highs[-1] < last_two_highs[-2]
    )

    latest = r[-1]
    prior12 = r[-13:-1]

    result = {
        "ok": True,
        "lastClosedTs": latest["ts"],
        "close": round(latest["c"], 8),
        "ret3Pct": pct(closes[-4], closes[-1]),
        "ret8Pct": pct(closes[-9], closes[-1]),
        "low12": round(min(x["l"] for x in r[-12:]), 8),
        "high12": round(max(x["h"] for x in r[-12:]), 8),
        "prior12Low": round(min(x["l"] for x in prior12), 8),
        "prior12High": round(max(x["h"] for x in prior12), 8),
        "higherLow": higher_low,
        "lowerLow": lower_low,
        "higherHigh": higher_high,
        "lowerHigh": lower_high,
        "last4Closes": [round(x, 8) for x in closes[-4:]],
    }

    if interval == "15m":
        result["abc"] = find_abc(r)

    return result


def main():
    results = []

    for symbol in SYMBOLS:
        for interval in INTERVALS:
            results.append(fetch_candles(symbol, interval))
            time.sleep(0.08)

    failures = [x for x in results if not x["ok"]]
    market = {}
    quality_failures = []

    for r in results:
        if not r["ok"]:
            continue

        closed = normalize_closed(r["candles"], r["interval"])
        summary = summarize(closed, r["interval"])

        if not summary.get("ok"):
            quality_failures.append({
                "symbol": r["symbol"],
                "interval": r["interval"],
                "reason": summary.get("reason", "unknown"),
            })

        market.setdefault(r["symbol"], {})[r["interval"]] = summary

    all_failures = [
        {
            "symbol": x["symbol"],
            "interval": x["interval"],
            "reason": x.get("error", "fetch_failed"),
        }
        for x in failures
    ] + quality_failures

    rs = []
    for symbol in SYMBOLS:
        frames = market.get(symbol, {})
        if all(k in frames and frames[k].get("ok") for k in INTERVALS):
            score = (
                frames["15m"]["ret8Pct"] * 0.25
                + frames["1H"]["ret8Pct"] * 0.35
                + frames["4H"]["ret3Pct"] * 0.40
            )
            rs.append((symbol, round(score, 4)))

    rs.sort(key=lambda x: x[1], reverse=True)

    payload = {
        "source": "Bitget",
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "schema": "compact-v1",
        "complete": len(all_failures) == 0 and len(market) == len(SYMBOLS),
        "summary": {
            "expected": 21,
            "success": 21 - len(all_failures),
            "failed": len(all_failures),
        },
        "failures": all_failures,
        "relativeStrength": [
            {"symbol": s, "score": v}
            for s, v in rs
        ],
        "market": market,
    }

    with open("kline.json", "w", encoding="utf-8") as f:
        json.dump(
            payload,
            f,
            ensure_ascii=False,
            separators=(",", ":"),
        )

    print(json.dumps({
        "complete": payload["complete"],
        "summary": payload["summary"],
        "bytes": len(json.dumps(payload, ensure_ascii=False).encode("utf-8")),
    }, ensure_ascii=False))

    if not payload["complete"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
