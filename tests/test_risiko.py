"""Tester for risikomål og datavindu-vurderingen.

Prisseriene er syntetiske, så fasiten er kjent. Poenget med `vurder_datavindu`
er at et tall som bygger på fire år ikke skal presenteres som om det bygger på
tjue — testene her fester terskelene.
"""

import math

import numpy as np
import pandas as pd
import pytest

from analyse.config import DATAVINDU_KORT_AR, DATAVINDU_SVAERT_KORT_AR
from analyse.risiko import beregn_risiko, vurder_datavindu


def serie(verdier, start="2020-01-01"):
    """Prisserie med daglig frekvens (kalenderdager holder for testformål)."""
    idx = pd.date_range(start=start, periods=len(verdier), freq="D")
    return pd.Series(verdier, index=idx)


# ─── Datavindu-vurdering ────────────────────────────────────────────────────

@pytest.mark.parametrize("ar, forventet", [
    (0.5, "svært kort"),
    (2.99, "svært kort"),
    (3.0, "kort"),
    (4.4, "kort"),
    (9.99, "kort"),
    (10.0, "ok"),
    (25.0, "ok"),
])
def test_nivå_følger_tersklene(ar, forventet):
    assert vurder_datavindu(ar, int(ar * 252))["niva"] == forventet


def test_tersklene_er_de_som_er_konfigurert():
    """Nivåene skal følge config, ikke hardkodede tall i funksjonen."""
    assert vurder_datavindu(DATAVINDU_SVAERT_KORT_AR - 0.01, 100)["niva"] == "svært kort"
    assert vurder_datavindu(DATAVINDU_SVAERT_KORT_AR, 100)["niva"] == "kort"
    assert vurder_datavindu(DATAVINDU_KORT_AR - 0.01, 100)["niva"] == "kort"
    assert vurder_datavindu(DATAVINDU_KORT_AR, 100)["niva"] == "ok"


def test_datavindu_tar_med_datoene():
    p = vurder_datavindu(4.4, 1030, fra="2022-03-07", til="2026-08-05")
    assert p["fra"] == "2022-03-07"
    assert p["til"] == "2026-08-05"
    assert p["handelsdager"] == 1030
    assert p["ar"] == 4.4


def test_kort_vindu_nevner_hva_som_mangler():
    m = vurder_datavindu(4.4, 1030)["merknad"]
    assert "2008" in m and "2020" in m
    assert "undervurdert" in m


def test_datavindu_uten_år_er_none():
    assert vurder_datavindu(None, 0) is None


# ─── beregn_risiko ──────────────────────────────────────────────────────────

def test_for_kort_serie_gir_none():
    assert beregn_risiko(serie([100, 101, 102])) is None


def test_konstant_serie_har_null_volatilitet_og_drawdown():
    r = beregn_risiko(serie([100.0] * 400))
    assert r["vol_pct"] == 0
    assert r["max_drawdown_pct"] == 0
    assert r["cagr_pct"] == pytest.approx(0, abs=0.01)
    assert r["sharpe"] is None          # vol = 0 → udefinert, ikke uendelig


def test_drawdown_måles_fra_toppen():
    # Opp til 120, ned til 90 → maks drawdown = 90/120 − 1 = −25 %
    verdier = list(np.linspace(100, 120, 200)) + list(np.linspace(120, 90, 200))
    r = beregn_risiko(serie(verdier))
    assert r["max_drawdown_pct"] == pytest.approx(-25.0, abs=0.1)


def test_drawdown_serie_følger_prisene():
    r = beregn_risiko(serie([100.0] * 400))
    assert len(r["drawdown_serie"]) == 400
    assert len(r["drawdown_datoer"]) == 400
    assert all(x == 0 for x in r["drawdown_serie"])


def test_tid_i_drawdown_teller_dager_under_forrige_topp():
    # 100 dager opp, så 100 dager under toppen
    verdier = [100 + i for i in range(100)] + [150] * 100
    r = beregn_risiko(serie(verdier))
    assert r["tid_i_dd_dager"] == 100      # de 100 dagene på 150 < toppen 199


def test_cagr_stemmer_med_lukket_form():
    """Dobling over nøyaktig to år → CAGR = √2 − 1 ≈ 41,42 %."""
    n = 731                                 # 2020-01-01 → 2021-12-31, to år
    verdier = [100 * (2 ** (i / (n - 1))) for i in range(n)]
    r = beregn_risiko(serie(verdier))
    assert r["cagr_pct"] == pytest.approx((math.sqrt(2) - 1) * 100, abs=0.5)
    assert r["total_avk_pct"] == pytest.approx(100.0, abs=0.5)


def test_risiko_rapporterer_datavinduet():
    r = beregn_risiko(serie([100.0] * 400, start="2022-03-07"))
    p = r["periode"]
    assert p is not None
    assert p["fra"] == "2022-03-07"
    assert p["handelsdager"] == 400
    assert p["ar"] == pytest.approx(1.1, abs=0.1)
    assert p["niva"] == "svært kort"


def test_langt_vindu_flagges_som_ok():
    r = beregn_risiko(serie([100.0] * 4200))       # ~11,5 år kalenderdager
    assert r["periode"]["niva"] == "ok"


def test_nan_verdier_filtreres_bort():
    verdier = [100.0, float("nan"), 102.0, 103.0, float("nan"), 105.0, 106.0, 107.0]
    r = beregn_risiko(serie(verdier))
    assert r is not None
    assert r["periode"]["handelsdager"] == 6       # kun de gyldige


def test_for_få_gyldige_punkter_etter_dropna_gir_none():
    """Grensen på 5 punkter gjelder ETTER at NaN er fjernet."""
    verdier = [100.0, float("nan"), 102.0, 103.0, float("nan"), 105.0]
    assert beregn_risiko(serie(verdier)) is None   # 4 gyldige < 5
