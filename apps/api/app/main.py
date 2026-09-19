from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import accounts, forecast, health, leads, opportunities, reps
from app.config import get_settings

settings = get_settings()

app = FastAPI(title=settings.app_name, version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
for module in (health, reps, accounts, leads, opportunities, forecast):
    app.include_router(module.router, prefix="/api/v1")
