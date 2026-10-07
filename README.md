# Geospatial File Measurement API

A FastAPI backend that accepts Shapefiles (`.zip`) or KML files, extracts
features, and returns area/length measurements computed in an appropriate
projected coordinate system. Processing runs as a background task so uploads
return immediately; clients poll for completion.

## Setup

### Option A: Local virtualenv

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements-dev.txt   # includes test/lint tooling
```

> Note: `fiona`/`geopandas` depend on GDAL. If installation fails on your OS,
> install GDAL system libraries first (e.g. `apt install gdal-bin libgdal-dev`
> on Ubuntu, or use `conda install -c conda-forge geopandas`).

### Option B: Docker

```bash
docker compose up --build
```

The API will be available at http://localhost:8000. By default it uses a
SQLite file persisted in a named Docker volume. A commented-out Postgres/PostGIS
service is included in `docker-compose.yml` — uncomment it and swap
`GEOAPI_DATABASE_URL` to point at it if you'd rather not use SQLite.

## Run (local)

```bash
uvicorn app.main:app --reload
```

API docs (Swagger UI): http://127.0.0.1:8000/docs

## Configuration

Environment variables (prefix `GEOAPI_`), all optional:

| Variable                     | Default                     | Description                          |
|------------------------------|------------------------------|---------------------------------------|
| `GEOAPI_DATABASE_URL`        | `sqlite:///./geo_files.db`  | SQLAlchemy connection string          |
| `GEOAPI_MAX_UPLOAD_SIZE_MB`  | `25`                         | Max accepted upload size              |
| `GEOAPI_LOG_LEVEL`           | `INFO`                       | Python logging level                  |

## Testing

```bash
pip install -r requirements-dev.txt
pytest -v
```

