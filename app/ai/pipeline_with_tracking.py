# backend/app/ai/pipeline_with_tracking.py

import os
import re
import cv2
import json
import queue
import threading
import numpy as np
import subprocess
import time
from datetime import datetime

from sympy import fps

from app.ai.plate_detector import detect_plates
from app.ai.ocr import run_paddleocr
from app.db.models import Plate, Job
from app.ai.vehicle_detector import detect_vehicles
from app.ai.tracker import VehicleTracker, LineCrossCounter
from app.ai.utils import normalize_plate
from app.ai.pedestrian_detector import detect_pedestrians
from app.services.alert_service import create_alert
from app.ai.colors import (
    VEHICLE_COLOR,
    PLATE_COLOR,
    ALERT_COLOR,
    LINE_COLOR,
    ROI_COLOR,
    OUTSIDE_COLOR,
)

OUTPUT_DIR = "media/outputs"
PROCESSED_DIR = "media/processed"
DEBUG_DIR = "media/debug"

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(PROCESSED_DIR, exist_ok=True)
os.makedirs(DEBUG_DIR, exist_ok=True)

MIN_OCR_CONF = 0.20  # Lowered to capture plates earlier
DEBUG_OCR = True  # Enable OCR debugging


def _is_rtsp_source(source: str) -> bool:
    return isinstance(source, str) and source.lower().startswith("rtsp://")


def _open_capture_with_retry(source: str, retries: int = 5, retry_delay: float = 1.0):
    is_rtsp = _is_rtsp_source(source)
    if is_rtsp:
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
            "rtsp_transport;tcp"
            "|timeout;3000000"
            "|stimeout;3000000"
            "|reorder_queue_size;0"
            "|buffer_size;1048576"
            "|fflags;nobuffer+discardcorrupt"
            "|flags;low_delay"
            "|thread_type;slice"
            "|threads;1"
        )
        params = [
            cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
            8000,
            cv2.CAP_PROP_READ_TIMEOUT_MSEC,
            8000,
        ]
    else:
        params = []

    def _open(src, holder):
        try:
            if _is_rtsp_source(src):
                c = cv2.VideoCapture(src, cv2.CAP_FFMPEG, params)
            else:
                c = cv2.VideoCapture(src)
            c.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            holder[0] = c
        except Exception as exc:
            print(f"[ERROR] VideoCapture open exception: {exc}")

    for attempt in range(retries):
        cap_holder = [None]
        t = threading.Thread(
            target=_open, args=(source, cap_holder), daemon=True, name="cap_open"
        )
        t.start()
        t.join(timeout=10.0)

        if t.is_alive():
            print(
                f"[WARN] VideoCapture open timed out on attempt {attempt + 1}/{retries}"
            )
            time.sleep(retry_delay)
            continue

        cap = cap_holder[0]

        if cap is not None and cap.isOpened():
            for _ in range(3):
                cap.grab()
            return cap

        if cap is not None:
            cap.release()

        time.sleep(retry_delay)

    return None


def _safe_cap_read(cap, timeout_sec: float = 5.0):
    """Read a frame with a hard timeout to prevent cap.read() hangs."""
    result = [False, None]

    def _read():
        try:
            result[0], result[1] = cap.read()
        except Exception:
            # Capture may already be released by reconnect logic.
            result[0], result[1] = False, None

    read_thread = threading.Thread(target=_read, daemon=True, name="_read")
    read_thread.start()
    read_thread.join(timeout=timeout_sec)

    if read_thread.is_alive():
        return False, None, True

    return result[0], result[1], False


def is_inside(inner, outer):
    """Check if inner bbox is inside outer bbox"""
    ix1, iy1, ix2, iy2 = inner
    ox1, oy1, ox2, oy2 = outer
    return ix1 >= ox1 and iy1 >= oy1 and ix2 <= ox2 and iy2 <= oy2


def point_in_polygon(point, polygon):
    """Check if point is inside polygon (ROI check)"""
    x, y = point
    polygon = np.array(polygon, dtype=np.int32)
    return cv2.pointPolygonTest(polygon, (float(x), float(y)), False) >= 0


FLUSH_EVERY_N_FRAMES = 30  # periodic DB flush interval


