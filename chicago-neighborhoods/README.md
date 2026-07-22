# Chicago Neighborhoods — Quality-of-Life ROI

Ranks Chicago's 77 Community Areas twice, using only free public data:

- **Driver_Score** — best areas for car owners (safety, highway access, parking/congestion proxy, grocery access)
- **Transit_Score** — best areas for non-car owners (CTA 'L' proximity, walkability, transit ridership)

## Data Sources

| Source | Auth | Used for |
|---|---|---|
| Chicago Data Portal — Crimes (`ijzp-q8t2`) | none | Crime rate per 1k residents |
| Chicago Data Portal — Traffic Crashes (`85ca-t3if`) | none | Crash rate + pedestrian/cyclist crash rate |
| Chicago Data Portal — CTA 'L' Stops (`8pix-ypme`) | none | Nearest-station distance |
| Chicago Data Portal — Boundaries: Community Areas (`igwz-8jzy`) | none | Polygons, area, spatial-join spine |
| US Census ACS 5-Year API | **free key required** | Income, rent, transit ridership %, zero-vehicle % |
| Census Bureau cartographic boundary file (tracts) | none | Tract → Community Area crosswalk (vintage-matched to the ACS year, not the city's own possibly-stale tract dataset) |
| OpenStreetMap Overpass API | none | Supermarket density, highway ramp distance, walkable-amenity density |

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
```

Get a free, instant Census API key at https://api.census.gov/data/key_signup.html and put it in `.env` as `CENSUS_API_KEY`. `SOCRATA_APP_TOKEN` is optional (raises Chicago Data Portal rate limits) — the pipeline runs fine without it.

## Usage

```bash
python3 main.py            # uses cached data where available
python3 main.py --refresh  # forces a full re-pull from every API
```

## Output

- `data/processed/features.csv` — raw engineered features, one row per Community Area
- `data/processed/chicago_neighborhood_scores.csv` — final Driver_Score/Transit_Score rankings
- `data/pipeline.log` — full run log
- Console: top 5 Community Areas for each persona

All of `data/` is gitignored — every file in it is either an API cache or a pipeline output, reproducible by re-running `main.py`.

## Methodology

Every raw feature is min-max scaled to [0,1] across all 77 areas (features where lower is better, like crime rate or distance to a station, are flipped so every scaled feature points the same direction), then combined into a 0–100 score via a weighted sum. Weights and feature directions live in `config.py` as plain dicts — easy to retune without touching any logic. See `MEDIUM_POST.md` for the full weight tables and rationale.

## Known Limitations

- **Population density** is used as the parking/congestion proxy — no free direct parking-supply dataset exists.
- **Zero-vehicle-household %** conflates "car-free by choice" (walkable/transit-rich area) with "car-free due to poverty" — kept at a low weight (0.05) for this reason.
- Per-capita rates get noisy for low-residential-population areas with high daytime activity (e.g. the Loop, O'Hare) — logged as a warning, not silently smoothed over.
- Chicago's 77 official **Community Areas** are the geography used here, distinct from the city's ~200 informal "neighborhood" names.
