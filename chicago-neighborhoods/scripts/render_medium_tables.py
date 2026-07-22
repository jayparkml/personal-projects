"""Render every table in MEDIUM_POST.md as a standalone PNG.

Medium's editor has no table feature at all — pasted Markdown pipe-tables
just become a line of plain text with "|" characters in it, and pasted HTML
tables don't survive either. The only reliable fix the Medium community has
found is dropping each table in as an image, so that's what this does.

If you edit a table's numbers in MEDIUM_POST.md, update the matching
TABLES entry below (including "wrap", the per-column character-wrap width —
use None for short columns like Rank/Weight/Gap) and rerun this script.
"""

import os
import textwrap

import matplotlib.pyplot as plt

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "medium_assets", "tables")

TABLES = [
    {
        "filename": "data_sources.png",
        "headers": ["Source", "Access", "Used for"],
        "rows": [
            ["Chicago Data Portal — Crimes", "Free, no key", "Crime rate per 1,000 residents"],
            ["Chicago Data Portal — Traffic Crashes", "Free, no key", "Crash rate + pedestrian/cyclist crash rate"],
            ["Chicago Data Portal — CTA 'L' Stops", "Free, no key", "Distance to nearest train station"],
            ["Chicago Data Portal — Community Area boundaries", "Free, no key", "Area, spatial joins"],
            ["US Census ACS 5-Year", "Free (instant signup key)", "Income, rent, transit ridership %, zero-vehicle %"],
            ["OpenStreetMap Overpass API", "Free, no key", "Supermarket density, highway ramp distance, walkable-amenity density"],
        ],
        "col_widths": [0.30, 0.20, 0.50],
        "wrap": [22, 16, 32],
    },
    {
        "filename": "driver_weights.png",
        "title": "Driver_Score weights",
        "headers": ["Feature", "Weight", "Why"],
        "rows": [
            ["Crime rate per 1k", "0.25", "Safety"],
            ["Crash rate per 1k", "0.15", "Vehicle-occupant risk"],
            ["Distance to nearest highway ramp", "0.25", "The explicit “highway access” ask"],
            ["Population density (parking/congestion proxy)", "0.15", "No free parking-supply dataset exists — closest available stand-in"],
            ["Grocery (supermarket) density", "0.10", "Grocery access"],
            ["Affordability index (income ÷ annual rent)", "0.10", "General cost of living"],
        ],
        "col_widths": [0.34, 0.12, 0.54],
        "wrap": [26, None, 30],
    },
    {
        "filename": "transit_weights.png",
        "title": "Transit_Score weights",
        "headers": ["Feature", "Weight", "Why"],
        "rows": [
            ["Distance to nearest CTA 'L' stop", "0.25", "The explicit “CTA proximity” ask"],
            ["Crime rate per 1k", "0.20", "Safety"],
            ["Pedestrian/cyclist crash rate per 1k", "0.15", "Street safety on the walking/biking legs of a trip"],
            ["Walkable-amenity density", "0.15", "Cafes, restaurants, pharmacies, convenience stores, etc."],
            ["Transit ridership % (commute mode)", "0.10", "Revealed preference — people who already commute by transit"],
            ["Affordability index", "0.10", "General cost of living"],
            ["Zero-vehicle-household %", "0.05", "Same revealed-preference signal, weighted low — see caveats"],
        ],
        "col_widths": [0.34, 0.12, 0.54],
        "wrap": [26, None, 30],
    },
    {
        "filename": "top5_driver.png",
        "title": "Top 5 for Car Owners",
        "headers": ["Rank", "Community Area", "Driver_Score"],
        "rows": [
            ["1", "Forest Glen", "81.3"],
            ["2", "Norwood Park", "80.1"],
            ["3", "East Side", "80.0"],
            ["4", "Avondale", "78.5"],
            ["5", "North Center", "77.8"],
        ],
        "col_widths": [0.15, 0.55, 0.30],
        "wrap": [None, None, None],
    },
    {
        "filename": "top5_transit.png",
        "title": "Top 5 for Non-Car Owners",
        "headers": ["Rank", "Community Area", "Transit_Score"],
        "rows": [
            ["1", "Lake View", "75.7"],
            ["2", "Lincoln Park", "73.2"],
            ["3", "Edgewater", "72.2"],
            ["4", "Uptown", "70.8"],
            ["5", "North Center", "70.3"],
        ],
        "col_widths": [0.15, 0.55, 0.30],
        "wrap": [None, None, None],
    },
    {
        "filename": "gap_car_dependent.png",
        "title": "Most car-dependent (Driver − Transit)",
        "headers": ["Community Area", "Gap"],
        "rows": [
            ["East Side", "+36.2"],
            ["Hegewisch", "+32.6"],
            ["Morgan Park", "+28.6"],
        ],
        "col_widths": [0.65, 0.35],
        "wrap": [None, None],
    },
    {
        "filename": "gap_transit_leaning.png",
        "title": "Most transit-leaning (Transit − Driver)",
        "headers": ["Community Area", "Gap"],
        "rows": [
            ["Rogers Park", "−9.2"],
            ["Lake View", "−6.1"],
            ["Loop", "−5.5"],
        ],
        "col_widths": [0.65, 0.35],
        "wrap": [None, None],
    },
]


def _wrap_row(row, wrap_widths):
    wrapped = []
    max_lines = 1
    for text, width in zip(row, wrap_widths):
        cell_text = textwrap.fill(text, width=width) if width else text
        wrapped.append(cell_text)
        max_lines = max(max_lines, cell_text.count("\n") + 1)
    return wrapped, max_lines


def render_table(spec):
    headers = spec["headers"]
    col_widths = spec["col_widths"]
    wrap_widths = spec.get("wrap", [None] * len(headers))

    wrapped_rows = []
    row_line_counts = []
    for row in spec["rows"]:
        wrapped, max_lines = _wrap_row(row, wrap_widths)
        wrapped_rows.append(wrapped)
        row_line_counts.append(max_lines)

    n_rows = len(wrapped_rows) + 1
    total_lines = sum(row_line_counts) + 1  # +1 for the header row

    fig_width = 10
    fig_height = 0.42 * total_lines + 0.75 + (0.5 if spec.get("title") else 0)
    fig, ax = plt.subplots(figsize=(fig_width, fig_height))
    ax.axis("off")

    if spec.get("title"):
        _ = ax.set_title(spec["title"], fontsize=13, fontweight="bold", pad=14, loc="left")

    table = ax.table(cellText=wrapped_rows, colLabels=headers, cellLoc="left", colWidths=col_widths, loc="center")
    table.auto_set_font_size(False)
    table.set_fontsize(11)

    # Row heights proportional to how many wrapped lines that row needs,
    # in axes-fraction units (all cell heights in a table must sum to 1.0).
    line_unit = 1.0 / total_lines
    for (row, _col), cell in table.get_celld().items():
        cell.set_edgecolor("#d9d9d9")
        cell.PAD = 0.03
        n_lines = 1 if row == 0 else row_line_counts[row - 1]
        cell.set_height(line_unit * n_lines)
        if row == 0:
            cell.set_facecolor("#2c3e50")
            cell.set_text_props(color="white", weight="bold", va="center")
        else:
            cell.set_text_props(va="center")
            cell.set_facecolor("#f2f2f2" if row % 2 == 0 else "white")

    fig.tight_layout()
    out_path = os.path.join(OUT_DIR, spec["filename"])
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {out_path}")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for spec in TABLES:
        render_table(spec)


if __name__ == "__main__":
    main()
