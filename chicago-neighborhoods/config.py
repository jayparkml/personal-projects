"""Single source of truth for paths, data-source ids, and scoring weights."""

import os

# --- Paths -------------------------------------------------------------
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(PROJECT_DIR, "data")
RAW_DIR = os.path.join(DATA_DIR, "raw")
PROCESSED_DIR = os.path.join(DATA_DIR, "processed")
LOG_FILE = os.path.join(DATA_DIR, "pipeline.log")

FEATURES_CSV = os.path.join(PROCESSED_DIR, "features.csv")
SCORES_CSV = os.path.join(PROCESSED_DIR, "chicago_neighborhood_scores.csv")

# --- Chicago Data Portal (Socrata) resource ids -------------------------
SOCRATA_DOMAIN = "data.cityofchicago.org"
SOCRATA_CRIMES = "ijzp-q8t2"  # Crimes - 2001 to Present
SOCRATA_CRASHES = "85ca-t3if"  # Traffic Crashes - Crashes
SOCRATA_CTA_STOPS = "8pix-ypme"  # CTA - System Information - List of 'L' Stops
SOCRATA_COMMUNITY_AREAS = "igwz-8jzy"  # Boundaries - Community Areas
SOCRATA_CENSUS_TRACTS = "4hp8-2i8z"  # Boundaries - Census Tracts

N_COMMUNITY_AREAS = 77
CRIME_LOOKBACK_YEARS = 3
SOCRATA_PAGE_SIZE = 50000  # cuts a multi-year crimes/crashes pull from ~600 requests to ~10-15

# --- OpenStreetMap Overpass API ------------------------------------------
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",  # fallback mirror
]
# (south, west, north, east) — generous box around city limits
CHICAGO_BBOX = (41.60, -87.95, 42.05, -87.50)

# --- US Census ACS 5-Year API ---------------------------------------------
ACS_YEAR = 2022
CENSUS_STATE_FIPS = "17"  # Illinois
CENSUS_COUNTY_FIPS = "031"  # Cook County
ACS_VARIABLES = [
    "B01003_001E",  # total population
    "B19013_001E",  # median household income
    "B25064_001E",  # median gross rent
    "B08301_001E",  # total commuters
    "B08301_010E",  # commuters using public transportation
    "B25044_001E",  # total occupied housing units
    "B25044_003E",  # owner-occupied, no vehicle available
    "B25044_010E",  # renter-occupied, no vehicle available
]
CENSUS_NULL_SENTINEL = -666666666

# Crash types counted as pedestrian/cyclist-involved (Transit-specific safety cut)
PED_CYCLIST_CRASH_TYPES = {"PEDESTRIAN", "PEDALCYCLIST"}

# Population threshold below which per-capita rates are flagged as unstable
LOW_POPULATION_WARNING_THRESHOLD = 2000

# NAD83 / Illinois East (ftUS) — feet-based state plane CRS used by Chicago's
# own GIS systems. (EPSG:26971 is the meter-based "Illinois East" and would
# silently corrupt every distance/area conversion below — do not swap it in.)
IL_STATE_PLANE_EAST_CRS = "EPSG:3435"
WGS84_CRS = "EPSG:4326"
FEET_PER_MILE = 5280
SQFT_PER_SQMILE = FEET_PER_MILE**2

# --- Feature directions: True = higher raw value is better -------------
FEATURE_DIRECTIONS = {
    "crime_rate_per_1k": False,
    "crash_rate_per_1k": False,
    "ped_cyclist_crash_rate_per_1k": False,
    "nearest_ramp_distance_mi": False,
    "nearest_l_stop_distance_mi": False,
    "population_density_per_sq_mi": False,
    "grocery_density_per_sq_mi": True,
    "walkable_amenity_density_per_sq_mi": True,
    "transit_ridership_pct": True,
    "zero_vehicle_pct": True,
    "affordability_index": True,
}

# --- Scoring weights (each must sum to 1.0) -------------------------------
DRIVER_WEIGHTS = {
    "crime_rate_per_1k": 0.25,
    "crash_rate_per_1k": 0.15,
    "nearest_ramp_distance_mi": 0.25,
    "population_density_per_sq_mi": 0.15,
    "grocery_density_per_sq_mi": 0.10,
    "affordability_index": 0.10,
}

TRANSIT_WEIGHTS = {
    "crime_rate_per_1k": 0.20,
    "ped_cyclist_crash_rate_per_1k": 0.15,
    "nearest_l_stop_distance_mi": 0.25,
    "walkable_amenity_density_per_sq_mi": 0.15,
    "transit_ridership_pct": 0.10,
    "zero_vehicle_pct": 0.05,
    "affordability_index": 0.10,
}

assert abs(sum(DRIVER_WEIGHTS.values()) - 1.0) < 1e-9, "DRIVER_WEIGHTS must sum to 1.0"
assert abs(sum(TRANSIT_WEIGHTS.values()) - 1.0) < 1e-9, "TRANSIT_WEIGHTS must sum to 1.0"
