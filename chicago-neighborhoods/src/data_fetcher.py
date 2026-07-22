"""Fetch + cache raw data from the Chicago Data Portal, US Census ACS, and OSM Overpass.

Every function here is write-once cached to data/raw/: a cache hit skips the
network entirely, a miss (or force_refresh=True) fetches, caches, and returns.
Community Area boundaries are fetched once by the caller (main.py) and passed
into every function below that needs a spatial join or distance calc.
"""

import io
import json
import logging
import os
import time
import zipfile

import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import Point
from sodapy import Socrata

import config

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 5


def _retry(fn, description):
    """Personal-script-grade retry: linear backoff, MAX_RETRIES attempts."""
    last_exc = None
    for attempt in range(MAX_RETRIES):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - want to retry on anything network-shaped
            last_exc = exc
            wait = RETRY_BACKOFF_SECONDS * (attempt + 1)
            logger.warning(
                "%s failed (attempt %d/%d): %s — retrying in %ds",
                description, attempt + 1, MAX_RETRIES, exc, wait,
            )
            time.sleep(wait)
    raise RuntimeError(f"{description} failed after {MAX_RETRIES} attempts") from last_exc


def _socrata_client():
    app_token = os.environ.get("SOCRATA_APP_TOKEN") or None
    return Socrata(config.SOCRATA_DOMAIN, app_token, timeout=60)


def _cache_path(filename):
    return os.path.join(config.RAW_DIR, filename)


def _load_or_fetch_csv(cache_filename, fetch_fn, force_refresh=False):
    path = _cache_path(cache_filename)
    if os.path.exists(path) and not force_refresh:
        logger.info("Using cached %s", cache_filename)
        return pd.read_csv(path, dtype=str)
    df = fetch_fn()
    df.to_csv(path, index=False)
    logger.info("Cached %s (%d rows)", cache_filename, len(df))
    return df


def _load_or_fetch_geojson(cache_filename, fetch_fn, force_refresh=False):
    path = _cache_path(cache_filename)
    if os.path.exists(path) and not force_refresh:
        logger.info("Using cached %s", cache_filename)
        return gpd.read_file(path)
    gdf = fetch_fn()
    gdf.to_file(path, driver="GeoJSON")
    logger.info("Cached %s (%d rows)", cache_filename, len(gdf))
    return gdf


# --- Community Area boundaries -------------------------------------------

def get_community_area_boundaries(force_refresh=False) -> gpd.GeoDataFrame:
    """Boundaries - Community Areas (igwz-8jzy): polygons + area/community name.

    Adds area_sq_mi (via EPSG:3435 reprojection) and a WGS84 representative
    point per area (representative_point(), not centroid — several Community
    Areas are concave enough for a true centroid to fall outside the shape).
    """
    def fetch():
        url = f"https://{config.SOCRATA_DOMAIN}/resource/{config.SOCRATA_COMMUNITY_AREAS}.geojson"
        resp = _retry(lambda: requests.get(url, params={"$limit": 200}, timeout=60), "Community Area boundaries fetch")
        resp.raise_for_status()
        gdf = gpd.read_file(io.BytesIO(resp.content))
        if gdf.crs is None:
            gdf = gdf.set_crs(config.WGS84_CRS)
        gdf["area_numbe"] = gdf["area_numbe"].astype(int)
        gdf["community"] = gdf["community"].str.title()
        return gdf[["area_numbe", "community", "geometry"]]

    gdf = _load_or_fetch_geojson("boundaries_community_areas.geojson", fetch, force_refresh)
    gdf["area_numbe"] = gdf["area_numbe"].astype(int)

    # Derived every load rather than cached: a second geometry column
    # (rep_point) can't round-trip through to_file(driver="GeoJSON").
    projected = gdf.to_crs(config.IL_STATE_PLANE_EAST_CRS)
    gdf["area_sq_mi"] = projected.geometry.area / config.SQFT_PER_SQMILE
    gdf["rep_point"] = gdf.geometry.representative_point()

    if len(gdf) != config.N_COMMUNITY_AREAS:
        raise RuntimeError(
            f"Expected {config.N_COMMUNITY_AREAS} Community Areas, got {len(gdf)} "
            f"from resource {config.SOCRATA_COMMUNITY_AREAS} — aborting before any "
            "further fetching, since every downstream step depends on this."
        )
    return gdf


# --- Census tract boundaries (for the tract -> Community Area crosswalk) --

