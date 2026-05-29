"""HTTP-endepunkter for analyseappen."""

import math
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import yfinance as yf
from flask import Blueprint, current_app, jsonify, render_template, request

from .beholdning import les_beholdning, skriv_beholdning
from .cache import hent_historikk
from .chat import chat_konfigurert, chat_svar
from .config import DEFAULT_BENCH, PERIODER, RISIKOFRI_RENTE, SKJERMINGSRENTE_DEFAULT
from .info import hent_info
from .instrumenter import (
    aksjer,
    alle_instrumenter,
    er_brukerlagt,
    fjern,
    fond,
    legg_til,
    portefolje_tickere,
    sett_portefolje,
    valider_ticker,
)
from .kalkulator import glidebane_vekter, monte_carlo
from .marked import hent_markedstemperatur
from .nyheter import hent_nyheter_for, hete_siste_uke, retning
from .rapport import lag_rapport
from .risiko import beregn_risiko, portefolje_aksje_stats
from .skatt import beregn_skatt, beregn_skatt_ask


bp = Blueprint("api", __name__)


# ─── Forside ────────────────────────────────────────────────────────────────

@bp.route("/")
def index():
    return render_template("index.html", aksjer=aksjer(), fond=fond(), alle=alle_instrumenter())


# ─── Instrument-info ────────────────────────────────────────────────────────

@bp.route("/api/oversikt")
def api_oversikt():
    """Hent hurtiginfo for alle instrumenter — parallelt."""
    tickers = [item["ticker"] for item in alle_instrumenter()]
    if not tickers:
        return jsonify([])
    with ThreadPoolExecutor(max_workers=8) as ex:
        data = list(ex.map(hent_info, tickers))
    return jsonify(data)


@bp.route("/api/detalj/<ticker>")
def api_detalj(ticker):
    return jsonify(hent_info(ticker))


@bp.route("/api/historikk/<ticker>/<periode>")
def api_historikk(ticker, periode):
    yf_periode = PERIODER.get(periode, "1y")
    hist = hent_historikk(ticker, yf_periode)
    if hist is None:
        return jsonify({"feil": "Ingen data"})
    return jsonify({
        "ticker":  ticker,
        "periode": periode,
        "datoer":  [str(d.date()) for d in hist.index],
        "priser":  [round(float(p), 4) for p in hist["Close"]],
        "volum":   [int(v) for v in hist["Volume"]],
    })


@bp.route("/api/sammenlign/<tickers>/<periode>")
def api_sammenlign(tickers, periode):
    """Normalisert sammenligning av flere ticker."""
    yf_periode = PERIODER.get(periode, "1y")
    ticker_liste = [t.strip() for t in tickers.split(",")[:6]]

    def hent_en(tk):
        hist = hent_historikk(tk, yf_periode)
        if hist is None:
            return tk, None
        datoer = [str(d.date()) for d in hist.index]
        priser = [round(float(p), 4) for p in hist["Close"]]
        base = priser[0] if priser else None
        norm = [round(p / base * 100, 2) for p in priser] if base else []
        meta = next((x for x in alle_instrumenter() if x["ticker"] == tk), {})
        return tk, {
            "navn":   meta.get("navn", tk),
            "datoer": datoer,
            "norm":   norm,
            "priser": priser,
        }

    with ThreadPoolExecutor(max_workers=6) as ex:
        result = {tk: data for tk, data in ex.map(hent_en, ticker_liste) if data}
    return jsonify(result)


# ─── Investerings-prognose (per ticker) ──────────────────────────────────────

