import cv2
from ultralytics import YOLO

from app.ai.colors import FOOT_COLOR, OUTSIDE_COLOR, PERSON_COLOR, ROI_COLOR

# Load once when backend starts
model = YOLO("models/pedestrian.pt")

# COCO classes
PERSON_CLASS = 0
VEHICLE_CLASSES = [1, 2, 3, 5, 7]


def detect_pedestrians(
    frame,
    display_frame,
    roi_polygon=None,
):
    """
    Detect and analyze pedestrians.

    Returns:
    {
        "person_count": int,
        "persons": list
    }
    """

    results = model.track(
        frame,
        persist=True,
        classes=[0, 1, 2, 3, 5, 7],
        verbose=False,
    )

    # Draw ROI
    if roi_polygon is not None:
        cv2.polylines(
            display_frame,
            [roi_polygon],
            True,
            ROI_COLOR,
            2,
        )

    person_boxes = []
    vehicle_boxes = []

    # ---------------------------------
    # Separate persons and vehicles
    # ---------------------------------

    for r in results:

        boxes = r.boxes

        if boxes is None:
            continue

        if boxes.id is None:
            continue

        track_ids = boxes.id.int().cpu().tolist()

        for box, track_id in zip(boxes, track_ids):

            cls = int(box.cls[0])

            x1, y1, x2, y2 = map(int, box.xyxy[0])

            bbox = [x1, y1, x2, y2]

            if cls == PERSON_CLASS:

                person_boxes.append(
                    {
                        "track_id": track_id,
                        "bbox": bbox,
                    }
                )

            elif cls in VEHICLE_CLASSES:

                vehicle_boxes.append(bbox)

    # ---------------------------------
    # Process pedestrians
    # ---------------------------------

    person_count = 0

    detected_persons = []

    for person in person_boxes:

        track_id = person["track_id"]

        x1, y1, x2, y2 = person["bbox"]

        foot_x = (x1 + x2) // 2
        foot_y = y2

        # -----------------------------
        # Rider filtering
        # -----------------------------

        riding_vehicle = False

        for vx1, vy1, vx2, vy2 in vehicle_boxes:

            if vx1 <= foot_x <= vx2 and vy1 <= foot_y <= vy2:

                riding_vehicle = True

                break

        if riding_vehicle:
            continue

        # -----------------------------
        # ROI check
        # -----------------------------

        inside_roi = True

        if roi_polygon is not None:

            inside = cv2.pointPolygonTest(
                roi_polygon,
                (float(foot_x), float(foot_y)),
                False,
            )

            inside_roi = inside >= 0

        if inside_roi:

            person_count += 1

            color = PERSON_COLOR

        else:

            color = OUTSIDE_COLOR
        # -----------------------------
        # Draw
        # -----------------------------

        cv2.rectangle(
            display_frame,
            (x1, y1),
            (x2, y2),
            color,
            2,
        )

        cv2.putText(
            display_frame,
            f"ID:{track_id}",
            (x1, max(y1 - 10, 0)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            color,
            2,
        )

        cv2.circle(
            display_frame,
            (foot_x, foot_y),
            5,
            FOOT_COLOR,
            -1,
        )

        detected_persons.append(
            {
                "track_id": track_id,
                "bbox": [x1, y1, x2, y2],
                "foot_point": [foot_x, foot_y],
                "inside_roi": inside_roi,
            }
        )

    # ---------------------------------
    # Crowd Count
    # ---------------------------------

    cv2.putText(
        display_frame,
        f"Persons Inside ROI : {person_count}",
        (20, 40),
        cv2.FONT_HERSHEY_SIMPLEX,
        1,
        ROI_COLOR,
        3,
    )

    return {
        "person_count": person_count,
        "persons": detected_persons,
    }
