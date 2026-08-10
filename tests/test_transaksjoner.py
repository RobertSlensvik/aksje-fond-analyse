"""Tester for transaksjonsloggen: validering, FIFO-lots og XIRR.

Alle tester som rører disk peker `TRANSAKSJONER_FIL` mot en midlertidig fil, så
brukerens egne data aldri berøres.
"""

import datetime as dt

import pytest

from analyse import transaksjoner as TR


@pytest.fixture(autouse=True)
def midlertidig_fil(tmp_path, monkeypatch):
    """Isolér lagringen — ingen test skal skrive i data/."""
    monkeypatch.setattr(TR, "TRANSAKSJONER_FIL", str(tmp_path / "transaksjoner.json"))


def kjop(dato, antall, kurs, gebyr=0, ticker="AAPL"):
    return TR.legg_til({"ticker": ticker, "type": "kjøp", "dato": dato,
                        "antall": antall, "kurs": kurs, "gebyr": gebyr})


def salg(dato, antall, kurs, gebyr=0, ticker="AAPL"):
    return TR.legg_til({"ticker": ticker, "type": "salg", "dato": dato,
                        "antall": antall, "kurs": kurs, "gebyr": gebyr})


# ─── Validering ─────────────────────────────────────────────────────────────

def test_avviser_ukjent_type():
    with pytest.raises(ValueError, match="kjøp"):
        TR.legg_til({"ticker": "A", "type": "utbytte", "dato": "2024-01-01",
                     "antall": 1, "kurs": 1})


def test_avviser_manglende_ticker():
    with pytest.raises(ValueError, match="Ticker"):
        TR.legg_til({"ticker": "", "type": "kjøp", "dato": "2024-01-01",
                     "antall": 1, "kurs": 1})


@pytest.mark.parametrize("dato", ["01.01.2024", "2024-13-01", "i går", ""])
def test_avviser_ugyldig_dato(dato):
    with pytest.raises(ValueError, match="[Dd]ato"):
        TR.legg_til({"ticker": "A", "type": "kjøp", "dato": dato,
                     "antall": 1, "kurs": 1})


def test_avviser_framtidig_dato():
    imorgen = (dt.date.today() + dt.timedelta(days=1)).isoformat()
    with pytest.raises(ValueError, match="framtiden"):
        TR.legg_til({"ticker": "A", "type": "kjøp", "dato": imorgen,
                     "antall": 1, "kurs": 1})


@pytest.mark.parametrize("felt, verdi", [
    ("antall", 0), ("antall", -5), ("kurs", -1), ("gebyr", -1),
])
def test_avviser_ugyldige_tall(felt, verdi):
    rad = {"ticker": "A", "type": "kjøp", "dato": "2024-01-01", "antall": 1, "kurs": 100}
    rad[felt] = verdi
    with pytest.raises(ValueError):
        TR.legg_til(rad)


def test_antall_kan_være_desimaltall():
    """Fondsandeler kjøpes sjelden i hele enheter."""
    t = kjop("2024-01-01", 0.5831, 7287.73)
    assert t["antall"] == pytest.approx(0.5831)


# ─── Lagring ────────────────────────────────────────────────────────────────

def test_transaksjoner_sorteres_kronologisk():
    kjop("2024-06-01", 1, 100)
    kjop("2024-01-01", 1, 100)
    kjop("2024-03-01", 1, 100)
    assert [t["dato"] for t in TR.transaksjoner_for("AAPL")] == \
        ["2024-01-01", "2024-03-01", "2024-06-01"]


def test_fjern_sletter_riktig_rad():
    a = kjop("2024-01-01", 1, 100)
    b = kjop("2024-02-01", 2, 110)
    TR.fjern("AAPL", a["id"])
    igjen = TR.transaksjoner_for("AAPL")
    assert [t["id"] for t in igjen] == [b["id"]]


def test_fjern_siste_rad_fjerner_tickeren():
    a = kjop("2024-01-01", 1, 100)
    TR.fjern("AAPL", a["id"])
    assert TR.tickere_med_transaksjoner() == []


