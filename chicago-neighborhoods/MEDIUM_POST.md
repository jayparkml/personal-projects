# Medium Post Outline — "Should I Own a Car in Chicago?"

Skeleton only — section headers and what goes in each. Full prose gets drafted
after a considered look at the pipeline's output (`data/processed/chicago_neighborhood_scores.csv`)
and the charts from `notebooks/exploration.ipynb`.

## 1. Hook

Open on the question everyone moving to Chicago asks: keep the car, or go
carless and lean on the CTA? Frame it as a data question, not an opinion piece.

## 2. Motivation

- Why Community Areas (the official 77) rather than the ~200 informal
  neighborhood names — consistent, government-defined boundaries with data
  actually reported against them.
- Why two separate scores instead of one blended one — a driver and a
  transit rider are optimizing for genuinely different things, and blending
  them would hide that.

## 3. Methodology

Plain-language walkthrough (pull the tables straight from `README.md`):

- The three free data sources (Chicago Data Portal, Census ACS, OpenStreetMap).
- The two feature lists (Driver vs. Transit) and *why* each feature is in
  its persona's list.
- Min-max scaling + weighted sum, explained without the code — a diagram of
  the weight tables from `README.md` / `config.py` translates well here.

## 4. Data & Caveats

Lift directly from README's Known Limitations section — say it plainly,
don't bury it:
- Population density as a parking/congestion stand-in.
- Zero-vehicle % conflating choice vs. circumstance.
- Noisy per-capita rates in low-population areas (the Loop, O'Hare).

## 5. Results

- Top 5 Driver_Score areas, top 5 Transit_Score areas (pull live from
  `chicago_neighborhood_scores.csv` at drafting time).
- The interesting middle: areas that rank well on *both* (an "all-arounder"
  callout) vs. areas that trade off hard in one direction.
- Sanity-check anecdotes: does the result match intuition for a couple of
  well-known areas (the Loop, Lake View, Forest Glen)? Where does it
  surprise you, and can you explain why from the feature table?

## 6. Visualizations (build in `notebooks/exploration.ipynb`)

- Two choropleth maps of Chicago — one shaded by Driver_Score, one by
  Transit_Score (`geopandas.plot()`).
- A Driver vs. Transit scatter plot with quadrant labels: all-around winner,
  car-dependent, transit-only, underserved.
- Top-10 bar chart per persona.

## 7. Takeaways

Practical close — what would you actually tell a friend moving to Chicago
and deciding whether to bring a car? Link the GitHub repo for reproducibility.
