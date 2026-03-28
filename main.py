from datetime import datetime, timezone
import os

import httpx
from cachetools import TTLCache
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query

load_dotenv()

app = FastAPI(title="Apex Live API", version="1.0.0")

TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY")
TD_BASE = "https://api.twelvedata.com"

quote_cache = TTLCache(maxsize=200, ttl=60)
series_cache = TTLCache(maxsize=100, ttl=60)


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
        data = resp.json()

    if resp.status_code == 429:
        raise HTTPException(
            status_code=429,
            detail="Twelve Data minute limit hit. Wait and retry."
        )

    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=data)

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
    data = await td_get("/quote", {"symbol": "SPY,QQQ,IWM,DIA"})
    items = data if isinstance(data, list) else [data]

    changes = {}
    for item in items:
        sym = item.get("symbol")
        if sym in {"SPY", "QQQ", "IWM"}:
            try:
                changes[sym] = float(item.get("percent_change", 0))
            except Exception:
                changes[sym] = 0.0

    avg = sum(changes.values()) / max(len(changes), 1)

    if avg > 0.5:
        regime = "risk-on"
    elif avg < -0.5:
        regime = "risk-off"
    else:
        regime = "mixed"

    return {
        "regime": regime,
        "drivers": changes,
        "source": "twelve-data",
        "timestamp": now_utc(),
    }


@app.get("/index/snapshot")
async def index_snapshot():
    data = await td_get("/quote", {"symbol": "SPY,QQQ,IWM,DIA"})
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


@app.get("/sector/rotation")
async def sector_rotation():
    sector_symbols = "XLK,XLF,XLE,XLI,XLY,XLV"
    data = await td_get("/quote", {"symbol": sector_symbols})
    items = data if isinstance(data, list) else [data]

    parsed = []
    for item in items:
        try:
            parsed.append(
                {
                    "symbol": item.get("symbol"),
                    "changePct": float(item.get("percent_change", 0)),
                }
            )
        except Exception:
            continue

    parsed.sort(key=lambda x: x["changePct"], reverse=True)

    return {
        "leaders": parsed[:2],
        "laggards": parsed[-2:],
        "source": "twelve-data",
        "timestamp": now_utc(),
    }


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
async def ticker_intraday(
    symbol: str = Query(..., description="Ticker symbol"),
    interval: str = Query("5min", description="Bar interval"),
):
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


import feedparser

@app.get("/ticker/news")
def ticker_news(symbol: str = Query(..., description="Ticker symbol")):
    feed_url = f"https://finance.yahoo.com/rss/headline?s={symbol.upper()}"
    feed = feedparser.parse(feed_url)

    items = []
    for entry in feed.entries[:10]:
        items.append({
            "title": entry.get("title"),
            "link": entry.get("link"),
            "published": entry.get("published"),
            "summary": entry.get("summary"),
        })

    return {
        "symbol": symbol.upper(),
        "items": items,
        "source": "yahoo-rss",
        "timestamp": now_utc(),
    }


@app.get("/ipos/upcoming")
def upcoming_ipos():
    return {
        "items": [],
        "source": "stub",
        "timestamp": now_utc(),
    }