def get_census_tract_boundaries(force_refresh=False) -> gpd.GeoDataFrame:
    """Cook County census tract polygons from the Census Bureau's own
    cartographic boundary file for config.ACS_YEAR.

    Deliberately NOT sourced from the Chicago Data Portal's own tract
    boundary dataset: that dataset's vintage doesn't reliably match the
    tract numbering used by a given ACS 5-year release, which would silently
    mis-join income/rent/transit figures to the wrong tracts. The Census
    Bureau's cartographic boundary file for the same ACS_YEAR guarantees the
    GEOIDs match what the ACS API returns.
    """
    def fetch():
        zip_path = _cache_path(f"cb_{config.ACS_YEAR}_17_tract_500k.zip")
        if not os.path.exists(zip_path) or force_refresh:
            url = f"https://www2.census.gov/geo/tiger/GENZ{config.ACS_YEAR}/shp/cb_{config.ACS_YEAR}_17_tract_500k.zip"
            resp = _retry(lambda: requests.get(url, timeout=120), "Census tract cartographic boundary fetch")
            resp.raise_for_status()
            with open(zip_path, "wb") as f:
                f.write(resp.content)
        gdf = gpd.read_file(f"zip://{zip_path}")
        gdf = gdf[gdf["COUNTYFP"] == config.CENSUS_COUNTY_FIPS].copy()
        gdf = gdf[["GEOID", "geometry"]].rename(columns={"GEOID": "geoid"})
        return gdf.to_crs(config.WGS84_CRS)

    return _load_or_fetch_geojson("boundaries_census_tracts_cook.geojson", fetch, force_refresh)


def build_tract_to_community_area_map(tracts_gdf, ca_gdf, force_refresh=False) -> pd.DataFrame:
    """geoid -> area_numbe, via a point-in-polygon spatial join.

    Tracts outside Chicago (the rest of Cook County) simply match no
    Community Area polygon and are dropped here — that's intentional, not a
    bug, since only Chicago tracts should feed the scoring model.
    """
    path = _cache_path("tract_to_community_area.csv")
    if os.path.exists(path) and not force_refresh:
        logger.info("Using cached tract_to_community_area.csv")
        return pd.read_csv(path, dtype=str)

    proj_crs = config.IL_STATE_PLANE_EAST_CRS
    tract_points = gpd.GeoDataFrame(
        {"geoid": tracts_gdf["geoid"]},
        geometry=tracts_gdf.to_crs(proj_crs).geometry.representative_point(),
        crs=proj_crs,
    )
    ca_proj = ca_gdf[["area_numbe", "geometry"]].to_crs(proj_crs)
    joined = gpd.sjoin(tract_points, ca_proj, how="inner", predicate="within")

    n_dropped = len(tracts_gdf) - len(joined)
    logger.info(
        "Tract -> Community Area join: %d of %d Cook County tracts fell inside "
        "a Chicago Community Area (%d outside city limits, expected).",
        len(joined), len(tracts_gdf), n_dropped,
    )

    result = joined[["geoid", "area_numbe"]].reset_index(drop=True)
    result.to_csv(path, index=False)
    return result


# --- Chicago Data Portal: Crimes & Traffic Crashes -------------------------

def get_crimes(force_refresh=False) -> pd.DataFrame:
    """Crimes - 2001 to Present (ijzp-q8t2), last config.CRIME_LOOKBACK_YEARS years.

    Uses sodapy's get_all(), which pages automatically — a plain get() call
    would silently truncate at Socrata's default 1000-row limit and
    undercount crime_rate_per_1k with no error raised.
    """
    def fetch():
        cutoff = (pd.Timestamp.now() - pd.DateOffset(years=config.CRIME_LOOKBACK_YEARS)).strftime("%Y-%m-%dT00:00:00")
        client = _socrata_client()
        rows = _retry(
            lambda: list(client.get_all(
                config.SOCRATA_CRIMES,
                select="community_area,primary_type,date,arrest",
                where=f"date >= '{cutoff}'",
                limit=config.SOCRATA_PAGE_SIZE,
            )),
            "Crimes fetch",
        )
        df = pd.DataFrame.from_records(rows)
        return df

    return _load_or_fetch_csv("crimes.csv", fetch, force_refresh)


