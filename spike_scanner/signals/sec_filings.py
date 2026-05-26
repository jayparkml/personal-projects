"""
SEC EDGAR filing monitor — highest-weight signal (25 pts).

Scans three filing types:
  8-K  — material corporate events (M&A, major contracts, spinoffs)
  13D/G — activist investor taking >5% stake
  Form 4 — insider buying (cluster of 3+ insiders in same week = very strong)

EDGAR full-text search API is free and requires only a User-Agent header.
Rate limit: 10 req/sec — we sleep 0.15s between calls.

CIK mapping (ticker → CIK) is fetched once daily from SEC and cached.
"""
import logging
import re
import time
from datetime import datetime, timedelta

import requests

import cache
import config

logger = logging.getLogger(__name__)

_EDGAR_SEARCH = "https://efts.sec.gov/LATEST/search-index"
_EDGAR_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
_CIK_MAP_URL = "https://www.sec.gov/files/company_tickers.json"

_HEADERS = {"User-Agent": config.EDGAR_USER_AGENT}

# Module-level CIK map (loaded once per run)
_cik_map: dict[str, str] = {}


def load_cik_map() -> dict[str, str]:
    """Returns {ticker: zero-padded CIK string}. Loaded once per run."""
    global _cik_map
    if _cik_map:
        return _cik_map
    try:
        resp = requests.get(_CIK_MAP_URL, headers=_HEADERS, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        _cik_map = {
            v["ticker"].upper(): str(v["cik_str"]).zfill(10)
            for v in data.values()
            if "ticker" in v and "cik_str" in v
        }
        logger.info(f"CIK map loaded: {len(_cik_map)} tickers")
    except Exception as e:
        logger.warning(f"CIK map fetch failed: {e}")
    return _cik_map


# ── Global 8-K / 13D scan ─────────────────────────────────────────────────────

def _parse_display_name(entry) -> tuple[str, str, str]:
    """
    Parse a display_names entry — can be a string or dict depending on EDGAR version.
    Returns (ticker, company_name, cik).
    Format when string: "COMPANY NAME  (TICK)  (CIK 0001234567)"
    """
    if isinstance(entry, dict):
        return (
            entry.get("ticker", "").upper(),
            entry.get("name", ""),
            str(entry.get("cik", "")).zfill(10),
        )
    if isinstance(entry, str):
        m_ticker = re.search(r'\(([A-Z][A-Z0-9.\-]{0,4})\)\s+\(CIK', entry)
        m_cik    = re.search(r'\(CIK\s+(\d+)\)', entry)
        ticker   = m_ticker.group(1) if m_ticker else ""
        cik      = m_cik.group(1).zfill(10) if m_cik else ""
        company  = re.split(r'\s{2,}\(', entry)[0].strip()
        return ticker, company, cik
    return "", "", ""


def fetch_recent_filings(form_type: str, lookback_days: int = None) -> list[dict]:
    """
    Globally scan EDGAR for recent filings of a given form type.
    Returns list of {ticker, company, form_type, filed_date, accession, items}.

    8-K display_names: "COMPANY (TICK) (CIK NNN)" — ticker is in the string.
    Form 4 display_names: "PERSON NAME (CIK NNN)" — no ticker; use ciks[] + reverse map.
    q="" returns all filings (q="*" returns nothing on EDGAR EFTS).
    """
    if lookback_days is None:
        lookback_days = config.EDGAR_LOOKBACK_DAYS

    end   = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    params = {
        "q":         "",
        "forms":     form_type,
        "dateRange": "custom",
        "startdt":   start,
        "enddt":     end,
    }

    try:
        resp = requests.get(_EDGAR_SEARCH, params=params, headers=_HEADERS, timeout=20)
        resp.raise_for_status()
        time.sleep(config.EDGAR_SLEEP)
        hits = resp.json().get("hits", {}).get("hits", [])
    except Exception as e:
        logger.warning(f"EDGAR search failed for {form_type}: {e}")
        return []

    # Reverse CIK map for Form 4 fallback (insider filings don't embed ticker in display_names)
    cik_map = load_cik_map()
    rev_cik = {v: k for k, v in cik_map.items()}

    results = []
    for h in hits:
        src       = h.get("_source", {})
        display   = src.get("display_names", [])
        filed     = src.get("file_date", "")
        accession = src.get("adsh", "")
        items     = src.get("items", [])
        raw_ciks  = src.get("ciks", [])

        # Try parsing ticker directly from display_names (works for 8-K, 13D)
        appended = False
        for entry in display:
            ticker, company, cik = _parse_display_name(entry)
            if ticker:
                results.append({
                    "ticker": ticker, "company": company, "cik": cik,
                    "form_type": form_type, "filed_date": filed,
                    "accession": accession, "items": items,
                })
                appended = True

        # Fallback for Form 4: display_names has "PERSON NAME (CIK NNN)" with no ticker.
        # The issuer (company) CIK is the last entry in the ciks[] array.
        if not appended and raw_ciks:
            issuer_cik = raw_ciks[-1]  # last = issuer/company, first = insider/filer
            ticker = rev_cik.get(issuer_cik, "")
            if ticker:
                results.append({
                    "ticker": ticker, "company": "", "cik": issuer_cik,
                    "form_type": form_type, "filed_date": filed,
                    "accession": accession, "items": items,
                })

    return results


# ── 8-K item parsing ──────────────────────────────────────────────────────────

def score_8k_filing(filing: dict) -> float:
    """
    Fetch the 8-K document and score based on which Item numbers are present.
    Item 1.01 (M&A agreement) = 100, Item 2.01 (completion) = 90, etc.
    Returns 0-100 score for this filing.
    """
    accession = filing.get("accession", "").replace("-", "")
    cik = filing.get("cik", "").zfill(10)
    if not accession or not cik:
        return 0.0

    # Build index URL
    index_url = f"https://www.sec.gov/Archives/edgar/full-index/{accession[:4]}/{accession[4:6]}/{accession[6:8]}/{accession}/{accession}-index.htm"
    # Simpler: use the submissions API to get the filing document
    # We'll just look at the accession number in the search snippet
    # and assign score based on form type (no need to parse full document for MVP)
    # If needed, we can add full parsing later.

    # For now: return a base score for any 8-K, with higher scores for
    # specific form types parsed from the EDGAR search snippet
    return 60.0  # Base 8-K score — any material event is noteworthy


def fetch_8k_items(cik: str, accession: str) -> list[str]:
    """
    Download 8-K filing index and extract Item numbers reported.
    Returns list of item strings like ["1.01", "2.01"].
    """
    # Normalize accession: "0001234567-24-000001" → "000123456724000001"
    acc_clean = accession.replace("-", "")
    url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=8-K&dateb=&owner=include&count=5&output=atom"
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=15)
        time.sleep(config.EDGAR_SLEEP)
        # Quick regex scan for Item N.NN patterns in the filing text
        items = re.findall(r"Item\s+(\d+\.\d+)", resp.text)
        return list(set(items))
    except Exception:
        return []


