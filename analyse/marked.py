"""Markedstermometer: indekser, VIX, valuta og råvarer."""

from concurrent.futures import ThreadPoolExecutor

from .cache import hent_historikk
from .config import MARKED_TICKERS


def _hent_en(item):
    """Hent siste verdi + 1d/1u-endring for én markedsticker."""
    hist = hent_historikk(item["ticker"], "1mo")
    if hist is None or len(hist) < 2:
        return None
    priser = hist["Close"].dropna()
    if len(priser) < 2:
        return None
    naa = float(priser.iloc[-1])
    forrige = float(priser.iloc[-2])
    en_uke = float(priser.iloc[max(0, len(priser) - 6)])
    return {
        "ticker":     item["ticker"],
        "navn":       item["navn"],
        "kategori":   item["kategori"],
        "verdi":      round(naa, 2),
        "endring_1d": round((naa / forrige - 1) * 100, 2),
        "endring_1u": round((naa / en_uke - 1) * 100, 2),
    }


def hent_markedstemperatur():
    """Hent alle markedstickere parallelt og beregn samlet stemning fra VIX."""
    with ThreadPoolExecutor(max_workers=6) as ex:
        data = [d for d in ex.map(_hent_en, MARKED_TICKERS) if d]

    vix = next((d for d in data if d["ticker"] == "^VIX"), None)
    if vix:
        v = vix["verdi"]
        if v < 15:
            stemning = {"nivå": v, "tekst": "Rolig",  "farge": "pos"}
        elif v < 25:
            stemning = {"nivå": v, "tekst": "Normal", "farge": "neu"}
        else:
            stemning = {"nivå": v, "tekst": "Uro",    "farge": "neg"}
    else:
        stemning = {"nivå": None, "tekst": "Ukjent", "farge": "neu"}

    return {"instrumenter": data, "stemning": stemning}
