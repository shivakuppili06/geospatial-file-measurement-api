import io
import os
import shutil
import tempfile
import zipfile

import geopandas as gpd
import pytest
from fastapi.testclient import TestClient
from shapely.geometry import Polygon

os.environ["GEOAPI_DATABASE_URL"] = "sqlite:///./test_geo_files.db"

from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _setup_test_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    db_path = "./test_geo_files.db"
    if os.path.exists(db_path):
        os.remove(db_path)


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture()
def sample_kml_bytes() -> bytes:
    """
    A KML with one ~1km x 1km square polygon (approx, near the equator-ish
    longitude span used purely for geometry, not geographic accuracy),
    one line, and one point — covering all three supported geometry
    handling paths.
    """
    kml = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>Square Plot</name>
      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>
              0.0,0.0,0 0.01,0.0,0 0.01,0.01,0 0.0,0.01,0 0.0,0.0,0
            </coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>
    <Placemark>
      <name>Access Road</name>
      <LineString>
        <coordinates>
          0.0,0.0,0 0.02,0.02,0
        </coordinates>
      </LineString>
    </Placemark>
    <Placemark>
      <name>Marker</name>
      <Point>
        <coordinates>0.005,0.005,0</coordinates>
      </Point>
    </Placemark>
  </Document>
</kml>
"""
    return kml.encode("utf-8")


@pytest.fixture()
def sample_shapefile_zip_bytes() -> bytes:
    """Build a small valid Shapefile zip in memory using geopandas."""
    gdf = gpd.GeoDataFrame(
        {"name": ["Plot A", "Plot B"]},
        geometry=[
            Polygon([(0, 0), (0, 0.01), (0.01, 0.01), (0.01, 0)]),
            Polygon([(1, 1), (1, 1.01), (1.01, 1.01), (1.01, 1)]),
        ],
        crs="EPSG:4326",
    )
    tmp_dir = tempfile.mkdtemp()
    try:
        shp_path = os.path.join(tmp_dir, "plots.shp")
        gdf.to_file(shp_path)

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for fname in os.listdir(tmp_dir):
                zf.write(os.path.join(tmp_dir, fname), arcname=fname)
        buf.seek(0)
        return buf.read()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.fixture()
def invalid_zip_bytes() -> bytes:
    """A zip that doesn't contain shapefile components."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("readme.txt", "not a shapefile")
    buf.seek(0)
    return buf.read()
