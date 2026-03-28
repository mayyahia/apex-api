from datetime import datetime, timezone
from fastapi import FastAPI, Query

app = FastAPI(title="Apex Live API", version="1.0.0")

@app.get("/")
def root():
    return {"message": "Apex API is running"}

@app.get("/health")
def health():
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@app.get("/market/regime")
def market_regime():
    return {
        "regime": "mixed",
        "source": "live-api",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@app.get("/index/snapshot")
def index_snapshot():
    return {
        "SPY": 0,
        "QQQ": 0,
        "IWM": 0,
        "DIA": 0,
        "source": "live-api",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@app.get("/sector/rotation")
def sector_rotation():
    return {
        "leaders": ["XLK", "XLI"],
        "laggards": ["XLU", "XLP"],
        "source": "live-api",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@app.get("/ticker/quote")
def ticker_quote(symbol: str = Query(..., description="Ticker symbol")):
    return {
        "symbol": symbol.upper(),
        "price": 0,
        "changePct": 0,
        "volume": 0,
        "source": "live-api",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@app.get("/ticker/intraday")
def ticker_intraday(symbol: str = Query(..., description="Ticker symbol")):
    return {
        "symbol": symbol.upper(),
        "bars": [],
        "source": "live-api",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@app.get("/ticker/news")
def ticker_news(symbol: str = Query(..., description="Ticker symbol")):
    return {
        "symbol": symbol.upper(),
        "items": [],
        "source": "live-api",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
@app.get("/ipos/upcoming")
def upcoming_ipos():
    return {
        "items": [],
        "source": "live-api",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