def _smart_upsert(db, job_id: str, track_id: int, state: dict):
    """
    Single DB row per track_id. Only writes fields that improved.
    state keys: vehicle_type, vehicle_conf, vehicle_image,
                bbox_conf, plate_text, ocr_conf, plate_image,
                highres, lowres,
                frame_number, detected_at
    """
    existing = (
        db.query(Plate)
        .filter(Plate.job_id == job_id, Plate.track_id == track_id)
        .first()
    )

    # --- Fixed filenames per track (overwrite, never accumulate) ---
    vehicle_img_path = f"{OUTPUT_DIR}/{job_id}_track{track_id}_vehicle.jpg"
    plate_img_path = f"{OUTPUT_DIR}/{job_id}_track{track_id}_plate.jpg"

    if existing is None:
        # First time seeing this track — write everything we have
        if state.get("vehicle_image") is not None:
            cv2.imwrite(vehicle_img_path, state["vehicle_image"])
        if state.get("plate_image") is not None:
            cv2.imwrite(plate_img_path, state["plate_image"])

        hr = state.get("highres")
        lr = state.get("lowres")

        record = Plate(
            job_id=job_id,
            track_id=track_id,
            plate_text=state.get("plate_text"),
            best_confidence=state.get("ocr_conf"),
            bbox_confidence=state.get("bbox_conf"),
            best_image_path=(
                plate_img_path if state.get("plate_image") is not None else None
            ),
            vehicle_type=state.get("vehicle_type"),
            vehicle_confidence=state.get("vehicle_conf"),
            vehicle_image_path=(
                vehicle_img_path if state.get("vehicle_image") is not None else None
            ),
            frame_number=state.get("frame_number"),
            crossed_line=1,
            detected_at=state.get("detected_at"),
            # Per-pipeline columns
            plate_text_highres=hr["text"] if hr else None,
            ocr_conf_highres=hr["confidence"] if hr else None,
            plate_text_lowres=lr["text"] if lr else None,
            ocr_conf_lowres=lr["confidence"] if lr else None,
        )
        db.add(record)
        db.commit()
        return

    # --- Existing row: only update fields that improved ---
    changed = False

    # Vehicle image: update if new vehicle_conf is higher
    if (state.get("vehicle_conf") or 0.0) > (existing.vehicle_confidence or 0.0):
        if state.get("vehicle_image") is not None:
            cv2.imwrite(vehicle_img_path, state["vehicle_image"])
        existing.vehicle_type = state.get("vehicle_type")
        existing.vehicle_confidence = state.get("vehicle_conf")
        existing.vehicle_image_path = vehicle_img_path
        changed = True

    # High-res pipeline — update independently if confidence improved
    hr = state.get("highres")
    if hr and (hr["confidence"] > (existing.ocr_conf_highres or 0.0)):
        existing.plate_text_highres = hr["text"]
        existing.ocr_conf_highres = hr["confidence"]
        changed = True

    # Low-res pipeline — update independently if confidence improved
    lr = state.get("lowres")
    if lr and (lr["confidence"] > (existing.ocr_conf_lowres or 0.0)):
        existing.plate_text_lowres = lr["text"]
        existing.ocr_conf_lowres = lr["confidence"]
        changed = True

    # Legacy plate_text / best_confidence — mirror whichever pipeline is currently best
    if (state.get("ocr_conf") or 0.0) > (existing.best_confidence or 0.0):
        if state.get("plate_image") is not None:
            cv2.imwrite(plate_img_path, state["plate_image"])
        existing.plate_text = state.get("plate_text")
        existing.best_confidence = state.get("ocr_conf")
        existing.bbox_confidence = state.get("bbox_conf")
        existing.best_image_path = plate_img_path
        existing.frame_number = state.get("frame_number")
        changed = True

    if changed:
        db.commit()


