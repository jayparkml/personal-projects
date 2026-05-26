"""
Stock universe construction.

Sources (all free, no API key):
  - S&P 500:   Wikipedia table scrape
  - S&P 400:   Wikipedia table scrape
  - Russell 2000: iShares IWM holdings CSV
  - New listings: EDGAR recent S-1/registration filings

Filters:  price > $5, avg daily volume > 500K, market cap > $500M
Universe cached for UNIVERSE_REFRESH_DAYS (7 days) to avoid re-fetching daily.
"""
import logging
import re
import ssl
import time
from datetime import datetime, timedelta

import pandas as pd
import requests
import yfinance as yf

import cache
import config

# Build an SSL context that works on macOS where Python lacks system certs
try:
    import certifi
    _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
    _REQUESTS_VERIFY = certifi.where()
except ImportError:
    _SSL_CONTEXT = ssl.create_default_context()
    _REQUESTS_VERIFY = True

logger = logging.getLogger(__name__)

_SP500_URL      = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
_SP400_URL      = "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies"
_NASDAQ_SCREENER = "https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=10000&offset=0&download=true"
_EDGAR_RECENT   = "https://efts.sec.gov/LATEST/search-index?q=%22S-1%22&forms=S-1,S-11&dateRange=custom&startdt={start}&enddt={end}"


def load_universe() -> pd.DataFrame:
    """Return cached universe, rebuilding if stale or missing."""
    if _is_cache_fresh():
        df = pd.read_csv(config.UNIVERSE_FILE)
        logger.info(f"Universe loaded from cache: {len(df)} tickers")
        return df
    return build_universe()


def build_universe() -> pd.DataFrame:
    logger.info("Building stock universe...")
    tickers: set[str] = set()

    tickers |= _fetch_sp500()
    logger.info(f"  S&P 500: {len(tickers)} tickers")

    sp400 = _fetch_sp400()
    tickers |= sp400
    logger.info(f"  + S&P 400: {len(tickers)} tickers total")

    extended = _fetch_nasdaq_all_listed()
    tickers |= extended
    logger.info(f"  + NASDAQ screener (all US listed): {len(tickers)} tickers total")

    new_listings = _fetch_recent_edgar_listings()
    tickers |= new_listings
    logger.info(f"  + Recent EDGAR listings: {len(tickers)} tickers total")

    df = _filter_universe(list(tickers))
    df.to_csv(config.UNIVERSE_FILE, index=False)

    state = cache.load_state()
    state["universe_built"] = datetime.now().isoformat()
    cache.save_state(state)

    logger.info(f"Universe built and cached: {len(df)} tickers after filters")
    return df


def _is_cache_fresh() -> bool:
    import os
    if not os.path.exists(config.UNIVERSE_FILE):
        return False
    state = cache.load_state()
    built_str = state.get("universe_built")
    if not built_str:
        return False
    built = datetime.fromisoformat(built_str)
    return (datetime.now() - built) < timedelta(days=config.UNIVERSE_REFRESH_DAYS)


def _fetch_html(url: str) -> str:
    """Fetch URL text using requests with proper SSL cert handling."""
    headers = {"User-Agent": "Mozilla/5.0"}
    resp = requests.get(url, headers=headers, timeout=20, verify=_REQUESTS_VERIFY)
    resp.raise_for_status()
    return resp.text


def _fetch_sp500() -> set[str]:
    try:
        html = _fetch_html(_SP500_URL)
        tables = pd.read_html(pd.io.common.StringIO(html), attrs={"id": "constituents"})
        return set(tables[0]["Symbol"].str.replace(".", "-", regex=False).tolist())
    except Exception as e:
        logger.warning(f"S&P 500 fetch failed: {e}")
        return set()


def _fetch_sp400() -> set[str]:
    try:
        html = _fetch_html(_SP400_URL)
        tables = pd.read_html(pd.io.common.StringIO(html))
        for t in tables:
            if "Symbol" in t.columns or "Ticker" in t.columns:
                col = "Symbol" if "Symbol" in t.columns else "Ticker"
                return set(t[col].dropna().str.replace(".", "-", regex=False).tolist())
    except Exception as e:
        logger.warning(f"S&P 400 fetch failed: {e}")
    return set()


def _fetch_nasdaq_all_listed() -> set[str]:
    """
    Fetch all US-listed stocks from NASDAQ's public screener API.
    Covers NASDAQ, NYSE, and AMEX — replaces iShares Russell 2000 CSV.
    Pre-filters to market cap >= $300M to avoid wasting yfinance calls on micro-caps.
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
            "Accept": "application/json",
        }
        resp = requests.get(_NASDAQ_SCREENER, headers=headers, timeout=30, verify=_REQUESTS_VERIFY)
        resp.raise_for_status()
        rows = resp.json().get("data", {}).get("rows", [])
        tickers = set()
        for r in rows:
            if r.get("country") != "United States":
                continue
            try:
                mc = float(r.get("marketCap") or 0)
                if mc < 300_000_000:
                    continue
            except (ValueError, TypeError):
                continue
            sym = r.get("symbol", "").strip().replace("/", "-")
            # Accept clean alpha tickers and class-share tickers like BRK-B
            if sym and re.match(r"^[A-Z][A-Z0-9\-]{0,4}$", sym):
                tickers.add(sym)
        return tickers
    except Exception as e:
        logger.warning(f"NASDAQ screener fetch failed: {e}")
        return set()


def _fetch_recent_edgar_listings(days: int = 30) -> set[str]:
    """Catch newly listed/relisted companies via S-1 filings."""
    try:
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        url = _EDGAR_RECENT.format(start=start, end=end)
        headers = {"User-Agent": config.EDGAR_USER_AGENT}
        resp = requests.get(url, headers=headers, timeout=20, verify=_REQUESTS_VERIFY)
        resp.raise_for_status()
        hits = resp.json().get("hits", {}).get("hits", [])
        tickers = set()
        for h in hits:
            source = h.get("_source", {})
            display = source.get("display_names", [])
            for d in display:
                # display_names can be a list of dicts or strings depending on EDGAR version
                if isinstance(d, dict):
                    t = d.get("ticker", "")
                elif isinstance(d, str):
                    t = d
                else:
                    continue
                if t and t.isalpha() and len(t) <= 5:
                    tickers.add(t)
        return tickers
    except Exception as e:
        logger.warning(f"EDGAR recent listings fetch failed: {e}")
        return set()


def _filter_universe(tickers: list[str]) -> pd.DataFrame:
    """Apply market cap, volume, and price filters via yfinance batch metadata."""
    logger.info(f"  Filtering {len(tickers)} tickers...")
    rows = []
    batches = [tickers[i:i + config.YFINANCE_BATCH_SIZE]
               for i in range(0, len(tickers), config.YFINANCE_BATCH_SIZE)]

    for batch in batches:
        for ticker in batch:
            try:
                info = yf.Ticker(ticker).fast_info
                price     = getattr(info, "last_price", None) or 0
                market_cap = getattr(info, "market_cap", None) or 0
                avg_vol   = getattr(info, "three_month_average_volume", None) or 0

                if (price >= config.MIN_PRICE and
                        market_cap >= config.MIN_MARKET_CAP and
                        avg_vol >= config.MIN_AVG_VOLUME):
                    rows.append({
                        "ticker": ticker,
                        "market_cap": market_cap,
                        "avg_volume": avg_vol,
                        "price": price,
                    })
            except Exception:
                pass
        time.sleep(config.YFINANCE_SLEEP)

    return pd.DataFrame(rows)
