"""Tester for skattekalkulatoren (aksjonærmodellen og ASK).

Fasitverdiene er regnet for hånd fra reglene, ikke hentet fra koden — ellers
ville testene bare bekreftet det implementasjonen tilfeldigvis gjør.
"""

import pytest

from analyse.config import (
    OPPJUSTERINGSFAKTOR,
    SKATTESATS,
    SKJERMINGSRENTE_DEFAULT,
    SKJERMINGSRENTER,
)
from analyse.skatt import (
    akkumulert_skjerming,
    beregn_skatt,
    beregn_skatt_ask,
    skjermingsrente_for,
)


EFFEKTIV = SKATTESATS * OPPJUSTERINGSFAKTOR      # 0,22 × 1,72 = 0,3784


# ─── Skjermingsfradrag ──────────────────────────────────────────────────────

def test_skjerming_er_renters_rente_på_kostprisen():
    # 100 000 i 3 år à 3 % → 100000·(1,03³ − 1) = 9 272,70
    per_ar, total = akkumulert_skjerming(100_000, 3, 0.03)
    assert total == pytest.approx(9_272.70, abs=0.01)
    assert [d["belop"] for d in per_ar] == [3000.0, 3090.0, 3182.7]
    assert all(d["ar"] is None for d in per_ar)      # ingen konkrete årstall oppgitt
    # Grunnlaget vokser hvert år — ellers ville det vært 3 × 3000 = 9 000
    assert total > 3 * 3000


def test_skjerming_null_år_gir_null():
    assert akkumulert_skjerming(100_000, 0, 0.036) == ([], 0)


def test_skjerming_negativ_inngangsverdi_klippes_til_null():
    per_ar, total = akkumulert_skjerming(-5000, 3, 0.036)
    assert total == 0
    assert [d["belop"] for d in per_ar] == [0.0, 0.0, 0.0]


# ─── Aksjonærmodellen: gevinst ──────────────────────────────────────────────

def test_gevinst_uten_skjerming():
    r = beregn_skatt(100_000, 160_000, ar=0)
    assert r["raa_gevinst"] == 60_000
    assert r["skattepliktig"] == 60_000
    assert r["skatt"] == pytest.approx(60_000 * EFFEKTIV)      # 22 704
    assert r["netto_gevinst"] == pytest.approx(60_000 * (1 - EFFEKTIV))
    assert r["netto_utbetalt"] == pytest.approx(160_000 - 60_000 * EFFEKTIV)
    assert r["er_tap"] is False


def test_skjerming_reduserer_skattepliktig_gevinst():
    r = beregn_skatt(100_000, 160_000, ar=3, skjermingsrente=0.03)
    assert r["skjerming_total"] == pytest.approx(9_272.70, abs=0.01)
    assert r["brukt_skjerming"] == pytest.approx(9_272.70, abs=0.01)
    assert r["skattepliktig"] == pytest.approx(50_727.30, abs=0.01)
    assert r["skatt"] == pytest.approx(50_727.30 * EFFEKTIV, abs=0.01)
    assert r["ubenyttet_skjerming"] == pytest.approx(0, abs=0.01)


def test_skjerming_kan_ikke_skape_tap():
    """Skjerming større enn gevinsten nulles ut — den kan ikke gi negativ skatt."""
    r = beregn_skatt(100_000, 101_000, ar=10, skjermingsrente=0.05)
    assert r["skjerming_total"] > r["raa_gevinst"]
    assert r["brukt_skjerming"] == 1_000          # kun opp til gevinsten
    assert r["skattepliktig"] == 0
    assert r["skatt"] == 0
    assert r["ubenyttet_skjerming"] > 0           # resten går tapt


# ─── Aksjonærmodellen: tap ──────────────────────────────────────────────────

def test_tap_gir_oppjustert_fradrag():
    r = beregn_skatt(100_000, 70_000, ar=0)
    assert r["er_tap"] is True
    assert r["raa_gevinst"] == -30_000
    assert r["skatt"] == pytest.approx(-30_000 * EFFEKTIV)     # negativ = fradrag
    assert r["netto_utbetalt"] > r["salgssum"]                 # fradraget kommer i tillegg


