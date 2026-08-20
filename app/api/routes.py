# backend/app/api/routes.py

import asyncio
import json
import os
import queue
import shutil
import threading
import time as _time
import urllib.parse
import uuid
from datetime import datetime
from enum import Enum

import cv2
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, EmailStr
from sqlalchemy.orm import Session

from app.auth.jwt import verify_token
from app.auth.models import User
from app.auth.permissions import (
    get_job_for_read,
    get_job_for_update,
    require_operator,
    require_viewer,
)
from app.auth.repository import AuthRepository
from app.db.database import SessionLocal
from app.db.models import Alert, Job, Plate
from app.services.job_manager import process_job

router = APIRouter()

MEDIA_DIR = "media/videos"
FRAMES_DIR = "media/frames"
os.makedirs(MEDIA_DIR, exist_ok=True)
os.makedirs(FRAMES_DIR, exist_ok=True)

# Global registry for live camera streams: job_id -> latest-frame queue.
active_frame_queues: dict[str, queue.Queue] = {}


class AnalysisConfigRequest(BaseModel):
    vehicle: bool = True
    plate: bool = True
    pedestrian: bool = False


class ROILineRequest(BaseModel):
    job_id: str
    roi_coords: list[list[int]] | None = None  # [[x1,y1], [x2,y2], ...]
    line_coords: list[int] | None = None  # [x1, y1, x2, y2]
    line_distance_meters: float | None = None


class CameraCreateRequest(BaseModel):
    username: str
    password: str
    ip_address: str
    path: str = "/h264"
    name: str | None = None

    analysis_config: AnalysisConfigRequest = AnalysisConfigRequest()

    pedestrian_threshold: int = 10


class CameraStartRequest(BaseModel):
    roi_coords: list[list[int]] | None = None
    line_coords: list[int] | None = None
    line_distance_meters: float | None = None


class AlertResponse(BaseModel):
    id: int
    job_id: str
    alert_type: str
    title: str
    description: str
    frame_number: int | None
    image_path: str | None
    created_at: str | None



class EmailRole(str, Enum):
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"



def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _process_camera_job_with_queue(job_id: str, frame_queue: queue.Queue):
    try:
        process_job(job_id, frame_queue=frame_queue)
    finally:
        active_frame_queues.pop(job_id, None)


def _build_rtsp_url(username: str, password: str, ip_address: str, path: str) -> str:
    normalized_path = path if path.startswith("/") else f"/{path}"
    safe_password = urllib.parse.quote(password)
    return f"rtsp://{username}:{safe_password}@{ip_address}{normalized_path}"


def _capture_first_frame(source: str, output_path: str) -> bool:
    if source.startswith("rtsp://"):
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
            "rtsp_transport;tcp|timeout;5000000|reorder_queue_size;100|buffer_size;1024000"
        )
        cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG)
    else:
        cap = cv2.VideoCapture(source)

    ret, frame = cap.read()
    cap.release()

    if not ret:
        return False

    cv2.imwrite(output_path, frame)
    return True


@router.post("/upload-video")
def upload_video(
    file: UploadFile = File(...),
    analysis_config: str = Form(...),
    pedestrian_threshold: int = Form(10),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_operator),
):
    job_id = str(uuid.uuid4())
    analysis = json.loads(analysis_config)

    # Validation
    if analysis.get("plate") and not analysis.get("vehicle"):
        raise HTTPException(
            status_code=400, detail="Plate analysis requires vehicle analysis."
        )
    video_filename = f"{job_id}.mp4"
    video_path = os.path.join(MEDIA_DIR, video_filename)

    with open(video_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    new_job = Job(
        job_id=job_id,
        owner_id=current_user.id,
        video_path=video_path,
        status="uploaded",
        analysis_config=analysis,
        pedestrian_threshold=pedestrian_threshold,
    )

    db.add(new_job)
    db.commit()
    db.refresh(new_job)

    return {"job_id": new_job.job_id, "status": new_job.status}


@router.get("/job/{job_id}/first-frame")
def get_first_frame(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_viewer),
):
    """Get first frame of video for ROI/line selection"""
    job = get_job_for_read(db, job_id)
    if not job:
        return {"error": "Job not found"}

    frame_path = os.path.join(FRAMES_DIR, f"{job_id}_first_frame.jpg")

    # Extract first frame if not exists
    if not os.path.exists(frame_path):
        if not job.video_path:
            return {"error": "No video source found"}

        if not _capture_first_frame(job.video_path, frame_path):
            return {"error": "Could not read video"}

    return FileResponse(frame_path, media_type="image/jpeg")


