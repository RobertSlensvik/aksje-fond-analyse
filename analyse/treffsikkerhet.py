"""Treffsikkerhet: gikk kursen faktisk opp etter positive nyheter?

For hver loggede nyhetssak finner vi siste sluttkurs FØR saken ble publisert,
og sammenligner med sluttkursen N handelsdager etter. Da kan vi svare på om
sentiment-etikettene faktisk henger sammen med kursbevegelsen.

Merk: dette er en observasjon av samvariasjon, ikke årsak. Nyheter kommer ofte
ETTER at kursen har beveget seg, og utvalget er lite til å begynne med.
"""

from bisect import bisect_left
from concurrent.futures import ThreadPoolExecutor

from .cache import hent_historikk
from .config import (
    TREFF_HORISONTER,
    TREFF_HORISONT_DEFAULT,
    TREFF_TERSKEL_PCT,
)
from .instrumenter import alle_instrumenter
from .nyhetslogg import parse_dato, saker_for


# Nok historikk til å dekke hele loggvinduet (365 dager) med margin.
_HIST_PERIODE = "2y"


def _kursserie(ticker):
    """(datoer, sluttkurser) som parallelle lister sortert stigende. None ved feil."""
    hist = hent_historikk(ticker, _HIST_PERIODE)
    if hist is None or len(hist) < 2:
        return None
    priser = hist["Close"].dropna()
    if len(priser) < 2:
        return None
    datoer = [d.date() for d in priser.index]
    return datoer, [float(p) for p in priser]


def _retning(endring_pct, terskel):
    if endring_pct > terskel:
        return "opp"
    if endring_pct < -terskel:
        return "ned"
    return "flat"


def _utfall(etikett, retning):
    """Traff sentimentet? Nøytrale saker og flate kurser gir ingen dom."""
    if etikett == "nøytral":
        return "nøytral_sak"
    if retning == "flat":
        return "flat"
    if (etikett == "positiv" and retning == "opp") or (etikett == "negativ" and retning == "ned"):
        return "treff"
    return "bom"


def _mal_sak(datoer, priser, sak, horisont, terskel):
    """Mål kursbevegelsen rundt én sak. None hvis saken ikke kan vurderes."""
    d = parse_dato(sak.get("dato"))
    if d is None:
        return None
    sak_dag = d.date()

    # Første handelsdag på eller etter publisering; basen er dagen før.
    i = bisect_left(datoer, sak_dag)
    if i == 0:
        return None                          # saken er eldre enn kurshistorikken
    if i >= len(datoer):
        return {"status": "venter"}          # saken er nyere enn siste sluttkurs
    base_idx = i - 1
    mal_idx = base_idx + horisont
    if mal_idx >= len(datoer):
        return {"status": "venter"}          # ikke nok handelsdager ennå

    base = priser[base_idx]
    if base <= 0:
        return None
    endring = (priser[mal_idx] / base - 1) * 100
    retning = _retning(endring, terskel)
    return {
        "status":       "vurdert",
        "tittel":       sak.get("tittel", ""),
        "url":          sak.get("url", ""),
        "kilde":        sak.get("kilde", ""),
        "dato":         sak.get("dato", ""),
        "dato_antatt":  bool(sak.get("dato_antatt")),
        "score":        sak.get("score", 0.0),
        "etikett":      sak.get("etikett", "nøytral"),
        "fra_dato":     str(datoer[base_idx]),
        "til_dato":     str(datoer[mal_idx]),
        "endring_pct":  round(endring, 2),
        "retning":      retning,
        "utfall":       _utfall(sak.get("etikett", "nøytral"), retning),
    }


def _snitt(verdier):
    return round(sum(verdier) / len(verdier), 2) if verdier else None


