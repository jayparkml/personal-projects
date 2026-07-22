"""End-to-end pipeline: fetch -> engineer features -> score -> rank.

Usage:
    python3 main.py            # uses cached data where available
    python3 main.py --refresh  # forces a full re-pull from every API
"""

import argparse
import logging
import os

from dotenv import load_dotenv

import config
from src import data_fetcher, feature_engineering, model


def _setup_logging():
    os.makedirs(config.DATA_DIR, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(config.LOG_FILE)],
    )


def main():
    parser = argparse.ArgumentParser(description="Chicago Neighborhoods quality-of-life ROI pipeline")
    parser.add_argument("--refresh", action="store_true", help="Force a full re-pull from every data source")
    args = parser.parse_args()

    load_dotenv()
    _setup_logging()
    logger = logging.getLogger(__name__)

    os.makedirs(config.RAW_DIR, exist_ok=True)
    os.makedirs(config.PROCESSED_DIR, exist_ok=True)
    refresh = args.refresh

    logger.info("Fetching Community Area boundaries (spine of every spatial join)...")
    ca_gdf = data_fetcher.get_community_area_boundaries(refresh)

    logger.info("Building the tract -> Community Area crosswalk for Census aggregation...")
    tracts_gdf = data_fetcher.get_census_tract_boundaries(refresh)
    tract_to_ca_map = data_fetcher.build_tract_to_community_area_map(tracts_gdf, ca_gdf, refresh)

    logger.info("Fetching Crimes, Traffic Crashes, CTA 'L' Stops, Census ACS, and OSM POIs...")
    crimes_df = data_fetcher.get_crimes(refresh)
    crashes_df = data_fetcher.get_traffic_crashes(refresh)
    cta_stops_df = data_fetcher.get_cta_stops(refresh)
    acs_df = data_fetcher.get_census_acs(refresh)
    groceries_df = data_fetcher.get_osm_supermarkets(refresh)
    ramps_df = data_fetcher.get_osm_motorway_ramps(refresh)
    amenities_df = data_fetcher.get_osm_walkable_amenities(refresh)

    logger.info("Engineering features...")
    census_features = feature_engineering.aggregate_census_to_community_area(acs_df, tract_to_ca_map)

    crashes_assigned = data_fetcher.assign_community_area(crashes_df, ca_gdf)
    groceries_assigned = data_fetcher.assign_community_area(groceries_df, ca_gdf)
    amenities_assigned = data_fetcher.assign_community_area(amenities_df, ca_gdf)

    crime_rate_df = feature_engineering.compute_crime_rate(crimes_df, census_features)
    crash_rate_df = feature_engineering.compute_crash_rate(crashes_assigned, census_features)
    station_dist_df = feature_engineering.compute_nearest_station_distance(ca_gdf, cta_stops_df)
    ramp_dist_df = feature_engineering.compute_nearest_ramp_distance(ca_gdf, ramps_df)
    grocery_density_df = feature_engineering.compute_poi_density(ca_gdf, groceries_assigned, "grocery_density_per_sq_mi")
    amenity_density_df = feature_engineering.compute_poi_density(ca_gdf, amenities_assigned, "walkable_amenity_density_per_sq_mi")

    features_df = feature_engineering.assemble_feature_table(
        ca_gdf, census_features, crime_rate_df, crash_rate_df,
        station_dist_df, ramp_dist_df, grocery_density_df, amenity_density_df,
    )
    features_df.to_csv(config.FEATURES_CSV, index=False)
    logger.info("Wrote %s", config.FEATURES_CSV)

    logger.info("Scoring and ranking...")
    rankings_df = model.build_rankings(features_df)
    rankings_df.to_csv(config.SCORES_CSV, index=False)
    logger.info("Wrote %s", config.SCORES_CSV)

    print("\nTop 5 Community Areas for Car Owners (Driver_Score):")
    print(
        rankings_df.sort_values("Driver_Score", ascending=False)
        .head(5)[["community", "Driver_Score"]]
        .to_string(index=False)
    )

    print("\nTop 5 Community Areas for Non-Car Owners (Transit_Score):")
    print(
        rankings_df.sort_values("Transit_Score", ascending=False)
        .head(5)[["community", "Transit_Score"]]
        .to_string(index=False)
    )


if __name__ == "__main__":
    main()
