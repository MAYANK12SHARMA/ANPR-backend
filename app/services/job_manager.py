import queue
from threading import Thread

from app.ai.pipeline_with_tracking import run_pipeline_with_tracking
from app.db.database import SessionLocal
from app.db.models import Job
from app.email.notification import NotificationService


def process_job(
    job_id: str,
    frame_queue: queue.Queue | None = None,
):
    db = SessionLocal()

    job = db.query(Job).filter(Job.job_id == job_id).first()

    if job is None:
        db.close()
        return

    try:
        # -------------------------------------------------
        # Mark Job as Processing
        # -------------------------------------------------
        job.status = "processing"
        db.commit()

        # -------------------------------------------------
        # Determine Input Source
        # -------------------------------------------------
        source_path = job.video_path

        if job.job_type == "camera_stream":
            source_path = job.camera_rtsp_url or job.video_path

        if not source_path:
            raise ValueError("No valid source path found for job.")

        # -------------------------------------------------
        # Run AI Pipeline
        # -------------------------------------------------
        run_pipeline_with_tracking(
            job_id=job_id,
            video_path=source_path,
            db=db,
            frame_queue=frame_queue,
            analysis_config=job.analysis_config,
        )

        # -------------------------------------------------
        # Refresh Job
        # -------------------------------------------------
        db.refresh(job)

        if job.status != "stopped":
            job.status = "completed"

        # If is_live is a Boolean column
        job.is_live = False

        db.commit()
        db.refresh(job)

        print(f"[JOB] Processing completed: {job.job_id}")

        # -------------------------------------------------
        # Send Completion Email (Background Thread)
        # -------------------------------------------------
        Thread(
            target=NotificationService(db).send_completion_email,
            args=(job.job_id,),
            daemon=True,
        ).start()

        print(f"[EMAIL] Notification thread started for Job {job.job_id}")

    except Exception as e:
        job.status = "failed"
        job.is_live = False

        db.commit()

        print(f"[ERROR] Job {job_id} failed")
        print(e)

    finally:
        db.close()