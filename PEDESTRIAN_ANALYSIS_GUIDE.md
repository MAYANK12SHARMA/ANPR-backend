# 🚶 Pedestrian Analysis — Backend Developer & Intern Guide

Welcome to the **ANPR & Pedestrian Analytics Backend**! This document provides a complete technical deep-dive into how pedestrian detection, tracking, rider filtering, region-of-interest (ROI) spatial validation, crowd alerting, and live streaming operate across the codebase.

---

## 📚 Table of Contents

1. [Executive Architecture Overview](#1-executive-architecture-overview)
2. [End-to-End Execution Flowchart](#2-end-to-end-execution-flowchart)
3. [Core Subsystems & Module Map](#3-core-subsystems--module-map)
4. [Deep-Dive: Pedestrian AI Detection Engine](#4-deep-dive-pedestrian-ai-detection-engine)
   - [4.1 Model & Target Classes](#41-model--target-classes)
   - [4.2 Rider Filtering Algorithm](#42-rider-filtering-algorithm)
   - [4.3 Polygon ROI Spatial Testing](#43-polygon-roi-spatial-testing)
   - [4.4 Frame Annotation & Visual Output](#44-frame-annotation--visual-output)
5. [Orchestration, Alerting & Cooldown Management](#5-orchestration-alerting--cooldown-management)
   - [5.1 Pipeline Loop Integration](#51-pipeline-loop-integration)
   - [5.2 Crowd Threshold & Alert Cooldown Logic](#52-crowd-threshold--alert-cooldown-logic)
   - [5.3 Alert Persistence & Snapshot Storage](#53-alert-persistence--snapshot-storage)
6. [API Specification for Developers](#6-api-specification-for-developers)
   - [6.1 Video Upload with Pedestrian Config](#61-video-upload-with-pedestrian-config)
   - [6.2 Live RTSP Camera Job Creation](#62-live-rtsp-camera-job-creation)
   - [6.3 Setting ROI & Triggering Background Pipeline](#63-setting-roi--triggering-background-pipeline)
   - [6.4 Fetching Results & Crowd Alerts](#64-fetching-results--crowd-alerts)
   - [6.5 WebSocket Live Streaming](#65-websocket-live-streaming)
7. [Database Schema & Entity Relations](#7-database-schema--entity-relations)
8. [Notification & Email Reporting](#8-notification--email-reporting)
9. [Intern Onboarding & Debugging Guide](#9-intern-onboarding--debugging-guide)

---

## 1. Executive Architecture Overview

The backend is built with **FastAPI**, **SQLAlchemy** (PostgreSQL/SQLite), **Ultralytics YOLO**, **OpenCV**, and **PaddleOCR**.

While the system handles Automatic Number Plate Recognition (ANPR), the **Pedestrian Analysis Subsystem** is an optional module within the computer vision pipeline. When enabled:

- It tracks human beings in video files or live RTSP streams.
- Filters out individuals riding vehicles (motorcycles, bicycles).
- Tests if remaining pedestrians are inside a user-defined **Region of Interest (ROI)** polygon.
- Monitors crowd counts against a configurable threshold (`pedestrian_threshold`).
- Triggers persistent alerts with frame snapshots and sends summary emails upon job completion.

---

## 2. End-to-End Execution Flowchart

The following sequence details how frame data flows from HTTP/RTSP ingest through AI inference to DB storage and WebSocket dispatch:

```mermaid
sequenceDiagram
    autonumber

    actor Client as Frontend / Operator
    participant API as FastAPI Router
    participant Worker as Pipeline Worker
    participant AI as Pedestrian Detector
    participant Alert as Alert Service
    participant DB as PostgreSQL
    participant WS as WebSocket Streamer

    Client->>API: POST upload-video or camera-job-create
    Note over Client,API: pedestrian=true, threshold=N

    API->>DB: Create Job
    Note right of DB: status=uploaded<br/>pedestrian=true

    DB-->>API: Job saved
    API-->>Client: Return job_id

    Client->>API: POST set-roi-line
    Note right of API: roi_coords=[[x1,y1], ...]

    API->>DB: Update Job
    Note right of DB: status=pending<br/>save ROI coordinates

    API->>Worker: Start process_job(job_id)
    API-->>Client: 200 OK - Processing started

    activate Worker

    Worker->>DB: Update job status
    Note right of DB: status=processing

    Worker->>Worker: Open Video or RTSP stream

    loop For every frame
        Worker->>AI: detect_pedestrians(frame, ROI)
        activate AI

        AI->>AI: YOLO tracking
        Note right of AI: Classes = person and vehicles

        AI->>AI: Separate persons and vehicles

        AI->>AI: Calculate foot point
        Note right of AI: foot_x = (x1 + x2) / 2<br/>foot_y = y2

        AI->>AI: Apply rider filter
        Note right of AI: Ignore person if foot point<br/>is inside vehicle box

        AI->>AI: Check ROI
        Note right of AI: pointPolygonTest(ROI, foot point)

        AI->>AI: Annotate frame
        Note right of AI: Bounding boxes, IDs,<br/>foot point and crowd count

        AI-->>Worker: Return detection result
        Note left of Worker: person_count and person list

        deactivate AI

        alt Crowd threshold exceeded and cooldown elapsed
            Worker->>Alert: Create pedestrian alert

            Alert->>Alert: Save JPEG snapshot
            Note right of Alert: media/alerts/job_id/

            Alert->>DB: Insert alert record
            Note right of DB: alert_type, title,<br/>image_path and frame_number

            DB-->>Alert: Alert saved
        end

        opt Live camera stream
            Worker->>WS: Push annotated frame
            Note right of WS: active_frame_queues[job_id]

            WS-->>Client: Send JPEG over WebSocket
            Note left of Client: /ws/camera-job/job_id/live
        end
    end

    Worker->>DB: Update job status
    Note right of DB: status=completed

    Worker->>Worker: Dispatch completion email

    deactivate Worker
```

---

## 3. Core Subsystems & Module Map

| Module File                                                                  | Responsibility                                                                                         |
| ---------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| [app/main.py](backend/app/main.py)                                           | FastAPI app initialization, CORS, database table creation, schema auto-migration.                      |
| [app/api/routes.py](backend/app/api/routes.py)                               | REST API endpoints for job creation, ROI setup, results retrieval, and WebSocket streaming.            |
| [app/ai/pedestrian_detector.py](backend/app/ai/pedestrian_detector.py)       | Core pedestrian AI module (YOLO tracking, rider filtering logic, foot-point calculation, ROI testing). |
| [app/ai/pipeline_with_tracking.py](backend/app/ai/pipeline_with_tracking.py) | Master frame loop orchestrator combining vehicle detection, plate OCR, and pedestrian alerting.        |
| [app/services/alert_service.py](backend/app/services/alert_service.py)       | Service layer responsible for deduplicating, capturing snapshot images, and saving DB alert records.   |
| [app/services/job_manager.py](backend/app/services/job_manager.py)           | Job status manager and background worker entry point (`process_job`).                                  |
| [app/db/models.py](backend/app/db/models.py)                                 | SQLAlchemy ORM models (`Job`, `Alert`, `Plate`, `User`).                                               |
| [app/email/notification.py](backend/app/email/notification.py)               | Prepares statistical metrics (total pedestrian alerts) and sends summary HTML emails.                  |

---

## 4. Deep-Dive: Pedestrian AI Detection Engine

Located in [`app/ai/pedestrian_detector.py`](backend/app/ai/pedestrian_detector.py), the `detect_pedestrians()` function processes raw BGR video frames.

### 4.1 Model & Target Classes

The detector initializes Ultralytics YOLO with pre-trained or fine-tuned pedestrian weights:

```python
model = YOLO("models/pedestrian.pt")

PERSON_CLASS = 0
VEHICLE_CLASSES = [1, 2, 3, 5, 7]  # bicycle, car, motorcycle, bus, truck
```

When tracking is invoked:

```python
results = model.track(
    frame,
    persist=True,
    classes=[0, 1, 2, 3, 5, 7],
    verbose=False,
)
```

- `persist=True`: Maintains track IDs across consecutive video frames.
- Multi-class tracking ensures both persons and nearby vehicles are identified in a single forward pass.

---

### 4.2 Rider Filtering Algorithm

A common challenge in computer vision is distinguishing **freely walking pedestrians** from **people riding vehicles** (e.g., bicyclists, motorcyclists). Counting riders as pedestrians leads to false crowd alerts on roadways.

The system resolves this using **Foot-Point Spatial Intersect Testing**:

```mermaid
flowchart TD
    A[Detected Person Bounding Box: x1, y1, x2, y2] --> B["Calculate Foot Point: foot_x = (x1 + x2) / 2, foot_y = y2"]
    B --> C{Loop Through All Vehicle Boxes vx1, vy1, vx2, vy2}
    C -->|foot_x, foot_y inside vehicle bbox?| D[Rider Detected! riding_vehicle = True]
    D --> E[Discard from Pedestrian Count]
    C -->|No overlap found| F[Valid Pedestrian]
    F --> G[Proceed to ROI Spatial Check]
```

#### Code Snippet ([`app/ai/pedestrian_detector.py`](backend/app/ai/pedestrian_detector.py#L94-L119)):

```python
foot_x = (x1 + x2) // 2
foot_y = y2

riding_vehicle = False
for vx1, vy1, vx2, vy2 in vehicle_boxes:
    if vx1 <= foot_x <= vx2 and vy1 <= foot_y <= vy2:
        riding_vehicle = True
        break

if riding_vehicle:
    continue  # Skip rider, do not count as pedestrian
```

---

### 4.3 Polygon ROI Spatial Testing

Users specify custom Region-of-Interest (ROI) polygons (e.g., sidewalks, entrances, restricted zones).

The system tests if the pedestrian's **foot point** `(foot_x, foot_y)` falls within the polygon using OpenCV's `pointPolygonTest`:

```python
inside_roi = True
if roi_polygon is not None:
    inside = cv2.pointPolygonTest(
        roi_polygon,
        (float(foot_x), float(foot_y)),
        False,
    )
    inside_roi = inside >= 0
```

- `inside >= 0`: Point is inside or on the boundary of the ROI polygon.
- `person_count`: Incremented only when `inside_roi` evaluates to `True`.

---

### 4.4 Frame Annotation & Visual Output

Every frame processed by `detect_pedestrians()` is visually annotated in real-time:

```python
# Bounding Box Color Scheme (BGR)
PERSON_COLOR = (0, 255, 0)   # Green for pedestrians inside ROI
OUTSIDE_COLOR = (0, 0, 255)  # Red for pedestrians outside ROI
FOOT_COLOR = (255, 255, 0)   # Cyan circle at foot point
ROI_COLOR = (255, 0, 255)    # Magenta for ROI boundary polygon
```

1. **Bounding Box**: Bounded with `PERSON_COLOR` (Green) if inside ROI, or `OUTSIDE_COLOR` (Red) if outside.
2. **ID Tag**: `ID:{track_id}` displayed above the head (`y1 - 10`).
3. **Foot Circle**: Filled circle drawn at `(foot_x, foot_y)`.
4. **Crowd HUD**: Top-left text overlay: `"Persons Inside ROI : {person_count}"`.

---

## 5. Orchestration, Alerting & Cooldown Management

### 5.1 Pipeline Loop Integration

In [`app/ai/pipeline_with_tracking.py`](backend/app/ai/pipeline_with_tracking.py), the `run_pipeline_with_tracking()` loop coordinates pedestrian analysis alongside ANPR vehicle tracking:

```python
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
```

---

### 5.2 Crowd Threshold & Alert Cooldown Logic

To prevent flooding the database with dozens of alerts per second while a crowd remains in the frame, an **Alert Cooldown State Machine** is implemented:

```mermaid
stateDiagram-v2
    [*] --> NormalState: person_count < threshold
    NormalState --> AlertState: person_count >= threshold

    state AlertState {
        [*] --> TriggerAlert: Cooldown elapsed (frame_count - last_alert_frame >= 10*fps)
        TriggerAlert --> WaitCooldown: Save Alert DB & Snapshot
        WaitCooldown --> WaitCooldown: Next frame (person_count still >= threshold)
    }

    AlertState --> NormalState: person_count < threshold (Reset alert state)
```

#### Cooldown Formula:

```python
ALERT_COOLDOWN_FRAMES = int(fps * 10)  # Cooldown = 10 seconds of video footage

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
    pedestrian_alert_active = False  # Reset state when crowd disperses
```

---

### 5.3 Alert Persistence & Snapshot Storage

When `create_alert()` in [`app/services/alert_service.py`](backend/app/services/alert_service.py) is invoked:

1. Directory check/creation: `media/alerts/{job_id}/`.
2. Image export: Saves the current annotated frame as `pedestrian_{frame_number}.jpg`.
3. Database record insertion: Inserts a row into the `alerts` table.

```python
alert = Alert(
    job_id=job_id,
    alert_type="pedestrian",
    title="Crowd Threshold Exceeded",
    description=f"{person_count} persons detected inside ROI",
    frame_number=frame_number,
    image_path="media/alerts/{job_id}/pedestrian_{frame_number}.jpg",
)
db.add(alert)
db.commit()
```

---

## 6. API Specification for Developers

All endpoints require standard authentication dependencies (`require_operator` or `require_viewer`).

### 6.1 Video Upload with Pedestrian Config

Uploads a static video file and defines pipeline features and crowd threshold.

- **Method**: `POST`
- **Path**: `/upload-video`
- **Headers**: `Authorization: Bearer <JWT_TOKEN>` (Operator role required)
- **Form Data**:
  - `file`: `UploadFile` (Video file, e.g., `.mp4`, `.avi`)
  - `analysis_config`: `string` (JSON string) -> `{"vehicle": true, "plate": true, "pedestrian": true}`
  - `pedestrian_threshold`: `integer` (Default: `10`)

#### Example Request (cURL):

```bash
curl -X POST "http://localhost:8000/upload-video" \
  -H "Authorization: Bearer <TOKEN>" \
  -F "file=@sample.mp4" \
  -F 'analysis_config={"vehicle": true, "plate": false, "pedestrian": true}' \
  -F "pedestrian_threshold=5"
```

#### Response (`200 OK`):

```json
{
  "job_id": "a1b2c3d4-e5f6-7890-abcd-1234567890ab",
  "status": "uploaded"
}
```

---

### 6.2 Live RTSP Camera Job Creation

Configures a live RTSP IP camera stream with pedestrian monitoring.

- **Method**: `POST`
- **Path**: `/camera-job/create`
- **Headers**: `Authorization: Bearer <JWT_TOKEN>` (Operator role required)
- **Request Body** (`application/json`):

```json
{
  "username": "admin",
  "password": "secretpassword",
  "ip_address": "192.168.1.100",
  "path": "/h264",
  "name": "Entrance-Camera-01",
  "analysis_config": {
    "vehicle": false,
    "plate": false,
    "pedestrian": true
  },
  "pedestrian_threshold": 8
}
```

#### Response (`200 OK`):

```json
{
  "job_id": "c9d8e7f6-a5b4-3210-9876-fedcba098765",
  "status": "uploaded",
  "job_type": "camera_stream"
}
```

---

### 6.3 Setting ROI & Triggering Background Pipeline

Sets ROI polygon coordinates and kicks off pipeline processing in a background worker thread.

- **Method**: `POST`
- **Path**: `/job/set-roi-line` (or `/camera-job/{job_id}/start` for streams)
- **Headers**: `Authorization: Bearer <JWT_TOKEN>` (Operator role required)
- **Request Body** (`application/json`):

```json
{
  "job_id": "a1b2c3d4-e5f6-7890-abcd-1234567890ab",
  "roi_coords": [
    [100, 200],
    [500, 200],
    [500, 600],
    [100, 600]
  ],
  "line_coords": null,
  "line_distance_meters": null
}
```

#### Response (`200 OK`):

```json
{
  "job_id": "a1b2c3d4-e5f6-7890-abcd-1234567890ab",
  "status": "pending",
  "message": "Processing started with ROI and line"
}
```

---

### 6.4 Fetching Results & Crowd Alerts

Retrieves all job data, detected plates, and crowd threshold violation alerts.

- **Method**: `GET`
- **Path**: `/job/{job_id}/results`
- **Headers**: `Authorization: Bearer <JWT_TOKEN>` (Viewer or Operator role required)

#### Response (`200 OK`):

```json
{
  "job_id": "a1b2c3d4-e5f6-7890-abcd-1234567890ab",
  "status": "completed",
  "processed_video": "media/processed/a1b2c3d4..._final.mp4",
  "total_plates": 0,
  "plates": [],
  "total_alerts": 2,
  "alerts": [
    {
      "id": 14,
      "alert_type": "pedestrian",
      "title": "Crowd Threshold Exceeded",
      "description": "12 persons detected inside ROI",
      "frame_number": 150,
      "image_path": "media/alerts/a1b2c3d4.../pedestrian_150.jpg",
      "created_at": "20-08-2026 16:45:10"
    },
    {
      "id": 15,
      "alert_type": "pedestrian",
      "title": "Crowd Threshold Exceeded",
      "description": "15 persons detected inside ROI",
      "frame_number": 450,
      "image_path": "media/alerts/a1b2c3d4.../pedestrian_450.jpg",
      "created_at": "20-08-2026 16:45:25"
    }
  ]
}
```

---

### 6.5 WebSocket Live Streaming

Streams live annotated JPEG frames directly to the frontend for camera streams.

- **Protocol**: `WebSocket`
- **Path**: `/ws/camera-job/{job_id}/live?token=<JWT_ACCESS_TOKEN>`
- **Payload Format**: Binary JPEG byte frames (`image/jpeg`)
- **Control Messages** (`JSON`):
  - Error: `{"type": "error", "message": "Reason..."}`
  - Completion: `{"type": "done", "status": "completed"}`

---

## 7. Database Schema & Entity Relations

```mermaid
erDiagram
    USERS ||--o{ JOBS : owns
    JOBS ||--o{ ALERTS : generates
    JOBS ||--o{ PLATES : records

    JOBS {
        string job_id PK
        int owner_id FK
        string status
        string job_type
        json analysis_config "contains {'pedestrian': bool}"
        int pedestrian_threshold
        string roi_coords
        string video_path
        datetime created_at
    }

    ALERTS {
        int id PK
        string job_id FK
        string alert_type "'pedestrian' | 'vehicle'"
        string title "e.g. Crowd Threshold Exceeded"
        string description
        int frame_number
        string image_path
        datetime created_at
    }
```

---

## 8. Notification & Email Reporting

When a job completes processing:

1. [`app/services/job_manager.py`](backend/app/services/job_manager.py) spawns a background thread targeting `NotificationService.send_completion_email(job_id)`.
2. [`app/email/notification.py`](backend/app/email/notification.py) queries all alerts associated with the job and calculates pedestrian statistics:
   ```python
   pedestrian_alerts = sum(
       1 for alert in alerts if alert.alert_type.lower() == "pedestrian"
   )
   ```
3. [`app/email/email_template.py`](backend/app/email/email_template.py) formats an HTML report containing:
   - Total Pedestrian Crowd Alerts triggered.
   - Direct image attachments / links for snapshot evidence.
   - Job metadata and overall status.

---

## 9. Intern Onboarding & Debugging Guide

### 9.1 Local Environment Setup

1. **Verify Weights File**: Ensure `models/pedestrian.pt` is present in the repository root directory.
2. **Environment Variables**: Verify `.env` configuration:
   ```ini
   DATABASE_URL=postgresql://user:pass@localhost:5432/anpr_db
   SECRET_KEY=your_jwt_secret_key
   ```

### 9.2 Tracing a Pedestrian Bug Step-by-Step

If pedestrian detection or alerting is failing in a job, follow this step-by-step diagnostic workflow:

```mermaid
flowchart TD

    Step1["Check Job JSON Config"]
    Step2["Check ROI Coordinates"]
    Step3["Inspect Terminal Logs"]
    Step4["Check Alert Media Directory"]
    Step5["Inspect Database Alerts"]

    Step1 -->|"Verify pedestrian = true"| Step2
    Step2 -->|"Verify valid ROI polygon"| Step3
    Step3 -->|"Look for Persons count"| Step4
    Step4 -->|"Inspect media/alerts/JOB_ID/"| Step5
```

1. **Check `analysis_config`**: Query the DB or check the upload API request to ensure `"pedestrian": true` was sent.
2. **Verify ROI Format**: Inspect `job.roi_coords`. It must be a valid JSON array of points `[[x1,y1], [x2,y2], ...]`.
3. **Terminal Output**: Check the backend console output while pipeline runs:
   ```text
   [INFO] Frame 120 | Vehicles: 2 | Persons: 14
   ```
4. **Inspect Alert Images**: Check `media/alerts/{job_id}/` to verify whether JPEGs are being rendered and saved to disk properly.
5. **Database Query**: Run SQL to inspect generated alerts:
   ```sql
   SELECT id, alert_type, title, description, frame_number, image_path
   FROM alerts
   WHERE job_id = 'YOUR_JOB_ID' AND alert_type = 'pedestrian';
   ```

---
