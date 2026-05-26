"""All parameters — single source of truth for spike_scanner."""
import os

# ── Paths ─────────────────────────────────────────────────────────────────────
PROJECT_DIR   = os.path.dirname(os.path.abspath(__file__))
DATA_DIR      = os.path.join(PROJECT_DIR, "data")
CACHE_DIR     = os.path.join(DATA_DIR, "cache")
REPORT_DIR    = os.path.join(DATA_DIR, "reports")
STATE_FILE    = os.path.join(DATA_DIR, "state.json")
UNIVERSE_FILE = os.path.join(DATA_DIR, "universe_cache.csv")
LOG_FILE      = os.path.join(DATA_DIR, "scanner.log")

# ── Universe Filters ──────────────────────────────────────────────────────────
MIN_MARKET_CAP        = 500_000_000   # $500M — filter out micro-caps
MIN_AVG_VOLUME        = 500_000       # 500K shares/day
MIN_PRICE             = 5.0           # Skip penny stocks
UNIVERSE_REFRESH_DAYS = 7             # Rebuild universe weekly

# ── Signal Weights (must sum to 100) ─────────────────────────────────────────
WEIGHTS = {
    "sec_filings":         25,
    "insider_buying":      20,
    "volume_anomaly":      20,
    "sentiment_velocity":  15,
    "short_squeeze":       10,
    "options_flow":         5,
    "technicals":           5,
}

# ── Score Thresholds ──────────────────────────────────────────────────────────
HOT_THRESHOLD  = 60   # Score >= 60
WARM_THRESHOLD = 40   # Score 40-59
TOP_N_REPORT   = 25   # Stocks shown in daily report

# ── Volume Anomaly ────────────────────────────────────────────────────────────
VOL_LOOKBACK_SHORT  = 5    # Recent: 5-day avg
VOL_LOOKBACK_LONG   = 30   # Baseline: 30-day avg
VOL_SURGE_THRESHOLD = 2.0  # 2x baseline = notable
VOL_SPIKE_THRESHOLD = 4.0  # 4x baseline = max score

# ── Price Compression (Bollinger Band) ───────────────────────────────────────
BB_PERIOD                  = 20
BB_COMPRESSION_PERCENTILE  = 10   # Bottom 10th percentile of 252-day BB width history

# ── EDGAR Settings ────────────────────────────────────────────────────────────
EDGAR_USER_AGENT    = "SpikeScanner/1.0 contact@example.com"  # SEC requires User-Agent
EDGAR_LOOKBACK_DAYS = 3     # Check filings from last 3 calendar days
EDGAR_SLEEP         = 0.15  # ~7 req/sec — well under SEC's 10 req/sec limit
FORM_TYPES_MATERIAL = ["8-K", "8-K/A"]
FORM_TYPES_ACTIVIST = ["SC 13D", "SC 13D/A", "SC 13G", "SC 13G/A"]
FORM_TYPES_INSIDER  = ["4", "4/A"]

# 8-K item scores (Item number → score contribution 0-100)
EDGAR_8K_ITEM_SCORES = {
    "1.01": 100,  # M&A / definitive agreement
    "2.01": 90,   # Completion of acquisition/disposition
    "7.01": 70,   # Regulation FD disclosure (often revenue guidance)
    "8.01": 60,   # Other events (catch-all, still material)
    "5.02": 40,   # Leadership change (new CEO/board)
    "2.02": 30,   # Results of operations (earnings)
    "1.02": 20,   # Termination of material agreement (negative)
}

# ── Reddit Settings ───────────────────────────────────────────────────────────
REDDIT_CLIENT_ID     = os.environ.get("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.environ.get("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT    = "spike_scanner/1.0"
SUBREDDITS           = ["wallstreetbets", "stocks", "investing", "options"]
SENTIMENT_LOOKBACK_HOURS = 24   # Mentions in last 24h vs prior 7-day average

# Known false-positive ticker strings to filter from Reddit text
TICKER_FALSE_POSITIVES = {
    "A", "I", "IT", "AT", "BE", "BY", "DO", "GO", "IF", "IN", "IS",
    "ME", "NO", "OF", "ON", "OR", "SO", "TO", "UP", "US", "WE",
    "ALL", "AND", "ARE", "FOR", "HAS", "NEW", "NOW", "THE", "TOO",
    "CEO", "CFO", "COO", "IPO", "ETF", "NYSE", "SEC", "FED", "GDP",
    "EPS", "ATM", "OTM", "ITM", "WSB", "DD", "TA", "PT",
}

# ── yfinance Settings ─────────────────────────────────────────────────────────
YFINANCE_BATCH_SIZE = 50    # Tickers per yfinance.download() call
YFINANCE_SLEEP      = 1.0   # Seconds between batches
YFINANCE_PERIOD     = "1y"  # Price history period (enough for BB, 52w high)

# ── Parallel Processing ───────────────────────────────────────────────────────
MAX_WORKERS = 4   # ThreadPoolExecutor workers for signal computation

# ── API Keys (optional — free tier works without these) ──────────────────────
POLYGON_API_KEY    = os.environ.get("POLYGON_API_KEY", "")
UNUSUAL_WHALES_KEY = os.environ.get("UNUSUAL_WHALES_KEY", "")