@bp.route("/api/prognose/<ticker>/<belop>", defaults={"manedlig": 0})
@bp.route("/api/prognose/<ticker>/<belop>/<manedlig>")
def api_prognose(ticker, belop, manedlig):
    """Estimer fremtidig verdi basert på historisk CAGR og volatilitet."""
    try:
        belop = float(belop)
        manedlig = float(manedlig)
        if belop < 0 or manedlig < 0:
            return jsonify({"feil": "Beløp kan ikke være negative"})
        if belop == 0 and manedlig == 0:
            return jsonify({"feil": "Oppgi engangssum og/eller månedlig innskudd"})

        hist = hent_historikk(ticker, "max")
        if hist is None or len(hist) < 60:
            return jsonify({"feil": "For lite historikk for å lage prognose"})

        priser = hist["Close"].dropna()
        priser = priser.tail(min(len(priser), 252 * 10))

        start_pris = float(priser.iloc[0])
        slutt_pris = float(priser.iloc[-1])
        dager = (priser.index[-1] - priser.index[0]).days
        ar_hist = dager / 365.25
        if ar_hist < 1 or start_pris <= 0:
            return jsonify({"feil": "For kort historisk periode (minst 1 år kreves)"})

        cagr = (slutt_pris / start_pris) ** (1 / ar_hist) - 1
        log_ret = np.log(priser / priser.shift(1)).dropna()
        annual_vol = float(log_ret.std()) * math.sqrt(252)

        mu_m = math.log(1 + cagr) / 12
        sigma_m = annual_vol / math.sqrt(12)

        # Seed: default 42 (deterministisk), ?seed=random for tilfeldig.
        n_sim = 3000
        n_months = 120
        seed_param = request.args.get("seed", "42")
        if seed_param == "random":
            rng = np.random.default_rng()
        else:
            try:
                rng = np.random.default_rng(seed=int(seed_param))
            except (TypeError, ValueError):
                rng = np.random.default_rng(seed=42)
        gross = np.exp(rng.normal(mu_m, sigma_m, size=(n_sim, n_months)))

        verdier = np.full(n_sim, belop, dtype=np.float64)
        target_months = {1: 12, 3: 36, 5: 60, 10: 120}
        snapshots = {}
        for m in range(n_months):
            verdier = verdier * gross[:, m] + manedlig
            if (m + 1) in target_months.values():
                ar = next(a for a, mm in target_months.items() if mm == m + 1)
                snapshots[ar] = verdier.copy()

        prognoser = []
        for ar in [1, 3, 5, 10]:
            v = snapshots[ar]
            p5  = float(np.percentile(v, 5))
            p50 = float(np.percentile(v, 50))
            p95 = float(np.percentile(v, 95))
            innskudd_totalt = belop + manedlig * 12 * ar
            prognoser.append({
                "ar":                    ar,
                "pessimistisk":          round(p5, 2),
                "forventet":             round(p50, 2),
                "optimistisk":           round(p95, 2),
                "innskudd":              round(innskudd_totalt, 2),
                "gevinst_forventet_pct": round((p50 / innskudd_totalt - 1) * 100, 1) if innskudd_totalt > 0 else 0,
            })

        info = yf.Ticker(ticker).info or {}
        meta = next((x for x in alle_instrumenter() if x["ticker"] == ticker), {})

        return jsonify({
            "ticker":          ticker,
            "navn":            meta.get("navn", info.get("longName", ticker)),
            "flagg":           meta.get("flagg", ""),
            "valuta":          info.get("currency", ""),
            "belop":           belop,
            "manedlig":        manedlig,
            "cagr_pct":        round(cagr * 100, 2),
            "volatilitet_pct": round(annual_vol * 100, 2),
            "historikk_ar":    round(ar_hist, 1),
            "prognoser":       prognoser,
        })
    except Exception as e:
        return jsonify({"feil": str(e)})


# ─── Nyheter & sentiment ────────────────────────────────────────────────────

@bp.route("/api/nyheter")
def api_nyheter():
    """Aggregert nyhets-sentiment for alle instrumenter + topp 3 mest 'hete'."""
    instrumenter = []
    for item in alle_instrumenter():
        saker = hent_nyheter_for(item)
        if saker:
            snitt = sum(s["score"] for s in saker) / len(saker)
            pos = sum(1 for s in saker if s["etikett"] == "positiv")
            neg = sum(1 for s in saker if s["etikett"] == "negativ")
            nøy = sum(1 for s in saker if s["etikett"] == "nøytral")
        else:
            snitt, pos, neg, nøy = 0.0, 0, 0, 0
        ret = retning(snitt) if saker else {"retning": "ukjent", "tekst": "Ingen data", "farge": "neu"}
        ferske = hete_siste_uke(saker, logger=current_app.logger)

        instrumenter.append({
            "ticker":      item["ticker"],
            "navn":        item["navn"],
            "flagg":       item.get("flagg", ""),
            "type":        item["type"],
            "antall":      len(saker),
            "ferske":      ferske,
            "snitt_score": round(snitt, 3),
            "positive":    pos,
            "negative":    neg,
            "nøytrale":    nøy,
            "prognose":    ret,
            "saker":       saker,
        })

    # Topp 3 "hete": flest ferske saker, bryt med |snitt|·antall.
    rangert = sorted(
        [d for d in instrumenter if d["ferske"] > 0],
        key=lambda d: (d["ferske"], abs(d["snitt_score"]) * d["antall"]),
        reverse=True,
    )
    hete = []
    for d in rangert[:3]:
        topp_sak = max(d["saker"], key=lambda s: abs(s["score"]), default=None)
        hete.append({
            "ticker":      d["ticker"],
            "navn":        d["navn"],
            "flagg":       d["flagg"],
            "type":        d["type"],
            "ferske":      d["ferske"],
            "snitt_score": d["snitt_score"],
            "prognose":    d["prognose"],
            "topp_sak":    topp_sak,
        })

    return jsonify({"instrumenter": instrumenter, "hete": hete})


