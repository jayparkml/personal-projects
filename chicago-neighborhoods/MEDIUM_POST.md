*Note: Medium's own editor doesn't render pasted Markdown tables — either use a Markdown-paste browser extension (e.g. "Markdown Here"), or drop each table in as a screenshot. The three charts below are real PNGs already exported to `medium_assets/` — just drag-and-drop them into the post at the marked points.*

---

# Should You Own a Car in Chicago? I Built a Model to Find Out

### Scoring all 77 Chicago Community Areas for drivers and transit riders, using nothing but free public data

If you've ever moved to Chicago, you've had this argument with yourself: keep the car, or go carless and lean on the CTA? The honest answer is "it depends where you live" — but nobody tells you *how much* it depends, or which neighborhoods actually deliver on either promise.

So I built a small data pipeline to answer it properly. It pulls crime data, traffic crash records, CTA station locations, Census income and commuting data, and OpenStreetMap points of interest, then scores all 77 of Chicago's official Community Areas twice: once for car owners, once for everyone else.

The code is [on GitHub](#) (link your repo here). Here's what it found.

## Why Community Areas, and why two scores

Chicago doesn't have official boundaries for its ~200 informal neighborhood names — "Wicker Park" and "Bucktown" are real to anyone who lives there, but no city dataset agrees on exactly where one ends and the other begins. The 77 **Community Areas**, on the other hand, are a fixed, decades-old geography that the city itself reports crime, health, and planning data against. If you want numbers that are actually comparable across the whole city, this is the grid to use.

The two-score design is deliberate. A driver and a transit rider are not optimizing for the same thing, and averaging their priorities into one blended "livability score" would just hide the tradeoff that makes this question interesting in the first place. So instead of one number, you get two, and the gap between them *is* the finding.

## Methodology

Every feature below is pulled from a free public API — no paid data, no scraping tricks:

| Source | Access | Used for |
|---|---|---|
| Chicago Data Portal — Crimes | Free, no key | Crime rate per 1,000 residents |
| Chicago Data Portal — Traffic Crashes | Free, no key | Crash rate + pedestrian/cyclist crash rate |
| Chicago Data Portal — CTA 'L' Stops | Free, no key | Distance to nearest train station |
| Chicago Data Portal — Community Area boundaries | Free, no key | Area, spatial joins |
| US Census ACS 5-Year | Free (instant signup key) | Income, rent, transit ridership %, zero-vehicle % |
| OpenStreetMap Overpass API | Free, no key | Supermarket density, highway ramp distance, walkable-amenity density |

Every raw feature gets min-max scaled to a 0–1 range across all 77 areas (features where *lower* is better — crime, crash rate, distance to a station — get flipped so every scaled feature points the same direction), then combined into a 0–100 score with a weighted sum.

**Driver_Score weights:**

| Feature | Weight | Why |
|---|---|---|
| Crime rate per 1k | 0.25 | Safety |
| Crash rate per 1k | 0.15 | Vehicle-occupant risk |
| Distance to nearest highway ramp | 0.25 | The explicit "highway access" ask |
| Population density (parking/congestion proxy) | 0.15 | No free parking-supply dataset exists — this is the closest available stand-in |
| Grocery (supermarket) density | 0.10 | Grocery access |
| Affordability index (income ÷ annual rent) | 0.10 | General cost of living |

**Transit_Score weights:**

| Feature | Weight | Why |
|---|---|---|
| Distance to nearest CTA 'L' stop | 0.25 | The explicit "CTA proximity" ask |
| Crime rate per 1k | 0.20 | Safety |
| Pedestrian/cyclist crash rate per 1k | 0.15 | Street safety on the walking/biking legs of a trip |
| Walkable-amenity density | 0.15 | Cafes, restaurants, pharmacies, convenience stores, etc. |
| Transit ridership % (commute mode) | 0.10 | Revealed preference — people who already commute by transit there |
| Affordability index | 0.10 | General cost of living |
| Zero-vehicle-household % | 0.05 | Same revealed-preference signal, weighted low — see caveats |

## The caveats, up front

Three honest limitations, because a model like this is only useful if you know where it's guessing:

- **No free parking-supply dataset exists**, so Driver_Score leans on population density as a congestion/parking proxy. Denser areas mean more competition for street parking and more local traffic friction — it's a reasonable stand-in, but it's not a direct measurement.
- **Zero-vehicle-household %** conflates two very different situations: being car-free by choice in a walkable, transit-rich area, versus being car-free because you can't afford a car. That's why it gets the lowest weight in the model (0.05) rather than being dropped — it's a real signal, just a noisy one.
- **Per-capita rates get unstable in low-population areas** with heavy daytime activity, like the Loop or O'Hare — a handful of incidents divided by a small residential base can swing a rate a lot. The pipeline logs a warning for these rather than silently smoothing them over.

## The Results

### Top 5 for Car Owners

| Rank | Community Area | Driver_Score |
|---|---|---|
| 1 | Forest Glen | 81.3 |
| 2 | Norwood Park | 80.1 |
| 3 | East Side | 80.0 |
| 4 | Avondale | 78.5 |
| 5 | North Center | 77.8 |

### Top 5 for Non-Car Owners

| Rank | Community Area | Transit_Score |
|---|---|---|
| 1 | Lake View | 75.7 |
| 2 | Lincoln Park | 73.2 |
| 3 | Edgewater | 72.2 |
| 4 | Uptown | 70.8 |
| 5 | North Center | 70.3 |

**[Insert `medium_assets/top10_bar_charts.png` here]**

The driver winners line up with intuition the moment you look at a map: Forest Glen and Norwood Park sit in Chicago's low-density, single-family-home far northwest corner, close to the Edens Expressway, with none of the congestion of the lakefront core. The transit winners are the opposite profile entirely — Lake View, Lincoln Park, Edgewater, and Uptown are the dense North Side corridor that the Red, Brown, and Purple lines were practically built to serve.

**[Insert `medium_assets/choropleth_maps.png` here]**

Side by side, the two maps make the geography of the tradeoff obvious: Driver_Score is strongest at the edges of the city, Transit_Score is strongest along the lakefront spine. Chicago doesn't really have a "bad for everyone" or "good for everyone" gradient running in one direction — it has two different gradients pointed in two different directions.

### The all-arounder: North Center

One neighborhood shows up in *both* top-5 lists: **North Center** (5th for drivers, 5th for transit). It's the closest thing this model finds to a genuine "have it both ways" neighborhood in Chicago — solid highway access without sacrificing walkability and train proximity. If you're not sure yet whether you'll want the car in six months, this is the kind of place the model says to hedge with.

### The quadrant view

**[Insert `medium_assets/quadrant_scatter.png` here]**

Splitting the city on the median of each score gives four groups:

- **Top-right (31 areas): above-median on both.** North Center, Lincoln Park, Avondale, Logan Square — broadly, the North and Near Side.
- **Bottom-left (30 areas): below-median on both.** Fuller Park, Chicago Lawn, West Englewood, North Lawndale — mostly West and South Side areas that current transit and highway infrastructure underserves on both fronts.
- **Bottom-right: car-friendly, transit-poor.** East Side, Hegewisch, Morgan Park, South Chicago, Mount Greenwood — the far South and Southeast Side, well outside 'L' territory.
- **Top-left: transit-friendly, car-unfriendly.** Rogers Park, Lake View, the Loop — dense, congested, and not really built around driving.

### An asymmetry worth naming honestly

Here's the part I didn't expect going in: **the "worst for transit" extreme is much more extreme than the "worst for driving" extreme.**

| Most car-dependent (Driver − Transit) | Gap |
|---|---|
| East Side | +36.2 |
| Hegewisch | +32.6 |
| Morgan Park | +28.6 |

| Most transit-leaning (Transit − Driver) | Gap |
|---|---|
| Rogers Park | −9.2 |
| Lake View | −6.1 |
| Loop | −5.5 |

No neighborhood beats its Driver_Score by more than about 9 points on the Transit side, but several beat their Transit_Score by 30+ points on the Driver side. My read: driving in Chicago is *never great* even in the best spots (the lakefront core is congested, dense, and short on parking no matter how you slice it), so there's a ceiling on how much better a car-friendly area can look. But *transit access is close to binary* — you're either within reach of an 'L' line or you're genuinely miles from one — so the worst-served areas fall off a cliff in a way driving access never quite does.

## Takeaways

If you're moving to Chicago and can only pick one:

- **Committed to the car?** Look at the far Northwest Side (Forest Glen, Norwood Park, Jefferson Park) — good highway access, lower density, without the crime or affordability tradeoffs some other car-friendly pockets carry.
- **Going carless?** The North Side lakefront corridor (Lake View through Edgewater/Uptown) is Chicago's actual transit sweet spot, not just the most Instagrammed one.
- **Not sure yet?** North Center is the model's answer for "don't make me choose."
- **Wherever you land, check the map above against your own must-haves** — this model can't see school quality, noise, or whether you like your future landlord. It's a data-informed starting point, not a verdict.

All the code, the exact weights, and the full 77-area ranking are in the [GitHub repo](#) — clone it, change the weights in `config.py` to match what *you* actually care about, and re-run it.

---

*Data current as of the pipeline's last run. Full methodology, caveats, and column-level detail live in the project [README](#).*
