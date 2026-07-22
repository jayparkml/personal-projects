"""Turn raw fetched data into one row per Community Area, one column per feature.

Population (B01003_001E) is summed per area (it's additive); income and rent
are population-weighted averages across contributing tracts (a median-of-
medians isn't mathematically correct, but a population-weighted average is
the standard, documented approximation used here).
"""

import logging

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

import config

logger = logging.getLogger(__name__)


def _population_weighted_mean(group, value_col, weight_col):
    valid = group.dropna(subset=[value_col])
    total_weight = valid[weight_col].sum()
    if total_weight == 0:
        return float("nan")
    return (valid[value_col] * valid[weight_col]).sum() / total_weight


def aggregate_census_to_community_area(acs_df, tract_to_ca_map) -> pd.DataFrame:
    """One row per Community Area: population, income, rent, commute mode, vehicles."""
    merged = acs_df.merge(tract_to_ca_map, on="geoid", how="inner")
    n_unmatched = len(acs_df) - len(merged)
    if n_unmatched:
        logger.info(
            "%d of %d Cook County ACS tracts fell outside Chicago city limits "
            "(expected — Cook County includes many suburbs).",
            n_unmatched, len(acs_df),
        )

    for col in config.ACS_VARIABLES:
        merged[col] = pd.to_numeric(merged[col], errors="coerce")
        merged.loc[merged[col] == config.CENSUS_NULL_SENTINEL, col] = pd.NA

    merged["area_numbe"] = merged["area_numbe"].astype(int)

    records = []
    for area_numbe, group in merged.groupby("area_numbe"):
        zero_vehicle = group["B25044_003E"].fillna(0) + group["B25044_010E"].fillna(0)
        records.append({
            "area_numbe": area_numbe,
            "total_population": group["B01003_001E"].sum(min_count=1),
            "median_household_income": _population_weighted_mean(group, "B19013_001E", "B01003_001E"),
            "median_gross_rent": _population_weighted_mean(group, "B25064_001E", "B01003_001E"),
            "total_commuters": group["B08301_001E"].sum(min_count=1),
            "public_transit_commuters": group["B08301_010E"].sum(min_count=1),
            "total_occupied_housing_units": group["B25044_001E"].sum(min_count=1),
            "zero_vehicle_households": zero_vehicle.sum(),
        })
    return pd.DataFrame(records)


def compute_crime_rate(crimes_df, population_df) -> pd.DataFrame:
    """Annualized crimes per 1,000 residents, per Community Area."""
    df = crimes_df.copy()
    df["community_area"] = pd.to_numeric(df["community_area"], errors="coerce")
    df = df[df["community_area"].between(1, config.N_COMMUNITY_AREAS)]
    df["community_area"] = df["community_area"].astype(int)

    counts = df.groupby("community_area").size().reindex(population_df["area_numbe"], fill_value=0)

    result = population_df[["area_numbe", "total_population"]].copy()
    result["crime_rate_per_1k"] = (
        counts.values / config.CRIME_LOOKBACK_YEARS / result["total_population"] * 1000
    )
    return result[["area_numbe", "crime_rate_per_1k"]]


def compute_crash_rate(crashes_assigned_df, population_df) -> pd.DataFrame:
    """Annualized crashes per 1,000 residents — overall, and pedestrian/cyclist-only.

    crashes_assigned_df must already carry an area_numbe column (see
    data_fetcher.assign_community_area — this dataset has no native
    community-area field, only lat/lon).
    """
    df = crashes_assigned_df.copy()
    df["area_numbe"] = df["area_numbe"].astype(int)
    years = config.CRIME_LOOKBACK_YEARS

    total_counts = df.groupby("area_numbe").size().reindex(population_df["area_numbe"], fill_value=0)

    ped_cyc = df[df["first_crash_type"].isin(config.PED_CYCLIST_CRASH_TYPES)]
    ped_cyc_counts = ped_cyc.groupby("area_numbe").size().reindex(population_df["area_numbe"], fill_value=0)

    result = population_df[["area_numbe", "total_population"]].copy()
    result["crash_rate_per_1k"] = total_counts.values / years / result["total_population"] * 1000
    result["ped_cyclist_crash_rate_per_1k"] = ped_cyc_counts.values / years / result["total_population"] * 1000
    return result[["area_numbe", "crash_rate_per_1k", "ped_cyclist_crash_rate_per_1k"]]


def _nearest_distance_miles(ca_gdf, target_points_df, lat_col="latitude", lon_col="longitude") -> pd.DataFrame:
    """Per-Community-Area distance (miles) from its representative point to
    the nearest point in target_points_df. Both layers reprojected to
    EPSG:3435 (feet) first — lat/lon degrees aren't valid for distance math.
    """
    ca_points = gpd.GeoDataFrame(
        {"area_numbe": ca_gdf["area_numbe"].values},
        geometry=gpd.GeoSeries(ca_gdf["rep_point"].values, crs=config.WGS84_CRS)
            .to_crs(config.IL_STATE_PLANE_EAST_CRS)
            .values,
        crs=config.IL_STATE_PLANE_EAST_CRS,
    )

    targets = target_points_df.copy()
    targets[lat_col] = pd.to_numeric(targets[lat_col], errors="coerce")
    targets[lon_col] = pd.to_numeric(targets[lon_col], errors="coerce")
    targets = targets.dropna(subset=[lat_col, lon_col])
    targets_gdf = gpd.GeoDataFrame(
        targets,
        geometry=[Point(xy) for xy in zip(targets[lon_col], targets[lat_col])],
        crs=config.WGS84_CRS,
    ).to_crs(config.IL_STATE_PLANE_EAST_CRS)

    nearest = gpd.sjoin_nearest(ca_points, targets_gdf[["geometry"]], distance_col="dist_ft")
    nearest = nearest.drop_duplicates(subset="area_numbe")  # ties: keep first, distance is identical anyway
    nearest["distance_mi"] = nearest["dist_ft"] / config.FEET_PER_MILE
    return nearest[["area_numbe", "distance_mi"]].reset_index(drop=True)


