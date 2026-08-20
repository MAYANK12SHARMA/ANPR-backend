import os
from datetime import datetime

from sqlalchemy.orm import Session

from app.auth.models import User
from app.db.models import (
    Alert,
    Job,
    Plate,
)

from app.email.email_sender import EmailSender
from app.email.email_template import build_completion_email


class NotificationService:
    """
    Handles notification-related business logic.

    - Load Job
    - Load Notification Users
    - Load Alerts
    - Load Plates
    - Calculate Statistics
    - Collect Attachment Paths

    Email sending will be implemented in Part 2.
    """

    def __init__(self, db: Session):
        self.db = db

    def _get_notification_users(self) -> list[User]:
        """
        Get all active users that have enabled
        processing completion emails.
        """

        return (
            self.db.query(User)
            .filter(
                User.is_active.is_(True),
                User.receive_processing_email.is_(True),
            )
            .order_by(User.full_name.asc())
            .all()
        )

    def _get_job(self, job_id: str) -> Job | None:
        """
        Get job details.
        """
        return self.db.query(Job).filter(Job.job_id == job_id).first()

    def _get_alerts(self, job_id: str) -> list[Alert]:
        """
        Get all alerts for a job.
        """
        return (
            self.db.query(Alert)
            .filter(Alert.job_id == job_id)
            .order_by(Alert.created_at.asc())
            .all()
        )

    def _get_plates(self, job_id: str) -> list[Plate]:
        """
        Get all detected plates for a job.
        """
        return self.db.query(Plate).filter(Plate.job_id == job_id).all()

    def _calculate_processing_time(
        self,
        job: Job,
    ) -> str:
        """
        Calculate processing duration.
        """

        if job.created_at is None or job.last_frame_processed_at is None:
            return "N/A"

        duration = job.last_frame_processed_at - job.created_at

        total_seconds = int(duration.total_seconds())

        hours = total_seconds // 3600

        minutes = (total_seconds % 3600) // 60

        seconds = total_seconds % 60

        if hours > 0:
            return f"{hours}h {minutes}m {seconds}s"

        return f"{minutes}m {seconds}s"

    def _collect_alert_images(
        self,
        alerts: list[Alert],
    ) -> list[str]:
        """
        Collect valid alert image paths.
        """

        image_paths = []

        for alert in alerts:

            if alert.image_path and os.path.exists(alert.image_path):
                image_paths.append(alert.image_path)

        return image_paths

    def _build_statistics(
        self,
        alerts: list[Alert],
        plates: list[Plate],
    ) -> dict:
        """
        Calculate all statistics required
        for the completion email.
        """

        total_alerts = len(alerts)

        total_plates = len(plates)

        total_vehicles = len(
            {plate.track_id for plate in plates if plate.track_id is not None}
        )

        pedestrian_alerts = sum(
            1 for alert in alerts if alert.alert_type.lower() == "pedestrian"
        )

        vehicle_alerts = sum(
            1 for alert in alerts if alert.alert_type.lower() == "vehicle"
        )

        return {
            "total_alerts": total_alerts,
            "total_plates": total_plates,
            "total_vehicles": total_vehicles,
            "total_pedestrians": pedestrian_alerts,
            "total_vehicle_alerts": vehicle_alerts,
        }

    def prepare_job_notification(
        self,
        job_id: str,
    ) -> dict | None:
        """
        Prepare all data required for
        sending the completion email.

        Email sending is intentionally
        NOT performed in Part 1.
        """

        job = self._get_job(job_id)

        if job is None:
            print(f"[EMAIL] Job '{job_id}' not found.")
            return None

        users = self._get_notification_users()

        if not users:
            print("[EMAIL] No users have enabled email notifications.")

        alerts = self._get_alerts(job_id)

        plates = self._get_plates(job_id)

        statistics = self._build_statistics(
            alerts,
            plates,
        )

        attachments = self._collect_alert_images(
            alerts,
        )

        processing_time = self._calculate_processing_time(
            job,
        )

        recipients = [
            {
                "id": user.id,
                "name": user.full_name,
                "email": user.email,
                "role": user.role.value,
            }
            for user in users
        ]

        notification_data = {
            "job": job,
            "recipients": recipients,
            "alerts": alerts,
            "plates": plates,
            "attachments": attachments,
            "processing_time": processing_time,
            "statistics": statistics,
            "generated_at": datetime.now(),
        }

        print(f"[EMAIL] Prepared notification for Job {job.job_id}")

        print(f"[EMAIL] Notification Users : {len(recipients)}")

        print(f"[EMAIL] Alerts : {statistics['total_alerts']}")

        print(f"[EMAIL] Attachments : {len(attachments)}")

        return notification_data

    def send_completion_email(
        self,
        job_id: str,
    ) -> bool:
        """
        Send completion email to all users
        who have enabled notifications.
        """

        notification_data = self.prepare_job_notification(job_id)

        if notification_data is None:
            return False

        job = notification_data["job"]
        recipients = notification_data["recipients"]
        if not recipients:
            print("[EMAIL] No recipients found. Skipping email sending.")
            return True
        attachments = notification_data["attachments"]
        processing_time = notification_data["processing_time"]
        statistics = notification_data["statistics"]

        sender = EmailSender()

        success = True

        for recipient in recipients:

            try:

                html = build_completion_email(
                    recipient_name=recipient["name"],
                    job_id=job.job_id,
                    total_vehicles=statistics["total_vehicles"],
                    total_plates=statistics["total_plates"],
                    total_pedestrians=statistics["total_pedestrians"],
                    total_alerts=statistics["total_alerts"],
                    processing_time=processing_time,
                    dashboard_url=None,
                )

                email_sent = sender.send_email(
                    recipients=[recipient["email"]],
                    subject=f"🚦 Video Processing Completed | {job.job_id}",
                    html_body=html,
                    attachments=attachments,
                )

                if email_sent:
                    print(f"[EMAIL] Successfully sent to {recipient['email']}")
                else:
                    success = False
                    print(f"[EMAIL] Failed to send to {recipient['email']}")

            except Exception as e:
                print(e)
                success = False

        print(f"[EMAIL ERROR] {recipient['email']} -> {e}")

        print("\n===================================")
        print(" EMAIL NOTIFICATION SUMMARY")
        print("===================================")
        print(f"Job ID            : {job.job_id}")
        print(f"Recipients        : {len(recipients)}")
        print(f"Alerts            : {statistics['total_alerts']}")
        print(f"Vehicles          : {statistics['total_vehicles']}")
        print(f"Plates            : {statistics['total_plates']}")
        print(f"Pedestrians       : {statistics['total_pedestrians']}")
        print(f"Attachments       : {len(attachments)}")
        print(f"Overall Status    : {'SUCCESS' if success else 'PARTIAL FAILURE'}")
        print("===================================\n")

        return success
