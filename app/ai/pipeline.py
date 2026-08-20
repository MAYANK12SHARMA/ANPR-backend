# backend/app/ai/pipeline.py

import os
import re
import subprocess
from collections import defaultdict

import cv2

from app.ai.ocr import run_paddleocr
from app.ai.plate_detector import detect_plates
from app.ai.vehicle_detector import detect_vehicles
from app.db.models import Job, Plate

OUTPUT_DIR = "media/outputs"
PROCESSED_DIR = "media/processed"
DEBUG_DIR = "media/debug"

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(PROCESSED_DIR, exist_ok=True)
os.makedirs(DEBUG_DIR, exist_ok=True)

MIN_OCR_CONF = 0.6


def is_inside(inner, outer):
    """Check if inner bbox is inside outer bbox (for plate-vehicle matching)"""
    ix1, iy1, ix2, iy2 = inner
    ox1, oy1, ox2, oy2 = outer
    return ix1 >= ox1 and iy1 >= oy1 and ix2 <= ox2 and iy2 <= oy2


def run_pipeline(job_id: str, video_path: str, db):

    cap = cv2.VideoCapture(video_path)

    if not cap.isOpened():
        raise Exception("Error opening video file")

    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))


    # Use mp4v codec (reliable, will be converted by FFmpeg later)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    output_video_path = f"{PROCESSED_DIR}/{job_id}_processed.mp4"

    out = cv2.VideoWriter(output_video_path, fourcc, fps, (width, height))
    
    if not out.isOpened():
        raise Exception("Failed to create VideoWriter with codec mp4v")

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total_frames <= 0:
        # Metadata missing — count quickly without decoding frames
        print("Counting frames...", flush=True)
        while cap.grab():
            total_frames += 1
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)  # rewind to start
    print(f"Total frames: {total_frames}", flush=True)

    grouped = defaultdict(list)
    frame_count = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        
        frame_count += 1
        print(f"\rPROCESSED {frame_count}/{total_frames}", end='', flush=True)

        vehicle_detections = detect_vehicles(frame)
        
        # Draw vehicle bounding boxes (blue)
        for v in vehicle_detections:
            vx1, vy1, vx2, vy2 = v["bbox"]
            cv2.rectangle(frame, (vx1, vy1), (vx2, vy2), (255, 0, 0), 2)
            cv2.putText(
                frame,
                v["label"],
                (vx1, max(vy1 - 10, 0)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.9,
                (255, 0, 0),
                2
            )
        
        detections = detect_plates(frame)

        for det in detections:
            x1, y1, x2, y2 = det["bbox"]
            det_conf = det.get("confidence", 0.0)
            
            # Match plate to vehicle
            vehicle_type = None
            vehicle_conf = None
            vehicle_crop = None
            for v in vehicle_detections:
                if is_inside([x1, y1, x2, y2], v["bbox"]):
                    vehicle_type = v["label"]
                    vehicle_conf = v["confidence"]
                    # Crop vehicle bbox from original frame
                    vx1, vy1, vx2, vy2 = v["bbox"]
                    vehicle_crop = frame[vy1:vy2, vx1:vx2].copy()
                    break

            # Always draw detection box (like the test script)
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 3)

            # Extract raw crop for OCR
            raw_crop = frame[max(0,y1):min(frame.shape[0],y2), max(0,x1):min(frame.shape[1],x2)]
            
            display_text = "Plate"  # Default fallback
            ocr_success = False

            if raw_crop is not None and raw_crop.size > 0:
                # Save debug image
                debug_filename = f"{DEBUG_DIR}/{job_id}_frame{frame_count}_det{det_conf:.2f}.jpg"
                cv2.imwrite(debug_filename, raw_crop)

                # Run OCR using the new PaddleOCR pipeline
                best = run_paddleocr(raw_crop)

                if best:
                    # best["text"] is already corrected by strict_plate_correction
                    raw_text = best["text"]
                    conf     = best["confidence"]

                    if conf >= MIN_OCR_CONF:
                        # Normalize for DB / display safety
                        text = re.sub(r'[^A-Z0-9]', '', raw_text.upper())

                        if text:
                            display_text = text
                            ocr_success  = True

                            grouped[text].append({
                                "confidence":       conf,
                                "bbox_confidence":  det_conf,
                                "image":            raw_crop,
                                "vehicle_type":     vehicle_type,
                                "vehicle_conf":     vehicle_conf,
                                "vehicle_crop":     vehicle_crop,
                            })

            # Draw text overlay (OCR result or "Plate")
            cv2.putText(
                frame,
                display_text,
                (x1, max(y1 - 10, 0)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 255, 0),
                2
            )

        out.write(frame)

    cap.release()
    out.release()

    print(f"[DEBUG] Video written to: {output_video_path}")
    print(f"[DEBUG] File size: {os.path.getsize(output_video_path) if os.path.exists(output_video_path) else 'FILE NOT FOUND'}")

    # Re-encode with FFmpeg for browser compatibility (if available)
    final_output_path = output_video_path
    
    if not os.path.exists(output_video_path) or os.path.getsize(output_video_path) == 0:
        raise Exception(f"VideoWriter failed to create output file: {output_video_path}")
    
    try:
        temp_path = f"{PROCESSED_DIR}/{job_id}_temp.mp4"
        os.rename(output_video_path, temp_path)
        
        # Hardcoded FFmpeg path (WinGet installation)
        FFMPEG_PATH = r"C:\Users\aanis\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.0.1-full_build\bin\ffmpeg.exe"
        
        # Use FFmpeg to convert to H.264
        result = subprocess.run([
            FFMPEG_PATH, "-i", temp_path,
            "-c:v", "libx264", "-preset", "fast",
            "-crf", "23", "-pix_fmt", "yuv420p",
            final_output_path, "-y"
        ], capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"[ERROR] FFmpeg failed: {result.stderr}")
            # Restore original file
            if os.path.exists(temp_path):
                os.rename(temp_path, output_video_path)
            print("Warning: FFmpeg conversion failed. Using original video.")
        else:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            print(f"[SUCCESS] FFmpeg conversion complete: {final_output_path}")
            
    except FileNotFoundError as e:
        # FFmpeg not available, restore temp file if it exists
        if 'temp_path' in locals() and os.path.exists(temp_path):
            os.rename(temp_path, output_video_path)
        print(f"Warning: FFmpeg not available: {e}. Using original video.")
    except Exception as e:
        # Any other error, restore original if temp exists
        if 'temp_path' in locals() and os.path.exists(temp_path):
            os.rename(temp_path, output_video_path)
        print(f"Warning: FFmpeg error: {e}. Using original video.")

    # 🔥 Save processed video path in DB (without 'media/' prefix for /media mount)
    job = db.query(Job).filter(Job.job_id == job_id).first()
    if job:
        # Store path relative to media directory
        job.processed_video_path = final_output_path.replace("media/", "", 1)
        db.commit()

    # 🔥 Insert final unique plates
    for plate_text, entries in grouped.items():
        best_entry = max(entries, key=lambda x: x["confidence"])

        # Safe filename
        safe_text = re.sub(r'[^A-Z0-9]', '', plate_text)

        output_path = f"{OUTPUT_DIR}/{job_id}_{safe_text}.jpg"
        cv2.imwrite(output_path, best_entry["image"])
        
        # Save vehicle crop image if available
        vehicle_image_path = None
        if best_entry.get("vehicle_crop") is not None:
            vehicle_output_path = f"{OUTPUT_DIR}/{job_id}_{safe_text}_vehicle.jpg"
            cv2.imwrite(vehicle_output_path, best_entry["vehicle_crop"])
            vehicle_image_path = vehicle_output_path.replace("media/", "", 1)

        final_plate = Plate(
            job_id=job_id,
            plate_text=plate_text,
            best_confidence=best_entry["confidence"],
            bbox_confidence=best_entry.get("bbox_confidence", 0.0),
            vehicle_type=best_entry.get("vehicle_type"),
            vehicle_confidence=best_entry.get("vehicle_conf"),
            vehicle_image_path=vehicle_image_path,
            # Store path relative to media directory
            best_image_path=output_path.replace("media/", "", 1)
        )

        db.add(final_plate)

    db.commit()
