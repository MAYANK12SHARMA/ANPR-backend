import torch
from ultralytics import YOLO

# Load model once
device = "cuda" if torch.cuda.is_available() else "cpu"

vehicle_model = YOLO("models/vehicle.pt")
vehicle_model.to(device)

VEHICLE_CONF_THRESHOLD = 0.65

def detect_vehicles(frame):
    results = vehicle_model(frame, conf=VEHICLE_CONF_THRESHOLD, verbose=False)[0]

    detections = []

    for box in results.boxes:
        x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
        conf = float(box.conf[0])
        cls_id = int(box.cls[0])
        label = results.names[cls_id]

        detections.append({
            "bbox": [x1, y1, x2, y2],
            "confidence": conf,
            "label": label
        })

    return detections
