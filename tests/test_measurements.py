def _upload_and_wait(client, filename, content, content_type):
    resp = client.post("/api/files/", files={"file": (filename, content, content_type)})
    assert resp.status_code == 202
    return resp.json()["id"]


def test_measurements_not_ready_returns_409(client, sample_kml_bytes, monkeypatch):
    # Upload then immediately hit measurements before forcing completion is hard
    # to simulate with synchronous background tasks, so instead we assert the
    # 409 contract directly against a file we mark PROCESSING after the fact.
    file_id = _upload_and_wait(client, "survey.kml", sample_kml_bytes, "application/vnd.google-earth.kml+xml")

    from app import models
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        geo_file = db.query(models.GeoFile).filter(models.GeoFile.id == file_id).first()
        geo_file.status = "PROCESSING"
        db.commit()
    finally:
        db.close()

    resp = client.get(f"/api/files/{file_id}/measurements/")
    assert resp.status_code == 409


def test_polygon_area_is_computed_in_projected_crs(client, sample_shapefile_zip_bytes):
    file_id = _upload_and_wait(client, "plots.zip", sample_shapefile_zip_bytes, "application/zip")
    resp = client.get(f"/api/files/{file_id}/measurements/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["feature_count"] == 2

    for feat in body["features"]:
        assert feat["geometry_type"] == "Polygon"
        assert feat["measurement_supported"] is True
        assert feat["measurement_type"] == "area"
        assert feat["unit"] == "square_meters"
        # A ~0.01deg x 0.01deg square is roughly 1.1km x 1.1km near the
        # equator -> area should be on the order of 1.0-1.5 million sqm,
        # NOT ~0.0001 (which is what raw degree-based area would give).
        assert feat["value"] > 100_000
        assert feat["projected_crs"] is not None
        assert "4326" not in feat["projected_crs"]  # must be reprojected


def test_linestring_length_and_point_unsupported(client, sample_kml_bytes):
    file_id = _upload_and_wait(client, "survey.kml", sample_kml_bytes, "application/vnd.google-earth.kml+xml")
    resp = client.get(f"/api/files/{file_id}/measurements/")
    assert resp.status_code == 200
    features = resp.json()["features"]

    by_type = {f["geometry_type"]: f for f in features}

    assert by_type["LineString"]["measurement_supported"] is True
    assert by_type["LineString"]["measurement_type"] == "length"
    assert by_type["LineString"]["unit"] == "meters"
    assert by_type["LineString"]["value"] > 0

    assert by_type["Point"]["measurement_supported"] is False
    assert by_type["Point"]["measurement_type"] is None
    assert by_type["Point"]["value"] is None


def test_measurements_filter_by_geometry_type(client, sample_kml_bytes):
    file_id = _upload_and_wait(client, "survey.kml", sample_kml_bytes, "application/vnd.google-earth.kml+xml")
    resp = client.get(f"/api/files/{file_id}/measurements/", params={"geometry_type": "Polygon"})
    assert resp.status_code == 200
    features = resp.json()["features"]
    assert len(features) == 1
    assert features[0]["geometry_type"] == "Polygon"
