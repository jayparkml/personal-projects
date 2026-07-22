"""Normalize engineered features and compute Driver_Score / Transit_Score."""

import logging

import config

logger = logging.getLogger(__name__)


def impute_missing(df, strategy="citywide_median"):
    """Fill NaN with the citywide median for that feature — min-max cannot
    tolerate nulls, they'd propagate through the weighted sum and silently
    zero out a Community Area's whole score."""
    if strategy != "citywide_median":
        raise ValueError(f"Unsupported imputation strategy: {strategy}")

    df = df.copy()
    for col in config.FEATURE_DIRECTIONS:
        n_missing = df[col].isna().sum()
        if n_missing:
            median = df[col].median()
            logger.warning(
                "Imputing %d missing value(s) in '%s' with citywide median (%.3f): areas %s",
                n_missing, col, median, df.loc[df[col].isna(), "community"].tolist(),
            )
            df[col] = df[col].fillna(median)
    return df


def min_max_normalize(df, feature_directions=config.FEATURE_DIRECTIONS):
    """Add a *_scaled [0,1] column per feature. higher_is_better features use
    (x - min) / (max - min); lower_is_better features use the flipped
    (max - x) / (max - min) so every scaled feature points the same
    direction before weighting. A zero-variance column falls back to 0.5
    (shouldn't happen with real data, but guards a division by zero)."""
    df = df.copy()
    for col, higher_is_better in feature_directions.items():
        col_min, col_max = df[col].min(), df[col].max()
        scaled_col = f"{col}_scaled"
        if col_max == col_min:
            logger.warning("'%s' has zero variance across all areas — scaling to 0.5", col)
            df[scaled_col] = 0.5
            continue
        if higher_is_better:
            df[scaled_col] = (df[col] - col_min) / (col_max - col_min)
        else:
            df[scaled_col] = (col_max - df[col]) / (col_max - col_min)
    return df


def _weighted_score(scaled_df, weights):
    score = sum(scaled_df[f"{feature}_scaled"] * weight for feature, weight in weights.items())
    return score * 100


def compute_driver_score(scaled_df, weights=config.DRIVER_WEIGHTS):
    return _weighted_score(scaled_df, weights)


def compute_transit_score(scaled_df, weights=config.TRANSIT_WEIGHTS):
    return _weighted_score(scaled_df, weights)


def build_rankings(features_df):
    """impute -> normalize -> score both personas -> rank -> final table.

    Sort order is area_numbe ascending (stable, canonical) — this table
    serves two different rankings at once, so Driver_Rank/Transit_Rank let
    any consumer re-sort by whichever persona they care about.
    """
    imputed = impute_missing(features_df)
    scaled = min_max_normalize(imputed)

    scaled["Driver_Score"] = compute_driver_score(scaled)
    scaled["Transit_Score"] = compute_transit_score(scaled)
    scaled["Driver_Rank"] = scaled["Driver_Score"].rank(ascending=False, method="min").astype(int)
    scaled["Transit_Rank"] = scaled["Transit_Score"].rank(ascending=False, method="min").astype(int)

    raw_feature_cols = list(config.FEATURE_DIRECTIONS.keys())
    output_cols = (
        ["area_numbe", "community", "total_population", "area_sq_mi"]
        + ["Driver_Score", "Driver_Rank", "Transit_Score", "Transit_Rank"]
        + raw_feature_cols
    )
    return scaled[output_cols].sort_values("area_numbe").reset_index(drop=True)
