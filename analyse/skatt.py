"""Skattekalkulator for realisert aksjegevinst etter norsk aksjonærmodell.

Gjelder privatperson som eier aksjer/aksjefond utenfor aksjesparekonto (ASK).
Skattepliktig gevinst reduseres med ubenyttet skjermingsfradrag og oppjusteres
deretter med oppjusteringsfaktoren før alminnelig skattesats. Tap gir fradrag
(oppjustert) — skjerming kan ikke skape eller øke et tap, og ubenyttet skjerming
ved realisasjon går tapt (kan ikke overføres til andre aksjer).
"""

from .config import OPPJUSTERINGSFAKTOR, SKATTESATS, SKJERMINGSRENTE_DEFAULT


def akkumulert_skjerming(inngangsverdi, ar, skjermingsrente):
    """Akkumulert ubenyttet skjermingsfradrag etter `ar` hele eierår.

    Skjermingen beregnes per år på skjermingsgrunnlaget (= inngangsverdi +
    tidligere ubenyttet skjerming) og legges til grunnlaget året etter når den
    ikke er brukt mot utbytte. Med konstant rente og uten utbytte gir det:

        skjerming = inngangsverdi · ((1 + rente)^år − 1)

    Returnerer en liste med årlig skjerming (for visning) og totalsummen.
    """
    grunnlag = max(0.0, inngangsverdi)
    per_ar = []
    for _ in range(max(0, int(ar))):
        skjerming = grunnlag * skjermingsrente
        per_ar.append(round(skjerming, 2))
        grunnlag += skjerming
    return per_ar, round(sum(per_ar), 2)


def beregn_skatt(inngangsverdi, salgssum, ar=0,
                 skjermingsrente=SKJERMINGSRENTE_DEFAULT,
                 skjerming_override=None):
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
            inngangsverdi, ar, skjermingsrente)

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
        "ar":                  int(ar),
        "skjerming_total":     round(skjerming_total, 2),
        "skjerming_per_ar":    skjerming_per_ar,
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
                     skjerming_override=None):
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
            innskudd, ar, skjermingsrente)

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
        "ar":                  int(ar),
        "skjerming_total":     round(skjerming_total, 2),
        "skjerming_per_ar":    skjerming_per_ar,
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
