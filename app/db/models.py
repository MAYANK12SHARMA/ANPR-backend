# backend/app/db/models.py

import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy import (
    Enum as SqlEnum,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.database import Base

class Job(Base):
    __tablename__ = "jobs"

    job_id = Column(
        String, primary_key=True, index=True, default=lambda: str(uuid.uuid4())
    )
    owner_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    video_path = Column(String, nullable=True)
    processed_video_path = Column(String, nullable=True)
    status = Column(String, default="pending")
    roi_coords = Column(String, nullable=True)  # JSON string of polygon points
    line_coords = Column(String, nullable=True)  # JSON string of line points
    line_distance_meters = Column(Float, nullable=True)
    job_type = Column(String, default="video_upload")
    analysis_config = Column(
        JSON,
        nullable=False,
        default=lambda: {
            "vehicle": True,
            "plate": True,
            "pedestrian": False,
        },
    )

    pedestrian_threshold = Column(Integer, nullable=False, default=10)
    is_live = Column(String, default="false")
    camera_rtsp_url = Column(String, nullable=True)
    camera_config = Column(String, nullable=True)
    stream_started_at = Column(DateTime(timezone=True), nullable=True)
    last_frame_processed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    plates = relationship(
        "Plate",
        back_populates="job",
        cascade="all, delete-orphan",
    )

    alerts = relationship(
        "Alert",
        back_populates="job",
        cascade="all, delete-orphan",
    )

    owner = relationship(
        "User",
        back_populates="jobs",
    )


class Plate(Base):
    __tablename__ = "plates"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(
        String,
        ForeignKey("jobs.job_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    plate_text = Column(String, nullable=True)
    best_confidence = Column(Float, nullable=True)
    bbox_confidence = Column(Float, nullable=True)

    # Per-pipeline OCR results (stored independently)
    plate_text_highres = Column(String, nullable=True)
    ocr_conf_highres = Column(Float, nullable=True)
    plate_text_lowres = Column(String, nullable=True)
    ocr_conf_lowres = Column(Float, nullable=True)

    best_image_path = Column(String, nullable=True)
    vehicle_type = Column(String, nullable=True)
    vehicle_confidence = Column(Float, nullable=True)
    vehicle_image_path = Column(String, nullable=True)

    # Tracking information
    track_id = Column(Integer, nullable=True)  # Vehicle tracking ID
    frame_number = Column(Integer, nullable=True)  # Frame when detected
    crossed_line = Column(Integer, default=1)  # 1 if crossed line (filtered)
    speed_kmh = Column(Float, nullable=True)
    detected_at = Column(DateTime(timezone=True), nullable=True)
    job = relationship(
        "Job",
        back_populates="plates",
    )


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, index=True)

    job_id = Column(
        String,
        ForeignKey("jobs.job_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    alert_type = Column(String, nullable=False)

    title = Column(String, nullable=False)

    description = Column(String, nullable=False)

    frame_number = Column(Integer, nullable=True)

    image_path = Column(String, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    job = relationship(
        "Job",
        back_populates="alerts",
    )


class EmailRole(str, Enum):
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"

