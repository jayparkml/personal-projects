"""
Reddit mention velocity — rate of change in ticker mentions.

Key insight: *acceleration* of mentions (going from 2/day to 20/day) is a
leading indicator. Absolute mention count is lagging — by the time a stock
has 500 mentions on WSB, the move has already happened.

Uses Reddit's public JSON API (no OAuth required for read-only scrapes).
Unauthenticated: ~30 req/min. Set REDDIT_CLIENT_ID env var for OAuth (600/10min).
"""
import logging
import re
import time
from datetime import datetime

import requests

import cache
import config

logger = logging.getLogger(__name__)

_REDDIT_BASE = "https://www.reddit.com/r/{subreddit}/new.json?limit=100&after={after}"
_REDDIT_HEADERS = {
    "User-Agent": config.REDDIT_USER_AGENT,
}

# Pre-compiled ticker pattern: $AAPL or AAPL in word context
_TICKER_RE = re.compile(r"\$([A-Z]{1,5})\b|\b([A-Z]{2,5})\b")


def fetch_subreddit_mentions(subreddit: str, pages: int = 3) -> dict[str, int]:
    """
    Scrape recent posts from a subreddit and count ticker mentions.
    Returns {ticker: count}.
    """
    mentions: dict[str, int] = {}
    after = ""

    for _ in range(pages):
        url = _REDDIT_BASE.format(subreddit=subreddit, after=after)
        try:
            resp = requests.get(url, headers=_REDDIT_HEADERS, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.debug(f"Reddit fetch failed for r/{subreddit}: {e}")
            break

        posts = data.get("data", {}).get("children", [])
        if not posts:
            break

        for post in posts:
            post_data = post.get("data", {})
            text = f"{post_data.get('title', '')} {post_data.get('selftext', '')}"
            for ticker in _extract_tickers(text):
                mentions[ticker] = mentions.get(ticker, 0) + 1

        after = data.get("data", {}).get("after", "")
        if not after:
            break
        time.sleep(0.5)  # Respect rate limit

    return mentions


def _extract_tickers(text: str) -> list[str]:
    """Extract valid ticker symbols from text, filtering known false positives."""
    found = []
    for m in _TICKER_RE.finditer(text):
        ticker = (m.group(1) or m.group(2)).upper()
        if ticker not in config.TICKER_FALSE_POSITIVES and 2 <= len(ticker) <= 5:
            found.append(ticker)
    return found


def fetch_all_subreddit_mentions() -> dict[str, int]:
    """Aggregate mentions across all configured subreddits."""
    combined: dict[str, int] = {}
    for subreddit in config.SUBREDDITS:
        sub_mentions = fetch_subreddit_mentions(subreddit)
        for ticker, count in sub_mentions.items():
            combined[ticker] = combined.get(ticker, 0) + count
    return combined


def compute_sentiment_score(ticker: str, today_mentions: dict[str, int]) -> tuple[float, dict]:
    """
    Compute mention velocity score (0-100) for a ticker.

    Velocity = today_mentions / 7-day_average_baseline
    2x = 30 pts, 5x = 60 pts, 10x+ = 100 pts
    """
    current = today_mentions.get(ticker, 0)
    baseline = cache.get_sentiment_baseline(ticker, lookback_days=7)

    if baseline < 1:
        # No historical baseline — score based on absolute mentions alone
        # A stock getting 5+ mentions with no history is interesting
        if current >= 10:
            score = min(60, current * 4)
        elif current >= 5:
            score = 20
        else:
            score = 0
        velocity = None
    else:
        velocity = current / baseline
        if velocity < 2:
            score = 0
        elif velocity >= 10:
            score = 100
        else:
            # Linear: 2x = 30, 10x = 100
            score = int(30 + (velocity - 2) * 70 / 8)

    return float(score), {
        "today_mentions": current,
        "baseline_avg": round(baseline, 1),
        "velocity": round(velocity, 2) if velocity is not None else None,
    }