def test_fjern_ukjent_id_kaster():
    kjop("2024-01-01", 1, 100)
    with pytest.raises(ValueError, match="Fant ingen"):
        TR.fjern("AAPL", "finnesikke")


def test_tom_fil_gir_tom_dict():
    assert TR.les_alle() == {}
    assert TR.transaksjoner_for("AAPL") == []
    assert TR.beregn_posisjon("AAPL") is None


def test_korrupt_fil_krasjer_ikke(tmp_path, monkeypatch):
    sti = tmp_path / "ødelagt.json"
    sti.write_text("{ ikke json", encoding="utf-8")
    monkeypatch.setattr(TR, "TRANSAKSJONER_FIL", str(sti))
    assert TR.les_alle() == {}


# ─── FIFO: kostpris og beholdning ───────────────────────────────────────────

def test_enkelt_kjop_gir_kostpris_og_snittpris():
    kjop("2024-01-01", 10, 100)
    p = TR.beregn_posisjon("AAPL", pris_naa=120)
    assert p["andeler"] == 10
    assert p["kostpris"] == 1000
    assert p["snittpris"] == 100
    assert p["verdi"] == 1200
    assert p["urealisert_gevinst"] == 200
    assert p["urealisert_pct"] == pytest.approx(20.0)


def test_kjopsgebyr_inngår_i_kostprisen():
    """Kjøpsomkostninger er en del av inngangsverdien etter norske regler."""
    kjop("2024-01-01", 10, 100, gebyr=99)
    p = TR.beregn_posisjon("AAPL", pris_naa=100)
    assert p["kostpris"] == 1099
    assert p["snittpris"] == pytest.approx(109.9)
    assert p["urealisert_gevinst"] == -99      # i minus med én gang, pga. gebyret


def test_flere_kjop_gir_vektet_snittpris():
    kjop("2024-01-01", 10, 100)
    kjop("2024-06-01", 10, 200)
    p = TR.beregn_posisjon("AAPL", pris_naa=150)
    assert p["andeler"] == 20
    assert p["kostpris"] == 3000
    assert p["snittpris"] == 150


def test_fifo_selger_eldste_lot_først():
    kjop("2024-01-01", 10, 100)      # billig lot
    kjop("2024-06-01", 10, 200)      # dyrt lot
    salg("2024-09-01", 10, 250)
    p = TR.beregn_posisjon("AAPL", pris_naa=250)
    # Solgte det billige lotet → gevinst = 10·(250 − 100) = 1500
    assert p["realisert_gevinst"] == 1500
    # Igjen: det dyre lotet
    assert p["andeler"] == 10
    assert p["snittpris"] == 200


def test_fifo_er_ikke_gjennomsnitt():
    """Vakt mot å bytte til snittkostpris — det ville gitt 750, ikke 1500."""
    kjop("2024-01-01", 10, 100)
    kjop("2024-06-01", 10, 200)
    salg("2024-09-01", 10, 250)
    p = TR.beregn_posisjon("AAPL")
    assert p["realisert_gevinst"] == 1500
    assert p["realisert_gevinst"] != 750


def test_salg_over_flere_lots():
    kjop("2024-01-01", 10, 100)
    kjop("2024-06-01", 10, 200)
    salg("2024-09-01", 15, 300)
    p = TR.beregn_posisjon("AAPL", pris_naa=300)
    # Kostpris: 10·100 + 5·200 = 2000. Salgssum 15·300 = 4500 → gevinst 2500
    assert p["realisert_gevinst"] == 2500
    assert p["andeler"] == 5
    assert p["snittpris"] == 200


def test_salgsgebyr_trekkes_fra_salgssummen():
    kjop("2024-01-01", 10, 100)
    salg("2024-09-01", 10, 150, gebyr=50)
    p = TR.beregn_posisjon("AAPL")
    assert p["realisert_gevinst"] == 450        # 1500 − 50 − 1000


