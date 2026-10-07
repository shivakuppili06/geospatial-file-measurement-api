from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class FileInfoResponse(BaseModel):
    id: str
    filename: str
    feature_count: int
    crs: Optional[str]
    status: str
    error_message: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class FeatureMeasurement(BaseModel):
    feature_id: int
    geometry_type: str
    measurement_supported: bool
    measurement_type: Optional[str] = None
    value: Optional[float] = None
    unit: Optional[str] = None
    projected_crs: Optional[str] = None
    properties: Optional[dict] = None


class MeasurementsResponse(BaseModel):
    file_id: str
    feature_count: int
    features: list[FeatureMeasurement]


class ErrorResponse(BaseModel):
    error: str
    detail: str
    request_id: Optional[str] = None


class PaginatedFiles(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[FileInfoResponse]