@router.post("/job/set-roi-line")
def set_roi_line(
    request: ROILineRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_operator),
):
    """Set ROI and counting line coordinates and start processing"""
    job = get_job_for_update(
        db,
        request.job_id,
        current_user,
    )
    if not job:
        return {"error": "Job not found"}

    # Store coordinates as JSON
    if request.roi_coords:
        job.roi_coords = json.dumps(request.roi_coords)
    if request.line_coords:
        job.line_coords = json.dumps(request.line_coords)
    if request.line_distance_meters is not None:
        job.line_distance_meters = request.line_distance_meters

    job.status = "pending"
    db.commit()

    # Start processing in background
    background_tasks.add_task(process_job, request.job_id)

    return {
        "job_id": job.job_id,
        "status": job.status,
        "message": "Processing started with ROI and line",
    }


@router.get("/job/{job_id}")
def get_job_status(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_viewer),
):
    job = get_job_for_read(db, job_id)
    if not job:
        return {"error": "Job not found"}

    return {
        "job_id": job.job_id,
        "status": job.status,
        "job_type": job.job_type,
        "is_live": job.is_live,
        "live_frame": (
            f"media/frames/{job_id}_live.jpg"
            if os.path.exists(os.path.join(FRAMES_DIR, f"{job_id}_live.jpg"))
            else None
        ),
    }


@router.get("/jobs")
def list_all_jobs(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_viewer),
):
    """List all jobs with their status"""
    jobs = db.query(Job).order_by(Job.created_at.desc()).all()

    return {
        "total": len(jobs),
        "jobs": [
            {
                "job_id": job.job_id,
                "status": job.status,
                "video_path": job.video_path,
                "processed_video_path": job.processed_video_path,
                "created_at": job.created_at.isoformat() if job.created_at else None,
                "roi_coords": job.roi_coords,
                "line_coords": job.line_coords,
                "job_type": job.job_type,
                "is_live": job.is_live,
                "camera_rtsp_url": job.camera_rtsp_url,
            }
            for job in jobs
        ],
    }