def test_salg_med_tap():
    kjop("2024-01-01", 10, 100)
    salg("2024-09-01", 10, 60)
    p = TR.beregn_posisjon("AAPL")
    assert p["realisert_gevinst"] == -400
    assert p["realiserte_salg"][0]["gevinst_pct"] == pytest.approx(-40.0)


def test_full_salg_nullstiller_beholdningen():
    kjop("2024-01-01", 10, 100)
    salg("2024-09-01", 10, 150)
    p = TR.beregn_posisjon("AAPL", pris_naa=150)
    assert p["andeler"] == 0
    assert p["kostpris"] == 0
    assert p["verdi"] == 0
    assert p["lots"] == []


def test_salg_uten_dekning_gir_advarsel_men_krasjer_ikke():
    kjop("2024-01-01", 5, 100)
    salg("2024-09-01", 10, 150)      # selger mer enn man eier
    p = TR.beregn_posisjon("AAPL")
    assert p["advarsler"]
    assert "shortsalg" in p["advarsler"][0]
    assert p["andeler"] == 0
    assert p["realisert_gevinst"] == 250     # kun de 5 som fantes


def test_eiertid_regnes_per_lot():
    kjop("2020-01-01", 10, 100)
    salg("2024-01-01", 10, 200)
    r = TR.beregn_posisjon("AAPL")["realiserte_salg"][0]
    assert r["eiertid_ar"] == 4
    assert r["eiertid_dager"] == pytest.approx(1461, abs=1)


def test_eiertid_vektes_når_salget_spenner_flere_lots():
    kjop("2020-01-01", 10, 100)      # 4 år
    kjop("2023-01-01", 10, 100)      # 1 år
    salg("2024-01-01", 20, 200)
    r = TR.beregn_posisjon("AAPL")["realiserte_salg"][0]
    assert 900 < r["eiertid_dager"] < 1100     # snitt av 1461 og 365


def test_innskutt_og_uttatt_summeres():
    kjop("2024-01-01", 10, 100, gebyr=10)
    kjop("2024-02-01", 5, 120)
    salg("2024-06-01", 3, 150, gebyr=5)
    p = TR.beregn_posisjon("AAPL")
    assert p["innskutt"] == 1010 + 600
    assert p["uttatt"] == 450 - 5


def test_posisjon_uten_pris_gir_ingen_falsk_verdi():
    kjop("2024-01-01", 10, 100)
    p = TR.beregn_posisjon("AAPL", pris_naa=None)
    assert p["verdi"] is None
    assert p["urealisert_gevinst"] is None


def test_tickere_holdes_adskilt():
    kjop("2024-01-01", 10, 100, ticker="AAPL")
    kjop("2024-01-01", 5, 200, ticker="MSFT")
    assert TR.beregn_posisjon("AAPL")["andeler"] == 10
    assert TR.beregn_posisjon("MSFT")["andeler"] == 5
    assert TR.tickere_med_transaksjoner() == ["AAPL", "MSFT"]


# ─── XIRR ───────────────────────────────────────────────────────────────────

def test_xirr_enkel_dobling_på_ett_år():
    strommer = [(dt.date(2024, 1, 1), -1000), (dt.date(2025, 1, 1), 2000)]
    assert TR.xirr(strommer) == pytest.approx(1.0, abs=0.01)     # +100 %


def test_xirr_ti_prosent_på_ett_år():
    strommer = [(dt.date(2024, 1, 1), -1000), (dt.date(2025, 1, 1), 1100)]
    assert TR.xirr(strommer) == pytest.approx(0.10, abs=0.005)


def test_xirr_tap():
    strommer = [(dt.date(2024, 1, 1), -1000), (dt.date(2025, 1, 1), 800)]
    r = TR.xirr(strommer)
    assert r == pytest.approx(-0.20, abs=0.01)


