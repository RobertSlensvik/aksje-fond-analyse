"""Skattekalkulator for realisert aksjegevinst etter norsk aksjonærmodell.

Gjelder privatperson som eier aksjer/aksjefond utenfor aksjesparekonto (ASK).
Skattepliktig gevinst reduseres med ubenyttet skjermingsfradrag og oppjusteres
deretter med oppjusteringsfaktoren før alminnelig skattesats. Tap gir fradrag
(oppjustert) — skjerming kan ikke skape eller øke et tap, og ubenyttet skjerming
ved realisasjon går tapt (kan ikke overføres til andre aksjer).
"""

from .config import (
    OPPJUSTERINGSFAKTOR,
    SKATTESATS,
    SKJERMINGSRENTE_DEFAULT,
    SKJERMINGSRENTER,
)


def skjermingsrente_for(ar, fallback=SKJERMINGSRENTE_DEFAULT):
    """Offisiell skjermingsrente for et inntektsår, ellers `fallback`.

    Renten fastsettes av Skatteetaten i januar året etter inntektsåret, så det
    nyeste året mangler alltid en offisiell sats.
    """
    return SKJERMINGSRENTER.get(int(ar), fallback)


def akkumulert_skjerming(inngangsverdi, ar, skjermingsrente, ar_liste=None):
    """Akkumulert ubenyttet skjermingsfradrag.

    Skjermingen beregnes per år på skjermingsgrunnlaget (= inngangsverdi +
    tidligere ubenyttet skjerming) og legges til grunnlaget året etter når den
    ikke er brukt mot utbytte.

    `ar_liste` er konkrete inntektsår, f.eks. [2023, 2024]. Da brukes den
    offisielle satsen for hvert enkelt år — satsen har variert fra 0,4 % (2016)
    til 3,9 % (2024), så én felles sats over flere år gir merkbart avvik. Uten
    `ar_liste` brukes `skjermingsrente` for alle `ar` år, som før.

    Returnerer (detaljer, total), der detaljer er en liste med
    {ar, sats_pct, grunnlag, belop} — én per år.
    """
    grunnlag = max(0.0, inngangsverdi)
    ar_ene = list(ar_liste) if ar_liste is not None else [None] * max(0, int(ar))

    detaljer = []
    for inntektsar in ar_ene:
        sats = skjermingsrente if inntektsar is None else skjermingsrente_for(
            inntektsar, fallback=skjermingsrente)
        belop = grunnlag * sats
        detaljer.append({
            "ar":       inntektsar,
            "sats_pct": round(sats * 100, 3),
            "grunnlag": round(grunnlag, 2),
            "belop":    round(belop, 2),
            "offisiell": inntektsar is not None and int(inntektsar) in SKJERMINGSRENTER,
        })
        grunnlag += belop

    return detaljer, round(sum(d["belop"] for d in detaljer), 2)


def beregn_skatt(inngangsverdi, salgssum, ar=0,
                 skjermingsrente=SKJERMINGSRENTE_DEFAULT,
                 skjerming_override=None, skjermingsar_liste=None):
    """Beregn skatt på realisert gevinst/tap etter aksjonærmodellen.

    Parametre:
      inngangsverdi      Kjøpesum inkl. kjøpsomkostninger (kostpris).
      salgssum           Salgssum etter salgsomkostninger (netto).
      ar                 Antall hele eierår (per 31.12) for skjermingsakkumulering.
      skjermingsrente    Årlig skjermingsrente (desimal, f.eks. 0.036).
      skjerming_override Oppgi akkumulert ubenyttet skjerming direkte (kr) i
                         stedet for å beregne den fra `ar` og renten.

    Returnerer en dict med alle mellomregninger og resultater.
    """
    inngangsverdi = max(0.0, float(inngangsverdi))
    salgssum = max(0.0, float(salgssum))

    if skjerming_override is not None:
        skjerming_total = max(0.0, float(skjerming_override))
        skjerming_per_ar = []
    else:
        skjerming_per_ar, skjerming_total = akkumulert_skjerming(
            inngangsverdi, ar, skjermingsrente, ar_liste=skjermingsar_liste)

    raa_gevinst = salgssum - inngangsverdi

    if raa_gevinst >= 0:
        # Skjerming reduserer kun gevinst, aldri under null.
        brukt_skjerming = min(skjerming_total, raa_gevinst)
        skattepliktig = raa_gevinst - brukt_skjerming
    else:
        # Tap: skjerming kan ikke brukes og går tapt. Tapet er fradragsberettiget.
        brukt_skjerming = 0.0
        skattepliktig = raa_gevinst

    ubenyttet_skjerming = skjerming_total - brukt_skjerming
    oppjustert = skattepliktig * OPPJUSTERINGSFAKTOR
    skatt = oppjustert * SKATTESATS          # Negativ = skattefradrag ved tap
    netto_gevinst = raa_gevinst - skatt
    netto_utbetalt = salgssum - skatt
    effektiv_sats = (skatt / raa_gevinst * 100) if raa_gevinst > 0 else 0.0

    return {
        "inngangsverdi":       round(inngangsverdi, 2),
        "salgssum":            round(salgssum, 2),
        "raa_gevinst":         round(raa_gevinst, 2),
        "er_tap":              raa_gevinst < 0,
        "skjermingsrente_pct": round(skjermingsrente * 100, 3),
        "ar":                  len(skjerming_per_ar) if skjermingsar_liste else int(ar),
        "skjerming_total":     round(skjerming_total, 2),
        "skjerming_per_ar":    skjerming_per_ar,
        "satser_per_ar":       bool(skjermingsar_liste),
        "alle_satser_offisielle": bool(skjerming_per_ar) and all(
            d.get("offisiell") for d in skjerming_per_ar),
        "brukt_skjerming":     round(brukt_skjerming, 2),
        "ubenyttet_skjerming": round(ubenyttet_skjerming, 2),
        "skattepliktig":       round(skattepliktig, 2),
        "oppjusteringsfaktor": OPPJUSTERINGSFAKTOR,
        "oppjustert":          round(oppjustert, 2),
        "skattesats_pct":      round(SKATTESATS * 100, 1),
        "effektiv_sats_pct":   round(SKATTESATS * OPPJUSTERINGSFAKTOR * 100, 2),
        "skatt":               round(skatt, 2),
        "netto_gevinst":       round(netto_gevinst, 2),
        "netto_utbetalt":      round(netto_utbetalt, 2),
        "gevinst_effektiv_pct": round(effektiv_sats, 2),
    }


