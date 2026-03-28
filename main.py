from datetime import datetime, timezone
import os

import feedparser
import httpx
from cachetools import TTLCache
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query

load_dotenv()

app = FastAPI(title="Apex Live API", version="1.0.0")

TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY")
TD_BASE = "https://api.twelvedata.com"

quote_cache = TTLCache(maxsize=300, ttl=60)
series_cache = TTLCache(maxsize=100, ttl=60)
movers_cache = TTLCache(maxsize=10, ttl=60)

WATCHLIST = [
    "SPY", "QQQ", "IWM",
    "NVDA", "AAPL", "TSLA",
    "AMD", "PLTR",
]


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
            detail="Twelve Data minute limit hit. Wait and retry.",
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
    spy = await td_get("/quote", {"symbol": "SPY"})
    qqq = await td_get("/quote", {"symbol": "QQQ"})
    iwm = await td_get("/quote", {"symbol": "IWM"})

    def pct(item):
        try:
            return float(item.get("percent_change", 0) or 0)
        except Exception:
            return 0.0

    changes = {
        "SPY": pct(spy),
        "QQQ": pct(qqq),
        "IWM": pct(iwm),
    }

    avg = sum(changes.values()) / 3

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
        "rawCount": 3,
    }


@app.get("/index/snapshot")
async def index_snapshot():
    symbols = ["SPY", "QQQ", "IWM", "DIA"]
    out = {"source": "twelve-data", "timestamp": now_utc()}

    for sym in symbols:
        item = await td_get("/quote", {"symbol": sym})
        out[sym] = {
            "price": item.get("close"),
            "change": item.get("change"),
            "changePct": item.get("percent_change"),
        }

    return out


@app.get("/sector/rotation")
async def sector_rotation():
    sector_symbols = ["XLK", "XLF", "XLE", "XLV"]
    parsed = []

    for sym in sector_symbols:
        item = await td_get("/quote", {"symbol": sym})
        try:
            parsed.append(
                {
                    "symbol": sym,
                    "changePct": float(item.get("percent_change", 0) or 0),
                }
            )
        except Exception:
            parsed.append({"symbol": sym, "changePct": 0.0})

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


@app.get("/ticker/news")
def ticker_news(symbol: str = Query(..., description="Ticker symbol")):
    feed_url = f"https://finance.yahoo.com/rss/headline?s={symbol.upper()}"
    feed = feedparser.parse(feed_url)

    items = []
    for entry in feed.entries[:10]:
        items.append(
            {
                "title": entry.get("title"),
                "link": entry.get("link"),
                "published": entry.get("published"),
                "summary": entry.get("summary"),
            }
        )

    return {
        "symbol": symbol.upper(),
        "items": items,
        "source": "yahoo-rss",
        "timestamp": now_utc(),
    }


@app.get("/ipos/upcoming")
async def upcoming_ipos():
    url = "https://api.nasdaq.com/api/ipo/calendar?date=upcoming"

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Referer": "https://www.nasdaq.com/",
    }

    async with httpx.AsyncClient(timeout=20.0, headers=headers) as client:
        resp = await client.get(url)

    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail="Failed to fetch Nasdaq IPO API")

    data = resp.json()

    try:
        rows = data["data"]["upcoming"]["rows"]
    except Exception:
        return {
            "items": [],
            "source": "nasdaq-api",
            "timestamp": now_utc(),
            "error": "Structure changed or no data",
        }

    items = []
    for row in rows:
        items.append(
            {
                "symbol": row.get("symbol"),
                "name": row.get("companyName"),
                "exchange": row.get("exchange"),
                "price": row.get("priceRange"),
                "shares": row.get("shares"),
                "expectedDate": row.get("expectedDate"),
            }
        )

    return {
        "items": items,
        "count": len(items),
        "source": "nasdaq-api",
        "timestamp": now_utc(),
    }


@app.get("/market/movers")
async def market_movers():
    cache_key = "market_movers"

    if cache_key in movers_cache:
        return movers_cache[cache_key]

    movers = []

    for sym in WATCHLIST:
        item = await td_get("/quote", {"symbol": sym})
        try:
            movers.append(
                {
                    "symbol": sym,
                    "price": float(item.get("close", 0) or 0),
                    "change": float(item.get("change", 0) or 0),
                    "changePct": float(item.get("percent_change", 0) or 0),
                    "volume": float(item.get("volume", 0) or 0),
                }
            )
        except Exception:
            continue

    gainers = [x for x in movers if x["changePct"] > 0]
    losers = [x for x in movers if x["changePct"] < 0]

    result = {
        "gainers": sorted(gainers, key=lambda x: x["changePct"], reverse=True)[:3],
        "losers": sorted(losers, key=lambda x: x["changePct"])[:3],
        "mostActive": sorted(movers, key=lambda x: x["volume"], reverse=True)[:3],
        "universeSize": len(movers),
        "source": "twelve-data-derived",
        "timestamp": now_utc(),
    }

    movers_cache[cache_key] = result
    return result


@app.get("/market/gainers")
async def market_gainers():
    data = await market_movers()
    return {
        "items": data["gainers"],
        "count": len(data["gainers"]),
        "source": data["source"],
        "timestamp": data["timestamp"],
    }


@app.get("/market/losers")
async def market_losers():
    data = await market_movers()
    return {
        "items": data["losers"],
        "count": len(data["losers"]),
        "source": data["source"],
        "timestamp": data["timestamp"],
    }
