"""Tester for treffsikkerhet: sentiment-etikett vs. faktisk kursbevegelse.

Kursserien er syntetisk, så fasiten er kjent. Ingen nettverkskall — `_kursserie`
og `saker_for` monkeypatches der de brukes.
"""

import datetime as dt

import pytest

from analyse import treffsikkerhet as T


# 10 handelsdager: man–fre i to uker (6.–7. juni er helg).
DATOER = [dt.date(2026, 6, d) for d in (1, 2, 3, 4, 5, 8, 9, 10, 11, 12)]
STIGENDE = [100 * (1.01 ** i) for i in range(10)]      # +1 % per dag
FALLENDE = [100 * (0.99 ** i) for i in range(10)]      # −1 % per dag


def sak(dato, etikett="positiv", tittel="tittel"):
    return {"tittel": tittel, "dato": dato, "etikett": etikett,
            "score": 0.5, "kilde": "Test", "url": ""}


# ─── Retning og utfall ──────────────────────────────────────────────────────

@pytest.mark.parametrize("endring, terskel, forventet", [
    (2.0, 0.3, "opp"),
    (-2.0, 0.3, "ned"),
    (0.1, 0.3, "flat"),
    (-0.1, 0.3, "flat"),
    (0.3, 0.3, "flat"),        # nøyaktig på terskelen teller ikke
    (0.31, 0.3, "opp"),
    (0.0, 0.0, "flat"),        # terskel 0: bare eksakt null er flat
    (0.01, 0.0, "opp"),
])
def test_retning(endring, terskel, forventet):
    assert T._retning(endring, terskel) == forventet


@pytest.mark.parametrize("etikett, retning, forventet", [
    ("positiv", "opp",  "treff"),
    ("negativ", "ned",  "treff"),
    ("positiv", "ned",  "bom"),
    ("negativ", "opp",  "bom"),
    ("positiv", "flat", "flat"),
    ("negativ", "flat", "flat"),
    ("nøytral", "opp",  "nøytral_sak"),
    ("nøytral", "ned",  "nøytral_sak"),
    ("nøytral", "flat", "nøytral_sak"),
])
def test_utfall(etikett, retning, forventet):
    assert T._utfall(etikett, retning) == forventet


def test_nøytral_sak_slår_ut_før_flat():
    """En nøytral sak skal aldri klassifiseres som «flat» — den er uavgjort på
    sentiment-siden, uansett hva kursen gjorde."""
    assert T._utfall("nøytral", "flat") == "nøytral_sak"


# ─── Måling av én sak ───────────────────────────────────────────────────────

def test_måler_fra_dagen_før_saken():
    """Basis er siste sluttkurs FØR publisering — reaksjonen skal fanges."""
    r = T._mal_sak(DATOER, STIGENDE, sak("2026-06-04T09:00:00+00:00"), 1, 0.3)
    assert r["fra_dato"] == "2026-06-03"
    assert r["til_dato"] == "2026-06-04"
    assert r["endring_pct"] == pytest.approx(1.0, abs=0.01)
    assert r["utfall"] == "treff"


def test_horisont_teller_handelsdager_ikke_kalenderdager():
    r = T._mal_sak(DATOER, STIGENDE, sak("2026-06-04T09:00:00+00:00"), 3, 0.3)
    assert r["fra_dato"] == "2026-06-03"
    assert r["til_dato"] == "2026-06-08"        # hopper over helgen
    assert r["endring_pct"] == pytest.approx(3.03, abs=0.01)


def test_helgesak_måles_fra_fredag_til_mandag():
    r = T._mal_sak(DATOER, STIGENDE, sak("2026-06-06T09:00:00+00:00"), 1, 0.3)
    assert r["fra_dato"] == "2026-06-05"
    assert r["til_dato"] == "2026-06-08"


def test_negativ_sak_i_fallende_marked_er_treff():
    r = T._mal_sak(DATOER, FALLENDE, sak("2026-06-04T09:00:00+00:00", "negativ"), 1, 0.3)
    assert r["retning"] == "ned"
    assert r["utfall"] == "treff"


