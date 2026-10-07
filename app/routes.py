import json
import os

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app import models, schemas
from app.config import settings
from app.database import get_db
from app.logging_config import logger
from app.services import process_uploaded_file

router = APIRouter(prefix="/api/files", tags=["files"])


@router.post("/", response_model=schemas.FileInfoResponse, status_code=202)
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in settings.allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Only {settings.allowed_extensions} are accepted.",
        )

    # Enforce size limit by streaming/measuring before full read
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    contents = await file.read()
    if len(contents) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds maximum allowed size of {settings.max_upload_size_mb}MB.",
        )
    if len(contents) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    geo_file = models.GeoFile(filename=file.filename, status="PROCESSING")
    db.add(geo_file)
    db.commit()
    db.refresh(geo_file)

    # Save to temp synchronously (cheap), process in background (expensive)
    import tempfile
    tmp_dir = tempfile.mkdtemp()
    tmp_path = os.path.join(tmp_dir, file.filename)
    with open(tmp_path, "wb") as f:
        f.write(contents)

    logger.info("Accepted upload geo_file=%s filename=%s size=%d", geo_file.id, file.filename, len(contents))
    background_tasks.add_task(process_uploaded_file, geo_file.id, tmp_path, file.filename)

    return geo_file


@router.get("/", response_model=schemas.PaginatedFiles)
def list_files(
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status_filter: str | None = Query(None, alias="status"),
    db: Session = Depends(get_db),
):
    q = db.query(models.GeoFile)
    if status_filter:
        q = q.filter(models.GeoFile.status == status_filter.upper())
    total = q.count()
    items = q.order_by(models.GeoFile.created_at.desc()).offset(offset).limit(limit).all()
    return schemas.PaginatedFiles(total=total, limit=limit, offset=offset, items=items)


@router.get("/{file_id}/", response_model=schemas.FileInfoResponse)
def get_file_info(file_id: str, db: Session = Depends(get_db)):
    geo_file = db.query(models.GeoFile).filter(models.GeoFile.id == file_id).first()
    if not geo_file:
        raise HTTPException(status_code=404, detail="File not found")
    return geo_file


@router.delete("/{file_id}/", status_code=204)
def delete_file(file_id: str, db: Session = Depends(get_db)):
    geo_file = db.query(models.GeoFile).filter(models.GeoFile.id == file_id).first()
    if not geo_file:
        raise HTTPException(status_code=404, detail="File not found")
    db.delete(geo_file)  # cascades to features
    db.commit()
    logger.info("Deleted geo_file=%s", file_id)
    return None


@router.get("/{file_id}/measurements/", response_model=schemas.MeasurementsResponse)
def get_measurements(
    file_id: str,
    geometry_type: str | None = Query(None, description="Filter by geometry type, e.g. Polygon"),
    db: Session = Depends(get_db),
):
    geo_file = db.query(models.GeoFile).filter(models.GeoFile.id == file_id).first()
    if not geo_file:
        raise HTTPException(status_code=404, detail="File not found")
    if geo_file.status != "COMPLETED":
        raise HTTPException(
            status_code=409,
            detail=f"File is not ready for measurements (status={geo_file.status})",
        )

    q = db.query(models.Feature).filter(models.Feature.geo_file_id == file_id)
    if geometry_type:
        q = q.filter(models.Feature.geometry_type == geometry_type)
    features = q.order_by(models.Feature.feature_index).all()

    feature_list = [
        schemas.FeatureMeasurement(
            feature_id=f.feature_index,
            geometry_type=f.geometry_type,
            measurement_supported=bool(f.measurement_supported),
            measurement_type=f.measurement_type,
            value=f.measurement_value,
            unit=f.measurement_unit,
            projected_crs=f.projected_crs,
            properties=json.loads(f.properties_json) if f.properties_json else None,
        )
        for f in features
    ]

    return schemas.MeasurementsResponse(
        file_id=geo_file.id,
        feature_count=len(feature_list),
        features=feature_list,
    )
