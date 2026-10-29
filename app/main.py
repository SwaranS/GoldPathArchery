"""Main FastAPI application entry point for GoldPathArchery."""

from __future__ import annotations

from fastapi import FastAPI

from app.api.v1.routers.training_plans import router as training_plans_router

app = FastAPI(
    title="GoldPathArchery API",
    version="1.0.0",
    description="GoldPathArchery FastAPI Backend — Periodized Training Plans & Live Session Runner.",
)

app.include_router(training_plans_router)

