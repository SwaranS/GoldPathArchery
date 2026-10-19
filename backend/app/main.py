from fastapi import FastAPI

from .auth.router import router as auth_router

app = FastAPI(title="GoldPathArchery API", version="0.1.0")
app.include_router(auth_router)


@app.get("/health")
def health():
    return {"status": "ok"}
