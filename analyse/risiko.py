"""Risikomål: Sharpe, drawdown, volatilitet og porteføljens historiske stats.

Alle målene beskriver vinduet de er regnet på, ikke instrumentet generelt. Et
fond med fire års historikk fra 2022 har ikke opplevd et eneste ordentlig
bjørnemarked, og volatiliteten blir tilsvarende lav. Derfor returnerer
funksjonene her alltid `periode`-metadata, slik at UI-et kan vise hvor tynt
grunnlaget er i stedet for å presentere tallene som absolutte.
"""

import math

import numpy as np
import pandas as pd

from .cache import hent_historikk
from .config import DATAVINDU_KORT_AR, DATAVINDU_SVAERT_KORT_AR, RISIKOFRI_RENTE
from .instrumenter import portefolje_tickere


def vurder_datavindu(ar, handelsdager, fra=None, til=None):
    """Beskriv hvor mye historikk et tall bygger på, og hvor mye det betyr.

    `niva` er "ok", "kort" eller "svært kort" — UI-et bruker det til å velge
    hvor kraftig advarselen skal være.
    """
    if ar is None:
        return None
    if ar < DATAVINDU_SVAERT_KORT_AR:
        niva = "svært kort"
        merknad = (f"Bare {ar:.1f} års historikk — for lite til å si noe om risiko. "
                   "Tallene beskriver en enkelt markedsfase.")
    elif ar < DATAVINDU_KORT_AR:
        niva = "kort"
        merknad = (f"{ar:.1f} års historikk dekker ikke en full markedssyklus. "
                   "Verken finanskrisen (2008) eller koronafallet (2020) er med, "
                   "så volatilitet og drawdown er trolig undervurdert.")
    else:
        niva = "ok"
        merknad = f"{ar:.1f} års historikk — dekker minst én full markedssyklus."
    return {
        "fra":           fra,
        "til":           til,
        "handelsdager":  handelsdager,
        "ar":            round(ar, 1),
        "niva":          niva,
        "merknad":       merknad,
    }


def beregn_risiko(priser):
    """Beregn risikomål for en prisserie (pandas Series).

    Returnerer dict med vol, CAGR, Sharpe, max drawdown og drawdown-tidsserie.
    Returnerer None hvis det er for lite data.
    """
    priser = priser.dropna()
    if len(priser) < 5:
        return None

    log_ret = np.log(priser / priser.shift(1)).dropna()
    annual_vol = float(log_ret.std() * math.sqrt(252))

    total_avk = float(priser.iloc[-1] / priser.iloc[0] - 1)
    dager = max((priser.index[-1] - priser.index[0]).days, 1)
    ar = dager / 365.25
    cagr = (priser.iloc[-1] / priser.iloc[0]) ** (1 / ar) - 1 if ar > 0 and priser.iloc[0] > 0 else 0.0
    cagr = float(cagr)

    sharpe = (cagr - RISIKOFRI_RENTE) / annual_vol if annual_vol > 0 else None

    kum_max = priser.cummax()
    drawdown = priser / kum_max - 1
    max_dd = float(drawdown.min())

    # Tid i drawdown: hvor lenge under forrige topp (i kalenderdager).
    under_topp = priser < kum_max
    tid_i_dd_dager = int(under_topp.sum())

    return {
        "vol_pct":          round(annual_vol * 100, 2),
        "cagr_pct":         round(cagr * 100, 2),
        "total_avk_pct":    round(total_avk * 100, 2),
        "sharpe":           round(sharpe, 2) if sharpe is not None else None,
        "max_drawdown_pct": round(max_dd * 100, 2),
        "tid_i_dd_dager":   tid_i_dd_dager,
        "drawdown_serie":   [round(float(x) * 100, 2) for x in drawdown],
        "drawdown_datoer":  [str(d.date()) for d in drawdown.index],
        "periode":          vurder_datavindu(
            ar, len(priser),
            fra=str(priser.index[0].date()),
            til=str(priser.index[-1].date()),
        ),
    }


def portefolje_aksje_stats():
    """Historisk vol og CAGR for brukerens portefølje (lik vekt på tvers av fond).

    Brukes som default-volatilitet i kalkulatoren. Returnerer None hvis data
    mangler eller overlapp er for kort.
    """
    tickere = portefolje_tickere()
    if not tickere:
        return None
    hist = {}
    for tk in tickere:
        h = hent_historikk(tk, "max")
        if h is not None:
            hist[tk] = h["Close"]
    if not hist:
        return None
    df = pd.DataFrame(hist).dropna()
    if len(df) < 60:
        return None
    log_ret = np.log(df / df.shift(1)).dropna()
    n = len(hist)
    port_daglig = (log_ret * (1 / n)).sum(axis=1)
    ann_vol = float(port_daglig.std() * math.sqrt(252))
    hist_cagr = float(math.exp(port_daglig.mean() * 252) - 1)

    # Overlappet begrenses av det korteste fondet — det er dette vinduet
    # kalkulatorens default-volatilitet faktisk stammer fra.
    ar = max((df.index[-1] - df.index[0]).days, 1) / 365.25
    return {
        "vol":        ann_vol,
        "hist_cagr":  hist_cagr,
        "dager":      int(len(df)),
        "periode":    vurder_datavindu(ar, int(len(df)),
                                       fra=str(df.index[0].date()),
                                       til=str(df.index[-1].date())),
    }
