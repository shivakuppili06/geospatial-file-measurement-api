"""
Core geospatial processing logic:
- Reads Shapefile (.zip) or KML files
- Extracts features + original CRS
- Picks an appropriate projected CRS (UTM zone based on centroid) for
  accurate area/length measurement
- Computes area (sq meters) for polygons, length (meters) for lines
"""
import json
import os
import zipfile

import geopandas as gpd


class GeoProcessingError(Exception):
    """Raised for any user-facing geospatial processing failure."""


SUPPORTED_MEASUREMENT_TYPES = {
    "Polygon": "area",
    "MultiPolygon": "area",
    "LineString": "length",
    "MultiLineString": "length",
}


def utm_crs_for_bounds(gdf: gpd.GeoDataFrame) -> str:
    """
    Pick a projected CRS appropriate for accurate measurement.
    Strategy: estimate UTM zone from the data's centroid (in EPSG:4326),
    using GeoPandas' built-in UTM estimation utility.
    """
    try:
        estimated = gdf.estimate_utm_crs()
        if estimated is not None:
            return estimated.to_string()
    except Exception:
        pass
    # Fallback: World Mercator (not ideal for area, but better than raw degrees)
    return "EPSG:3395"


def _validate_shapefile_zip(file_path: str) -> None:
    """Ensure the zip actually contains the mandatory Shapefile components."""
    try:
        with zipfile.ZipFile(file_path) as zf:
            names = {os.path.splitext(n)[1].lower() for n in zf.namelist()}
    except zipfile.BadZipFile as exc:
        raise GeoProcessingError("Uploaded file is not a valid zip archive.") from exc

    required = {".shp", ".shx", ".dbf"}
    missing = required - names
    if missing:
        raise GeoProcessingError(
            f"Zip archive is missing required Shapefile component(s): {', '.join(sorted(missing))}"
        )


def load_vector_file(file_path: str, filename: str) -> gpd.GeoDataFrame:
    """
    Load a Shapefile (.zip) or KML file into a GeoDataFrame.
    """
    lower = filename.lower()

    try:
        if lower.endswith(".zip"):
            _validate_shapefile_zip(file_path)
            # geopandas can read directly from a zip using the "zip://" prefix
            gdf = gpd.read_file(f"zip://{file_path}")
        elif lower.endswith(".kml"):
            # pyogrio (geopandas>=1.0 default engine) reads KML natively;
            # pass engine="pyogrio" explicitly to bypass any legacy fiona path
            gdf = gpd.read_file(file_path, driver="KML", engine="pyogrio")
        else:
            raise GeoProcessingError(
                "Unsupported file type. Only .zip (Shapefile) and .kml are supported."
            )
    except GeoProcessingError:
        raise
    except Exception as exc:
        # Wrap raw GDAL/pyogrio exceptions with a clean, user-facing message
        raise GeoProcessingError(f"Failed to read geospatial file: {exc}") from exc

    if gdf.empty:
        raise GeoProcessingError("No features found in the uploaded file.")

    if gdf.crs is None:
        # Assume WGS84 if no CRS is defined (common for KML)
        gdf.set_crs(epsg=4326, inplace=True)

    return gdf


def process_file(file_path: str, filename: str) -> dict[str, object]:
    """
    Main processing entrypoint. Returns a dict with:
      - original_crs
      - feature_count
      - features: list of dicts ready to persist
    """
    gdf = load_vector_file(file_path, filename)
    original_crs = gdf.crs.to_string() if gdf.crs else None

    projected_crs = utm_crs_for_bounds(gdf)
    gdf_projected = gdf.to_crs(projected_crs)

    features = []
    for idx, (orig_row, proj_row) in enumerate(zip(gdf.itertuples(), gdf_projected.itertuples(), strict=False)):
        geom = orig_row.geometry
        proj_geom = proj_row.geometry
        geom_type = geom.geom_type if geom is not None else "Unknown"

        measurement_type = SUPPORTED_MEASUREMENT_TYPES.get(geom_type)
        value = None
        unit = None
        supported = measurement_type is not None

        if measurement_type == "area" and proj_geom is not None:
            value = round(proj_geom.area, 4)
            unit = "square_meters"
        elif measurement_type == "length" and proj_geom is not None:
            value = round(proj_geom.length, 4)
            unit = "meters"

        properties = {
            col: getattr(orig_row, col)
            for col in gdf.columns
            if col != "geometry"
        }
        # Ensure JSON-serializable
        properties = json.loads(json.dumps(properties, default=str))

        features.append({
            "feature_index": idx,
            "geometry_type": geom_type,
            "geometry_geojson": json.dumps(geom.__geo_interface__ if geom else None),
            "properties_json": json.dumps(properties),
            "measurement_supported": 1 if supported else 0,
            "measurement_type": measurement_type,
            "measurement_value": value,
            "measurement_unit": unit,
            "projected_crs": projected_crs if supported else None,
        })

    return {
        "original_crs": original_crs,
        "feature_count": len(features),
        "features": features,
    }
