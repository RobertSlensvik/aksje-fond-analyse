"""TTL-cache for yfinance-data.

Yahoo-kall er trege og rate-limites lett. Caches deles på tvers av alle
endpoints. Cache lever i prosessen — perfekt for én-bruker-lokal-app, dårlig
hvis du noensinne vil skalere horisontalt.
"""

import threading
import time

import yfinance as yf


# Cache-strukturer: key → (timestamp, value).
INFO_CACHE = {}                     # ticker → (ts, dict)
HIST_CACHE = {}                     # (ticker, periode) → (ts, DataFrame)

INFO_TTL = 300                      # 5 min
HIST_TTL = 900                      # 15 min

_LOCK = threading.Lock()


def cache_get(cache, key, ttl):
    """Returner cached verdi hvis fersk, ellers None."""
    now = time.time()
    with _LOCK:
        entry = cache.get(key)
        if entry and now - entry[0] < ttl:
            return entry[1]
    return None


def cache_set(cache, key, value):
    """Lagre verdi i cache med nåværende timestamp."""
    with _LOCK:
        cache[key] = (time.time(), value)


def hent_historikk(ticker_str, yf_periode):
    """Hent historikk-DataFrame med TTL-cache. Returner None ved feil/tom."""
    key = (ticker_str, yf_periode)
    cached = cache_get(HIST_CACHE, key, HIST_TTL)
    if cached is not None:
        return cached
    try:
        hist = yf.Ticker(ticker_str).history(period=yf_periode)
        if hist.empty:
            return None
        cache_set(HIST_CACHE, key, hist)
        return hist
    except Exception:
        return None
