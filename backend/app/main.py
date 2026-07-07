"""Occitanie MaaS scenario API."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.app.api.jobs import router as jobs_router
from backend.app.services.constants import OUTPUT_DIR
from backend.app.services.process_service import stop_running_jobs_on_shutdown

app = FastAPI(title="Eqasim France Scenario Backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(jobs_router)
app.mount("/resources", StaticFiles(directory=str(OUTPUT_DIR)), name="resources")


@app.on_event("shutdown")
def on_shutdown() -> None:
    stop_running_jobs_on_shutdown()
