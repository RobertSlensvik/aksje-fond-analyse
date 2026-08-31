"""Nyhetsaggregering og sentiment-analyse (E24 RSS + Yahoo Finance, VADER)."""

import html
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

import feedparser
import yfinance as yf
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from .config import (
    GOOGLE_NEWS_AKTIV,
    GOOGLE_NEWS_LOKALE,
    GOOGLE_NEWS_LOKALE_DEFAULT,
    GOOGLE_NEWS_MAKS,
    GOOGLE_NEWS_URL,
    RSS_KILDER,
)
from .nyhetslogg import logg_saker


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


def _rens(tekst):
    """Fjern HTML-tagger og dekod entiteter (&nbsp;, &amp; osv.)."""
    return html.unescape(_HTML_TAG.sub("", tekst or "")).replace("\xa0", " ").strip()


def _kilde_navn(e):
    """Publisist fra <source>-elementet. Google News setter dette per sak."""
    kilde = e.get("source")
    if isinstance(kilde, dict):
        return (kilde.get("title") or "").strip()
    return ""


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
        tittel = _rens(e.get("title"))
        if not tittel:
            continue
        sammendrag = _rens(e.get("summary"))
        publisist = _kilde_navn(e)

        # Google News henger " - Publisist" på tittelen og gjentar tittelen som
        # sammendrag. Uten opprydding ville duplikater slippe gjennom dedupe og
        # sentiment-ordene blitt talt to ganger.
        if publisist:
            suffiks = f" - {publisist}"
            if tittel.endswith(suffiks):
                tittel = tittel[: -len(suffiks)].strip()
            if sammendrag.replace("  ", " ").startswith(tittel):
                sammendrag = ""

        if e.get("published_parsed"):
            dato = datetime(*e.published_parsed[:6], tzinfo=timezone.utc).isoformat()
        else:
            dato = e.get("published", "") or ""
        saker.append({
            "tittel":     tittel,
            "sammendrag": sammendrag,
            "dato":       dato,
            "url":        e.get("link", ""),
            "publisist":  publisist,
        })
    with _RSS_LOCK:
        _RSS_CACHE[url] = (now, saker)
    return saker


def _forhandshent(urls):
    """Fyll cachen for flere feeder parallelt — ellers blir det ti serielle kall."""
    manglende = [u for u in dict.fromkeys(urls) if u]
    if not manglende:
        return
    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(_hent_rss, manglende))


def _google_news_url(søkeord, flagg=""):
    """Søke-URL for ett søkeord. Lokale velges fra instrumentets flagg."""
    hl, gl = GOOGLE_NEWS_LOKALE.get(flagg, GOOGLE_NEWS_LOKALE_DEFAULT)
    q = f'"{søkeord}"' if " " in søkeord else søkeord
    return GOOGLE_NEWS_URL.format(q=quote_plus(q), hl=hl, gl=gl)


def _som_sak(sak, kilde_navn):
    """Normaliser en rå feed-sak til formatet resten av appen bruker."""
    score, etikett = scor(f"{sak['tittel']}. {sak['sammendrag']}".strip())
    return {
        "tittel":     sak["tittel"],
        "sammendrag": sak["sammendrag"][:240],
        "kilde":      sak.get("publisist") or kilde_navn,
        "dato":       sak["dato"],
        "url":        sak["url"],
        "score":      score,
        "etikett":    etikett,
    }


def _rss_treff(søkeord, flagg=""):
    """Alle RSS-saker som gjelder et instrument, nyeste først.

    Redaksjonelle feeder matches mot søkeordene. Google News-treff slipper
    matchingen — søket er allerede filteret, og en frase som "Nordea Global
    Dividend" står sjelden ordrett i en overskrift som likevel handler om det.
    `flagg` styrer Google News-lokale (norsk for 🇳🇴, engelsk ellers).
    """
    if not søkeord:
        return []

    gn_kilder = ([(s, _google_news_url(s, flagg)) for s in søkeord[:4]]
                 if GOOGLE_NEWS_AKTIV else [])
    _forhandshent([u for _, u in RSS_KILDER] + [u for _, u in gn_kilder])

    mønstre = [re.compile(rf"\b{re.escape(s)}\b", re.IGNORECASE) for s in søkeord]
    treff = []

    for kilde_navn, url in RSS_KILDER:
        for sak in _hent_rss(url):
            tekst = f"{sak['tittel']} {sak['sammendrag']}"
            if any(p.search(tekst) for p in mønstre):
                treff.append(_som_sak(sak, kilde_navn))

    for _, url in gn_kilder:
        for sak in _hent_rss(url)[:GOOGLE_NEWS_MAKS]:
            treff.append(_som_sak(sak, "Google News"))

    treff.sort(key=lambda s: s["dato"], reverse=True)
    return treff


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
    for s in _rss_treff(item.get("søkeord", []), flagg=item.get("flagg", "")):
        if s["tittel"].lower() not in sett_titler:
            saker.append(s)
            sett_titler.add(s["tittel"].lower())

    # Loggfør ALT vi fant, også måneder gamle Google News-treff — de er straks
    # målbare mot kurshistorikken og er hovedgevinsten for treffsikkerheten.
    try:
        logg_saker(item["ticker"], saker)
    except Exception:
        pass

    # ...men returner bare de ferskeste. Ellers ville gamle saker dratt
    # dagens sentiment-snitt i Nyheter-fanen.
    saker.sort(key=lambda s: s["dato"] or "", reverse=True)
    return saker[:maks]


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