def beregn_skatt_ask(innskudd, verdi, uttak=None, ar=0,
                     skjermingsrente=SKJERMINGSRENTE_DEFAULT,
                     skjerming_override=None, skjermingsar_liste=None):
    """Beregn skatt ved uttak fra aksjesparekonto (ASK).

    På ASK kan du kjøpe og selge skattefritt inne på kontoen. Skatt utløses
    først ved uttak som overstiger samlet innskudd: innskuddet kan tas ut
    skattefritt, og kun gevinstdelen over innskuddet beskattes (oppjustert,
    minus skjerming). Skjermingsgrunnlaget er innskuddet på kontoen.

    Parametre:
      innskudd   Samlet innskudd (kostpris) ført inn på kontoen.
      verdi      Markedsverdi på kontoen nå.
      uttak      Beløp som tas ut. None/utelatt = tøm kontoen (= verdi).
      ar         Antall hele år med skjermingsgrunnlag.
      skjermingsrente / skjerming_override — som i `beregn_skatt`.
    """
    innskudd = max(0.0, float(innskudd))
    verdi = max(0.0, float(verdi))
    uttak = verdi if uttak is None else max(0.0, min(float(uttak), verdi))

    if skjerming_override is not None:
        skjerming_total = max(0.0, float(skjerming_override))
        skjerming_per_ar = []
    else:
        skjerming_per_ar, skjerming_total = akkumulert_skjerming(
            innskudd, ar, skjermingsrente, ar_liste=skjermingsar_liste)

    urealisert_gevinst = verdi - innskudd
    avslutter = uttak >= verdi  # Tømmer kontoen → realiserer evt. tap

    # Uttak dekkes av innskudd først (skattefritt), deretter gevinst.
    skattefritt_uttak = min(uttak, innskudd)
    if avslutter:
        gevinst_uttak = urealisert_gevinst          # Kan være negativ (tap)
    else:
        gevinst_uttak = max(0.0, uttak - innskudd)

    if gevinst_uttak >= 0:
        brukt_skjerming = min(skjerming_total, gevinst_uttak)
        skattepliktig = gevinst_uttak - brukt_skjerming
    else:
        brukt_skjerming = 0.0                        # Tap: skjerming ikke brukt
        skattepliktig = gevinst_uttak

    ubenyttet_skjerming = skjerming_total - brukt_skjerming
    oppjustert = skattepliktig * OPPJUSTERINGSFAKTOR
    skatt = oppjustert * SKATTESATS                  # Negativ = fradrag ved tap
    netto_uttak = uttak - skatt
    gjenstaende_verdi = verdi - uttak

    return {
        "innskudd":            round(innskudd, 2),
        "verdi":               round(verdi, 2),
        "uttak":               round(uttak, 2),
        "avslutter":           avslutter,
        "urealisert_gevinst":  round(urealisert_gevinst, 2),
        "er_tap":              gevinst_uttak < 0,
        "skattefritt_uttak":   round(skattefritt_uttak, 2),
        "gevinst_uttak":       round(gevinst_uttak, 2),
        "skjermingsrente_pct": round(skjermingsrente * 100, 3),
        "ar":                  len(skjerming_per_ar) if skjermingsar_liste else int(ar),
        "skjerming_total":     round(skjerming_total, 2),
        "skjerming_per_ar":    skjerming_per_ar,
        "satser_per_ar":       bool(skjermingsar_liste),
        "alle_satser_offisielle": bool(skjerming_per_ar) and all(
            d.get("offisiell") for d in skjerming_per_ar),
        "brukt_skjerming":     round(brukt_skjerming, 2),
        "ubenyttet_skjerming": round(ubenyttet_skjerming, 2),
        "skattepliktig":       round(skattepliktig, 2),
        "oppjusteringsfaktor": OPPJUSTERINGSFAKTOR,
        "oppjustert":          round(oppjustert, 2),
        "skattesats_pct":      round(SKATTESATS * 100, 1),
        "effektiv_sats_pct":   round(SKATTESATS * OPPJUSTERINGSFAKTOR * 100, 2),
        "skatt":               round(skatt, 2),
        "netto_uttak":         round(netto_uttak, 2),
        "gjenstaende_verdi":   round(gjenstaende_verdi, 2),
    }