def get_traffic_crashes(force_refresh=False) -> pd.DataFrame:
    """Traffic Crashes - Crashes (85ca-t3if), last config.CRIME_LOOKBACK_YEARS years.

    This dataset has no community_area field (confirmed against the live
    schema) — only lat/lon, so crashes get assigned to a Community Area via
    the same spatial-join helper used for CTA stops and OSM points.
    """
    def fetch():
        cutoff = (pd.Timestamp.now() - pd.DateOffset(years=config.CRIME_LOOKBACK_YEARS)).strftime("%Y-%m-%dT00:00:00")
        client = _socrata_client()
        rows = _retry(
            lambda: list(client.get_all(
                config.SOCRATA_CRASHES,
                select="crash_date,first_crash_type,latitude,longitude",
                where=f"crash_date >= '{cutoff}' AND latitude IS NOT NULL",
                limit=config.SOCRATA_PAGE_SIZE,
            )),
            "Traffic crashes fetch",
        )
        df = pd.DataFrame.from_records(rows)
        return df

    return _load_or_fetch_csv("crashes.csv", fetch, force_refresh)


# --- Chicago Data Portal: CTA 'L' Stops -----------------------------------

def get_cta_stops(force_refresh=False) -> pd.DataFrame:
    """CTA - System Information - List of 'L' Stops (8pix-ypme).

    Deduped to one row per map_id (station) — the raw dataset has one row
    per direction/platform, which would otherwise double- or triple-count
    the same physical station.
    """
    def fetch():
        client = _socrata_client()
        rows = _retry(
            lambda: client.get(config.SOCRATA_CTA_STOPS, limit=500),
            "CTA stops fetch",
        )
        df = pd.DataFrame.from_records(rows)
        df["latitude"] = df["location"].apply(lambda loc: loc["latitude"])
        df["longitude"] = df["location"].apply(lambda loc: loc["longitude"])
        df = df[["map_id", "station_name", "latitude", "longitude"]].drop_duplicates(subset="map_id")
        return df

    return _load_or_fetch_csv("cta_stops.csv", fetch, force_refresh)


# --- US Census ACS 5-Year API ----------------------------------------------

def get_census_acs(force_refresh=False) -> pd.DataFrame:
    """ACS 5-year detailed tables for every Cook County tract.

    Plain requests.get, not a Census client library — a single fixed-URL GET
    with a handful of variables doesn't justify another dependency. Requires
    CENSUS_API_KEY (via .env) unless a cache already exists.
    """
    path = _cache_path("census_acs_tracts.csv")
    if os.path.exists(path) and not force_refresh:
        logger.info("Using cached census_acs_tracts.csv")
        return pd.read_csv(path, dtype=str)

    api_key = os.environ.get("CENSUS_API_KEY")
    if not api_key:
        raise RuntimeError(
            "CENSUS_API_KEY is not set and no cached census_acs_tracts.csv exists. "
            "Sign up for a free key at https://api.census.gov/data/key_signup.html "
            "and add it to .env (see .env.example)."
        )

    def fetch():
        url = f"https://api.census.gov/data/{config.ACS_YEAR}/acs/acs5"
        params = {
            "get": ",".join(config.ACS_VARIABLES),
            "for": "tract:*",
            "in": f"state:{config.CENSUS_STATE_FIPS} county:{config.CENSUS_COUNTY_FIPS}",
            "key": api_key,
        }
        resp = _retry(lambda: requests.get(url, params=params, timeout=60), "Census ACS fetch")
        resp.raise_for_status()
        rows = resp.json()
        df = pd.DataFrame(rows[1:], columns=rows[0])
        df["geoid"] = df["state"] + df["county"] + df["tract"]
        return df

    df = fetch()
    df.to_csv(path, index=False)
    logger.info("Cached census_acs_tracts.csv (%d rows)", len(df))
    return df


# --- OpenStreetMap Overpass API ---------------------------------------------

OVERPASS_HEADERS = {"User-Agent": "chicago-neighborhoods-personal-project/1.0"}


def _overpass_query(query_str, description):
    """GET (not POST — POST triggers a 406 on the primary endpoint), primary
    URL first, then one fallback mirror. Raises if both fail.

    A descriptive User-Agent is required — Overpass's frontend 406s the
    default python-requests User-Agent outright.
    """
    last_exc = None
    for url in config.OVERPASS_URLS:
        try:
            def _do_request(url=url):
                resp = requests.get(url, params={"data": query_str}, headers=OVERPASS_HEADERS, timeout=90)
                resp.raise_for_status()
                return resp.json()

            return _retry(_do_request, f"{description} ({url})")
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            logger.warning("Overpass endpoint %s failed for %s: %s", url, description, exc)
    raise RuntimeError(f"All Overpass endpoints failed for {description}") from last_exc