def test_tap_bruker_ikke_skjerming():
    """Ved tap går skjermingen tapt — den kan ikke øke tapsfradraget."""
    r = beregn_skatt(100_000, 70_000, ar=5, skjermingsrente=0.036)
    assert r["skjerming_total"] > 0
    assert r["brukt_skjerming"] == 0
    assert r["skattepliktig"] == -30_000
    assert r["ubenyttet_skjerming"] == r["skjerming_total"]


# ─── Override og kanttilfeller ──────────────────────────────────────────────

def test_override_erstatter_beregnet_skjerming():
    r = beregn_skatt(100_000, 160_000, ar=5, skjermingsrente=0.036,
                     skjerming_override=12_345)
    assert r["skjerming_total"] == 12_345
    assert r["skjerming_per_ar"] == []
    assert r["skattepliktig"] == pytest.approx(60_000 - 12_345)


def test_override_null_er_ikke_det_samme_som_utelatt():
    """0 må bety «ingen skjerming», ikke «beregn fra år» — falsy-fella."""
    med_override = beregn_skatt(100_000, 160_000, ar=5, skjermingsrente=0.036,
                                skjerming_override=0)
    uten = beregn_skatt(100_000, 160_000, ar=5, skjermingsrente=0.036)
    assert med_override["skjerming_total"] == 0
    assert uten["skjerming_total"] > 0


def test_salg_til_null_er_totaltap():
    r = beregn_skatt(50_000, 0)
    assert r["raa_gevinst"] == -50_000
    assert r["skatt"] == pytest.approx(-50_000 * EFFEKTIV)


def test_effektiv_sats_er_3784_prosent():
    r = beregn_skatt(100_000, 200_000)
    assert r["effektiv_sats_pct"] == pytest.approx(37.84, abs=0.01)
    assert r["gevinst_effektiv_pct"] == pytest.approx(37.84, abs=0.01)


# ─── Aksjesparekonto (ASK) ──────────────────────────────────────────────────

def test_ask_uttak_innenfor_innskudd_er_skattefritt():
    r = beregn_skatt_ask(100_000, 160_000, uttak=80_000)
    assert r["skattefritt_uttak"] == 80_000
    assert r["gevinst_uttak"] == 0
    assert r["skatt"] == 0
    assert r["netto_uttak"] == 80_000
    assert r["gjenstaende_verdi"] == 80_000


def test_ask_uttak_over_innskudd_beskatter_kun_overskytende():
    r = beregn_skatt_ask(100_000, 160_000, uttak=130_000, ar=0)
    assert r["skattefritt_uttak"] == 100_000
    assert r["gevinst_uttak"] == 30_000
    assert r["skatt"] == pytest.approx(30_000 * EFFEKTIV)


def test_ask_tomming_realiserer_hele_gevinsten():
    r = beregn_skatt_ask(100_000, 160_000, uttak=None, ar=0)
    assert r["avslutter"] is True
    assert r["uttak"] == 160_000
    assert r["gevinst_uttak"] == 60_000
    assert r["skatt"] == pytest.approx(60_000 * EFFEKTIV)
    assert r["gjenstaende_verdi"] == 0


def test_ask_tomming_med_tap_gir_fradrag():
    r = beregn_skatt_ask(100_000, 70_000)
    assert r["avslutter"] is True
    assert r["er_tap"] is True
    assert r["skatt"] == pytest.approx(-30_000 * EFFEKTIV)


def test_ask_delvis_uttak_ved_tap_gir_ingen_skatt():
    """Tar du ut mindre enn verdien når kontoen er i minus, realiseres ingenting."""
    r = beregn_skatt_ask(100_000, 70_000, uttak=50_000)
    assert r["avslutter"] is False
    assert r["gevinst_uttak"] == 0
    assert r["skatt"] == 0


def test_ask_uttak_større_enn_verdi_klippes():
    r = beregn_skatt_ask(100_000, 160_000, uttak=999_999)
    assert r["uttak"] == 160_000
    assert r["avslutter"] is True


def test_ask_skjermingsgrunnlaget_er_innskuddet():
    r = beregn_skatt_ask(100_000, 160_000, ar=3, skjermingsrente=0.03)
    assert r["skjerming_total"] == pytest.approx(9_272.70, abs=0.01)
    assert r["skattepliktig"] == pytest.approx(60_000 - 9_272.70, abs=0.01)


