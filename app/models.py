import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


def gen_id():
    return uuid.uuid4().hex[:12]


class GeoFile(Base):
    __tablename__ = "geo_files"

    id = Column(String, primary_key=True, default=gen_id)
    filename = Column(String, nullable=False)
    original_crs = Column(String, nullable=True)
    feature_count = Column(Integer, default=0)
    status = Column(String, default="PROCESSING")  # PROCESSING, COMPLETED, FAILED
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    features = relationship(
        "Feature", back_populates="geo_file", cascade="all, delete-orphan"
    )

    @property
    def crs(self) -> str | None:
        """Alias so the API response field `crs` maps to `original_crs`."""
        return self.original_crs


class Feature(Base):
    __tablename__ = "features"

    id = Column(Integer, primary_key=True, autoincrement=True)
    geo_file_id = Column(String, ForeignKey("geo_files.id"), nullable=False)
    feature_index = Column(Integer, nullable=False)
    geometry_type = Column(String, nullable=False)
    geometry_geojson = Column(Text, nullable=False)
    properties_json = Column(Text, nullable=True)

    measurement_supported = Column(Integer, default=0)  # 0/1 boolean
    measurement_type = Column(String, nullable=True)  # "area" | "length" | None
    measurement_value = Column(Float, nullable=True)
    measurement_unit = Column(String, nullable=True)
    projected_crs = Column(String, nullable=True)

    geo_file = relationship("GeoFile", back_populates="features")
