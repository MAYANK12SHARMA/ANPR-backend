# backend/app/main.py

import os

os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")

from fastapi import FastAPI
from app.api.routes import router
from app.auth.routes import router as auth_router
from app.db.database import engine
from app.db import models
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

# Create tables
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="ANPR Backend")
app.mount("/media", StaticFiles(directory="media"), name="media")
app.include_router(router)
app.include_router(
    auth_router,
    prefix="/auth",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _ensure_legacy_schema_columns():
    statements = [
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS line_distance_meters DOUBLE PRECISION",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS job_type VARCHAR",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS is_live VARCHAR",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS camera_rtsp_url VARCHAR",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS camera_config VARCHAR",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS stream_started_at TIMESTAMPTZ",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS last_frame_processed_at TIMESTAMPTZ",
        "ALTER TABLE plates ADD COLUMN IF NOT EXISTS speed_kmh DOUBLE PRECISION",
        "ALTER TABLE plates ADD COLUMN IF NOT EXISTS plate_text_highres VARCHAR",
        "ALTER TABLE plates ADD COLUMN IF NOT EXISTS ocr_conf_highres DOUBLE PRECISION",
        "ALTER TABLE plates ADD COLUMN IF NOT EXISTS plate_text_lowres VARCHAR",
        "ALTER TABLE plates ADD COLUMN IF NOT EXISTS ocr_conf_lowres DOUBLE PRECISION",
    ]

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


@app.on_event("startup")
def _startup_db_sync():
    _ensure_legacy_schema_columns()


@app.get("/health")
def health_check():
    return {"status": "Backend is running"}