def treffsikkerhet_for(ticker, horisont=TREFF_HORISONT_DEFAULT, terskel=TREFF_TERSKEL_PCT,
                       maks_saker=25):
    """Statistikk for én ticker: treffprosent og snittbevegelse per sentiment."""
    saker = saker_for(ticker)
    if not saker:
        return {"ticker": ticker, "antall_logget": 0, "vurdert": 0, "venter": 0,
                "treff": 0, "bom": 0, "flat": 0, "treffprosent": None,
                "snitt_positiv": None, "snitt_negativ": None, "snitt_nøytral": None,
                "snitt_alle": None, "edge": None, "saker": []}

    serie = _kursserie(ticker)
    if serie is None:
        return {"ticker": ticker, "antall_logget": len(saker), "vurdert": 0, "venter": 0,
                "treff": 0, "bom": 0, "flat": 0, "treffprosent": None,
                "snitt_positiv": None, "snitt_negativ": None, "snitt_nøytral": None,
                "snitt_alle": None, "edge": None, "saker": [],
                "feil": "Mangler kursdata"}
    datoer, priser = serie

    vurderte, venter = [], 0
    for sak in saker:
        r = _mal_sak(datoer, priser, sak, horisont, terskel)
        if r is None:
            continue
        if r["status"] == "venter":
            venter += 1
        else:
            vurderte.append(r)

    treff = sum(1 for r in vurderte if r["utfall"] == "treff")
    bom   = sum(1 for r in vurderte if r["utfall"] == "bom")
    flat  = sum(1 for r in vurderte if r["utfall"] == "flat")

    pos = [r["endring_pct"] for r in vurderte if r["etikett"] == "positiv"]
    neg = [r["endring_pct"] for r in vurderte if r["etikett"] == "negativ"]
    nøy = [r["endring_pct"] for r in vurderte if r["etikett"] == "nøytral"]
    alle = [r["endring_pct"] for r in vurderte]

    snitt_pos, snitt_neg = _snitt(pos), _snitt(neg)
    edge = round(snitt_pos - snitt_neg, 2) if snitt_pos is not None and snitt_neg is not None else None

    vurderte.sort(key=lambda r: r["dato"], reverse=True)
    return {
        "ticker":         ticker,
        "antall_logget":  len(saker),
        "vurdert":        len(vurderte),
        "venter":         venter,
        "treff":          treff,
        "bom":            bom,
        "flat":           flat,
        "treffprosent":   round(treff / (treff + bom) * 100, 1) if (treff + bom) else None,
        "antall_positiv": len(pos),
        "antall_negativ": len(neg),
        "antall_nøytral": len(nøy),
        "snitt_positiv":  snitt_pos,
        "snitt_negativ":  snitt_neg,
        "snitt_nøytral":  _snitt(nøy),
        "snitt_alle":     _snitt(alle),
        "edge":           edge,
        "saker":          vurderte[:maks_saker],
    }


def hent_treffsikkerhet(horisont=TREFF_HORISONT_DEFAULT, terskel=TREFF_TERSKEL_PCT,
                        tickere=None):
    """Treffsikkerhet for alle (eller utvalgte) instrumenter + samlet fasit."""
    if horisont not in TREFF_HORISONTER:
        horisont = TREFF_HORISONT_DEFAULT

    katalog = alle_instrumenter()
    if tickere:
        ønsket = set(tickere)
        katalog = [i for i in katalog if i["ticker"] in ønsket]

    with ThreadPoolExecutor(max_workers=6) as ex:
        stats = list(ex.map(
            lambda i: treffsikkerhet_for(i["ticker"], horisont, terskel),
            katalog,
        ))

    resultat = []
    for item, s in zip(katalog, stats):
        resultat.append({**s, "navn": item["navn"], "flagg": item.get("flagg", ""),
                         "type": item["type"]})

    treff = sum(r["treff"] for r in resultat)
    bom   = sum(r["bom"] for r in resultat)
    flat  = sum(r["flat"] for r in resultat)
    vurdert = sum(r["vurdert"] for r in resultat)
    venter  = sum(r["venter"] for r in resultat)

    # Vektet snitt på tvers: vekt hver tickers snitt med antall saker bak det.
    def _vektet(nøkkel, antall_nøkkel):
        par = [(r[nøkkel], r[antall_nøkkel]) for r in resultat
               if r.get(nøkkel) is not None and r.get(antall_nøkkel)]
        n = sum(a for _, a in par)
        return round(sum(v * a for v, a in par) / n, 2) if n else None

    snitt_pos = _vektet("snitt_positiv", "antall_positiv")
    snitt_neg = _vektet("snitt_negativ", "antall_negativ")

    samlet = {
        "vurdert":       vurdert,
        "venter":        venter,
        "treff":         treff,
        "bom":           bom,
        "flat":          flat,
        "treffprosent":  round(treff / (treff + bom) * 100, 1) if (treff + bom) else None,
        "snitt_positiv": snitt_pos,
        "snitt_negativ": snitt_neg,
        "snitt_alle":    _vektet("snitt_alle", "vurdert"),
        "edge":          round(snitt_pos - snitt_neg, 2)
                         if snitt_pos is not None and snitt_neg is not None else None,
    }

    # Rangér instrumenter med nok datagrunnlag øverst.
    resultat.sort(key=lambda r: (r["treff"] + r["bom"], r["treffprosent"] or 0), reverse=True)

    return {
        "horisont":    horisont,
        "horisonter":  TREFF_HORISONTER,
        "terskel_pct": terskel,
        "samlet":      samlet,
        "instrumenter": resultat,
    }
