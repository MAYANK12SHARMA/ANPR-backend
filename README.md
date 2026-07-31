# 🖥️ Backend — ANRP FastAPI Service

> The backend is a **FastAPI** application that accepts video uploads and live RTSP camera streams, runs a multi-stage AI pipeline (vehicle detection → tracking → plate detection → OCR), and persists results to PostgreSQL. It also serves processed video and cropped images as static files.

---

## 📋 Table of Contents

- [Directory Structure](#-directory-structure)
- [How It Works — End-to-End Flow](#-how-it-works--end-to-end-flow)
- [Modules](#-modules)
  - [app/main.py — Application Entry Point](#appmainpy--application-entry-point)
  - [app/config.py — Configuration](#appconfigpy--configuration)
  - [app/api/routes.py — REST & WebSocket Endpoints](#appapiroutespy--rest--websocket-endpoints)
  - [app/db/ — Database Layer](#appdb--database-layer)
  - [app/ai/ — AI Pipeline](#appai--ai-pipeline)
    - [pipeline_with_tracking.py — Main Pipeline](#pipeline_with_trackingpy--main-pipeline)
    - [tracker.py — Vehicle Tracker](#trackerpy--vehicle-tracker)
    - [vehicle_detector.py — Vehicle Detection](#vehicle_detectorpy--vehicle-detection)
    - [plate_detector.py — Plate Detection](#plate_detectorpy--plate-detection)
    - [ocr.py — Text Recognition](#ocrpy--text-recognition)
    - [preprocessing.py — Image Enhancement](#preprocessingpy--image-enhancement)
    - [utils.py — Plate Utilities](#utilspy--plate-utilities)
  - [app/services/ — Business Logic](#appservices--business-logic)
  - [workers/ — Background Workers](#workers--background-workers)
  - [models/ — YOLO Weights](#models--yolo-weights)
  - [media/ — Runtime Storage](#media--runtime-storage)
- [API Reference](#-api-reference)
  - [Video Upload Endpoints](#video-upload-endpoints)
  - [Camera Stream Endpoints](#camera-stream-endpoints)
  - [WebSocket Endpoint](#websocket-endpoint)
- [Database Schema](#-database-schema)
- [Configuration Reference](#-configuration-reference)
- [Running the Backend](#-running-the-backend)
- [Dependencies](#-dependencies)

---

## 📁 Directory Structure

```
backend/
├── app/
│   ├── main.py                     # FastAPI app creation, CORS, static files, startup
│   ├── config.py                   # Environment-driven settings
│   │
│   ├── api/
│   │   └── routes.py               # All HTTP and WebSocket route handlers
│   │
│   ├── db/
│   │   ├── database.py             # SQLAlchemy engine and session factory
│   │   └── models.py               # ORM models: Job, Plate
│   │
│   ├── ai/
│   │   ├── pipeline_with_tracking.py  # Main orchestration loop (video & RTSP)
│   │   ├── tracker.py                 # Hungarian-algorithm multi-object tracker
│   │   ├── vehicle_detector.py        # YOLOv11 vehicle inference
│   │   ├── plate_detector.py          # YOLOv11 plate inference
│   │   ├── ocr.py                     # PaddleOCR + multi-candidate scoring
│   │   ├── preprocessing.py           # Image enhancement (deskew, sharpen)
│   │   ├── utils.py                   # Plate normalisation & validation regex
│   │   └── pipeline.py                # Legacy basic pipeline (no tracking)
│   │
│   └── services/
│       ├── job_manager.py          # Job lifecycle: status updates, error handling
│       └── storage.py              # (reserved) file-path helper stubs
│
├── workers/
│   └── run_job.py                  # (reserved) standalone worker entrypoint
│
├── models/
│   ├── vehicle.pt                  # YOLOv11 vehicle detection weights
│   └── no_plate.pt                 # YOLOv11 plate detection weights
│
├── media/                          # Created at runtime, gitignored
│   ├── videos/                     # Uploaded source videos
│   ├── frames/                     # Extracted first-frame JPEGs & live frames
│   ├── outputs/                    # Vehicle and plate crop images
│   ├── processed/                  # Annotated output videos (raw + H.264)
│   └── debug/                      # Best OCR crop per track (for debugging)
│
└── requirements.txt
```

---

## 🔄 How It Works — End-to-End Flow

```
User action                     Backend action
──────────────────────────────────────────────────────────────────────
POST /upload-video              Save file → create Job(status=uploaded)
GET  /job/{id}/first-frame      Extract frame 0 → return JPEG
POST /job/set-roi-line          Store ROI+line JSON → start background task
        │
        └─► process_job()       Set status=processing
                │
                └─► run_pipeline_with_tracking()
                        │
                        ├── Open video / RTSP stream (with retry)
                        ├── For every frame:
                        │     ├── detect_vehicles()      → YOLOv11
                        │     ├── tracker.update()       → assign track IDs
                        │     ├── ROI filter             → cv2.pointPolygonTest
                        │     ├── line_counter.check()   → cross-product test
                        │     ├── detect_plates()        → YOLOv11 on vehicle crop
                        │     ├── run_paddleocr()        → 5-candidate scoring
                        │     ├── _smart_upsert()        → write best per track
                        │     └── Draw annotations → write to VideoWriter
                        │
                        ├── FFmpeg re-encode → H.264 .mp4
                        └── Update job.status = completed
```

---

## 📦 Modules

### `app/main.py` — Application Entry Point

**Responsibility:** Creates and configures the FastAPI instance.

**What it does:**
- Creates all DB tables via `models.Base.metadata.create_all()`
- Mounts `media/` as a static file directory at `/media`
- Registers all routes from `app.api.routes`
- Configures CORS to allow `http://localhost:3000`
- On startup, runs `_ensure_legacy_schema_columns()` which safely `ALTER TABLE … ADD COLUMN IF NOT EXISTS` for any columns added after initial deployment (schema migration without Alembic)
- Exposes `GET /health` → `{ "status": "Backend is running" }`

---

### `app/config.py` — Configuration

**Responsibility:** Single source of truth for environment-driven settings.

| Variable | Env Key | Default | Description |
|----------|---------|---------|-------------|
| `OCR_ENGINE` | `OCR_ENGINE` | `"paddleocr"` | Selects OCR backend |
| `USE_GPU` | `OCR_USE_GPU` | `"true"` | Enable GPU for PaddleOCR |
| `PADDLE_OCR_MODEL_DIR` | `PADDLE_OCR_MODEL_DIR` | *(local path)* | Directory with fine-tuned recognition model |

---

### `app/api/routes.py` — REST & WebSocket Endpoints

**Responsibility:** All HTTP and WebSocket handler functions. Uses FastAPI `BackgroundTasks` for async pipeline execution and a global `active_frame_queues` dict for live camera frame dispatch.

**Pydantic request models:**

| Model | Fields |
|-------|--------|
| `ROILineRequest` | `job_id`, `roi_coords`, `line_coords`, `line_distance_meters` |
| `CameraCreateRequest` | `username`, `password`, `ip_address`, `path`, `name` |
| `CameraStartRequest` | `roi_coords`, `line_coords`, `line_distance_meters` |

**Helper functions:**

| Function | Description |
|----------|-------------|
| `get_db()` | FastAPI dependency — yields a SQLAlchemy `Session` |
| `_build_rtsp_url()` | Assembles `rtsp://user:pass@ip/path` (URL-encodes password) |
| `_capture_first_frame()` | Opens video/RTSP, reads one frame, saves as JPEG |
| `_process_camera_job_with_queue()` | Thread target: calls `process_job`, cleans up queue on exit |

**Route handlers — Video Upload:**

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/upload-video` | Saves file, creates `Job(status=uploaded)`, returns `job_id` |
| `GET` | `/job/{job_id}/first-frame` | Returns JPEG of first video frame for ROI selection |
| `POST` | `/job/set-roi-line` | Persists ROI+line, sets `status=pending`, triggers background `process_job` |
| `GET` | `/job/{job_id}` | Returns current job status + live frame URL if applicable |
| `GET` | `/jobs` | Returns all jobs sorted by creation time (newest first) |
| `GET` | `/job/{job_id}/results` | Returns plates array + processed video path |

**Route handlers — Camera Stream:**

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/camera-job/create` | Creates camera `Job`, stores RTSP URL + config JSON |
| `GET` | `/camera-job/{job_id}/first-frame` | Captures a snapshot from RTSP for ROI setup |
| `POST` | `/camera-job/{job_id}/start` | Saves ROI+line, sets `is_live=true`, spawns pipeline thread |
| `POST` | `/camera-job/{job_id}/stop` | Sets `is_live=false`, `status=stopped`, returns captured plates |
| `GET` | `/camera-job/{job_id}/live-frame` | Returns latest JPEG saved every 5 processed frames |
| `WS` | `/ws/camera-job/{job_id}/live` | Streams annotated JPEG frames to browser (WebSocket) |

**WebSocket behaviour (`camera_live_ws`):**
- Dequeues frames from `active_frame_queues[job_id]` (a 2-slot `queue.Queue`)
- JPEG-encodes each frame at 70% quality and sends as binary message
- Every 25 iterations, re-checks job status from DB — sends `{"type":"done"}` when job ends
- Sleeps 40 ms when queue is empty to avoid busy-looping

---

### `app/db/` — Database Layer

#### `database.py`

Creates the SQLAlchemy `engine` using the connection string:
```
postgresql://postgres:postgres@localhost:5432/anpr_db
```
Also exports `SessionLocal` (session factory) and `Base` (declarative base class).

#### `models.py`

Two ORM models:

**`Job`** — one row per processing job

| Column | Type | Description |
|--------|------|-------------|
| `job_id` | String PK | UUID auto-generated |
| `video_path` | String | Path to uploaded file |
| `processed_video_path` | String | Path to output H.264 video |
| `status` | String | `uploaded → pending → processing → completed / failed / stopped` |
| `roi_coords` | String | JSON array of `[x,y]` polygon points |
| `line_coords` | String | JSON `[x1,y1,x2,y2]` |
| `line_distance_meters` | Float | Physical line length (for speed calc) |
| `job_type` | String | `"video_upload"` or `"camera_stream"` |
| `is_live` | String | `"true"` / `"false"` — RTSP stream active flag |
| `camera_rtsp_url` | String | Full RTSP URL |
| `camera_config` | String | JSON blob: name, ip, path, username |
| `stream_started_at` | DateTime | When RTSP stream began |
| `last_frame_processed_at` | DateTime | Heartbeat for the pipeline loop |
| `created_at` | DateTime | Server-side `now()` |

**`Plate`** — one row per unique tracked vehicle (not one per frame)

| Column | Type | Description |
|--------|------|-------------|
| `id` | Integer PK | Auto-increment |
| `job_id` | String | FK to `jobs.job_id` |
| `plate_text` | String | Best OCR result (legacy: best of two pipelines) |
| `best_confidence` | Float | OCR confidence for `plate_text` |
| `bbox_confidence` | Float | YOLO detection confidence for the plate box |
| `plate_text_highres` | String | OCR on upscaled crop |
| `ocr_conf_highres` | Float | Confidence for high-res result |
| `plate_text_lowres` | String | OCR on light-preprocessed crop |
| `ocr_conf_lowres` | Float | Confidence for low-res result |
| `best_image_path` | String | Path to best plate crop JPEG |
| `vehicle_type` | String | `car`, `bus`, `truck`, `motorcycle` |
| `vehicle_confidence` | Float | YOLO detection confidence for vehicle |
| `vehicle_image_path` | String | Path to vehicle crop JPEG |
| `track_id` | Integer | Remapped sequential ID (1, 2, 3 …) |
| `frame_number` | Integer | Frame at which best plate was captured |
| `crossed_line` | Integer | Always 1 (only crossed vehicles are saved) |
| `speed_kmh` | Float | Estimated speed (reserved, not yet computed) |
| `detected_at` | DateTime | Timestamp of best detection |

---

### `app/ai/` — AI Pipeline

#### `pipeline_with_tracking.py` — Main Pipeline

**Entry function:** `run_pipeline_with_tracking(job_id, video_path, db, frame_queue=None)`

This is the heart of the system. It orchestrates the entire per-frame processing loop for both video files and RTSP streams.

**Key responsibilities:**

1. **Source opening** — `_open_capture_with_retry()` opens `cv2.VideoCapture` with up to 5 retries and a 10-second thread-based timeout to prevent hangs on broken RTSP streams. For RTSP, sets TCP transport and low-delay flags via `OPENCV_FFMPEG_CAPTURE_OPTIONS`.

2. **Safe frame reading** — `_safe_cap_read()` reads a frame in a daemon thread with a 5-second hard timeout, returning a `(ret, frame, timed_out)` tuple.

3. **ROI mask creation** — builds a binary `numpy` mask from the polygon using `cv2.fillPoly`; centroid-in-mask check is `roi_mask[cy, cx] > 0` (O(1) per vehicle).

4. **Detection side computation** — determines which side of the counting line the *far side of frame* is on, so that vehicles already past the line at stream start are processed immediately.

5. **Per-frame processing loop:**
   - Camera jobs poll the DB every 5 frames to detect a stop signal
   - `detect_vehicles()` → update tracker → for each active track:
     - ROI check
     - `line_counter.check_crossing()` — adds to `crossed_track_ids` on crossing
     - Only processes plate detection for: *(in ROI)* AND *(crossed OR on detection side)*
     - Plate detection → OCR → `_smart_upsert()` with only the best confidence

6. **Smart DB upsert (`_smart_upsert`)** — one row per `track_id` per job. Updates a field *only if* the new value has higher confidence than the stored value. Saves images to fixed filenames (`{job_id}_track{id}_vehicle.jpg`, `{job_id}_track{id}_plate.jpg`) so they get overwritten rather than accumulated.

7. **Periodic flush** — every 30 frames, dirty tracks are written to DB. Final flush happens when the loop exits.

8. **FFmpeg re-encode** — after the loop, runs:
   ```
   ffmpeg -y -i {processed}.mp4 -c:v libx264 -preset fast -crf 23 {final}.mp4
   ```
   Skipped if job was stopped (too slow for interrupted streams).

**RTSP reconnect logic:**
- 2 consecutive timeouts → full reconnect with 3 retries
- 3 consecutive read failures → reconnect
- Reconnect only breaks the loop for non-camera (file) sources

---

#### `tracker.py` — Vehicle Tracker

Contains three classes:

##### `VehicleTracker`

Multi-object tracker using the **Hungarian Algorithm** (`scipy.optimize.linear_sum_assignment`).

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_disappeared` | 30 | Frames a track can be invisible before deletion |
| `max_distance` | 80 px | Maximum centroid distance for a valid match |

**`update(detections)` method:**
1. Compute centroids of all current detections
2. Build pairwise Euclidean distance cost matrix (tracks × detections)
3. Threshold distances > 80 px to `1e6` (effectively infinite)
4. Run Hungarian assignment to get optimal matching
5. Update matched tracks, increment `disappeared` on unmatched tracks (delete if > 30), create new tracks for unmatched detections
6. Return only tracks with `disappeared == 0`

**`get_previous_centroid(track_id)`** — returns the second-to-last position from the track's history buffer (used by `LineCrossCounter`).

##### `TrackState`

Stores per-track state: bounding box, centroid, class, `disappeared` counter, and a rolling history of the last 30 centroids.

##### `LineCrossCounter`

Detects single-pass line crossings using the **cross product** method.

**`check_crossing(track_id, current_centroid, previous_centroid)`:**
1. Computes the signed cross product of `line_vec × (point - line_p1)` → gives which side a point is on
2. If the current and previous sides differ AND distance to line < 50 px → crossing confirmed
3. Adds `track_id` to `counted_ids` so it is never double-counted

**`_compute_side(point)`:** returns `+1`, `-1`, or `0` (on the line within ±5 px tolerance).

---

#### `vehicle_detector.py` — Vehicle Detection

Loads `models/vehicle.pt` once at import time (module-level singleton). Auto-selects CUDA if available.

**`detect_vehicles(frame)`:**
- Runs YOLOv11 with `conf=0.65`
- Returns a list of dicts: `{ "bbox": [x1,y1,x2,y2], "confidence": float, "label": str }`
- Classes: `car`, `bus`, `truck`, `motorcycle`

---

#### `plate_detector.py` — Plate Detection

Loads `models/no_plate.pt` once at import time.

**`detect_plates(vehicle_crop)`:**
- Runs YOLOv11 on the cropped vehicle image
- Returns bounding boxes relative to the crop's coordinate space
- Pipeline offsets these back to full-frame coordinates

---

#### `ocr.py` — Text Recognition

The most complex module. Implements a **5-candidate voting** OCR strategy on top of PaddleOCR.

**Initialization:**
```python
ocr = PaddleOCR(rec_model_dir=PADDLE_OCR_MODEL_DIR, det=False, use_angle_cls=False, use_gpu=False)
```
Detection is disabled (`det=False`) because the plate region is already cropped; only the recognition head runs.

**`run_paddleocr(img)`** — public API — runs 5 reads and picks the best:

| Candidate | Input |
|-----------|-------|
| `RAW` | Original crop |
| `LIGHT` | `light_preprocess(img)` output |
| `TOP` | Top half of LIGHT output |
| `BOTTOM` | Bottom half of LIGHT output |
| `COMBINED` | `TOP.text + BOTTOM.text`, averaged confidence |

**`score_candidate(raw_text, conf)`** — scoring formula:

```
score = conf
      + min(len(cleaned), 10) × 0.15   # prefer longer strings
      + 1.5  if len(cleaned) == 10      # exact 10-char bonus
      + 1.0  if len(corrected) == 10    # corrected to 10 chars
      + 2.5  if regex matches           # valid Indian plate format
      + 1.0  if state code valid        # known state prefix
      − 1.5  if len(cleaned) > 12       # junk penalty
      − 1.0  if len(cleaned) ≤ 2        # tiny result penalty
```

**`strict_plate_correction(raw_text)`** — heuristic correction:
- Position 0–1: must be letters → maps digits to letters via `DIGIT_TO_LETTER`
- Position 2–3: must be digits → maps letters to digits via `LETTER_TO_DIGIT`
- Position 4–5: must be letters (series)
- Position 6–9: must be digits (serial number)
- If state code not in `VALID_STATES` (all 37 Indian state/UT codes), substitutes the fallback state `"MH"`

**Returns:** `{ "text": corrected, "text_raw": raw, "confidence": float, "score": float }`

---

#### `preprocessing.py` — Image Enhancement

**`light_preprocess(img)`:**
1. Upscale if height < 40 px (scale = `48 / height`, cubic interpolation)
2. Convert to grayscale
3. Gaussian blur (3×3) to reduce noise
4. `deskew_simple()` — Hough line transform → compute median angle → `warpAffine` rotation (±20° limit)
5. Unsharp masking: `cv2.addWeighted(gray, 1.2, blur, -0.2, 0)` — slight sharpening
6. Convert back to BGR (PaddleOCR expects 3-channel input)

**`deskew_simple(gray)`:**
- Detects dominant line angles via Hough transform
- Computes median angle across candidate lines
- Rotates the image to straighten skewed plates

---

#### `utils.py` — Plate Utilities

| Function | Description |
|----------|-------------|
| `normalize_plate(text)` | Uppercase + strip non-alphanumeric → `"MH 12 AB 1234"` → `"MH12AB1234"` |
| `is_valid_plate(text)` | Regex `^[A-Z]{2}[0-9]{2}[A-Z]{1,2}[0-9]{4}$` → `bool` |

Valid examples: `MH12AB1234`, `DL01CA9999`, `KA03MH1234`

---

### `app/services/` — Business Logic

#### `job_manager.py`

**`process_job(job_id, frame_queue=None)`:**

1. Opens a new DB session
2. Sets `job.status = "processing"`
3. Determines source path: `job.video_path` for file jobs, `job.camera_rtsp_url` for camera jobs
4. Calls `run_pipeline_with_tracking()`
5. On success: sets `status = "completed"` (unless already `"stopped"`)
6. On exception: sets `status = "failed"`, prints error
7. Always closes the DB session in `finally`

This is the function called by both `BackgroundTasks.add_task()` (for file jobs) and `threading.Thread` (for camera jobs).

---

### `workers/` — Background Workers

`workers/run_job.py` is an empty placeholder reserved for a future Celery/RQ-based worker implementation. Currently all jobs run in FastAPI background tasks or daemon threads.

---

### `models/` — YOLO Weights

| File | Size | Purpose |
|------|------|---------|
| `vehicle.pt` | ~18 MB | YOLOv11 model fine-tuned for car/bus/truck/motorcycle detection |
| `no_plate.pt` | ~5.5 MB | YOLOv11 model fine-tuned for number plate region detection |

Both models are loaded once at Python import time (module-level) and remain in memory for the lifetime of the process.

---

### `media/` — Runtime Storage

Created automatically on first run. Gitignored.

```
media/
├── videos/         ← {job_id}.mp4 — original uploaded file
├── frames/         ← {job_id}_first_frame.jpg, {job_id}_live.jpg
├── outputs/        ← {job_id}_track{N}_vehicle.jpg, {job_id}_track{N}_plate.jpg
├── processed/      ← {job_id}_processed.mp4 (raw), {job_id}_final.mp4 (H.264)
└── debug/          ← {job_id}_track{N}_best.jpg — best OCR input per track
```

---

## 📡 API Reference

### Video Upload Endpoints

#### `POST /upload-video`
Upload a video file to start a new job.

**Request:** `multipart/form-data` with `file` field

**Response:**
```json
{ "job_id": "550e8400-...", "status": "uploaded" }
```

---

#### `GET /job/{job_id}/first-frame`
Get first frame JPEG for ROI/line drawing UI.

**Response:** `image/jpeg` binary

---

#### `POST /job/set-roi-line`
Set ROI polygon and counting line, then start processing.

**Request body:**
```json
{
  "job_id": "550e8400-...",
  "roi_coords": [[100,100],[800,100],[800,600],[100,600]],
  "line_coords": [200, 350, 900, 350],
  "line_distance_meters": 8.0
}
```
Both `roi_coords` and `line_coords` are optional. Pass `null` to skip.

**Response:**
```json
{ "job_id": "...", "status": "pending", "message": "Processing started with ROI and line" }
```

---

#### `GET /job/{job_id}`
Poll current job status.

**Response:**
```json
{
  "job_id": "...",
  "status": "processing",
  "job_type": "video_upload",
  "is_live": "false",
  "live_frame": null
}
```

---

#### `GET /jobs`
List all jobs, newest first.

**Response:**
```json
{
  "total": 5,
  "jobs": [{ "job_id": "...", "status": "completed", "video_path": "...", ... }]
}
```

---

#### `GET /job/{job_id}/results`
Get final detection results.

**Response:**
```json
{
  "job_id": "...",
  "status": "completed",
  "processed_video": "media/processed/..._final.mp4",
  "total_plates": 3,
  "plates": [{
    "plate_text": "MH12AB1234",
    "confidence": 0.91,
    "bbox_confidence": 0.87,
    "image_path": "media/outputs/..._plate.jpg",
    "vehicle_type": "car",
    "vehicle_confidence": 0.95,
    "vehicle_image_path": "media/outputs/..._vehicle.jpg",
    "track_id": 1,
    "frame_number": 145,
    "speed_kmh": null,
    "detected_at": "29-06-2026 14:05:33",
    "plate_text_highres": "MH12AB1234",
    "ocr_conf_highres": 0.91,
    "plate_text_lowres": "MH12AB1234",
    "ocr_conf_lowres": 0.88
  }]
}
```

---

### Camera Stream Endpoints

#### `POST /camera-job/create`
```json
{ "username": "admin", "password": "pass", "ip_address": "10.0.0.1", "path": "/h264" }
```
Returns `{ "job_id": "...", "status": "uploaded", "job_type": "camera_stream" }`

---

#### `GET /camera-job/{job_id}/first-frame`
Captures a live snapshot from the RTSP stream for ROI setup.
Returns `image/jpeg`.

---

#### `POST /camera-job/{job_id}/start`
```json
{ "roi_coords": [[...]], "line_coords": [...], "line_distance_meters": 8.0 }
```
Starts the pipeline in a daemon thread. Returns `{ "is_live": "true", ... }`.

---

#### `POST /camera-job/{job_id}/stop`
Signals pipeline to stop. Returns final plate list.

---

#### `GET /camera-job/{job_id}/live-frame`
Returns the most recently saved JPEG (`media/frames/{job_id}_live.jpg`).

---

### WebSocket Endpoint

#### `WS /ws/camera-job/{job_id}/live`
Binary JPEG frames pushed at ~25 fps.
Sends `{"type": "done", "status": "stopped"}` when the stream ends.

---

## 🗄️ Database Schema

```sql
CREATE TABLE jobs (
    job_id                  VARCHAR PRIMARY KEY,
    video_path              VARCHAR,
    processed_video_path    VARCHAR,
    status                  VARCHAR DEFAULT 'pending',
    roi_coords              VARCHAR,
    line_coords             VARCHAR,
    line_distance_meters    DOUBLE PRECISION,
    job_type                VARCHAR,
    is_live                 VARCHAR DEFAULT 'false',
    camera_rtsp_url         VARCHAR,
    camera_config           VARCHAR,
    stream_started_at       TIMESTAMPTZ,
    last_frame_processed_at TIMESTAMPTZ,
    created_at              TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE plates (
    id                  SERIAL PRIMARY KEY,
    job_id              VARCHAR NOT NULL,
    plate_text          VARCHAR,
    best_confidence     DOUBLE PRECISION,
    bbox_confidence     DOUBLE PRECISION,
    plate_text_highres  VARCHAR,
    ocr_conf_highres    DOUBLE PRECISION,
    plate_text_lowres   VARCHAR,
    ocr_conf_lowres     DOUBLE PRECISION,
    best_image_path     VARCHAR,
    vehicle_type        VARCHAR,
    vehicle_confidence  DOUBLE PRECISION,
    vehicle_image_path  VARCHAR,
    track_id            INTEGER,
    frame_number        INTEGER,
    crossed_line        INTEGER DEFAULT 1,
    speed_kmh           DOUBLE PRECISION,
    detected_at         TIMESTAMPTZ
);
```

---

## ⚙️ Configuration Reference

| Setting | Env Variable | Default | Notes |
|---------|-------------|---------|-------|
| OCR backend | `OCR_ENGINE` | `paddleocr` | Only PaddleOCR is wired in |
| GPU inference | `OCR_USE_GPU` | `true` | Set `false` for CPU-only |
| PaddleOCR model | `PADDLE_OCR_MODEL_DIR` | Local path | Point to fine-tuned model dir |
| DB URL | (hardcoded) | `postgresql://postgres:postgres@localhost:5432/anpr_db` | Change in `database.py` |
| Min OCR confidence | `MIN_OCR_CONF` | `0.20` | In `pipeline_with_tracking.py` |
| Vehicle conf threshold | `VEHICLE_CONF_THRESHOLD` | `0.65` | In `vehicle_detector.py` |
| Tracker max disappear | — | `30` frames | In `VehicleTracker.__init__` |
| Tracker max distance | — | `80` px | In `VehicleTracker.__init__` |
| DB flush interval | — | `30` frames | `FLUSH_EVERY_N_FRAMES` |

---

## 🚀 Running the Backend

```bash
cd backend

# Activate venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS / Linux

# Start server
uvicorn app.main:app --reload --port 8000

# With host binding (LAN access)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Swagger UI available at: http://localhost:8000/docs

---

## 📦 Dependencies

```
fastapi             - ASGI web framework
uvicorn             - ASGI server
sqlalchemy          - ORM
psycopg2-binary     - PostgreSQL driver
python-multipart    - File upload parsing
pydantic            - Request/response validation
opencv-python       - Image and video processing
ultralytics         - YOLOv11 inference
easyocr             - (installed, not actively used — replaced by PaddleOCR)
scipy               - Hungarian algorithm (linear_sum_assignment)
supervision         - (installed, utility helpers)
paddleocr==2.8.1    - Plate text recognition
```
