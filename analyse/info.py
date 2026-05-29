"""Henting og presentasjon av instrument-info (pris, nøkkeltall, MA-signal)."""

import pandas as pd
import yfinance as yf

from .cache import INFO_CACHE, INFO_TTL, cache_get, cache_set, hent_historikk
from .formatting import fmt_store, fmt_tall, fmt_utbytte
from .instrumenter import alle_instrumenter


# Avkastningsperioder for oversikten: nøkkel → kalenderdager tilbake.
AVK_PERIODER = {"1d": 1, "1u": 7, "1m": 30, "1y": 365, "5y": 1826, "10y": 3652}


def periode_avkastning(close):
    """Prosentvis avkastning per periode i AVK_PERIODER fra en prisserie.

    For hver periode brukes siste tilgjengelige kurs på eller før måldatoen,
    slik at helger/helligdager håndteres. Mangler historikken så langt
    tilbake, blir verdien None.
    """
    avk = {nøkkel: None for nøkkel in AVK_PERIODER}
    if close is None or len(close) < 2:
        return avk
    siste_dato = close.index[-1]
    siste = float(close.iloc[-1])
    if siste <= 0:
        return avk
    for nøkkel, dager in AVK_PERIODER.items():
        tidligere = close[close.index <= siste_dato - pd.Timedelta(days=dager)]
        if tidligere.empty:
            continue
        base = float(tidligere.iloc[-1])
        if base > 0:
            avk[nøkkel] = round((siste / base - 1) * 100, 2)
    return avk


def hent_info(ticker_str):
    """Hent og normaliser info for ett instrument. Cache 5 min."""
    cached = cache_get(INFO_CACHE, ticker_str, INFO_TTL)
    if cached is not None:
        return cached

    meta = next((x for x in alle_instrumenter() if x["ticker"] == ticker_str), {})
    try:
        info = yf.Ticker(ticker_str).info or {}
        hist = hent_historikk(ticker_str, "5d")

        naapris = None
        endring_pct = None
        if hist is not None and not hist.empty:
            naapris = float(hist["Close"].iloc[-1])
            if len(hist) >= 2:
                forrige = float(hist["Close"].iloc[-2])
                endring_pct = ((naapris - forrige) / forrige) * 100

        # Full historikk for periode-avkastning (siste dag → 10 år). "max"
        # framfor "10y" sikrer at det finnes en kurs >10 år tilbake; deles med
        # prognose-cachen. Eldre/lengre historikk enn 10 år ignoreres her.
        lang_hist = hent_historikk(ticker_str, "max")
        avkastning = periode_avkastning(lang_hist["Close"] if lang_hist is not None else None)
        if avkastning["1d"] is None and endring_pct is not None:
            avkastning["1d"] = round(endring_pct, 2)

        valuta = info.get("currency", "")
        snitt_200d_raw = info.get("twoHundredDayAverage")
        ma_signal = None
        if naapris and snitt_200d_raw:
            try:
                ma_signal = "over" if naapris >= float(snitt_200d_raw) else "under"
            except (TypeError, ValueError):
                ma_signal = None

        resultat = {
            "ticker":        ticker_str,
            "navn":          meta.get("navn", info.get("longName", ticker_str)),
            "type":          meta.get("type", "ukjent"),
            "sektor":        meta.get("sektor", info.get("sector", "–")),
            "flagg":         meta.get("flagg", ""),
            "pris":          naapris,
            "pris_fmt":      f"{fmt_tall(naapris)} {valuta}" if naapris else "–",
            "endring_pct":   endring_pct,
            "avkastning":    avkastning,
            "valuta":        valuta,
            "markedsverdi":  fmt_store(info.get("marketCap")),
            "pe_ratio":      fmt_tall(info.get("trailingPE")),
            "utbytte":       fmt_utbytte(info.get("dividendYield")),
            "52_ukers_høy":  fmt_tall(info.get("fiftyTwoWeekHigh")),
            "52_ukers_lav":  fmt_tall(info.get("fiftyTwoWeekLow")),
            "snitt_50d":     fmt_tall(info.get("fiftyDayAverage")),
            "snitt_200d":    fmt_tall(snitt_200d_raw),
            "ma_signal":     ma_signal,
            "beskrivelse":   (info.get("longBusinessSummary") or "")[:300],
        }
        cache_set(INFO_CACHE, ticker_str, resultat)
        return resultat
    except Exception as e:
        # Ikke cache feil — neste forespørsel skal kunne prøve på nytt.
        return {
            "ticker":  ticker_str,
            "navn":    meta.get("navn", ticker_str),
            "type":    meta.get("type", "ukjent"),
            "sektor":  meta.get("sektor", "–"),
            "flagg":   meta.get("flagg", ""),
            "feil":    str(e),
        }
