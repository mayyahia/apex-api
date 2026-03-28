from cachetools import TTLCache

quote_cache = TTLCache(maxsize=200, ttl=30)
series_cache = TTLCache(maxsize=100, ttl=30)
from datetime import datetime, timezone
import os

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query

load_dotenv()

app = FastAPI(title="Apex Live API", version="1.0.0")

TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY")
TD_BASE = "https://api.twelvedata.com"


def now_utc():
    return datetime.now(timezone.utc).isoformat()


async def td_get(path: str, params: dict):
    if not TWELVE_DATA_API_KEY:
        raise HTTPException(status_code=500, detail="Missing TWELVE_DATA_API_KEY")

    merged = {**params, "apikey": TWELVE_DATA_API_KEY}
    cache_key = f"{path}|{str(sorted(merged.items()))}"

    cache = series_cache if path == "/time_series" else quote_cache
    if cache_key in cache:
        return cache[cache_key]

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(f"{TD_BASE}{path}", params=merged)
        resp.raise_for_status()
        data = resp.json()

    if isinstance(data, dict) and data.get("status") == "error":
        raise HTTPException(status_code=400, detail=data)

    cache[cache_key] = data
    return data


@app.get("/")
def root():
    return {"message": "Apex API is running"}


@app.get("/health")
def health():
    return {"status": "ok", "timestamp": now_utc()}


@app.get("/market/regime")
async def market_regime():
    spy = await td_get("/quote", {"symbol": "SPY"})
    qqq = await td_get("/quote", {"symbol": "QQQ"})
    iwm = await td_get("/quote", {"symbol": "IWM"})

    def pct(x):
        try:
            return float(x.get("percent_change", 0))
        except Exception:
            return 0.0

    avg = (pct(spy) + pct(qqq) + pct(iwm)) / 3

    if avg > 0.5:
        regime = "risk-on"
    elif avg < -0.5:
        regime = "risk-off"
    else:
        regime = "mixed"

    return {
        "regime": regime,
        "drivers": {
            "SPY": spy.get("percent_change"),
            "QQQ": qqq.get("percent_change"),
            "IWM": iwm.get("percent_change"),
        },
        "source": "twelve-data",
        "timestamp": now_utc(),
    }


@app.get("/index/snapshot")
async def index_snapshot():
    symbols = "SPY,QQQ,IWM,DIA"
    data = await td_get("/quote", {"symbol": symbols})

    items = data if isinstance(data, list) else [data]
    out = {"source": "twelve-data", "timestamp": now_utc()}

    for item in items:
        sym = item.get("symbol")
        if sym:
            out[sym] = {
                "price": item.get("close"),
                "change": item.get("change"),
                "changePct": item.get("percent_change"),
            }

    return out


@app.get("/ticker/quote")
async def ticker_quote(symbol: str = Query(..., description="Ticker symbol")):
    data = await td_get("/quote", {"symbol": symbol.upper()})
    return {
        "symbol": data.get("symbol", symbol.upper()),
        "price": data.get("close"),
        "change": data.get("change"),
        "changePct": data.get("percent_change"),
        "volume": data.get("volume"),
        "open": data.get("open"),
        "high": data.get("high"),
        "low": data.get("low"),
        "previousClose": data.get("previous_close"),
        "source": "twelve-data",
        "timestamp": now_utc(),
    }


@app.get("/ticker/intraday")
async def ticker_intraday(symbol: str = Query(...), interval: str = "5min"):
    data = await td_get(
        "/time_series",
        {
            "symbol": symbol.upper(),
            "interval": interval,
            "outputsize": 50,
            "format": "JSON",
        },
    )

    values = data.get("values", [])
    bars = [
        {
            "datetime": row.get("datetime"),
            "open": row.get("open"),
            "high": row.get("high"),
            "low": row.get("low"),
            "close": row.get("close"),
            "volume": row.get("volume"),
        }
        for row in values
    ]

    return {
        "symbol": symbol.upper(),
        "interval": interval,
        "bars": bars,
        "source": "twelve-data",
        "timestamp": now_utc(),
    }
@app.get("/sector/rotation")
async def sector_rotation():
    sector_symbols = "XLK,XLF,XLE,XLV,XLI,XLY,XLP,XLU,XLB,XLRE,XLC"
    data = await td_get("/quote", {"symbol": sector_symbols})

    items = data if isinstance(data, list) else [data]

    parsed = []
    for item in items:
        try:
            parsed.append({
                "symbol": item.get("symbol"),
                "changePct": float(item.get("percent_change", 0))
            })
        except Exception:
            continue

    parsed.sort(key=lambda x: x["changePct"], reverse=True)

    return {
        "leaders": parsed[:3],
        "laggards": parsed[-3:],
        "source": "twelve-data",
        "timestamp": now_utc(),
    }
