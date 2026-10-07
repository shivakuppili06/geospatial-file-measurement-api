def test_upload_kml_success(client, sample_kml_bytes):
    resp = client.post(
        "/api/files/",
        files={"file": ("survey.kml", sample_kml_bytes, "application/vnd.google-earth.kml+xml")},
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["filename"] == "survey.kml"
    assert data["status"] in ("PROCESSING", "COMPLETED")

    # Poll (TestClient runs background tasks synchronously, so it should
    # already be COMPLETED, but poll defensively)
    file_id = data["id"]
    info = client.get(f"/api/files/{file_id}/").json()
    assert info["status"] == "COMPLETED"
    assert info["feature_count"] == 3
    assert info["crs"] is not None


def test_upload_shapefile_zip_success(client, sample_shapefile_zip_bytes):
    resp = client.post(
        "/api/files/",
        files={"file": ("plots.zip", sample_shapefile_zip_bytes, "application/zip")},
    )
    assert resp.status_code == 202
    file_id = resp.json()["id"]
    info = client.get(f"/api/files/{file_id}/").json()
    assert info["status"] == "COMPLETED"
    assert info["feature_count"] == 2


def test_upload_rejects_unsupported_extension(client):
    resp = client.post(
        "/api/files/",
        files={"file": ("notes.txt", b"hello world", "text/plain")},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert "error" in body
    assert "Unsupported file type" in body["detail"]


def test_upload_rejects_empty_file(client):
    resp = client.post(
        "/api/files/",
        files={"file": ("empty.kml", b"", "application/vnd.google-earth.kml+xml")},
    )
    assert resp.status_code == 400


def test_upload_invalid_zip_marks_file_failed(client, invalid_zip_bytes):
    resp = client.post(
        "/api/files/",
        files={"file": ("bad.zip", invalid_zip_bytes, "application/zip")},
    )
    assert resp.status_code == 202
    file_id = resp.json()["id"]
    info = client.get(f"/api/files/{file_id}/").json()
    assert info["status"] == "FAILED"
    assert info["error_message"] is not None


def test_get_file_info_404(client):
    resp = client.get("/api/files/doesnotexist/")
    assert resp.status_code == 404
    assert resp.json()["error"] == "HTTPException"
