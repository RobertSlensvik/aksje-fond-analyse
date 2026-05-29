"""Nyhetsaggregering og sentiment-analyse (E24 RSS + Yahoo Finance, VADER)."""

import re
import threading
import time
from datetime import datetime, timedelta, timezone

import feedparser
import yfinance as yf
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from .config import RSS_KILDER


_HTML_TAG = re.compile(r"<[^>]+>")
_sentiment = SentimentIntensityAnalyzer()

_RSS_CACHE = {}                    # url → (henta_ts, [normaliserte saker])
_RSS_CACHE_TTL = 600               # 10 min
_RSS_LOCK = threading.Lock()


def scor(tekst):
    """VADER compound + etikett for en streng."""
    compound = _sentiment.polarity_scores(tekst)["compound"]
    return round(compound, 3), (
        "positiv" if compound > 0.05 else "negativ" if compound < -0.05 else "nøytral"
    )


def retning(snitt):
    """Tolkning av aggregert sentiment-score til retning."""
    if snitt > 0.1:
        return {"retning": "opp",     "tekst": "↗ Opp",     "farge": "pos"}
    if snitt < -0.1:
        return {"retning": "ned",     "tekst": "↘ Ned",     "farge": "neg"}
    return {"retning": "nøytral", "tekst": "→ Nøytral", "farge": "neu"}


def _hent_rss(url):
    """Hent og normaliser RSS-saker fra én feed, med TTL-cache."""
    now = time.time()
    with _RSS_LOCK:
        cached = _RSS_CACHE.get(url)
        if cached and now - cached[0] < _RSS_CACHE_TTL:
            return cached[1]
    try:
        feed = feedparser.parse(url, request_headers={"User-Agent": "Mozilla/5.0"})
    except Exception:
        return []
    saker = []
    for e in feed.entries:
        tittel = (e.get("title") or "").strip()
        if not tittel:
            continue
        sammendrag = _HTML_TAG.sub("", e.get("summary", "") or "").strip()
        if e.get("published_parsed"):
            dato = datetime(*e.published_parsed[:6], tzinfo=timezone.utc).isoformat()
        else:
            dato = e.get("published", "") or ""
        saker.append({
            "tittel":     tittel,
            "sammendrag": sammendrag,
            "dato":       dato,
            "url":        e.get("link", ""),
        })
    with _RSS_LOCK:
        _RSS_CACHE[url] = (now, saker)
    return saker


def _rss_treff(søkeord, maks=6):
    """Finn RSS-saker som matcher minst ett søkeord (case-insensitivt, ordgrense)."""
    if not søkeord:
        return []
    mønstre = [re.compile(rf"\b{re.escape(s)}\b", re.IGNORECASE) for s in søkeord]
    treff = []
    for kilde_navn, url in RSS_KILDER:
        for sak in _hent_rss(url):
            tekst = f"{sak['tittel']} {sak['sammendrag']}"
            if any(p.search(tekst) for p in mønstre):
                score, etikett = scor(f"{sak['tittel']}. {sak['sammendrag']}")
                treff.append({
                    "tittel":     sak["tittel"],
                    "sammendrag": sak["sammendrag"][:240],
                    "kilde":      kilde_navn,
                    "dato":       sak["dato"],
                    "url":        sak["url"],
                    "score":      score,
                    "etikett":    etikett,
                })
    treff.sort(key=lambda s: s["dato"], reverse=True)
    return treff[:maks]


def hent_nyheter_for(item, maks=8):
    """Hent nyhetsoverskrifter via yfinance + RSS, dedupe og scor."""
    try:
        raw = yf.Ticker(item["ticker"]).news or []
    except Exception:
        raw = []

    saker = []
    for n in raw[:maks]:
        c = n.get("content", n) if isinstance(n, dict) else {}
        tittel = c.get("title") or n.get("title", "")
        if not tittel:
            continue
        sammendrag = c.get("summary") or n.get("summary", "") or ""
        prov = c.get("provider") or {}
        kilde = (prov.get("displayName") if isinstance(prov, dict) else None) or n.get("publisher", "")
        dato = c.get("pubDate") or ""
        url = ""
        link = c.get("canonicalUrl") or c.get("clickThroughUrl")
        if isinstance(link, dict):
            url = link.get("url", "")
        elif isinstance(link, str):
            url = link
        if not url:
            url = n.get("link", "")

        score, etikett = scor(f"{tittel}. {sammendrag}".strip())
        saker.append({
            "tittel":     tittel,
            "sammendrag": sammendrag[:240],
            "kilde":      kilde,
            "dato":       dato,
            "url":        url,
            "score":      score,
            "etikett":    etikett,
        })

    sett_titler = {s["tittel"].lower() for s in saker}
    for s in _rss_treff(item.get("søkeord", [])):
        if s["tittel"].lower() not in sett_titler:
            saker.append(s)
            sett_titler.add(s["tittel"].lower())

    return saker


def hete_siste_uke(saker, logger=None):
    """Antall saker siste 7 dager — brukes til å rangere 'hete' instrumenter."""
    grense = datetime.now(timezone.utc) - timedelta(days=7)
    n = 0
    for s in saker:
        dato_raw = s.get("dato", "")
        if not dato_raw:
            continue
        try:
            d = datetime.fromisoformat(dato_raw.replace("Z", "+00:00"))
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            if d >= grense:
                n += 1
        except (ValueError, AttributeError) as e:
            if logger is not None:
                logger.debug("Kunne ikke parse dato %r: %s", dato_raw, e)
            continue
    return n