def _overpass_points_to_df(elements):
    rows = []
    for el in elements:
        if el.get("type") == "node":
            lat, lon = el.get("lat"), el.get("lon")
        else:  # way/relation — Overpass "out center" attaches a center point
            center = el.get("center", {})
            lat, lon = center.get("lat"), center.get("lon")
        if lat is not None and lon is not None:
            rows.append({"osm_id": el.get("id"), "latitude": lat, "longitude": lon})
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    # Same physical POI is sometimes tagged as both a node and a way.
    df["_lat_round"] = df["latitude"].round(4)
    df["_lon_round"] = df["longitude"].round(4)
    df = df.drop_duplicates(subset=["_lat_round", "_lon_round"]).drop(columns=["_lat_round", "_lon_round"])
    return df.reset_index(drop=True)


def get_osm_supermarkets(force_refresh=False) -> pd.DataFrame:
    """Supermarket point locations within the Chicago bbox (one Overpass query)."""
    def fetch():
        s, w, n, e = config.CHICAGO_BBOX
        query = (
            f"[out:json][timeout:60];"
            f"(node['shop'='supermarket']({s},{w},{n},{e});"
            f"way['shop'='supermarket']({s},{w},{n},{e}););"
            f"out center;"
        )
        data = _overpass_query(query, "OSM supermarkets")
        return _overpass_points_to_df(data.get("elements", []))

    return _load_or_fetch_csv("osm_supermarkets.csv", fetch, force_refresh)


def get_osm_motorway_ramps(force_refresh=False) -> pd.DataFrame:
    """Highway on/off-ramp way locations within the Chicago bbox (one Overpass query)."""
    def fetch():
        s, w, n, e = config.CHICAGO_BBOX
        query = f"[out:json][timeout:60];way['highway'='motorway_link']({s},{w},{n},{e});out center;"
        data = _overpass_query(query, "OSM motorway ramps")
        return _overpass_points_to_df(data.get("elements", []))

    return _load_or_fetch_csv("osm_motorway_ramps.csv", fetch, force_refresh)


def get_osm_walkable_amenities(force_refresh=False) -> pd.DataFrame:
    """Broader walkable-amenity POIs (cafe/restaurant/pharmacy/convenience/shop)
    within the Chicago bbox — a single combined Overpass query, not one per tag.
    """
    def fetch():
        s, w, n, e = config.CHICAGO_BBOX
        query = (
            f"[out:json][timeout:90];"
            f"("
            f"node['amenity'~'cafe|restaurant|pharmacy|fast_food|bar']({s},{w},{n},{e});"
            f"node['shop'~'convenience|bakery|clothes|hairdresser|books']({s},{w},{n},{e});"
            f");"
            f"out center;"
        )
        data = _overpass_query(query, "OSM walkable amenities")
        return _overpass_points_to_df(data.get("elements", []))

    return _load_or_fetch_csv("osm_walkable_amenities.csv", fetch, force_refresh)


# --- Shared spatial-join helper --------------------------------------------

def assign_community_area(df, ca_gdf, lat_col="latitude", lon_col="longitude") -> pd.DataFrame:
    """Attach area_numbe to any lat/lon point table via point-in-polygon.

    Used for CTA stops, traffic crashes, and OSM POIs — none of which carry
    a native community-area field. Points outside all 77 polygons (bad
    coordinates, Lake Michigan) are dropped with a logged count so a bbox or
    CRS bug doesn't silently disappear.
    """
    df = df.copy()
    df[lat_col] = pd.to_numeric(df[lat_col], errors="coerce")
    df[lon_col] = pd.to_numeric(df[lon_col], errors="coerce")
    df = df.dropna(subset=[lat_col, lon_col])

    points_gdf = gpd.GeoDataFrame(
        df,
        geometry=[Point(xy) for xy in zip(df[lon_col], df[lat_col])],
        crs=config.WGS84_CRS,
    ).to_crs(config.IL_STATE_PLANE_EAST_CRS)

    ca_proj = ca_gdf[["area_numbe", "geometry"]].to_crs(config.IL_STATE_PLANE_EAST_CRS)
    joined = gpd.sjoin(points_gdf, ca_proj, how="inner", predicate="within")

    n_dropped = len(df) - len(joined)
    if n_dropped:
        pct = 100 * n_dropped / len(df)
        logger.warning(
            "assign_community_area: dropped %d/%d points (%.1f%%) that fell "
            "outside all 77 Community Areas.", n_dropped, len(df), pct,
        )

    return pd.DataFrame(joined.drop(columns=["geometry", "index_right"]))