14 tests cover: successful KML/Shapefile upload, unsupported file type
rejection, empty-file rejection, malformed-zip handling (marks job FAILED,
doesn't crash), area accuracy in a projected CRS, length calculation,
Point/unsupported-geometry graceful handling, 404s on unknown file IDs, 409
when measurements are requested before processing completes, pagination,
status filtering, geometry-type filtering, and delete.

Tests use FastAPI's `TestClient`, a dedicated SQLite test database
(torn down after the session), and in-memory-generated sample KML/Shapefile
fixtures (no external test data files needed).

## API

### Upload a file
```
POST /api/files/
Content-Type: multipart/form-data
Body: file=<survey.kml | parcels.zip>
```
Returns **202 Accepted** immediately — processing happens in the background:
```json
{
  "id": "abc123def456",
  "filename": "survey.kml",
  "feature_count": 0,
  "crs": null,
  "status": "PROCESSING",
  "error_message": null,
  "created_at": "2026-10-08T10:00:00Z"
}
```
Poll `GET /api/files/{id}/` until `status` becomes `COMPLETED` or `FAILED`.

### List files
```
GET /api/files/?limit=20&offset=0&status=COMPLETED
```
```json
{
  "total": 42,
  "limit": 20,
  "offset": 0,
  "items": [ { "...": "FileInfoResponse" } ]
}
```

### Get file info
```
GET /api/files/{id}/
```
```json
{
  "id": "abc123def456",
  "filename": "survey.kml",
  "feature_count": 120,
  "crs": "EPSG:4326",
  "status": "COMPLETED",
  "error_message": null,
  "created_at": "2026-10-08T10:00:00Z"
}
```

### Get measurements
```
GET /api/files/{id}/measurements/?geometry_type=Polygon
```
`geometry_type` is optional and filters results.
```json
{
  "file_id": "abc123def456",
  "feature_count": 2,
  "features": [
    {
      "feature_id": 0,
      "geometry_type": "Polygon",
      "measurement_supported": true,
      "measurement_type": "area",
      "value": 15234.87,
      "unit": "square_meters",
      "projected_crs": "EPSG:32644",
      "properties": {"name": "Plot A"}
    },
    {
      "feature_id": 1,
      "geometry_type": "Point",
      "measurement_supported": false,
      "measurement_type": null,
      "value": null,
      "unit": null,
      "projected_crs": null,
      "properties": {"name": "Marker 1"}
    }
  ]
}
```
Returns **409** if the file's status is not yet `COMPLETED`.

### Delete a file
```
DELETE /api/files/{id}/
```
Returns **204** on success; cascades to delete associated features.

### Errors
All errors (4xx/5xx) share a consistent JSON shape, with a request ID
(also echoed in the `X-Request-ID` response header) for log correlation:
```json
{ "error": "HTTPException", "detail": "File not found", "request_id": "a1b2c3d4" }
```

## Architecture

**Structure**
- `app/main.py` — app factory, middleware, global exception handlers
- `app/routes.py` — all API endpoints (`APIRouter`)
- `app/services.py` — background processing orchestration (own DB session)
- `app/geo_processing.py` — file parsing, CRS reprojection, measurement logic
- `app/models.py` — SQLAlchemy models (`GeoFile`, `Feature`)
- `app/schemas.py` — Pydantic request/response schemas
- `app/database.py` — SQLAlchemy engine/session setup
- `app/config.py` — `pydantic-settings`-based configuration
- `app/logging_config.py` — structured logging setup
- `tests/` — pytest suite with in-memory-generated sample files

**File-processing flow**
1. Client uploads a `.zip` (Shapefile) or `.kml` file.
2. Request handler validates extension, size (configurable limit), and that
   the file isn't empty — fast-failing before any DB/background work.
3. A `GeoFile` row is created with status `PROCESSING`; file bytes are
   written to a temp path; the response returns **202** immediately.
4. A FastAPI `BackgroundTask` picks up the temp file, opens its own DB
   session (the request's session is closed by the time the task runs),
   and calls into `geo_processing.process_file`.
5. GeoPandas reads the file (`zip://` prefix for Shapefiles after validating
   `.shp`/`.shx`/`.dbf` are present; `KML` driver for KML).
6. On success, status becomes `COMPLETED`, features are persisted, and the
   temp directory is cleaned up. On any failure — bad zip, corrupt geometry,
   unreadable file — status becomes `FAILED` with a clear `error_message`,
   never a raw stack trace, and the client discovers this by polling
   `GET /api/files/{id}/`.

**Measurement calculation flow**
1. The original CRS is read from the file (defaults to `EPSG:4326` if
   absent, common for KML).
2. An appropriate projected CRS is chosen via
   `GeoDataFrame.estimate_utm_crs()`, which picks the UTM zone matching the
   data's location — this keeps area/length accurate and local rather than
   using a single global projection that distorts far from its origin.
3. Geometries are reprojected (`to_crs`) into that UTM CRS.
4. Area (`Polygon`/`MultiPolygon`) and length (`LineString`/
   `MultiLineString`) are computed from the *projected* geometry, never from
   raw lat/lon degrees.
5. `Point` and unsupported geometry types are marked
   `measurement_supported: false` rather than causing an error.
6. The `measurements` endpoint supports an optional `geometry_type` filter.

**CRS handling**
- Never compute area/length directly on EPSG:4326 (or other geographic)
  coordinates.
- Use per-file UTM zone auto-detection (`estimate_utm_crs`) instead of a
  single fixed projection, so results stay accurate regardless of where in
  the world the data is.
- Fallback to `EPSG:3395` (World Mercator) if UTM estimation fails for any
  reason, so processing never hard-crashes on CRS issues.

## Design Decisions

- **Background tasks over Celery**: FastAPI's `BackgroundTasks` is enough
  for this workload (single-process, moderate file sizes, no retry/priority
  queue needed) and keeps the submission dependency-light (no Redis/broker).
  The processing function lives in `services.py` with its own DB session, so
  swapping to Celery later is a matter of changing *how* the function is
  invoked, not its logic — genuinely a drop-in replacement. For high-volume
  production use with large files or horizontal scaling, Celery + Redis (or
  RQ) would be the next step, with the same `PROCESSING → COMPLETED/FAILED`
  status contract already in place for polling.
- **SQLite by default** for zero-setup; swappable for Postgres by changing
  `GEOAPI_DATABASE_URL` — the SQLAlchemy models don't need to change. A
  commented Postgres/PostGIS service is in `docker-compose.yml`.
- **GeoJSON stored as text** for each feature's geometry rather than a
  spatial column type, to keep the dependency footprint minimal (no
  PostGIS requirement) while still being fully queryable/parseable.
- **Request-scoped error schema + request ID**: global exception handlers
  normalize all error responses (`error`/`detail`/`request_id`) and a
  middleware stamps every request with an ID (returned in `X-Request-ID`),
  making it possible to correlate a client-reported error with the exact
  server log line.
- **Zip content validation before GDAL read**: checking for `.shp`/`.shx`/
  `.dbf` presence up front gives a precise, actionable error message instead
  of a generic GDAL driver failure buried in a traceback.
- **mypy non-blocking in CI**: SQLAlchemy 2.0's declarative `Column[T]`
  attributes don't fully satisfy static analysis without `Mapped[]`
  annotations throughout; rather than do a large typing refactor under
  submission time constraints, mypy runs in CI for visibility but doesn't
  block merges. Documented here rather than silently ignored.

## Learnings & Future Scope

- Learned how UTM zone selection materially affects area/length accuracy
  for geographic-CRS source data, and why a single projection (e.g. Web
  Mercator) is unsuitable for precise measurement across large extents.
- Learned the practical difference between synchronous and background
  request handling in FastAPI, and how to structure a service layer so the
  same processing function can run under `BackgroundTasks` today and a real
  task queue later with minimal change.
- Future scope:
  - Swap to Celery + Redis (or RQ) for true out-of-process, retryable,
    horizontally-scalable processing.
  - PostGIS-backed geometry storage for spatial queries (bounding box
    search, intersection, etc.) instead of GeoJSON-as-text.
  - Support for GeoJSON and GPX as additional input formats.
  - Authentication/ownership of uploaded files, with per-user file listing.
  - `Mapped[]`-typed SQLAlchemy models for full mypy strictness.
  - WebSocket or SSE endpoint for live processing-status push instead of
    polling.