@router.get("/job/{job_id}/results")
def get_job_results(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_viewer),
):
    job = get_job_for_read(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    alerts = (
        db.query(Alert)
        .filter(Alert.job_id == job_id)
        .order_by(Alert.created_at.desc())
        .all()
    )

    plates = (
        db.query(Plate)
        .filter(Plate.job_id == job_id)
        .order_by(Plate.track_id.asc())
        .all()
    )

    response = {
        "job_id": job_id,
        "status": job.status,
        "processed_video": job.processed_video_path,
        "total_plates": len(plates),
        "plates": [
            {
                "plate_text": plate.plate_text,
                "confidence": plate.best_confidence,
                "bbox_confidence": plate.bbox_confidence,
                "image_path": plate.best_image_path,
                "vehicle_type": plate.vehicle_type,
                "vehicle_confidence": plate.vehicle_confidence,
                "vehicle_image_path": plate.vehicle_image_path,
                "track_id": plate.track_id,
                "frame_number": plate.frame_number,
                "speed_kmh": plate.speed_kmh,
                "detected_at": (
                    plate.detected_at.strftime("%d-%m-%Y %H:%M:%S")
                    if plate.detected_at
                    else None
                ),
                # Per-pipeline OCR results
                "plate_text_highres": plate.plate_text_highres,
                "ocr_conf_highres": plate.ocr_conf_highres,
                "plate_text_lowres": plate.plate_text_lowres,
                "ocr_conf_lowres": plate.ocr_conf_lowres,
            }
            for plate in plates
        ],
        "total_alerts": len(alerts),
        "alerts": [
            {
                "id": alert.id,
                "alert_type": alert.alert_type,
                "title": alert.title,
                "description": alert.description,
                "frame_number": alert.frame_number,
                "image_path": alert.image_path,
                "created_at": (
                    alert.created_at.strftime("%d-%m-%Y %H:%M:%S")
                    if alert.created_at
                    else None
                ),
            }
            for alert in alerts
        ],
    }

    if job.status not in {"completed", "stopped"}:
        response["message"] = "Live partial detections"

    return response


@router.post("/camera-job/create")
def create_camera_job(
    request: CameraCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_operator),
):
    rtsp_url = _build_rtsp_url(
        request.username, request.password, request.ip_address, request.path
    )
    job_id = str(uuid.uuid4())

    camera_config = {
        "name": request.name or request.ip_address,
        "ip_address": request.ip_address,
        "path": request.path,
        "username": request.username,
    }

    analysis = request.analysis_config.model_dump()

    if analysis["plate"] and not analysis["vehicle"]:
        raise HTTPException(
            status_code=400, detail="Plate analysis requires vehicle analysis."
        )

    new_job = Job(
        job_id=job_id,
        owner_id=current_user.id,
        video_path="",
        status="uploaded",
        job_type="camera_stream",
        camera_rtsp_url=rtsp_url,
        camera_config=json.dumps(camera_config),
        is_live="false",
        analysis_config=analysis,
        pedestrian_threshold=request.pedestrian_threshold,
    )

    db.add(new_job)
    db.commit()
    db.refresh(new_job)

    return {
        "job_id": new_job.job_id,
        "status": new_job.status,
        "job_type": new_job.job_type,
    }


@router.get("/camera-job/{job_id}/first-frame")
def get_camera_first_frame(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_viewer),
):

    job = get_job_for_read(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.job_type != "camera_stream":
        raise HTTPException(status_code=400, detail="Not a camera stream job")
    if not job.camera_rtsp_url:
        raise HTTPException(status_code=400, detail="Camera RTSP URL is missing")

    frame_path = os.path.join(FRAMES_DIR, f"{job_id}_first_frame.jpg")
    if not _capture_first_frame(job.camera_rtsp_url, frame_path):
        raise HTTPException(status_code=500, detail="Could not read camera stream")

    return FileResponse(frame_path, media_type="image/jpeg")


@router.post("/camera-job/{job_id}/start")
def start_camera_job(
    job_id: str,
    request: CameraStartRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_operator),
):
    job = get_job_for_update(
        db,
        job_id,
        current_user,
    )

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.job_type != "camera_stream":
        raise HTTPException(status_code=400, detail="Not a camera stream job")

    if request.roi_coords:
        job.roi_coords = json.dumps(request.roi_coords)
    if request.line_coords:
        job.line_coords = json.dumps(request.line_coords)
    if request.line_distance_meters is not None:
        job.line_distance_meters = request.line_distance_meters

    job.status = "pending"
    job.is_live = "true"
    job.stream_started_at = datetime.utcnow()
    db.commit()

    frame_q = queue.Queue(maxsize=2)
    active_frame_queues[job_id] = frame_q

    thread = threading.Thread(
        target=_process_camera_job_with_queue,
        args=(job_id, frame_q),
        daemon=True,
        name=f"pipeline-{job_id}",
    )
    thread.start()

    return {
        "job_id": job.job_id,
        "status": job.status,
        "is_live": job.is_live,
        "message": "Live camera processing started",
    }


