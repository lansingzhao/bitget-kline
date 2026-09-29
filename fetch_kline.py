import json, time, urllib.parse, urllib.request
from datetime import datetime, timezone

SYMBOLS = ["SOLUSDT","TAOUSDT","NEARUSDT","UNIUSDT","LINKUSDT","XRPUSDT","HYPEUSDT"]
INTERVALS = ["15m","1H","4H"]
MS = {"15m":900000,"1H":3600000,"4H":14400000}
V2 = {"15m":"15min","1H":"1h","4H":"4h"}
HEADERS = {"User-Agent":"bitget-kline-action/3.0","Accept":"application/json"}

def get_json(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status, json.loads(r.read().decode())

def fetch(symbol, interval):
    q = urllib.parse.urlencode({
        "category":"SPOT","symbol":symbol,"interval":interval,"limit":60
    })
    try:
        st, j = get_json("https://api.bitget.com/api/v3/market/candles?" + q)
        if st == 200 and j.get("code") == "00000" and j.get("data"):
            return j["data"]
    except Exception:
        pass

    q = urllib.parse.urlencode({
        "symbol":symbol,"granularity":V2[interval],"limit":60
    })
    st, j = get_json("https://api.bitget.com/api/v2/spot/market/candles?" + q)
    if st == 200 and j.get("code") == "00000" and j.get("data"):
        return j["data"]
    raise RuntimeError(f"{symbol} {interval} fetch failed")

def closed_rows(raw, interval):
    now = int(time.time() * 1000)
    rows = []
    for x in raw:
        try:
            rows.append({
                "ts":int(x[0]),"o":float(x[1]),"h":float(x[2]),
                "l":float(x[3]),"c":float(x[4])
            })
        except Exception:
            pass
    rows.sort(key=lambda x: x["ts"])
    return [x for x in rows if x["ts"] + MS[interval] <= now]

def piv_lows(r):
    return [(i,r[i]["l"]) for i in range(1,len(r)-1)
            if r[i]["l"] < r[i-1]["l"] and r[i]["l"] <= r[i+1]["l"]]

def piv_highs(r):
    return [(i,r[i]["h"]) for i in range(1,len(r)-1)
            if r[i]["h"] > r[i-1]["h"] and r[i]["h"] >= r[i+1]["h"]]

def pct(a,b):
    return round((b/a-1)*100,3) if a else 0.0

def abc15(r):
    r = r[-18:]
    lows, highs = piv_lows(r), piv_highs(r)
    best = None
    for ai,av in lows:
        for bi,bv in highs:
            if bi <= ai: continue
            for ci,cv in lows:
                if ci <= bi or cv <= av: continue
                best = {
                    "A":round(av,8),"B":round(bv,8),"C":round(cv,8),
                    "breakout":any(x["c"] > bv for x in r[ci+1:])
                }
    return best

def summarize(raw, interval):
    r = closed_rows(raw, interval)
    if len(r) < 12:
        raise RuntimeError(f"{interval} closed candles < 12")
    r = r[-24:]
    closes = [x["c"] for x in r]
    lows = [v for _,v in piv_lows(r)]
    highs = [v for _,v in piv_highs(r)]
    out = {
        "close":round(r[-1]["c"],8),
        "lastClosedTs":r[-1]["ts"],
        "ret3Pct":pct(closes[-4],closes[-1]),
        "ret8Pct":pct(closes[-9],closes[-1]),
        "low12":round(min(x["l"] for x in r[-12:]),8),
        "high12":round(max(x["h"] for x in r[-12:]),8),
        "higherLow":len(lows)>=2 and lows[-1] > lows[-2],
        "lowerLow":len(lows)>=2 and lows[-1] < lows[-2],
        "higherHigh":len(highs)>=2 and highs[-1] > highs[-2],
        "lowerHigh":len(highs)>=2 and highs[-1] < highs[-2],
        "last4Closes":[round(x,8) for x in closes[-4:]]
    }
    if interval == "15m":
        out["abc"] = abc15(r)
    return out

def main():
    market, failures = {}, []
    for s in SYMBOLS:
        market[s] = {}
        for itv in INTERVALS:
            try:
                market[s][itv] = summarize(fetch(s,itv), itv)
            except Exception as e:
                failures.append({"symbol":s,"interval":itv,"reason":str(e)})
            time.sleep(0.08)

    rs = []
    for s in SYMBOLS:
        f = market.get(s,{})
        if all(k in f for k in INTERVALS):
            score = (f["15m"]["ret8Pct"]*0.25 +
                     f["1H"]["ret8Pct"]*0.35 +
                     f["4H"]["ret3Pct"]*0.40)
            rs.append({"symbol":s,"score":round(score,4)})
    rs.sort(key=lambda x:x["score"], reverse=True)

    payload = {
        "source":"Bitget",
        "schema":"compact-v1",
        "generatedAt":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
        "complete":len(failures)==0,
        "summary":{"expected":21,"success":21-len(failures),"failed":len(failures)},
        "failures":failures,
        "relativeStrength":rs,
        "market":market
    }
    with open("kline.json","w",encoding="utf-8") as f:
        json.dump(payload,f,ensure_ascii=False,separators=(",",":"))

    print(json.dumps({"complete":payload["complete"],"summary":payload["summary"]}))
    if failures:
        raise SystemExit(1)

if __name__ == "__main__":
    main()
