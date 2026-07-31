import queue

from app.db.database import SessionLocal
from app.db.models import Job
from app.ai.pipeline_with_tracking import run_pipeline_with_tracking


def process_job(job_id: str, frame_queue: queue.Queue | None = None):
    db = SessionLocal()
    job = db.query(Job).filter(Job.job_id == job_id).first()

    if not job:
        db.close()
        return

    try:
        job.status = "processing"
        db.commit()

        source_path = job.video_path
        if job.job_type == "camera_stream":
            source_path = job.camera_rtsp_url or job.video_path

        if not source_path:
            raise Exception("No valid source path found for job")

        analysis_config = job.analysis_config

        run_pipeline_with_tracking(
            job_id,
            source_path,
            db,
            frame_queue=frame_queue,
            analysis_config=analysis_config,
        )

        db.refresh(job)
        if job.status != "stopped":
            job.status = "completed"
        job.is_live = "false"
        db.commit()

    except Exception as e:
        job.status = "failed"
        job.is_live = "false"
        db.commit()

        print(f"[ERROR] Job {job_id} failed: {e}")
    finally:
        db.close()