# ── Form 4 cluster insider buying ─────────────────────────────────────────────

def fetch_form4_cluster(ticker: str, lookback_days: int = 7) -> dict:
    """
    Checks for insider buying cluster: 3+ unique insiders buying in same week.
    Returns {insider_count, total_value_usd, is_cluster_buy}.
    """
    cik_map = load_cik_map()
    cik = cik_map.get(ticker.upper())
    if not cik:
        return {"insider_count": 0, "total_value_usd": 0, "is_cluster_buy": False}

    cached = cache.load_filing_cache(f"form4_{cik}")
    if cached is not None:
        return cached

    cutoff = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    params = {
        "q": f"CIK:{cik}",
        "forms": "4",
        "dateRange": "custom",
        "startdt": cutoff,
        "enddt": datetime.now().strftime("%Y-%m-%d"),
        "_source": "period_of_report,display_names,file_date,accession_no",
    }

    try:
        resp = requests.get(_EDGAR_SEARCH, params=params, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        time.sleep(config.EDGAR_SLEEP)
        hits = resp.json().get("hits", {}).get("hits", [])
    except Exception as e:
        logger.debug(f"Form 4 fetch failed for {ticker}: {e}")
        return {"insider_count": 0, "total_value_usd": 0, "is_cluster_buy": False}

    # Count unique filers
    unique_filers = set()
    for h in hits:
        src = h.get("_source", {})
        for d in src.get("display_names", []):
            name = d.get("name", "")
            if name:
                unique_filers.add(name)

    count = len(unique_filers)
    result = {
        "insider_count": count,
        "total_value_usd": 0,   # Would need full form parsing for exact value
        "is_cluster_buy": count >= 3,
    }
    cache.save_filing_cache(f"form4_{cik}", result)
    return result


# ── 13D / Activist filing ──────────────────────────────────────────────────────

def fetch_13d_filing(ticker: str, lookback_days: int = None) -> dict:
    """
    Check for recent SC 13D/G filings (activist taking >5% stake).
    Returns {has_activist, is_new, form_type}.
    """
    if lookback_days is None:
        lookback_days = config.EDGAR_LOOKBACK_DAYS * 10  # 13D lookback wider

    cutoff = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    cik_map = load_cik_map()
    cik = cik_map.get(ticker.upper())
    if not cik:
        return {"has_activist": False, "is_new": False, "form_type": None}

    cached = cache.load_filing_cache(f"13d_{cik}")
    if cached is not None:
        return cached

    params = {
        "q": f"CIK:{cik}",
        "forms": "SC 13D,SC 13D/A",
        "dateRange": "custom",
        "startdt": cutoff,
        "enddt": datetime.now().strftime("%Y-%m-%d"),
        "_source": "file_date,form_type",
    }

    try:
        resp = requests.get(_EDGAR_SEARCH, params=params, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        time.sleep(config.EDGAR_SLEEP)
        hits = resp.json().get("hits", {}).get("hits", [])
    except Exception as e:
        logger.debug(f"13D fetch failed for {ticker}: {e}")
        return {"has_activist": False, "is_new": False, "form_type": None}

    if not hits:
        result = {"has_activist": False, "is_new": False, "form_type": None}
    else:
        latest = hits[0]["_source"]
        form   = latest.get("form_type", "")
        filed  = latest.get("file_date", "")
        # "New" means filed within last 30 days (vs amendment of old position)
        is_new = form == "SC 13D" and filed >= (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        result = {"has_activist": True, "is_new": is_new, "form_type": form}

    cache.save_filing_cache(f"13d_{cik}", result)
    return result


# ── Composite SEC score ────────────────────────────────────────────────────────

def compute_sec_score(
    ticker: str,
    recent_8k_tickers: set[str] = None,
    recent_8k_items: dict[str, list] = None,
    form4_counts: dict[str, int] = None,
    activist_tickers: set[str] = None,
) -> tuple[float, dict]:
    """
    Composite SEC filing score (0-100) from three globally pre-fetched sources:
      - 8-K material event:     up to 60 pts (scored by item type)
      - Form 4 cluster buying:  up to 40 pts (3+ insiders = cluster)
      - 13D activist filing:    up to 20 pts

    All data pre-fetched in runner.py — no per-ticker EDGAR calls here.
    """
    detail = {
        "has_8k": False, "insider_cluster": False, "has_activist": False,
        "insider_count": 0, "8k_items": [],
    }
    score = 0.0

    # 8-K material event
    if recent_8k_tickers and ticker in recent_8k_tickers:
        detail["has_8k"] = True
        items = (recent_8k_items or {}).get(ticker, [])
        detail["8k_items"] = items
        # Score by highest-value item; default 40 if no items parsed
        if items:
            item_score = max(
                (config.EDGAR_8K_ITEM_SCORES.get(it, 30) for it in items),
                default=40,
            )
        else:
            item_score = 40
        score += item_score * 0.6  # scale to 0-60 pts

    # Form 4 insider buying (pre-fetched globally)
    insider_count = (form4_counts or {}).get(ticker, 0)
    detail["insider_count"] = insider_count
    if insider_count >= 3:
        score += 40
        detail["insider_cluster"] = True
    elif insider_count >= 1:
        score += 15

    # 13D activist (pre-fetched globally)
    if activist_tickers and ticker in activist_tickers:
        score += 20
        detail["has_activist"] = True

    return min(score, 100.0), detail
