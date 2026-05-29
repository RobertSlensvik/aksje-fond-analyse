"""Bruker-administrerte instrumenter og porteføljevalg.

Kombinerer en liten standard-katalog (`STANDARD_*` i config) med en bruker-lagt
liste i `bruker_instrumenter.json`. Brukerens portefølje-valg lagres separat i
`bruker_portefolje.json`. Begge filene er gitignored.

In-memory cache invalideres ved hver skriving.
"""

import json
import os
import tempfile
import threading

import yfinance as yf

from .config import (
    BRUKER_INSTRUMENTER_FIL,
    BRUKER_PORTEFOLJE_FIL,
    STANDARD_AKSJER,
    STANDARD_FOND,
    STANDARD_PORTEFOLJE_TICKERS,
)


_LOCK = threading.Lock()
_alle_cache = None
_portefolje_cache = None


# ─── JSON-hjelpere ──────────────────────────────────────────────────────────

def _les_json(path, default):
    """Les JSON-fil med fallback til default ved manglende fil eller parse-feil."""
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if data is not None else default
    except (OSError, json.JSONDecodeError):
        return default


def _skriv_json_atomisk(path, data):
    """Atomisk skriving via temp-fil + rename."""
    katalog = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(
        dir=katalog,
        prefix="." + os.path.basename(path) + "_",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _invalider():
    global _alle_cache, _portefolje_cache
    with _LOCK:
        _alle_cache = None
        _portefolje_cache = None


# ─── Lese-API ───────────────────────────────────────────────────────────────

def alle_instrumenter():
    """Standard + bruker-lagte instrumenter, kombinert. Cached i minne."""
    global _alle_cache
    with _LOCK:
        if _alle_cache is None:
            bruker = _les_json(BRUKER_INSTRUMENTER_FIL, [])
            _alle_cache = STANDARD_AKSJER + STANDARD_FOND + bruker
    return _alle_cache


def aksjer():
    return [x for x in alle_instrumenter() if x.get("type") == "aksje"]


def fond():
    return [x for x in alle_instrumenter() if x.get("type") == "fond"]


def er_brukerlagt(ticker):
    """True hvis ticker er bruker-lagt (ikke fra STANDARD-lister)."""
    standard = {x["ticker"] for x in STANDARD_AKSJER + STANDARD_FOND}
    return ticker not in standard


def portefolje_tickere():
    """Tickere markert som 'i min portefølje'. Cached."""
    global _portefolje_cache
    with _LOCK:
        if _portefolje_cache is None:
            fra_fil = _les_json(BRUKER_PORTEFOLJE_FIL, None)
            _portefolje_cache = list(fra_fil) if fra_fil is not None else list(STANDARD_PORTEFOLJE_TICKERS)
    return _portefolje_cache


# ─── Skrive-API ─────────────────────────────────────────────────────────────

def legg_til(instrument):
    """Legg til nytt bruker-instrument.

    Krever keys: ticker, navn, type ('aksje'/'fond'). Valgfritt: sektor, flagg, søkeord.
    Kaster ValueError hvis ticker allerede finnes.
    """
    ticker = (instrument.get("ticker") or "").strip()
    if not ticker:
        raise ValueError("Ticker mangler")
    if any(x["ticker"] == ticker for x in alle_instrumenter()):
        raise ValueError(f"{ticker} finnes allerede")

    bruker = _les_json(BRUKER_INSTRUMENTER_FIL, [])
    bruker.append({
        "ticker":  ticker,
        "navn":    instrument.get("navn") or ticker,
        "type":    instrument.get("type") if instrument.get("type") in ("aksje", "fond") else "aksje",
        "sektor":  instrument.get("sektor") or "–",
        "flagg":   instrument.get("flagg") or "",
        "søkeord": instrument.get("søkeord") or [instrument.get("navn") or ticker],
    })
    _skriv_json_atomisk(BRUKER_INSTRUMENTER_FIL, bruker)
    _invalider()


def fjern(ticker):
    """Fjern et bruker-lagt instrument. Standard-instrumenter kan ikke fjernes."""
    if not er_brukerlagt(ticker):
        raise ValueError(f"{ticker} er et standard-instrument og kan ikke slettes")

    bruker = _les_json(BRUKER_INSTRUMENTER_FIL, [])
    nye = [x for x in bruker if x["ticker"] != ticker]
    if len(nye) == len(bruker):
        raise ValueError(f"{ticker} finnes ikke i bruker-lista")
    _skriv_json_atomisk(BRUKER_INSTRUMENTER_FIL, nye)

    # Fjern også fra portefølje hvis den lå der.
    port = portefolje_tickere()
    if ticker in port:
        sett_portefolje([t for t in port if t != ticker])

    _invalider()


def sett_portefolje(tickere):
    """Erstatt porteføljelisten. Filtrerer bort tickere som ikke finnes."""
    gyldige = {x["ticker"] for x in alle_instrumenter()}
    rensa = [t for t in tickere if t in gyldige]
    _skriv_json_atomisk(BRUKER_PORTEFOLJE_FIL, rensa)
    _invalider()
    return rensa


# ─── Validering ─────────────────────────────────────────────────────────────

def valider_ticker(ticker):
    """Sjekk om en ticker eksisterer på Yahoo Finance.

    Returnerer dict med forslag (navn, valuta, sektor, type-hint), eller None
    hvis tickeren ikke gir gyldig data. Brukes til auto-fyll i UI før lagring.
    """
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
        navn = info.get("longName") or info.get("shortName")
        if not navn:
            # Mange norske 0P-fond mangler `info`. Sjekk om vi i det minste får
            # historikk — da regner vi tickeren som gyldig.
            hist = t.history(period="5d")
            if hist.empty:
                return None
        qtype = (info.get("quoteType") or "").upper()
        type_hint = "fond" if qtype in ("ETF", "MUTUALFUND") else "aksje"
        return {
            "ticker":    ticker,
            "navn":      navn or ticker,
            "valuta":    info.get("currency", ""),
            "sektor":    info.get("sector") or info.get("category") or "–",
            "type_hint": type_hint,
        }
    except Exception:
        return None
