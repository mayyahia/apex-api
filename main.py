from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def root():
    return {"message": "Apex API is running"}

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/market/regime")
def market_regime():
    return {
        "regime": "mixed",
        "source": "test",
        "timestamp": "placeholder"
    }
