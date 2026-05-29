"""Monte Carlo for spareplaner med konfigurerbar aksje/rente-glidebane."""

import math

import numpy as np


def glidebane_vekter(n_mnd, start_aksje, slutt_aksje, hold_aar):
    """Bygg månedlige aksjevekter for en glidebane.

    Aksjevekt holdes på `start_aksje` i `hold_aar` år, deretter lineær reduksjon
    til `slutt_aksje` over resterende måneder. `hold_aar=0` gir ren lineær glidebane.
    """
    hold_mnd = max(0, min(int(hold_aar * 12), n_mnd))
    resten = n_mnd - hold_mnd
    hode = np.full(hold_mnd, start_aksje, dtype=np.float64)
    if resten > 0:
        hale = np.linspace(start_aksje, slutt_aksje, resten)
        return np.concatenate([hode, hale])
    return hode


def monte_carlo(start, manedlig, n_mnd, vekter,
                aksje_cagr, aksje_vol, rente_cagr, rente_vol,
                sjokk=False, n_sim=20_000, seed=42):
    """Kjør Monte Carlo for en blandet aksje/rente-portefølje over `n_mnd` måneder.

    Returnerer (sluttverdier, median_bane) der median_bane har lengde n_mnd+1
    (start-verdien er først).

    `sjokk=True` påtvinger en samlet -25% i siste 6 måneder (for stress-test).
    """
    mu_a = math.log(1 + aksje_cagr) / 12
    sig_a = aksje_vol / math.sqrt(12)
    mu_r = math.log(1 + rente_cagr) / 12
    sig_r = rente_vol / math.sqrt(12)

    rng = np.random.default_rng(seed=seed)
    aksje_g = np.exp(rng.normal(mu_a, sig_a, size=(n_sim, n_mnd)))
    rente_g = np.exp(rng.normal(mu_r, sig_r, size=(n_sim, n_mnd)))

    if sjokk:
        krasj_lengde = min(6, n_mnd)
        krasj_pr_mnd = (1 - 0.25) ** (1 / krasj_lengde)
        for m in range(n_mnd - krasj_lengde, n_mnd):
            aksje_g[:, m] = krasj_pr_mnd

    verdier = np.full(n_sim, start, dtype=np.float64)
    median_bane = np.empty(n_mnd + 1)
    median_bane[0] = start
    for m in range(n_mnd):
        v = vekter[m]
        blandet = v * aksje_g[:, m] + (1 - v) * rente_g[:, m]
        verdier = verdier * blandet + manedlig
        median_bane[m + 1] = float(np.median(verdier))

    return verdier, median_bane