@router.post("/camera-job/{job_id}/stop")
def stop_camera_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_operator),
):
    job = get_job_for_update(
        db,
        job_id,
        current_user,
    )

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.job_type != "camera_stream":
        raise HTTPException(status_code=400, detail="Not a camera stream job")

    job.is_live = "false"
    if job.status in {"processing", "pending"}:
        job.status = "stopped"
    db.commit()
    active_frame_queues.pop(job_id, None)

    _time.sleep(1.5)

    plates = (
        db.query(Plate)
        .filter(Plate.job_id == job_id)
        .order_by(Plate.track_id.asc())
        .all()
    )

    return {
        "job_id": job.job_id,
        "status": job.status,
        "is_live": job.is_live,
        "message": "Stop signal sent",
        "total_plates": len(plates),
        "plates": [
            {
                "plate_text": plate.plate_text,
                "confidence": plate.best_confidence,
                "bbox_confidence": plate.bbox_confidence,
                "image_path": plate.best_image_path,
                "vehicle_type": plate.vehicle_type,
                "vehicle_confidence": plate.vehicle_confidence,
                "vehicle_image_path": plate.vehicle_image_path,
                "track_id": plate.track_id,
                "frame_number": plate.frame_number,
                # Per-pipeline OCR results
                "plate_text_highres": plate.plate_text_highres,
                "ocr_conf_highres": plate.ocr_conf_highres,
                "plate_text_lowres": plate.plate_text_lowres,
                "ocr_conf_lowres": plate.ocr_conf_lowres,
            }
            for plate in plates
        ],
    }


@router.get("/camera-job/{job_id}/live-frame")
def get_camera_live_frame(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_viewer),
):
    job = get_job_for_read(db, job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail="Job not found.",
        )

    live_frame_path = os.path.join(
        FRAMES_DIR,
        f"{job_id}_live.jpg",
    )

    if not os.path.exists(live_frame_path):
        raise HTTPException(
            status_code=404,
            detail="Live frame not available yet.",
        )

    return FileResponse(
        live_frame_path,
        media_type="image/jpeg",
    )


@router.websocket("/ws/camera-job/{job_id}/live")
async def camera_live_ws(websocket: WebSocket, job_id: str):

    db = SessionLocal()

    # ---------------------------------------------------
    # STEP 1: Read JWT Token
    # ---------------------------------------------------
    token = websocket.query_params.get("token")

    if token is None:
        await websocket.close(code=1008)
        db.close()
        return
    # ---------------------------------------------------
    # STEP 2: Verify JWT
    # ---------------------------------------------------
    try:
        payload = verify_token(token)

        if payload is None:
            raise HTTPException(
                status_code=401,
                detail="Invalid or expired access token.",
            )

    except Exception:
        await websocket.send_json(
            {
                "type": "error",
                "message": "Authentication failed. Please login again.",
            }
        )
        await websocket.close(code=1008)
        db.close()
        return

    # ---------------------------------------------------
    # STEP 3: Load User
    # ---------------------------------------------------
    repository = AuthRepository(db)

    user = repository.get_user_by_id(int(payload["sub"]))

    if user is None:
        await websocket.close(code=1008)
        db.close()
        return

    if not user.is_active:
        await websocket.close(code=1008)
        db.close()
        return

    # ---------------------------------------------------
    # STEP 4: Check Job Ownership
    # ---------------------------------------------------
    try:
        job = get_job_for_read(db, job_id)

    except HTTPException as exc:
        await websocket.send_json(
            {
                "type": "error",
                "message": exc.detail,
            }
        )
        await websocket.close(code=1008)
        db.close()
        return

    # ---------------------------------------------------
    # STEP 5: Accept Connection
    # ---------------------------------------------------
    await websocket.accept()

    # ---------------------------------------------------
    # Wait for the processing thread to register its queue
    # ---------------------------------------------------
    frame_queue = None

    for _ in range(50):  # Wait up to 5 seconds
        frame_queue = active_frame_queues.get(job_id)

        if frame_queue is not None:
            break

        await asyncio.sleep(0.1)

    if frame_queue is None:
        await websocket.send_json(
            {
                "type": "error",
                "message": "Live stream queue not available.",
            }
        )
        await websocket.close(code=1011)
        db.close()
        return
    status_check_counter = 0

    try:
        while True:
            status_check_counter += 1
            if status_check_counter >= 25:
                status_check_counter = 0
                db.expire_all()
                job = db.query(Job).filter(Job.job_id == job_id).first()
                if not job:
                    await websocket.send_json({"type": "done", "status": "unknown"})
                    break
                if job.job_type != "camera_stream":
                    await websocket.send_json(
                        {"type": "error", "message": "Not a camera stream job"}
                    )
                    break
                if job.status in {"completed", "failed", "stopped"}:
                    await websocket.send_json({"type": "done", "status": job.status})
                    break

            try:
                frame = frame_queue.get_nowait()
                ok, encoded = cv2.imencode(
                    ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70]
                )
                if ok:
                    await websocket.send_bytes(encoded.tobytes())
            except queue.Empty:
                await asyncio.sleep(0.04)
                continue
            await asyncio.sleep(0.01)

    except WebSocketDisconnect:
        pass
    finally:
        db.close()


