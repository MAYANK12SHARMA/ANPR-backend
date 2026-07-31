import os
import cv2

from app.db.models import Alert

ALERT_DIR = "media/alerts"

os.makedirs(ALERT_DIR, exist_ok=True)

ALERT_COOLDOWN_FRAMES = 5


def create_alert(
    db,
    job_id: str,
    alert_type: str,
    title: str,
    description: str,
    frame=None,
    frame_number=None,
):
    """
    Create an alert and optionally save a snapshot image.
    """

    image_path = None

    # Save snapshot if frame is provided
    if frame is not None:

        job_alert_dir = os.path.join(ALERT_DIR, job_id)
        os.makedirs(job_alert_dir, exist_ok=True)

        filename = f"{alert_type}_{frame_number}.jpg"

        image_path = os.path.join(job_alert_dir, filename)

        cv2.imwrite(image_path, frame)

    alert = Alert(
        job_id=job_id,
        alert_type=alert_type,
        title=title,
        description=description,
        frame_number=frame_number,
        image_path=image_path,
    )

    existing = (
        db.query(Alert)
        .filter(
            Alert.job_id == job_id,
            Alert.alert_type == alert_type,
            Alert.frame_number >= frame_number - ALERT_COOLDOWN_FRAMES,
        )
        .first()
    )

    if existing:
        return existing

    db.add(alert)
    db.commit()

    return alert