def test_sak_nyere_enn_siste_kurs_venter():
    r = T._mal_sak(DATOER, STIGENDE, sak("2026-07-01T09:00:00+00:00"), 1, 0.3)
    assert r == {"status": "venter"}


def test_for_få_handelsdager_igjen_venter():
    # 11. juni = indeks 8, basis 7, +5 = 12 > siste indeks 9
    r = T._mal_sak(DATOER, STIGENDE, sak("2026-06-11T09:00:00+00:00"), 5, 0.3)
    assert r == {"status": "venter"}


def test_sak_eldre_enn_historikken_forkastes():
    """Uten en kurs FØR saken finnes det ingen basis å måle fra."""
    assert T._mal_sak(DATOER, STIGENDE, sak("2026-01-01T09:00:00+00:00"), 1, 0.3) is None


def test_sak_på_første_handelsdag_forkastes():
    assert T._mal_sak(DATOER, STIGENDE, sak("2026-06-01T09:00:00+00:00"), 1, 0.3) is None


def test_sak_uten_dato_forkastes():
    assert T._mal_sak(DATOER, STIGENDE, sak(""), 1, 0.3) is None
    assert T._mal_sak(DATOER, STIGENDE, sak("tullball"), 1, 0.3) is None


def test_høy_terskel_gjør_bevegelsen_flat():
    r = T._mal_sak(DATOER, STIGENDE, sak("2026-06-04T09:00:00+00:00"), 1, 5.0)
    assert r["retning"] == "flat"
    assert r["utfall"] == "flat"


def test_basis_null_forkastes():
    priser = [0.0] + STIGENDE[1:]
    assert T._mal_sak(DATOER, priser, sak("2026-06-02T09:00:00+00:00"), 1, 0.3) is None


# ─── Aggregering per instrument ─────────────────────────────────────────────

@pytest.fixture
def stub(monkeypatch):
    """Lar en test bestemme både kursserie og loggede saker."""
    def sett(saker, priser=STIGENDE):
        monkeypatch.setattr(T, "saker_for", lambda tk: saker)
        monkeypatch.setattr(T, "_kursserie", lambda tk: (DATOER, priser))
    return sett


def test_treffprosent_regnes_kun_av_avgjorte_saker(stub):
    stub([
        sak("2026-06-02T09:00:00+00:00", "positiv"),   # treff (stigende)
        sak("2026-06-03T09:00:00+00:00", "negativ"),   # bom
        sak("2026-06-04T09:00:00+00:00", "nøytral"),   # teller ikke
    ])
    r = T.treffsikkerhet_for("X", horisont=1, terskel=0.3)
    assert (r["treff"], r["bom"]) == (1, 1)
    assert r["treffprosent"] == 50.0
    assert r["vurdert"] == 3                # nøytral er vurdert, men ikke avgjort


def test_treffprosent_er_none_uten_avgjorte_saker(stub):
    stub([sak("2026-06-02T09:00:00+00:00", "nøytral")])
    r = T.treffsikkerhet_for("X", horisont=1, terskel=0.3)
    assert r["treffprosent"] is None
    assert r["vurdert"] == 1


def test_edge_er_none_når_én_side_mangler(stub):
    """Uten negative saker finnes det ingen forskjell å regne ut."""
    stub([sak("2026-06-02T09:00:00+00:00", "positiv"),
          sak("2026-06-03T09:00:00+00:00", "positiv")])
    r = T.treffsikkerhet_for("X", horisont=1, terskel=0.3)
    assert r["snitt_positiv"] is not None
    assert r["snitt_negativ"] is None
    assert r["edge"] is None


def test_edge_er_differansen_mellom_snittene(stub):
    stub([sak("2026-06-02T09:00:00+00:00", "positiv"),
          sak("2026-06-03T09:00:00+00:00", "negativ")], priser=STIGENDE)
    r = T.treffsikkerhet_for("X", horisont=1, terskel=0.3)
    assert r["edge"] == pytest.approx(r["snitt_positiv"] - r["snitt_negativ"], abs=0.01)


