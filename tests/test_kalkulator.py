"""Tester for Monte Carlo-kalkulatoren og glidebanen.

Stokastisk kode testes på to måter her: deterministisk (vol = 0, der fasiten
kan regnes i lukket form) og på egenskaper som må holde uansett trekning.
"""

import math

import numpy as np
import pytest

from analyse.kalkulator import glidebane_vekter, monte_carlo


# ─── Glidebane ──────────────────────────────────────────────────────────────

def test_glidebane_har_riktig_lengde():
    assert len(glidebane_vekter(84, 1.0, 0.2, 5)) == 84


def test_glidebane_holder_startandelen_i_holdeperioden():
    v = glidebane_vekter(120, 1.0, 0.2, 5)      # 10 år, hold 5
    assert all(x == 1.0 for x in v[:60])
    assert v[60] < 1.0                          # nedtrappingen starter presis


def test_glidebane_har_nøyaktig_hold_aar_på_startandelen():
    """Regresjonsvakt: linspace tok med start-endepunktet og ga én måned for
    mye på startandelen (61 i stedet for 60 ved hold_aar=5)."""
    for hold_aar, forventet in [(1, 12), (5, 60), (9, 108)]:
        v = glidebane_vekter(120, 1.0, 0.2, hold_aar)
        assert sum(1 for x in v if x == 1.0) == forventet, f"hold_aar={hold_aar}"


def test_ren_lineær_bane_starter_på_startandelen():
    """Uten holdeperiode finnes ingen måned å duplisere — da skal banen spenne
    hele intervallet, og måned 1 ligger på startandelen."""
    v = glidebane_vekter(120, 1.0, 0.2, 0)
    assert v[0] == pytest.approx(1.0)
    assert sum(1 for x in v if x == 1.0) == 1


def test_glidebane_lander_på_sluttandelen():
    v = glidebane_vekter(120, 1.0, 0.2, 5)
    assert v[-1] == pytest.approx(0.2)


def test_glidebane_uten_hold_er_rent_lineær():
    v = glidebane_vekter(12, 1.0, 0.0, 0)
    assert v[0] == pytest.approx(1.0)
    assert v[-1] == pytest.approx(0.0)
    diff = np.diff(v)
    assert np.allclose(diff, diff[0])           # konstant stigningstall


def test_glidebane_faller_aldri_stigende():
    v = glidebane_vekter(120, 1.0, 0.2, 3)
    assert all(v[i] >= v[i + 1] - 1e-12 for i in range(len(v) - 1))


def test_hold_lengre_enn_horisonten_gir_flat_bane():
    v = glidebane_vekter(24, 0.8, 0.2, 10)      # hold 120 mnd > 24 mnd
    assert len(v) == 24
    assert all(x == 0.8 for x in v)


def test_glidebane_kan_gå_oppover():
    """Slutt høyere enn start skal også fungere — ingen antakelse om nedtrapping."""
    v = glidebane_vekter(24, 0.2, 0.8, 0)
    assert v[0] == pytest.approx(0.2)
    assert v[-1] == pytest.approx(0.8)


# ─── Monte Carlo: deterministisk (vol = 0) ──────────────────────────────────

def test_uten_volatilitet_treffer_lukket_form():
    """100 % aksjer, vol 0, ingen innskudd → ren renters rente."""
    n_mnd = 120
    vekter = np.ones(n_mnd)
    verdier, bane = monte_carlo(
        start=100_000, manedlig=0, n_mnd=n_mnd, vekter=vekter,
        aksje_cagr=0.07, aksje_vol=0.0, rente_cagr=0.0, rente_vol=0.0,
        n_sim=50,
    )
    forventet = 100_000 * (1.07 ** 10)
    assert verdier.mean() == pytest.approx(forventet, rel=1e-9)
    assert verdier.std() == pytest.approx(0, abs=1e-6)   # ingen spredning
    assert bane[-1] == pytest.approx(forventet, rel=1e-9)


def test_månedlige_innskudd_akkumuleres_riktig():
    """Vekst 0 og vol 0 → sluttverdi er nøyaktig sum av innskuddene."""
    n_mnd = 36
    verdier, _ = monte_carlo(
        start=10_000, manedlig=1_000, n_mnd=n_mnd, vekter=np.ones(n_mnd),
        aksje_cagr=0.0, aksje_vol=0.0, rente_cagr=0.0, rente_vol=0.0,
        n_sim=20,
    )
    assert verdier.mean() == pytest.approx(10_000 + 1_000 * 36)


def test_rentedelen_brukes_når_aksjevekten_er_null():
    n_mnd = 12
    verdier, _ = monte_carlo(
        start=100_000, manedlig=0, n_mnd=n_mnd, vekter=np.zeros(n_mnd),
        aksje_cagr=0.50, aksje_vol=0.0,      # skal ignoreres helt
        rente_cagr=0.04, rente_vol=0.0,
        n_sim=20,
    )
    assert verdier.mean() == pytest.approx(104_000, rel=1e-9)


