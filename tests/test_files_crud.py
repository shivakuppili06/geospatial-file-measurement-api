def test_list_files_pagination(client, sample_kml_bytes):
    for _ in range(3):
        client.post(
            "/api/files/",
            files={"file": ("survey.kml", sample_kml_bytes, "application/vnd.google-earth.kml+xml")},
        )

    resp = client.get("/api/files/", params={"limit": 2, "offset": 0})
    assert resp.status_code == 200
    body = resp.json()
    assert body["limit"] == 2
    assert len(body["items"]) == 2
    assert body["total"] >= 3


def test_list_files_status_filter(client, sample_kml_bytes):
    client.post(
        "/api/files/",
        files={"file": ("survey.kml", sample_kml_bytes, "application/vnd.google-earth.kml+xml")},
    )
    resp = client.get("/api/files/", params={"status": "COMPLETED"})
    assert resp.status_code == 200
    for item in resp.json()["items"]:
        assert item["status"] == "COMPLETED"


def test_delete_file(client, sample_kml_bytes):
    upload = client.post(
        "/api/files/",
        files={"file": ("survey.kml", sample_kml_bytes, "application/vnd.google-earth.kml+xml")},
    )
    file_id = upload.json()["id"]

    del_resp = client.delete(f"/api/files/{file_id}/")
    assert del_resp.status_code == 204

    get_resp = client.get(f"/api/files/{file_id}/")
    assert get_resp.status_code == 404


def test_delete_nonexistent_file_404(client):
    resp = client.delete("/api/files/doesnotexist/")
    assert resp.status_code == 404