def test_tom_logg_gir_nullstruktur_ikke_krasj(stub):
    stub([])
    r = T.treffsikkerhet_for("X", horisont=3)
    assert r["antall_logget"] == 0
    assert r["vurdert"] == 0
    assert r["treffprosent"] is None
    assert r["saker"] == []


def test_manglende_kursdata_rapporteres(monkeypatch):
    monkeypatch.setattr(T, "saker_for", lambda tk: [sak("2026-06-02T09:00:00+00:00")])
    monkeypatch.setattr(T, "_kursserie", lambda tk: None)
    r = T.treffsikkerhet_for("X")
    assert r["feil"] == "Mangler kursdata"
    assert r["antall_logget"] == 1
    assert r["vurdert"] == 0


def test_ventende_saker_telles_separat(stub):
    stub([sak("2026-06-03T09:00:00+00:00"),           # målbar
          sak("2026-07-01T09:00:00+00:00")])          # nyere enn kursdata
    r = T.treffsikkerhet_for("X", horisont=1, terskel=0.3)
    assert r["vurdert"] == 1
    assert r["venter"] == 1


def test_saker_sorteres_nyeste_først(stub):
    stub([sak("2026-06-02T09:00:00+00:00", tittel="eldst"),
          sak("2026-06-04T09:00:00+00:00", tittel="nyest"),
          sak("2026-06-03T09:00:00+00:00", tittel="midt")])
    r = T.treffsikkerhet_for("X", horisont=1, terskel=0.3)
    assert [s["tittel"] for s in r["saker"]] == ["nyest", "midt", "eldst"]


def test_maks_saker_begrenser_listen_men_ikke_statistikken(stub):
    saker = [sak(f"2026-06-{d:02d}T09:00:00+00:00") for d in (2, 3, 4, 5)]
    stub(saker)
    r = T.treffsikkerhet_for("X", horisont=1, terskel=0.3, maks_saker=2)
    assert len(r["saker"]) == 2
    assert r["vurdert"] == 4        # statistikken bruker alle


# ─── Samlet på tvers av instrumenter ────────────────────────────────────────

def test_ugyldig_horisont_faller_tilbake_til_default(monkeypatch):
    monkeypatch.setattr(T, "alle_instrumenter", lambda: [])
    assert T.hent_treffsikkerhet(horisont=99)["horisont"] == T.TREFF_HORISONT_DEFAULT
    assert T.hent_treffsikkerhet(horisont=3)["horisont"] == 3


def test_tickerfilter_begrenser_utvalget(monkeypatch):
    katalog = [{"ticker": "A", "navn": "A", "type": "aksje", "flagg": ""},
               {"ticker": "B", "navn": "B", "type": "aksje", "flagg": ""}]
    monkeypatch.setattr(T, "alle_instrumenter", lambda: katalog)
    monkeypatch.setattr(T, "saker_for", lambda tk: [])
    monkeypatch.setattr(T, "_kursserie", lambda tk: (DATOER, STIGENDE))
    r = T.hent_treffsikkerhet(tickere=["A"])
    assert [i["ticker"] for i in r["instrumenter"]] == ["A"]


def test_samlet_summerer_på_tvers(monkeypatch):
    katalog = [{"ticker": "A", "navn": "A", "type": "aksje", "flagg": ""},
               {"ticker": "B", "navn": "B", "type": "fond", "flagg": ""}]
    monkeypatch.setattr(T, "alle_instrumenter", lambda: katalog)
    monkeypatch.setattr(T, "_kursserie", lambda tk: (DATOER, STIGENDE))
    monkeypatch.setattr(T, "saker_for", lambda tk: [
        sak("2026-06-02T09:00:00+00:00", "positiv"),      # treff
        sak("2026-06-03T09:00:00+00:00", "negativ"),      # bom
    ])
    r = T.hent_treffsikkerhet(horisont=1, terskel=0.3)
    assert r["samlet"]["treff"] == 2        # ett per instrument
    assert r["samlet"]["bom"] == 2
    assert r["samlet"]["treffprosent"] == 50.0
    assert r["samlet"]["vurdert"] == 4