def test_ask_skjerming_kan_ikke_skape_tap():
    r = beregn_skatt_ask(100_000, 101_000, ar=10, skjermingsrente=0.05)
    assert r["brukt_skjerming"] == 1_000
    assert r["skattepliktig"] == 0
    assert r["skatt"] == 0


# ─── Offisielle skjermingsrenter per år ─────────────────────────────────────

def test_satstabellen_har_de_verifiserte_satsene():
    """Stikkprøver mot Skatteetaten. Endres et av disse tallene, er det en feil
    — ikke en oppdatering. Nye år legges til, gamle står fast."""
    for ar, forventet in [(2016, 0.004), (2021, 0.005), (2022, 0.017),
                          (2023, 0.032), (2024, 0.039), (2025, 0.036)]:
        assert SKJERMINGSRENTER[ar] == forventet, f"{ar} avviker"


def test_satsene_er_aksjesatsen_ikke_enkeltpersonforetak():
    """ENK-satsen for 2024 er 4,9 % — havner den her, er feil kolonne brukt."""
    assert SKJERMINGSRENTER[2024] == 0.039
    assert SKJERMINGSRENTER[2024] != 0.049
    assert SKJERMINGSRENTER[2023] != 0.042


def test_default_er_siste_kjente_år():
    assert SKJERMINGSRENTE_DEFAULT == SKJERMINGSRENTER[max(SKJERMINGSRENTER)]


def test_ukjent_år_faller_tilbake():
    assert skjermingsrente_for(2024) == 0.039
    assert skjermingsrente_for(1999, fallback=0.02) == 0.02
    assert skjermingsrente_for(2099, fallback=0.02) == 0.02


def test_per_år_satser_gir_annet_resultat_enn_én_felles_sats():
    """2024 = 3,9 % og 2025 = 3,6 %; én felles sats på 3,6 % undervurderer."""
    per_ar = beregn_skatt(624, 840, skjermingsar_liste=[2024, 2025])
    felles = beregn_skatt(624, 840, ar=2, skjermingsrente=0.036)
    assert per_ar["skjerming_total"] > felles["skjerming_total"]
    assert per_ar["skatt"] < felles["skatt"]
    assert per_ar["satser_per_ar"] is True
    assert felles["satser_per_ar"] is False


def test_per_år_bruker_riktig_sats_hvert_år():
    r = beregn_skatt(100_000, 200_000, skjermingsar_liste=[2023, 2024])
    d1, d2 = r["skjerming_per_ar"]
    assert (d1["ar"], d1["sats_pct"]) == (2023, 3.2)
    assert (d2["ar"], d2["sats_pct"]) == (2024, 3.9)
    # Grunnlaget for år 2 er kostpris + fjorårets skjerming
    assert d2["grunnlag"] == pytest.approx(100_000 + d1["belop"], abs=0.01)
    assert r["alle_satser_offisielle"] is True


def test_år_uten_offisiell_sats_flagges():
    r = beregn_skatt(100_000, 200_000, skjermingsar_liste=[2024, 2099])
    assert r["alle_satser_offisielle"] is False
    assert r["skjerming_per_ar"][0]["offisiell"] is True
    assert r["skjerming_per_ar"][1]["offisiell"] is False


def test_lavrenteår_gir_nesten_ingen_skjerming():
    """2016 var 0,4 % — skjermingen skal være tilsvarende liten."""
    r = beregn_skatt(100_000, 200_000, skjermingsar_liste=[2016])
    assert r["skjerming_total"] == pytest.approx(400, abs=1)


def test_ask_støtter_også_per_år_satser():
    r = beregn_skatt_ask(100_000, 200_000, skjermingsar_liste=[2023, 2024])
    assert r["satser_per_ar"] is True
    assert [d["sats_pct"] for d in r["skjerming_per_ar"]] == [3.2, 3.9]


def test_ar_speiler_antall_år_i_listen():
    r = beregn_skatt(100_000, 200_000, ar=99, skjermingsar_liste=[2023, 2024, 2025])
    assert r["ar"] == 3          # listen vinner over `ar`