def run_pipeline_with_tracking(
    job_id: str,
    video_path: str,
    db,
    frame_queue: queue.Queue | None = None,
    analysis_config: dict | None = None,
):
    """Pipeline with ROI filtering and line crossing detection"""

    if analysis_config is None:
        analysis_config = {
            "vehicle": True,
            "plate": True,
            "pedestrian": False,
        }
    vehicle_enabled = analysis_config.get("vehicle", True)
    plate_enabled = analysis_config.get("plate", True)
    pedestrian_enabled = analysis_config.get("pedestrian", False)

    # Get job to retrieve ROI and line coords
    job = db.query(Job).filter(Job.job_id == job_id).first()
    if not job:
        raise Exception("Job not found")

    # Parse ROI and line coordinates
    roi_polygon = None
    if job.roi_coords:
        try:
            roi_polygon = json.loads(job.roi_coords)
        except:
            pass  # invalid ROI, skip

    line_counter = None
    if job.line_coords:
        try:
            line_coords = json.loads(job.line_coords)
            if len(line_coords) == 4:
                line_counter = LineCrossCounter(
                    (line_coords[0], line_coords[1]), (line_coords[2], line_coords[3])
                )
        except:
            pass  # invalid line, skip

    cap = _open_capture_with_retry(video_path)
    if cap is None or not cap.isOpened():
        raise Exception("Error opening video file")

    fps = cap.get(cv2.CAP_PROP_FPS)
    if not fps or fps <= 0:
        fps = 20.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if width <= 0 or height <= 0:
        raise Exception("Invalid stream/video dimensions")

    # Create ROI mask if available
    roi_mask = None
    if roi_polygon:
        roi_mask = np.zeros((height, width), dtype=np.uint8)
        cv2.fillPoly(roi_mask, [np.array(roi_polygon, dtype=np.int32)], 255)

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total_frames <= 0 and not _is_rtsp_source(video_path):
        # Metadata missing — count quickly without decoding frames
        print("Counting frames...", flush=True)
        while cap.grab():
            total_frames += 1
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)  # rewind to start
    print(f"Total frames: {total_frames if total_frames > 0 else '?'}", flush=True)

    detection_side = None
    if line_counter:
        reference_point = (width // 2, height - 1)
        side = line_counter._compute_side(reference_point)
        if side != 0:
            detection_side = side

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    output_video_path = f"{PROCESSED_DIR}/{job_id}_processed.mp4"
    out = cv2.VideoWriter(output_video_path, fourcc, fps, (width, height))

    if not out.isOpened():
        raise Exception(f"Failed to create VideoWriter")

    # Initialize tracker
    tracker = VehicleTracker(max_disappeared=30, max_distance=80)

    # In-memory best state per track — flushed to DB periodically
    # Structure: { track_id: { vehicle_conf, vehicle_image, vehicle_type,
    #                          bbox_conf, plate_text, ocr_conf, plate_image,
    #                          frame_number, detected_at, dirty } }
    best_state: dict[int, dict] = {}
    last_flush_frame = 0

    track_id_remap = {}  # {raw_track_id: sequential_1based_id}
    next_display_id = [1]

    def _get_display_id(raw_id: int) -> int:
        if raw_id not in track_id_remap:
            track_id_remap[raw_id] = next_display_id[0]
            next_display_id[0] += 1
        return track_id_remap[raw_id]

    frame_count = 0
    # Pedestrian Alert State

    pedestrian_alert_active = False

    last_pedestrian_alert_frame = -1

    ALERT_COOLDOWN_FRAMES = int(fps * 10)

    #

    crossed_track_ids = set()  # Track IDs that crossed the line
    live_frame_path = os.path.join("media", "frames", f"{job_id}_live.jpg")
    is_camera_stream = job.job_type == "camera_stream"
    consecutive_read_failures = 0
    consecutive_timeouts = 0
    expected_h, expected_w = None, None

    while True:
        if is_camera_stream and frame_count > 0 and frame_count % 5 == 0:
            db.expire_all()  # force SQLAlchemy to re-read from DB, not cache
            fresh_job = db.query(Job).filter(Job.job_id == job_id).first()
            if (
                fresh_job is None
                or fresh_job.is_live != "true"
                or fresh_job.status == "stopped"
            ):
                job = fresh_job
                break
            job.last_frame_processed_at = datetime.utcnow()
            db.commit()

        if cap is None or not cap.isOpened():
            cap = _open_capture_with_retry(video_path, retries=5, retry_delay=1.0)
            if cap is None or not cap.isOpened():
                if not is_camera_stream:
                    break
                time.sleep(5.0)
                continue

        ret, frame, timed_out = _safe_cap_read(cap, timeout_sec=10.0)

        if timed_out:
            consecutive_timeouts += 1
            if consecutive_timeouts < 2:
                # Single blip - retry once before reconnecting
                time.sleep(1.0)
                continue

            # 2 consecutive timeouts - do a real reconnect
            consecutive_timeouts = 0
            old_cap = cap
            cap = None
            time.sleep(3.0)
            old_cap.release()
            time.sleep(1.0)
            new_cap = _open_capture_with_retry(video_path, retries=3, retry_delay=2.0)
            cap = new_cap
            if cap is None or not cap.isOpened():
                if not is_camera_stream:
                    break
            consecutive_read_failures = 0
            continue

        if not ret or frame is None:
            if not is_camera_stream:
                break

            consecutive_read_failures += 1
            if consecutive_read_failures > 2:
                old_cap = cap
                time.sleep(2.0)
                old_cap.release()
                time.sleep(1.5)
                new_cap = _open_capture_with_retry(
                    video_path, retries=3, retry_delay=2.0
                )
                cap = new_cap
                if cap is None or not cap.isOpened():
                    break
                consecutive_read_failures = 0
            time.sleep(0.05)
            continue

        if expected_h is None:
            expected_h, expected_w = frame.shape[0], frame.shape[1]

        if frame.shape[0] != expected_h or frame.shape[1] != expected_w:
            continue

        consecutive_read_failures = 0
        consecutive_timeouts = 0

        frame_count += 1
        if total_frames > 0:
            print(f"\rPROCESSED {frame_count}/{total_frames}", end="", flush=True)
        else:
            print(f"\rPROCESSED {frame_count}", end="", flush=True)
        display_frame = frame.copy()

        # Draw ROI polygon if exists
        if roi_polygon:
            cv2.polylines(
                display_frame,
                [np.array(roi_polygon, dtype=np.int32)],
                True,
                ROI_COLOR,
                2,
            )

        # Draw counting line if exists
        if line_counter:
            cv2.line(
                display_frame,
                tuple(map(int, line_counter.p1)),
                tuple(map(int, line_counter.p2)),
                LINE_COLOR,
                3,
            )

        # Detect
        vehicle_detections = []
        if vehicle_enabled:
            vehicle_detections = detect_vehicles(frame)

        # Convert to tracker format
        detections_for_tracking = []
        for v in vehicle_detections:
            vx1, vy1, vx2, vy2 = v["bbox"]
            conf = v["confidence"]
            detections_for_tracking.append([vx1, vy1, vx2, vy2, conf, 0])

        # Update tracker
        tracked_vehicles = []

        if vehicle_enabled:
            tracked_vehicles = tracker.update(detections_for_tracking)
        # Process tracked vehicles
        for tracked in tracked_vehicles:
            vx1, vy1, vx2, vy2, track_id, _ = tracked
            vx1, vy1, vx2, vy2 = map(int, [vx1, vy1, vx2, vy2])

            # Get centroid
            cx, cy = (vx1 + vx2) // 2, (vy1 + vy2) // 2

            # Check if in ROI
            in_roi = True
            if roi_mask is not None:
                in_roi = roi_mask[cy, cx] > 0

            # Check line crossing
            crossed = False
            current_side = None
            if line_counter and in_roi:
                prev_centroid = tracker.get_previous_centroid(track_id)
                crossed = line_counter.check_crossing(track_id, (cx, cy), prev_centroid)
                if crossed:
                    crossed_track_ids.add(track_id)
                current_side = line_counter._compute_side((cx, cy))

            # Only process vehicles that are in ROI (and crossed if line exists)
            should_process = in_roi
            if line_counter:
                on_detection_side = (
                    detection_side is not None and current_side == detection_side
                )
                should_process = should_process and (
                    track_id in crossed_track_ids or on_detection_side
                )

            # Draw vehicle box
            color = VEHICLE_COLOR if should_process else OUTSIDE_COLOR
            thickness = 3 if crossed else 2
            cv2.rectangle(display_frame, (vx1, vy1), (vx2, vy2), color, thickness)
            cv2.circle(display_frame, (cx, cy), 5, color, -1)

            # Do not allocate remapped IDs here; only plated vehicles should consume IDs.
            label_id = track_id_remap.get(track_id, track_id)
            cv2.putText(
                display_frame,
                f"ID:{label_id}",
                (vx1, max(vy1 - 10, 0)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                color,
                2,
            )

            # Crossing highlight
            if crossed:
                cv2.circle(display_frame, (cx, cy), 30, ALERT_COLOR, 3)

            # Only detect plates for vehicles that should be processed
            if should_process:
                vehicle_crop = frame[vy1:vy2, vx1:vx2]
                display_id = _get_display_id(track_id)

                # --- Get vehicle type from detections ---
                vehicle_type_now = None
                vehicle_conf_now = 0.0
                for v in vehicle_detections:
                    if is_inside([vx1, vy1, vx2, vy2], v["bbox"]):
                        vehicle_type_now = v["label"]
                        vehicle_conf_now = v["confidence"]
                        break

                # --- Initialise state for new track ---
                if display_id not in best_state:
                    best_state[display_id] = {
                        "vehicle_type": vehicle_type_now,
                        "vehicle_conf": vehicle_conf_now,
                        "vehicle_image": vehicle_crop.copy(),
                        "bbox_conf": None,
                        "plate_text": None,  # legacy: best of the two pipelines
                        "ocr_conf": None,  # legacy: best confidence seen
                        "plate_image": None,
                        "highres": None,  # { text, confidence, score } or None
                        "lowres": None,  # { text, confidence, score } or None
                        "frame_number": frame_count,
                        "detected_at": datetime.now(),
                        "dirty": True,
                    }
                else:
                    # Update vehicle image only if this detection is more confident
                    if vehicle_conf_now > (
                        best_state[display_id]["vehicle_conf"] or 0.0
                    ):
                        best_state[display_id]["vehicle_type"] = vehicle_type_now
                        best_state[display_id]["vehicle_conf"] = vehicle_conf_now
                        best_state[display_id]["vehicle_image"] = vehicle_crop.copy()
                        best_state[display_id]["dirty"] = True

                # --- Plate detection ---
                if plate_enabled:
                    plate_detections = detect_plates(vehicle_crop)

                    for det in plate_detections:
                        px1, py1, px2, py2 = det["bbox"]
                        px1 += vx1
                        py1 += vy1
                        px2 += vx1
                        py2 += vy1
                        det_conf = det.get("confidence", 0.0)

                        cv2.rectangle(
                            display_frame, (px1, py1), (px2, py2), PLATE_COLOR, 2
                        )

                        # Skip OCR if this bbox is not better than what we already stored
                        stored_bbox_conf = (
                            best_state[display_id].get("bbox_conf") or 0.0
                        )
                        if det_conf < stored_bbox_conf:
                            display_text = (
                                best_state[display_id].get("plate_text")
                                or f"Plate-{display_id}"
                            )
                            cv2.putText(
                                display_frame,
                                display_text,
                                (px1, max(py1 - 10, 0)),
                                cv2.FONT_HERSHEY_SIMPLEX,
                                0.6,
                                PLATE_COLOR,
                                2,
                            )
                            continue

                        # --- Run OCR ---
                        raw_crop = frame[
                            max(0, py1) : min(frame.shape[0], py2),
                            max(0, px1) : min(frame.shape[1], px2),
                        ]
                        display_text = (
                            best_state[display_id].get("plate_text")
                            or f"Plate-{display_id}"
                        )

                        if raw_crop is not None and raw_crop.size > 0:
                            ocr_result = run_paddleocr(raw_crop)

                            if ocr_result:
                                normalized = normalize_plate(ocr_result["text"])
                                text_final = (
                                    normalized
                                    if normalized
                                    else re.sub(
                                        r"[^A-Za-z0-9]", "", ocr_result["text"].upper()
                                    )
                                )

                                if text_final:
                                    best_candidate = ocr_result
                                    stored_ocr_conf = (
                                        best_state[display_id].get("ocr_conf") or 0.0
                                    )

                                    if best_candidate["confidence"] > stored_ocr_conf:
                                        # Overwrite one best debug image per track
                                        debug_filename = f"{DEBUG_DIR}/{job_id}_track{display_id}_best.jpg"
                                        cv2.imwrite(debug_filename, raw_crop)

                                        best_state[display_id]["plate_text"] = (
                                            best_candidate["text"]
                                        )
                                        best_state[display_id]["ocr_conf"] = (
                                            best_candidate["confidence"]
                                        )
                                        best_state[display_id]["bbox_conf"] = det_conf
                                        best_state[display_id]["plate_image"] = raw_crop
                                        best_state[display_id][
                                            "frame_number"
                                        ] = frame_count
                                        best_state[display_id]["dirty"] = True
                                        display_text = best_candidate["text"]
                                        print(
                                            f"[OCR] Track={display_id} | Plate: {best_candidate['text']} | Conf: {best_candidate['confidence']:.2f}"
                                        )
                            pass  # OCR returned no results (normal for many frames)
                        # raw_crop is empty — skip silently

                    cv2.putText(
                        display_frame,
                        display_text,
                        (px1, max(py1 - 10, 0)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.6,
                        PLATE_COLOR,
                        2,
                    )
        # ← END of `for tracked in tracked_vehicles` loop

        pedestrian_result = None

        if pedestrian_enabled:

            pedestrian_result = detect_pedestrians(
                frame=frame,
                display_frame=display_frame,
                roi_polygon=(
                    np.array(roi_polygon, dtype=np.int32) if roi_polygon else None
                ),
            )

            person_count = pedestrian_result["person_count"]

            threshold = job.pedestrian_threshold

            # ----------------------------------
            # Crowd threshold exceeded
            # ----------------------------------

            if person_count >= threshold:

                can_create_alert = not pedestrian_alert_active or (
                    frame_count - last_pedestrian_alert_frame >= ALERT_COOLDOWN_FRAMES
                )

                if can_create_alert:

                    create_alert(
                        db=db,
                        job_id=job.job_id,
                        alert_type="pedestrian",
                        title="Crowd Threshold Exceeded",
                        description=f"{person_count} persons detected inside ROI",
                        frame=display_frame,
                        frame_number=frame_count,
                    )

                    pedestrian_alert_active = True

                    last_pedestrian_alert_frame = frame_count

            else:

                pedestrian_alert_active = False
        print(
            f"[INFO] Frame {frame_count} | "
            f"Vehicles: {len(tracked_vehicles)} | "
            f"Persons: {pedestrian_result['person_count'] if pedestrian_result else 0}"
        )
        out.write(display_frame)

        # --- Periodic flush every N frames ---
        if frame_count - last_flush_frame >= FLUSH_EVERY_N_FRAMES:
            for tid, state in best_state.items():
                if state.get("dirty"):
                    _smart_upsert(db, job_id, tid, state)
                    state["dirty"] = False
            last_flush_frame = frame_count

        if frame_queue is not None:
            try:
                frame_queue.put_nowait(display_frame.copy())
            except queue.Full:
                pass

        if is_camera_stream and frame_count % 5 == 0:
            cv2.imwrite(live_frame_path, display_frame)

    if cap is not None:
        cap.release()
    out.release()

    print(
        f"[INFO] Processing complete. Frames: {frame_count} | Tracks: {len(best_state)} | Crossed: {len(crossed_track_ids)}"
    )

    # Flush best detection per plate per track to DB
    # Final flush — write every track's best state to DB
    saved_count = 0
    for tid, state in best_state.items():
        _smart_upsert(db, job_id, tid, state)
        saved_count += 1

    print(f"[INFO] Flushed {saved_count} track records to DB (1 row per vehicle)")

    # FFmpeg conversion (skip for stopped camera streams - too slow)
    db.expire_all()
    current_job = db.query(Job).filter(Job.job_id == job_id).first()
    is_stopped = current_job and current_job.status == "stopped"

    if not is_stopped:
        final_output = f"{PROCESSED_DIR}/{job_id}_final.mp4"
        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    output_video_path,
                    "-c:v",
                    "libx264",
                    "-preset",
                    "fast",
                    "-crf",
                    "23",
                    final_output,
                ],
                check=True,
                capture_output=True,
            )
            if current_job:
                current_job.processed_video_path = final_output
        except Exception:
            print("[WARN] FFmpeg conversion failed, using original")
            if current_job:
                current_job.processed_video_path = output_video_path
    else:
        print("[INFO] Job was stopped - skipping FFmpeg conversion")

    if current_job:
        current_job.is_live = "false"
        current_job.last_frame_processed_at = datetime.utcnow()

    db.commit()
    print(
        f"[INFO] Pipeline complete - {saved_count} plates saved, status={current_job.status if current_job else 'unknown'}"
    )
