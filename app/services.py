import os
import shutil
import tempfile
import time

from sqlalchemy.orm import Session

from app import models
from app.database import SessionLocal
from app.geo_processing import GeoProcessingError, process_file
from app.logging_config import logger


def process_uploaded_file(geo_file_id: str, tmp_path: str, filename: str) -> None:
    """
    Runs in a background task (own DB session, since the request's session
    is closed by the time this executes).
    """
    db: Session = SessionLocal()
    start = time.monotonic()
    try:
        geo_file = db.query(models.GeoFile).filter(models.GeoFile.id == geo_file_id).first()
        if not geo_file:
            logger.error("geo_file %s vanished before processing", geo_file_id)
            return

        try:
            result = process_file(tmp_path, filename)
        except GeoProcessingError as e:
            geo_file.status = "FAILED"
            geo_file.error_message = str(e)
            db.commit()
            logger.warning("Processing failed for %s: %s", geo_file_id, e)
            return
        except Exception as e:  # noqa: BLE001 - last-resort safety net
            geo_file.status = "FAILED"
            geo_file.error_message = f"Unexpected error: {e}"
            db.commit()
            logger.exception("Unexpected failure processing %s", geo_file_id)
            return

        geo_file.original_crs = result["original_crs"]
        geo_file.feature_count = result["feature_count"]
        geo_file.status = "COMPLETED"

        for feat in result["features"]:
            db.add(models.Feature(geo_file_id=geo_file.id, **feat))

        db.commit()
        duration = time.monotonic() - start
        logger.info(
            "Processed geo_file=%s filename=%s features=%d duration=%.2fs",
            geo_file_id, filename, result["feature_count"], duration,
        )
    finally:
        db.close()
        shutil.rmtree(os.path.dirname(tmp_path), ignore_errors=True)


def save_upload_to_temp(file_obj, filename: str) -> str:
    tmp_dir = tempfile.mkdtemp()
    tmp_path = os.path.join(tmp_dir, filename)
    with open(tmp_path, "wb") as f:
        shutil.copyfileobj(file_obj, f)
    return tmp_path
