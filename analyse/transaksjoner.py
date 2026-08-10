"""Transaksjonslogg: kjøp og salg som kilde til beholdning, kostpris og avkastning.

Uten transaksjoner kan appen bare svare på hva *fondet* har gjort. Med dem kan
den svare på hva *du* har gjort — og de to er sjelden det samme når du sparer
månedlig.

Modellen er FIFO (først inn, først ut), som er det norske skatteregler krever
ved realisasjon av aksjer og aksjefond. Hvert kjøp danner et lot; et salg spiser
lots i rekkefølge og realiserer gevinsten per lot. Det gir riktig kostpris på
det som er igjen, riktig realisert gevinst, og eiertid per lot til
skjermingsfradraget.

Filen `transaksjoner.json` er additiv i forhold til `beholdning.json`: har en
ticker transaksjoner, utledes beholdningen fra dem; ellers brukes de manuelt
registrerte tallene som før.
"""

import datetime as dt
import json
import os
import tempfile
import threading
import uuid

from .config import TRANSAKSJONER_FIL


_LOCK = threading.RLock()

TYPER = ("kjøp", "salg")


# ─── Lagring ────────────────────────────────────────────────────────────────

def les_alle():
    """Returner {ticker: [transaksjoner]}. Tom dict ved manglende/korrupt fil."""
    if not os.path.exists(TRANSAKSJONER_FIL):
        return {}
    try:
        with open(TRANSAKSJONER_FIL, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {tk: v for tk, v in data.items() if isinstance(v, list)}


def _skriv_alle(data):
    """Atomisk skriving: temp-fil → rename."""
    katalog = os.path.dirname(TRANSAKSJONER_FIL)
    fd, tmp = tempfile.mkstemp(dir=katalog, prefix=".transaksjoner_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, TRANSAKSJONER_FIL)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _valider(rad):
    """Normaliser og valider én transaksjon. Kaster ValueError ved feil."""
    ticker = (rad.get("ticker") or "").strip()
    if not ticker:
        raise ValueError("Ticker mangler")

    type_ = (rad.get("type") or "").strip().lower()
    if type_ not in TYPER:
        raise ValueError(f"Type må være 'kjøp' eller 'salg', ikke {type_!r}")

    dato_raw = (rad.get("dato") or "").strip()
    try:
        dato = dt.date.fromisoformat(dato_raw)
    except ValueError:
        raise ValueError(f"Ugyldig dato: {dato_raw!r} (forventet ÅÅÅÅ-MM-DD)")
    if dato > dt.date.today():
        raise ValueError("Dato kan ikke være i framtiden")

    try:
        antall = float(rad.get("antall"))
        kurs = float(rad.get("kurs"))
        gebyr = float(rad.get("gebyr") or 0)
    except (TypeError, ValueError):
        raise ValueError("Antall, kurs og gebyr må være tall")

    if antall <= 0:
        raise ValueError("Antall må være større enn 0")
    if kurs < 0:
        raise ValueError("Kurs kan ikke være negativ")
    if gebyr < 0:
        raise ValueError("Gebyr kan ikke være negativt")

    return {
        "id":      rad.get("id") or uuid.uuid4().hex[:12],
        "ticker":  ticker,
        "type":    type_,
        "dato":    dato.isoformat(),
        "antall":  antall,
        "kurs":    kurs,
        "gebyr":   gebyr,
        "notat":   (rad.get("notat") or "").strip()[:200],
    }


def legg_til(rad):
    """Legg til én transaksjon. Returnerer den lagrede raden."""
    post = _valider(rad)
    with _LOCK:
        alle = les_alle()
        liste = alle.setdefault(post["ticker"], [])
        liste.append(post)
        liste.sort(key=lambda t: (t["dato"], t["id"]))
        _skriv_alle(alle)
    return post


def fjern(ticker, trans_id):
    """Slett én transaksjon. Kaster ValueError hvis den ikke finnes."""
    with _LOCK:
        alle = les_alle()
        liste = alle.get(ticker, [])
        nye = [t for t in liste if t.get("id") != trans_id]
        if len(nye) == len(liste):
            raise ValueError(f"Fant ingen transaksjon {trans_id} for {ticker}")
        if nye:
            alle[ticker] = nye
        else:
            alle.pop(ticker, None)
        _skriv_alle(alle)


def transaksjoner_for(ticker):
    """Alle transaksjoner for én ticker, eldste først."""
    return sorted(les_alle().get(ticker, []), key=lambda t: (t["dato"], t["id"]))


def tickere_med_transaksjoner():
    return sorted(tk for tk, v in les_alle().items() if v)


# ─── FIFO-beregning ─────────────────────────────────────────────────────────

def skjermingsar_liste(kjopt, solgt):
    """Hvilke inntektsår andelen ga skjermingsfradrag for."""
    return [y for y in range(kjopt.year, solgt.year + 1)
            if kjopt <= dt.date(y, 12, 31) < solgt]


def skjermingsar(kjopt, solgt):
    """Antall år andelen ga skjermingsfradrag.

    Skjerming tilordnes den som eier aksjen ved utgangen av inntektsåret, så det
    som teller er hvor mange 31.12-datoer som ligger i eierperioden — ikke hvor
    mange 365-dagersperioder. En andel kjøpt 01.03.2024 og solgt 15.01.2026 er
    eid i 685 dager (= 1 «år» på kalenderen), men gir skjerming for både 2024 og
    2025.
    """
    return len(skjermingsar_liste(kjopt, solgt))


def _kjor_fifo(transer):
    """Kjør transaksjonene gjennom en FIFO-kø.

    Returnerer (åpne_lots, realiserte_salg, advarsler). Et lot er
    {dato, antall, kost_per_andel}; kjøpsgebyr fordeles inn i kostprisen, slik
    skatteregler legger opp til. Salgsgebyr trekkes fra salgssummen.
    """
    lots = []          # [{dato, antall, kost_per_andel}] — eldste først
    realiserte = []
    advarsler = []

    for t in transer:
        if t["type"] == "kjøp":
            brutto = t["antall"] * t["kurs"] + t["gebyr"]
            lots.append({
                "dato":           t["dato"],
                "antall":         t["antall"],
                "kost_per_andel": brutto / t["antall"],
            })
            continue

        # Salg: spis lots i rekkefølge.
        gjenstar = t["antall"]
        salgsdato = dt.date.fromisoformat(t["dato"])
        netto_per_andel = t["kurs"] - (t["gebyr"] / t["antall"] if t["antall"] else 0)
        kostpris = 0.0
        solgt = 0.0
        eiertid_dager = []
        skjerming_biter = []          # (skjermingsår, antall) per lot som ble spist
        ar_per_lot = []               # konkrete inntektsår per lot

        while gjenstar > 1e-12 and lots:
            lot = lots[0]
            tas = min(gjenstar, lot["antall"])
            kjopsdato = dt.date.fromisoformat(lot["dato"])
            kostpris += tas * lot["kost_per_andel"]
            solgt += tas
            eiertid_dager.append(((salgsdato - kjopsdato).days, tas))
            lot_ar = skjermingsar_liste(kjopsdato, salgsdato)
            skjerming_biter.append((len(lot_ar), tas))
            ar_per_lot.append(lot_ar)
            lot["antall"] -= tas
            gjenstar -= tas
            if lot["antall"] <= 1e-12:
                lots.pop(0)

        if gjenstar > 1e-9:
            advarsler.append(
                f"Salg {t['dato']}: {gjenstar:g} andeler mangler dekning i tidligere kjøp "
                f"— shortsalg er ikke støttet, så overskuddet er ignorert."
            )

        if solgt <= 0:
            continue

        salgssum = solgt * netto_per_andel
        vektet_dager = sum(d * a for d, a in eiertid_dager) / solgt if solgt else 0

        # Skjermingsår kan variere mellom lots i samme salg. Skattekalkulatoren
        # tar ett tall, så vi sender det andelsvektede — og flagger blandingen
        # slik at UI-et kan si fra at det er en tilnærming.
        ar_verdier = {a for a, _ in skjerming_biter}
        # Det lengst eide lotet gir årsrekken vi sender til skattekalkulatoren.
        dominerende_ar = max(ar_per_lot, key=len) if ar_per_lot else []
        vektet_skjermingsar = (sum(a * n for a, n in skjerming_biter) / solgt) if solgt else 0

        realiserte.append({
            "id":                t["id"],
            "dato":              t["dato"],
            "antall":            round(solgt, 6),
            "kurs":              t["kurs"],
            "salgssum":          round(salgssum, 2),
            "inngangsverdi":     round(kostpris, 2),
            "gevinst":           round(salgssum - kostpris, 2),
            "gevinst_pct":       round((salgssum / kostpris - 1) * 100, 2) if kostpris > 0 else None,
            "eiertid_dager":     int(round(vektet_dager)),
            "eiertid_ar":        int(vektet_dager // 365),
            "skjermingsar":      int(round(vektet_skjermingsar)),
            "skjermingsar_liste": dominerende_ar,
            "skjerming_blandet": len(ar_verdier) > 1,
        })

    return lots, realiserte, advarsler


def beregn_posisjon(ticker, pris_naa=None):
    """Beholdning, kostpris og gevinst for én ticker, utledet fra transaksjonene."""
    transer = transaksjoner_for(ticker)
    if not transer:
        return None

    lots, realiserte, advarsler = _kjor_fifo(transer)

    andeler = sum(l["antall"] for l in lots)
    kostpris = sum(l["antall"] * l["kost_per_andel"] for l in lots)
    snittpris = kostpris / andeler if andeler > 1e-12 else 0.0

    realisert_gevinst = sum(r["gevinst"] for r in realiserte)
    innskutt = sum(t["antall"] * t["kurs"] + t["gebyr"]
                   for t in transer if t["type"] == "kjøp")
    uttatt = sum(t["antall"] * t["kurs"] - t["gebyr"]
                 for t in transer if t["type"] == "salg")

    resultat = {
        "ticker":            ticker,
        "antall_transer":    len(transer),
        "andeler":           round(andeler, 6),
        "kostpris":          round(kostpris, 2),
        "snittpris":         round(snittpris, 4),
        "innskutt":          round(innskutt, 2),
        "uttatt":            round(uttatt, 2),
        "realisert_gevinst": round(realisert_gevinst, 2),
        "realiserte_salg":   realiserte,
        "forste_kjop":       transer[0]["dato"],
        "advarsler":         advarsler,
        "lots": [{"dato": l["dato"], "antall": round(l["antall"], 6),
                  "kost_per_andel": round(l["kost_per_andel"], 4)} for l in lots],
    }

    if pris_naa is not None and andeler > 1e-12:
        verdi = andeler * pris_naa
        resultat["verdi"] = round(verdi, 2)
        resultat["urealisert_gevinst"] = round(verdi - kostpris, 2)
        resultat["urealisert_pct"] = round((verdi / kostpris - 1) * 100, 2) if kostpris > 0 else None
    else:
        resultat["verdi"] = 0.0 if andeler <= 1e-12 else None
        resultat["urealisert_gevinst"] = None
        resultat["urealisert_pct"] = None

    return resultat


# ─── Pengevektet avkastning (XIRR) ──────────────────────────────────────────

def _npv(rate, kontantstrommer, t0):
    """Nåverdi av (dato, beløp)-par ved gitt årlig rente."""
    total = 0.0
    for dato, belop in kontantstrommer:
        ar = (dato - t0).days / 365.0
        total += belop / ((1.0 + rate) ** ar)
    return total


def xirr(kontantstrommer, lav=-0.9999, hoy=10.0):
    """Internrente for uregelmessige kontantstrømmer (som Excels XIRR).

    Konvensjon: innskudd er negative, uttak og sluttverdi positive. Bruker
    bisection framfor Newton — tregere, men konvergerer alltid når det finnes
    et fortegnsskifte, og kan ikke sprette ut i det blå slik Newton kan.

    Returnerer None hvis strømmene ikke har både inn- og utbetaling, eller
    hvis roten ligger utenfor [lav, hoy].
    """
    if len(kontantstrommer) < 2:
        return None
    if not (any(b < 0 for _, b in kontantstrommer) and any(b > 0 for _, b in kontantstrommer)):
        return None

    t0 = min(d for d, _ in kontantstrommer)
    f_lav = _npv(lav, kontantstrommer, t0)
    f_hoy = _npv(hoy, kontantstrommer, t0)
    if f_lav * f_hoy > 0:
        return None                      # ingen rot i intervallet

    for _ in range(200):
        midt = (lav + hoy) / 2
        f_midt = _npv(midt, kontantstrommer, t0)
        if abs(f_midt) < 1e-9:
            return midt
        if f_lav * f_midt < 0:
            hoy = midt
        else:
            lav, f_lav = midt, f_midt
    return (lav + hoy) / 2


def pengevektet_avkastning(ticker, pris_naa, idag=None):
    """XIRR for én ticker: kjøp ut, salg inn, dagens verdi som sluttstrøm."""
    transer = transaksjoner_for(ticker)
    if not transer:
        return None
    idag = idag or dt.date.today()

    strommer = []
    for t in transer:
        dato = dt.date.fromisoformat(t["dato"])
        if t["type"] == "kjøp":
            strommer.append((dato, -(t["antall"] * t["kurs"] + t["gebyr"])))
        else:
            strommer.append((dato, t["antall"] * t["kurs"] - t["gebyr"]))

    pos = beregn_posisjon(ticker, pris_naa)
    if pos and pos["andeler"] > 1e-12 and pris_naa:
        strommer.append((idag, pos["andeler"] * pris_naa))

    return xirr(strommer)