@router.delete("/job/{job_id}")
def delete_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_operator),
):
    job = get_job_for_update(
        db,
        job_id,
        current_user,
    )

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Prevent deleting running jobs
    if job.status in {"pending", "processing"}:
        raise HTTPException(
            status_code=400,
            detail="Stop the job before deleting it.",
        )

    # -----------------------------
    # Delete plate images
    # -----------------------------
    for plate in job.plates:
        for image_path in [
            plate.best_image_path,
            plate.vehicle_image_path,
        ]:
            if image_path:
                try:
                    if os.path.exists(image_path):
                        os.remove(image_path)
                except Exception as e:
                    print(f"Failed to delete image {image_path}: {e}")

    # -----------------------------
    # Delete alert images
    # -----------------------------
    for alert in job.alerts:
        if alert.image_path:
            try:
                if os.path.exists(alert.image_path):
                    os.remove(alert.image_path)
            except Exception as e:
                print(f"Failed to delete alert image {alert.image_path}: {e}")

    # -----------------------------
    # Delete uploaded video
    # -----------------------------
    if job.video_path:
        try:
            if os.path.exists(job.video_path):
                os.remove(job.video_path)
        except Exception as e:
            print(f"Failed to delete video: {e}")

    # -----------------------------
    # Delete processed video
    # -----------------------------
    if job.processed_video_path:
        try:
            if os.path.exists(job.processed_video_path):
                os.remove(job.processed_video_path)
        except Exception as e:
            print(f"Failed to delete processed video: {e}")

    # -----------------------------
    # Delete ROI frame
    # -----------------------------
    first_frame = os.path.join(
        FRAMES_DIR,
        f"{job_id}_first_frame.jpg",
    )

    if os.path.exists(first_frame):
        try:
            os.remove(first_frame)
        except Exception:
            pass

    # -----------------------------
    # Delete live frame
    # -----------------------------
    live_frame = os.path.join(
        FRAMES_DIR,
        f"{job_id}_live.jpg",
    )

    if os.path.exists(live_frame):
        try:
            os.remove(live_frame)
        except Exception:
            pass

    # -----------------------------
    # Remove active queue
    # -----------------------------
    active_frame_queues.pop(job_id, None)

    # -----------------------------
    # Delete database record
    # -----------------------------
    db.delete(job)
    db.commit()

    return {
        "message": "Job deleted successfully",
        "job_id": job_id,
    }
 