def test_xirr_krever_både_inn_og_ut():
    assert TR.xirr([(dt.date(2024, 1, 1), -100), (dt.date(2025, 1, 1), -100)]) is None
    assert TR.xirr([(dt.date(2024, 1, 1), 100)]) is None
    assert TR.xirr([]) is None


def test_xirr_med_flere_innskudd():
    """Månedlig sparing: 12 × 1000 inn, 13 000 ut etter ett år → positiv IRR."""
    strommer = [(dt.date(2024, m, 1), -1000) for m in range(1, 13)]
    strommer.append((dt.date(2025, 1, 1), 13_000))
    r = TR.xirr(strommer)
    assert r is not None and r > 0
    # Snittkapitalen er bundet ca. et halvt år, så IRR er langt over 8,3 %
    assert 0.10 < r < 0.30


def test_pengevektet_skiller_seg_fra_kursutviklingen():
    """Kjøper mest rett før et fall → din avkastning er verre enn fondets."""
    kjop("2024-01-01", 1, 100)        # lite tidlig
    kjop("2024-11-01", 100, 150)      # mye rett før toppen
    r = TR.pengevektet_avkastning("AAPL", pris_naa=120, idag=dt.date(2025, 1, 1))
    assert r is not None and r < 0    # tungvekten kjøpte dyrt


def test_pengevektet_uten_transaksjoner_er_none():
    assert TR.pengevektet_avkastning("AAPL", pris_naa=100) is None


def test_pengevektet_etter_full_exit_bruker_bare_transaksjonene():
    kjop("2024-01-01", 10, 100)
    salg("2025-01-01", 10, 110)
    r = TR.pengevektet_avkastning("AAPL", pris_naa=999, idag=dt.date(2025, 6, 1))
    assert r == pytest.approx(0.10, abs=0.01)   # dagens pris er irrelevant


# ─── Skjermingsår (kobling mot skattekalkulatoren) ──────────────────────────

@pytest.mark.parametrize("kjopt, solgt, forventet", [
    ("2024-03-01", "2026-01-15", 2),   # eid ved 31.12.2024 og 31.12.2025
    ("2024-03-01", "2024-12-01", 0),   # kjøpt og solgt samme år
    ("2024-12-31", "2025-01-02", 1),   # eid nøyaktig ved ett årsskifte
    ("2024-01-01", "2024-12-31", 0),   # solgt PÅ 31.12 → ikke eid ved utgangen
    ("2020-06-01", "2025-06-01", 5),
])
def test_skjermingsar_teller_årsskifter(kjopt, solgt, forventet):
    assert TR.skjermingsar(dt.date.fromisoformat(kjopt),
                           dt.date.fromisoformat(solgt)) == forventet


def test_skjermingsar_er_ikke_det_samme_som_eiertid():
    """685 dager er 1 «år» på kalenderen, men gir skjerming for to årsskifter."""
    kjop("2024-03-01", 10, 100)
    salg("2026-01-15", 10, 150)
    r = TR.beregn_posisjon("AAPL")["realiserte_salg"][0]
    assert r["eiertid_ar"] == 1
    assert r["skjermingsar"] == 2
    assert r["skjerming_blandet"] is False


def test_skjermingsar_flagges_når_lots_spriker():
    kjop("2020-01-01", 10, 100)      # mange årsskifter
    kjop("2025-06-01", 10, 100)      # ingen ennå
    salg("2025-09-01", 20, 150)
    r = TR.beregn_posisjon("AAPL")["realiserte_salg"][0]
    assert r["skjerming_blandet"] is True
    assert 0 < r["skjermingsar"] < 5          # andelsvektet mellom lotene


def test_skjermingsar_ikke_blandet_når_lots_er_like():
    kjop("2020-01-01", 10, 100)
    kjop("2020-06-01", 10, 100)      # samme antall årsskifter fram til salget
    salg("2025-09-01", 20, 150)
    r = TR.beregn_posisjon("AAPL")["realiserte_salg"][0]
    assert r["skjerming_blandet"] is False
    assert r["skjermingsar"] == 5
