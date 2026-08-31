"""Månedsrapport for porteføljen: forrige kalendermåned + siste 30 dager.

Avkastning regnes i hvert instruments egen valuta som *totalavkastning*:
yfinance leverer utbyttejusterte sluttkurser (`auto_adjust=True` er default
fra og med yfinance 0.2.51), så reinvestert utbytte og splitter er med i
tallene. Har brukeren registrert beholdning (andeler), vektes totalen etter
markedsverdi og kronebeløp vises; ellers brukes lik vekt og indeks (base 100).
Kryss-valuta-summer er en tilnærming og flagges med `flervaluta`.
"""

import datetime as dt
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from .beholdning import les_beholdning
from .cache import hent_historikk
from .info import hent_info
from .instrumenter import alle_instrumenter, portefolje_tickere


MND_NAVN = ["januar", "februar", "mars", "april", "mai", "juni", "juli",
            "august", "september", "oktober", "november", "desember"]


def _forrige_maned(idag):
    """Returner (første_dag, siste_dag, navn) for forrige kalendermåned."""
    forste_denne = idag.replace(day=1)
    siste_forrige = forste_denne - dt.timedelta(days=1)
    forste_forrige = siste_forrige.replace(day=1)
    navn = f"{MND_NAVN[siste_forrige.month - 1]} {siste_forrige.year}"
    return forste_forrige, siste_forrige, navn


def _kurs_paa_eller_for(close, dato):
    """Siste kurs på eller før `dato` (pandas Timestamp-sammenligning)."""
    grense = pd.Timestamp(dato)
    if close.index.tz is not None:
        grense = grense.tz_localize(close.index.tz)
    tidligere = close[close.index <= grense]
    if tidligere.empty:
        return None
    return float(tidligere.iloc[-1])