def test_banen_starter_på_startkapitalen_og_har_riktig_lengde():
    n_mnd = 60
    _, bane = monte_carlo(50_000, 1_000, n_mnd, np.ones(n_mnd),
                          0.07, 0.15, 0.03, 0.01, n_sim=200)
    assert len(bane) == n_mnd + 1
    assert bane[0] == 50_000


# ─── Monte Carlo: egenskaper som må holde uansett trekning ──────────────────

def test_samme_seed_gir_samme_resultat():
    args = (100_000, 5_000, 60, np.ones(60), 0.08, 0.15, 0.04, 0.005)
    a, _ = monte_carlo(*args, n_sim=500, seed=42)
    b, _ = monte_carlo(*args, n_sim=500, seed=42)
    assert np.array_equal(a, b)


def test_ulik_seed_gir_ulikt_resultat():
    args = (100_000, 5_000, 60, np.ones(60), 0.08, 0.15, 0.04, 0.005)
    a, _ = monte_carlo(*args, n_sim=500, seed=1)
    b, _ = monte_carlo(*args, n_sim=500, seed=2)
    assert not np.array_equal(a, b)


def test_høyere_volatilitet_gir_bredere_fordeling():
    args = dict(start=100_000, manedlig=0, n_mnd=120, vekter=np.ones(120),
                rente_cagr=0.03, rente_vol=0.0, n_sim=3000)
    lav, _ = monte_carlo(aksje_cagr=0.07, aksje_vol=0.10, **args)
    høy, _ = monte_carlo(aksje_cagr=0.07, aksje_vol=0.25, **args)
    p5_lav, p95_lav = np.percentile(lav, [5, 95])
    p5_høy, p95_høy = np.percentile(høy, [5, 95])
    assert (p95_høy - p5_høy) > (p95_lav - p5_lav)


def test_stresstest_gir_lavere_utfall():
    args = dict(start=100_000, manedlig=2_000, n_mnd=60, vekter=np.ones(60),
                aksje_cagr=0.08, aksje_vol=0.15, rente_cagr=0.03,
                rente_vol=0.005, n_sim=2000)
    normal, _ = monte_carlo(sjokk=False, **args)
    krasj, _ = monte_carlo(sjokk=True, **args)
    assert np.median(krasj) < np.median(normal)


def test_stresstest_trekker_ned_omtrent_25_prosent():
    """Sjokket er definert som samlet −25 % fordelt på siste seks måneder."""
    n_mnd = 24
    felles = dict(start=100_000, manedlig=0, n_mnd=n_mnd, vekter=np.ones(n_mnd),
                  aksje_cagr=0.0, aksje_vol=0.0, rente_cagr=0.0, rente_vol=0.0,
                  n_sim=10)
    uten, _ = monte_carlo(sjokk=False, **felles)
    med, _ = monte_carlo(sjokk=True, **felles)
    assert med.mean() / uten.mean() == pytest.approx(0.75, rel=1e-9)


def test_cagr_tolkes_som_median_ikke_gjennomsnitt():
    """mu = log(1+cagr) betyr at MEDIAN vekst treffer CAGR; snittet ligger over."""
    n_mnd = 120
    verdier, _ = monte_carlo(100_000, 0, n_mnd, np.ones(n_mnd),
                             aksje_cagr=0.07, aksje_vol=0.20,
                             rente_cagr=0.0, rente_vol=0.0, n_sim=40_000)
    forventet_median = 100_000 * (1.07 ** 10)
    assert np.median(verdier) == pytest.approx(forventet_median, rel=0.03)
    assert verdier.mean() > np.median(verdier)


def test_ingen_negative_sluttverdier():
    """Log-normal modell kan ikke gi negativ formue."""
    verdier, _ = monte_carlo(10_000, 500, 120, np.ones(120),
                             0.08, 0.40, 0.03, 0.01, n_sim=5000)
    assert (verdier > 0).all()


def test_null_start_og_kun_sparing_fungerer():
    n_mnd = 12
    verdier, bane = monte_carlo(0, 1_000, n_mnd, np.ones(n_mnd),
                                0.0, 0.0, 0.0, 0.0, n_sim=10)
    assert bane[0] == 0
    assert verdier.mean() == pytest.approx(12_000)


def test_glidebane_og_monte_carlo_henger_sammen():
    """Vektene fra glidebane_vekter skal kunne mates rett inn i simuleringen."""
    ar = 7
    n_mnd = ar * 12
    vekter = glidebane_vekter(n_mnd, 1.0, 0.2, ar - 2)
    verdier, bane = monte_carlo(120_000, 6_000, n_mnd, vekter,
                                0.08, 0.127, 0.04, 0.005, n_sim=1000)
    assert len(bane) == n_mnd + 1
    assert len(verdier) == 1000
    assert math.isfinite(float(np.median(verdier)))