def compute_nearest_station_distance(ca_gdf, cta_stops_df) -> pd.DataFrame:
    result = _nearest_distance_miles(ca_gdf, cta_stops_df)
    return result.rename(columns={"distance_mi": "nearest_l_stop_distance_mi"})


def compute_nearest_ramp_distance(ca_gdf, ramps_df) -> pd.DataFrame:
    result = _nearest_distance_miles(ca_gdf, ramps_df)
    return result.rename(columns={"distance_mi": "nearest_ramp_distance_mi"})


def compute_poi_density(ca_gdf, assigned_poi_df, out_col) -> pd.DataFrame:
    """POIs per square mile, per Community Area.

    assigned_poi_df must already carry an area_numbe column (see
    data_fetcher.assign_community_area). Areas with zero matching POIs get
    an explicit 0 (via reindex), not a missing row — a real 0 is a
    meaningful value here, not missing data.
    """
    counts = assigned_poi_df.groupby("area_numbe").size().reindex(ca_gdf["area_numbe"], fill_value=0)
    result = ca_gdf[["area_numbe", "area_sq_mi"]].copy()
    result[out_col] = counts.values / result["area_sq_mi"]
    return result[["area_numbe", out_col]]


def compute_population_density(ca_gdf, population_df) -> pd.DataFrame:
    """Residents per square mile — the Driver_Score proxy for parking/congestion
    (no free direct parking-supply dataset exists)."""
    merged = ca_gdf[["area_numbe", "area_sq_mi"]].merge(
        population_df[["area_numbe", "total_population"]], on="area_numbe"
    )
    merged["population_density_per_sq_mi"] = merged["total_population"] / merged["area_sq_mi"]
    return merged[["area_numbe", "population_density_per_sq_mi"]]


def compute_affordability_index(census_features_df) -> pd.DataFrame:
    """Median household income / annualized median gross rent. Higher = more affordable."""
    df = census_features_df.copy()
    df["affordability_index"] = df["median_household_income"] / (df["median_gross_rent"] * 12)
    return df[["area_numbe", "affordability_index"]]


def compute_transit_ridership_pct(census_features_df) -> pd.DataFrame:
    df = census_features_df.copy()
    df["transit_ridership_pct"] = df["public_transit_commuters"] / df["total_commuters"] * 100
    return df[["area_numbe", "transit_ridership_pct"]]


def compute_zero_vehicle_pct(census_features_df) -> pd.DataFrame:
    df = census_features_df.copy()
    df["zero_vehicle_pct"] = df["zero_vehicle_households"] / df["total_occupied_housing_units"] * 100
    return df[["area_numbe", "zero_vehicle_pct"]]


def assemble_feature_table(
    ca_gdf,
    census_features,
    crime_rate_df,
    crash_rate_df,
    station_dist_df,
    ramp_dist_df,
    grocery_density_df,
    amenity_density_df,
) -> pd.DataFrame:
    """Merge every engineered feature into one 77-row table keyed on area_numbe."""
    base = ca_gdf[["area_numbe", "community", "area_sq_mi"]].copy()

    frames = [
        census_features[["area_numbe", "total_population"]],
        crime_rate_df,
        crash_rate_df,
        station_dist_df,
        ramp_dist_df,
        compute_population_density(ca_gdf, census_features),
        grocery_density_df,
        amenity_density_df,
        compute_transit_ridership_pct(census_features),
        compute_zero_vehicle_pct(census_features),
        compute_affordability_index(census_features),
    ]

    result = base
    for frame in frames:
        result = result.merge(frame, on="area_numbe", how="left")

    if len(result) != config.N_COMMUNITY_AREAS:
        raise RuntimeError(
            f"assemble_feature_table produced {len(result)} rows, expected "
            f"{config.N_COMMUNITY_AREAS} — a merge likely dropped or duplicated a Community Area."
        )

    low_pop = result[result["total_population"] < config.LOW_POPULATION_WARNING_THRESHOLD]
    if not low_pop.empty:
        logger.warning(
            "%d Community Area(s) have residential population under %d — "
            "per-capita rates there may be noisy/unstable: %s",
            len(low_pop), config.LOW_POPULATION_WARNING_THRESHOLD, low_pop["community"].tolist(),
        )

    nan_counts = result.isna().sum()
    nan_counts = nan_counts[nan_counts > 0]
    if not nan_counts.empty:
        logger.warning("Missing values before imputation:\n%s", nan_counts.to_string())

    return result