def lag_rapport(idag=None):
    """Bygg månedsrapport-data for hele porteføljen."""
    idag = idag or dt.date.today()
    forste, siste, mnd_navn = _forrige_maned(idag)
    # Baseline = slutten av måneden FØR forrige måned (siste handledag).
    baseline_dato = forste - dt.timedelta(days=1)

    tickere = portefolje_tickere()
    if not tickere:
        return {"tom": True, "maned_navn": mnd_navn}

    beholdning = les_beholdning()
    katalog = alle_instrumenter()

    def hent_en(tk):
        return tk, hent_info(tk), hent_historikk(tk, "6mo")

    with ThreadPoolExecutor(max_workers=8) as ex:
        rader_raw = list(ex.map(hent_en, tickere))

    instrumenter = []
    serier = {}        # ticker -> close-serie (siste ~7 dager filtreres senere)
    valutaer = set()

    for tk, info, hist in rader_raw:
        meta = next((x for x in katalog if x["ticker"] == tk), {})
        navn = info.get("navn") or meta.get("navn", tk)
        flagg = info.get("flagg") or meta.get("flagg", "")
        valuta = info.get("valuta", "")
        andeler = float(beholdning.get(tk, {}).get("andeler", 0) or 0)

        if hist is None or hist.empty:
            instrumenter.append({
                "ticker": tk, "navn": navn, "flagg": flagg, "valuta": valuta,
                "andeler": andeler, "avkastning_pct": None, "mangler_data": True,
            })
            continue

        close = hist["Close"].dropna()
        serier[tk] = close
        pris_naa = float(close.iloc[-1])
        start = _kurs_paa_eller_for(close, baseline_dato)
        slutt = _kurs_paa_eller_for(close, siste)

        avk_pct = endring_kr = verdi_kr = None
        if start and slutt and start > 0:
            avk_pct = round((slutt / start - 1) * 100, 2)
        if andeler > 0:
            verdi_kr = round(andeler * pris_naa, 2)
            if start is not None and slutt is not None:
                endring_kr = round(andeler * (slutt - start), 2)
            valutaer.add(valuta)

        instrumenter.append({
            "ticker": tk, "navn": navn, "flagg": flagg, "valuta": valuta,
            "andeler": andeler, "pris": round(pris_naa, 4),
            "avkastning_pct": avk_pct, "verdi_kr": verdi_kr, "endring_kr": endring_kr,
            "mangler_data": False,
        })

    har_beholdning = any(i["andeler"] > 0 for i in instrumenter)

    # ── Total månedsavkastning (vektet) ──────────────────────────────────────
    vekt_sum = 0.0
    vektet_avk = 0.0
    for i in instrumenter:
        if i["avkastning_pct"] is None:
            continue
        if har_beholdning:
            v = i.get("verdi_kr") or 0.0
        else:
            v = 1.0
        vekt_sum += v
        vektet_avk += v * i["avkastning_pct"]
    total_avk_pct = round(vektet_avk / vekt_sum, 2) if vekt_sum > 0 else None

    # Andel av portefølje (vekt i prosent) for visning.
    for i in instrumenter:
        if har_beholdning:
            i["vekt_pct"] = round((i.get("verdi_kr") or 0) / vekt_sum * 100, 1) if vekt_sum else None
        else:
            gyldige = sum(1 for x in instrumenter if x["avkastning_pct"] is not None)
            i["vekt_pct"] = round(100 / gyldige, 1) if gyldige and i["avkastning_pct"] is not None else None

    total_endring_kr = total_verdi_kr = None
    if har_beholdning:
        total_verdi_kr = round(sum(i.get("verdi_kr") or 0 for i in instrumenter), 2)
        total_endring_kr = round(sum(i.get("endring_kr") or 0 for i in instrumenter), 2)

    # Beste/verste instrument i måneden.
    med_avk = [i for i in instrumenter if i["avkastning_pct"] is not None]
    beste = max(med_avk, key=lambda x: x["avkastning_pct"], default=None)
    verst = min(med_avk, key=lambda x: x["avkastning_pct"], default=None)

    # ── 30-dagers graf ────────────────────────────────────────────────────────
    graf = _bygg_30d_graf(serier, instrumenter, har_beholdning, idag)

    return {
        "tom": False,
        "maned_navn": mnd_navn,
        "generert": idag.isoformat(),
        "har_beholdning": har_beholdning,
        "flervaluta": len(valutaer) > 1,
        "valuta": next(iter(valutaer)) if len(valutaer) == 1 else "",
        "total": {
            "avkastning_pct": total_avk_pct,
            "verdi_kr": total_verdi_kr,
            "endring_kr": total_endring_kr,
        },
        "beste": {"navn": beste["navn"], "flagg": beste["flagg"],
                  "avkastning_pct": beste["avkastning_pct"]} if beste else None,
        "verst": {"navn": verst["navn"], "flagg": verst["flagg"],
                  "avkastning_pct": verst["avkastning_pct"]} if verst else None,
        "instrumenter": sorted(
            instrumenter,
            key=lambda x: (x["avkastning_pct"] is None, -(x["avkastning_pct"] or 0)),
        ),
        "graf_30d": graf,
    }


def _bygg_30d_graf(serier, instrumenter, har_beholdning, idag):
    """Porteføljeverdi/indeks for de siste 30 dagene.

    Med beholdning: sum(andeler · kurs) per dato (kr). Uten: lik-vektet indeks
    normalisert til 100 ved start. Datoer er snittet av alle seriers handledager.
    """
    if not serier:
        return {"datoer": [], "verdi": [], "type": "indeks"}

    df = pd.DataFrame(serier).dropna()
    if df.empty:
        return {"datoer": [], "verdi": [], "type": "indeks"}

    grense = pd.Timestamp(idag - dt.timedelta(days=30))
    if df.index.tz is not None:
        grense = grense.tz_localize(df.index.tz)
    df = df[df.index >= grense]
    if len(df) < 2:
        df = pd.DataFrame(serier).dropna().tail(30)
    if df.empty:
        return {"datoer": [], "verdi": [], "type": "indeks"}

    datoer = [str(d.date()) for d in df.index]

    if har_beholdning:
        andeler_map = {i["ticker"]: i["andeler"] for i in instrumenter}
        vekter = pd.Series({col: andeler_map.get(col, 0.0) for col in df.columns})
        verdi = [round(float(v), 2) for v in df.dot(vekter)]
        return {"datoer": datoer, "verdi": verdi, "type": "kr"}

    # Lik-vektet indeks: snitt av hver kolonnes normaliserte verdi.
    norm = df.divide(df.iloc[0]).multiply(100)
    verdi = [round(float(rad.mean()), 2) for _, rad in norm.iterrows()]
    return {"datoer": datoer, "verdi": verdi, "type": "indeks"}