# ─── Beholdning ─────────────────────────────────────────────────────────────

@bp.route("/api/beholdning", methods=["GET"])
def api_beholdning_get():
    return jsonify(les_beholdning())


@bp.route("/api/beholdning", methods=["POST"])
def api_beholdning_post():
    """Lagre hele beholdning-strukturen. Body: {ticker: {andeler, snittpris}}."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"feil": "Forventet JSON-objekt"}), 400
    portefolje = set(portefolje_tickere())
    rensa = {}
    for ticker, b in data.items():
        if ticker not in portefolje or not isinstance(b, dict):
            continue
        try:
            andeler = float(b.get("andeler", 0) or 0)
            snittpris = float(b.get("snittpris", 0) or 0)
        except (TypeError, ValueError):
            continue
        if andeler < 0 or snittpris < 0:
            continue
        rensa[ticker] = {"andeler": andeler, "snittpris": snittpris}
    try:
        skriv_beholdning(rensa)
    except Exception as e:
        return jsonify({"feil": f"Kunne ikke lagre: {e}"}), 500
    return jsonify({"ok": True, "beholdning": rensa})


# ─── Min portefølje ─────────────────────────────────────────────────────────

@bp.route("/api/portefolje")
def api_portefolje():
    """Min portefølje: info + 1Y historikk + topp nyheter for hver beholdning."""
    resultat = []
    for ticker_str in portefolje_tickere():
        item = next((x for x in alle_instrumenter() if x["ticker"] == ticker_str), None)
        if item is None:
            continue
        info = hent_info(ticker_str)

        hist = hent_historikk(ticker_str, "1y")
        if hist is not None:
            datoer = [str(d.date()) for d in hist.index]
            priser = [round(float(p), 4) for p in hist["Close"]]
            start = priser[0] if priser else None
            avk_1y = round((priser[-1] / start - 1) * 100, 2) if start else None
        else:
            datoer, priser, avk_1y = [], [], None

        saker = hent_nyheter_for(item, maks=6)
        topp_saker = sorted(saker, key=lambda s: s["dato"], reverse=True)[:3]
        snitt = round(sum(s["score"] for s in saker) / len(saker), 3) if saker else 0.0
        prognose = retning(snitt) if saker else {"retning": "ukjent", "tekst": "Ingen data", "farge": "neu"}

        resultat.append({
            "ticker":      info["ticker"],
            "navn":        info["navn"],
            "flagg":       info.get("flagg", ""),
            "sektor":      info.get("sektor", ""),
            "valuta":      info.get("valuta", ""),
            "pris":        info.get("pris"),
            "pris_fmt":    info.get("pris_fmt"),
            "endring_pct": info.get("endring_pct"),
            "avk_1y_pct":  avk_1y,
            "datoer":      datoer,
            "priser":      priser,
            "saker":       topp_saker,
            "snitt_score": snitt,
            "prognose":    prognose,
        })
    return jsonify(resultat)


# ─── Risiko ─────────────────────────────────────────────────────────────────

@bp.route("/api/risiko/<ticker>/<periode>")
def api_risiko(ticker, periode):
    """Sharpe, drawdown, vol, MA-signal og bench-relativ avkastning."""
    yf_periode = PERIODER.get(periode, "1y")
    hist = hent_historikk(ticker, yf_periode)
    if hist is None or len(hist) < 5:
        return jsonify({"feil": "For lite data"})

    risiko = beregn_risiko(hist["Close"])
    if risiko is None:
        return jsonify({"feil": "For lite data"})

    bench = request.args.get("bench", DEFAULT_BENCH)
    bench_data = None
    if bench and bench != ticker:
        bench_hist = hent_historikk(bench, yf_periode)
        if bench_hist is not None:
            df = pd.DataFrame({"a": hist["Close"], "b": bench_hist["Close"]}).dropna()
            if len(df) >= 5:
                a_norm = df["a"] / df["a"].iloc[0] * 100
                b_norm = df["b"] / df["b"].iloc[0] * 100
                bench_meta = next((x for x in alle_instrumenter() if x["ticker"] == bench), {})
                bench_data = {
                    "ticker":     bench,
                    "navn":       bench_meta.get("navn", bench),
                    "datoer":     [str(d.date()) for d in df.index],
                    "instrument": [round(float(x), 2) for x in a_norm],
                    "bench":      [round(float(x), 2) for x in b_norm],
                    "diff_pct":   round(float(a_norm.iloc[-1] - b_norm.iloc[-1]), 2),
                }

    info = hent_info(ticker)
    return jsonify({
        "ticker":              ticker,
        "navn":                info.get("navn", ticker),
        "flagg":               info.get("flagg", ""),
        "valuta":              info.get("valuta", ""),
        "periode":             periode,
        "ma_signal":           info.get("ma_signal"),
        "snitt_50d":           info.get("snitt_50d"),
        "snitt_200d":          info.get("snitt_200d"),
        "risikofri_rente_pct": round(RISIKOFRI_RENTE * 100, 1),
        "risiko":              risiko,
        "bench":               bench_data,
    })


@bp.route("/api/portefolje-stats")
def api_portefolje_stats():
    """Vol og historisk CAGR for porteføljen (lik vekt) — default for kalkulatoren."""
    stats = portefolje_aksje_stats()
    if stats is None:
        return jsonify({"feil": "Mangler data"})
    return jsonify({
        "aksje_vol":       round(stats["vol"], 4),
        "aksje_hist_cagr": round(stats["hist_cagr"], 4),
        "dager":           stats["dager"],
    })


# ─── Kalkulator (Monte Carlo med glidebane) ─────────────────────────────────

@bp.route("/api/kalkulator", methods=["POST"])
def api_kalkulator():
    """Monte Carlo for porteføljebygging mot mål, med konfigurerbar glidebane."""
    d = request.get_json(silent=True) or {}

    try:
        start = max(0.0, float(d.get("start", 0)))
        manedlig = max(0.0, float(d.get("manedlig", 0)))
        ar = max(1, min(40, int(d.get("ar", 7))))
        mal = max(1.0, float(d.get("mal", 1_000_000)))
    except (TypeError, ValueError):
        return jsonify({"feil": "Ugyldige tall i input"}), 400
    if start == 0 and manedlig == 0:
        return jsonify({"feil": "Trenger startkapital og/eller månedlig sparing"}), 400

    stats = portefolje_aksje_stats()
    default_vol = stats["vol"] if stats else 0.127

    aksje_cagr = float(d.get("aksje_cagr", 0.08))
    aksje_vol  = float(d.get("aksje_vol", default_vol))
    rente_cagr = float(d.get("rente_cagr", 0.04))
    rente_vol  = float(d.get("rente_vol", 0.005))
    start_aksje = max(0.0, min(1.0, float(d.get("start_aksje", 1.0))))
    slutt_aksje = max(0.0, min(1.0, float(d.get("slutt_aksje", 0.2))))
    hold_aar = float(d.get("hold_aar", max(0, ar - 2)))
    sjokk = bool(d.get("sjokk", False))

    n_mnd = ar * 12
    vekter = glidebane_vekter(n_mnd, start_aksje, slutt_aksje, hold_aar)

    verdier, median_bane = monte_carlo(
        start, manedlig, n_mnd, vekter,
        aksje_cagr, aksje_vol, rente_cagr, rente_vol,
        sjokk=sjokk,
    )

    p5, p25, p50, p75, p95 = (float(x) for x in np.percentile(verdier, [5, 25, 50, 75, 95]))
    innskudd = start + manedlig * n_mnd

    counts, edges = np.histogram(verdier, bins=40)
    histogram = {
        "kanter": [float(e) for e in edges],
        "antall": [int(c) for c in counts],
    }

    return jsonify({
        "input": {
            "start": start, "manedlig": manedlig, "ar": ar, "mal": mal,
            "aksje_cagr": aksje_cagr, "aksje_vol": aksje_vol,
            "rente_cagr": rente_cagr, "rente_vol": rente_vol,
            "start_aksje": start_aksje, "slutt_aksje": slutt_aksje, "hold_aar": hold_aar,
            "sjokk": sjokk,
        },
        "innskudd": innskudd,
        "stats": {
            "pessimistisk":         round(p5, 0),
            "p25":                  round(p25, 0),
            "median":               round(p50, 0),
            "p75":                  round(p75, 0),
            "optimistisk":          round(p95, 0),
            "p_mal":                round(float(np.mean(verdier >= mal)) * 100, 1),
            "p_80pct":              round(float(np.mean(verdier >= mal * 0.8)) * 100, 1),
            "p_50pct":              round(float(np.mean(verdier >= mal * 0.5)) * 100, 1),
            "snitt":                round(float(np.mean(verdier)), 0),
            "tap_vs_innskudd_pct":  round((p5 / innskudd - 1) * 100, 1) if innskudd > 0 else 0,
        },
        "vekter":      [round(float(v), 3) for v in vekter],
        "median_bane": [round(float(v), 0) for v in median_bane],
        "histogram":   histogram,
    })


# ─── AI-assistent (Claude) ──────────────────────────────────────────────────

@bp.route("/api/chat/status")
def api_chat_status():
    """Om AI-boblen er aktiv (dvs. om en API-nøkkel er konfigurert)."""
    return jsonify({"konfigurert": chat_konfigurert()})


@bp.route("/api/chat", methods=["POST"])
def api_chat():
    """Send samtalehistorikk til Claude. Body: {meldinger: [{role, content}]}."""
    data = request.get_json(silent=True) or {}
    meldinger = data.get("meldinger")
    if not isinstance(meldinger, list) or not meldinger:
        return jsonify({"feil": "Forventet en ikke-tom liste 'meldinger'"}), 400
    svar = chat_svar(meldinger)
    return jsonify(svar), (200 if "svar" in svar else 503 if svar.get("konfigurert") is False else 200)


# ─── Månedsrapport ──────────────────────────────────────────────────────────

@bp.route("/api/rapport")
def api_rapport():
    """Månedsrapport: forrige kalendermåned + 7-dagers utvikling for porteføljen."""
    return jsonify(lag_rapport())


# ─── Skattekalkulator (aksjonærmodellen) ────────────────────────────────────

@bp.route("/api/skatt", methods=["POST"])
def api_skatt():
    """Beregn skatt på realisert aksjegevinst med skjermingsfradrag.

    Body: {inngangsverdi, salgssum, ar?, skjermingsrente?, skjerming_override?}
    """
    d = request.get_json(silent=True) or {}
    try:
        inngangsverdi = float(d.get("inngangsverdi", 0))
        salgssum = float(d.get("salgssum", 0))
        ar = max(0, int(d.get("ar", 0)))
        skjermingsrente = float(d.get("skjermingsrente", SKJERMINGSRENTE_DEFAULT))
        override = d.get("skjerming_override")
        skjerming_override = float(override) if override not in (None, "") else None
    except (TypeError, ValueError):
        return jsonify({"feil": "Ugyldige tall i input"}), 400

    if inngangsverdi < 0 or salgssum < 0:
        return jsonify({"feil": "Beløp kan ikke være negative"}), 400
    if inngangsverdi == 0 and salgssum == 0:
        return jsonify({"feil": "Oppgi inngangsverdi og salgssum"}), 400

    return jsonify(beregn_skatt(
        inngangsverdi, salgssum, ar=ar,
        skjermingsrente=skjermingsrente,
        skjerming_override=skjerming_override,
    ))


@bp.route("/api/skatt-ask", methods=["POST"])
def api_skatt_ask():
    """Beregn skatt ved uttak fra aksjesparekonto (ASK).

    Body: {innskudd, verdi, uttak?, ar?, skjermingsrente?, skjerming_override?}
    """
    d = request.get_json(silent=True) or {}
    try:
        innskudd = float(d.get("innskudd", 0))
        verdi = float(d.get("verdi", 0))
        uttak_raw = d.get("uttak")
        uttak = float(uttak_raw) if uttak_raw not in (None, "") else None
        ar = max(0, int(d.get("ar", 0)))
        skjermingsrente = float(d.get("skjermingsrente", SKJERMINGSRENTE_DEFAULT))
        override = d.get("skjerming_override")
        skjerming_override = float(override) if override not in (None, "") else None
    except (TypeError, ValueError):
        return jsonify({"feil": "Ugyldige tall i input"}), 400

    if innskudd < 0 or verdi < 0 or (uttak is not None and uttak < 0):
        return jsonify({"feil": "Beløp kan ikke være negative"}), 400
    if innskudd == 0 and verdi == 0:
        return jsonify({"feil": "Oppgi innskudd og verdi på kontoen"}), 400

    return jsonify(beregn_skatt_ask(
        innskudd, verdi, uttak=uttak, ar=ar,
        skjermingsrente=skjermingsrente,
        skjerming_override=skjerming_override,
    ))


# ─── Korrelasjon ────────────────────────────────────────────────────────────

@bp.route("/api/korrelasjon")
def api_korrelasjon():
    """Korrelasjonsmatrise på daglige log-avkastninger for et sett tickere.

    Default = brukerens portefølje. Overstyr med ?tickere=A,B,C og ?periode=1Y.
    """
    tickere_param = request.args.get("tickere", ",".join(portefolje_tickere()))
    tickere = [t.strip() for t in tickere_param.split(",") if t.strip()][:10]
    periode = request.args.get("periode", "1Y")
    yf_periode = PERIODER.get(periode, "1y")

    with ThreadPoolExecutor(max_workers=6) as ex:
        hists = list(ex.map(lambda t: hent_historikk(t, yf_periode), tickere))
    series = {tk: h["Close"] for tk, h in zip(tickere, hists) if h is not None}
    if len(series) < 2:
        return jsonify({"feil": "Trenger minst 2 instrumenter med data"})

    df = pd.DataFrame(series).dropna()
    if len(df) < 10:
        return jsonify({"feil": "For lite overlappende data"})

    log_ret = np.log(df / df.shift(1)).dropna()
    corr = log_ret.corr()
    ordnet = list(series.keys())
    katalog = alle_instrumenter()
    navn = [next((x["navn"] for x in katalog if x["ticker"] == tk), tk) for tk in ordnet]

    return jsonify({
        "periode":      periode,
        "tickere":      ordnet,
        "navn":         navn,
        "matrise":      [[round(float(corr.loc[a, b]), 3) for b in ordnet] for a in ordnet],
        "antall_dager": int(len(log_ret)),
    })


# ─── Markedstermometer ──────────────────────────────────────────────────────

@bp.route("/api/marked")
def api_marked():
    return jsonify(hent_markedstemperatur())


# ─── Bruker-administrerte instrumenter ──────────────────────────────────────

@bp.route("/api/instrumenter", methods=["GET"])
def api_instrumenter_get():
    """List alle instrumenter med markering av standard vs. bruker-lagt."""
    portefolje = set(portefolje_tickere())
    data = []
    for inst in alle_instrumenter():
        data.append({
            **inst,
            "brukerlagt":    er_brukerlagt(inst["ticker"]),
            "i_portefolje":  inst["ticker"] in portefolje,
        })
    return jsonify(data)


@bp.route("/api/instrumenter/sjekk/<ticker>", methods=["GET"])
def api_instrumenter_sjekk(ticker):
    """Slå opp ticker på Yahoo Finance for auto-fyll. Returner 404 hvis ugyldig."""
    forslag = valider_ticker(ticker.strip())
    if forslag is None:
        return jsonify({"feil": f"Fant ikke '{ticker}' på Yahoo Finance"}), 404
    return jsonify(forslag)


@bp.route("/api/instrumenter", methods=["POST"])
def api_instrumenter_post():
    """Legg til nytt bruker-instrument.

    Body: {ticker, navn, type ('aksje'/'fond'), sektor?, flagg?, søkeord?}
    """
    data = request.get_json(silent=True) or {}
    try:
        legg_til(data)
    except ValueError as e:
        return jsonify({"feil": str(e)}), 400
    return jsonify({"ok": True, "ticker": data.get("ticker")}), 201


@bp.route("/api/instrumenter/<ticker>", methods=["DELETE"])
def api_instrumenter_delete(ticker):
    """Fjern et bruker-lagt instrument. Standard-instrumenter kan ikke slettes."""
    try:
        fjern(ticker)
    except ValueError as e:
        return jsonify({"feil": str(e)}), 400
    return jsonify({"ok": True})


@bp.route("/api/portefolje-tickere", methods=["GET"])
def api_portefolje_tickere_get():
    return jsonify(portefolje_tickere())


@bp.route("/api/portefolje-tickere", methods=["POST"])
def api_portefolje_tickere_post():
    """Erstatt porteføljelisten. Body: liste av tickere."""
    data = request.get_json(silent=True)
    if not isinstance(data, list):
        return jsonify({"feil": "Forventet liste av tickere"}), 400
    rensa = sett_portefolje(data)
    return jsonify({"ok": True, "portefolje": rensa})
