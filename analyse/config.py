"""Konfigurasjon: instrumentlister, perioder, nyhetskilder og benchmark-data."""

import os


# ─── Standard-instrumenter ──────────────────────────────────────────────────
#
# Disse er kun eksempler — universelt gjenkjennelige tickere som hjelper nye
# brukere komme i gang. Personlige fond/aksjer skal IKKE inn her; bruk
# "Mine instrumenter"-fanen i UI for å legge til egne, som lagres i
# bruker_instrumenter.json (gitignored).

STANDARD_AKSJER = [
    {"ticker": "AAPL", "navn": "Apple",     "type": "aksje", "sektor": "Teknologi", "flagg": "🇺🇸", "søkeord": ["Apple"]},
    {"ticker": "MSFT", "navn": "Microsoft", "type": "aksje", "sektor": "Teknologi", "flagg": "🇺🇸", "søkeord": ["Microsoft"]},
]

STANDARD_FOND = [
    {"ticker": "SPY",     "navn": "S&P 500 ETF (SPY)",        "type": "fond", "sektor": "USA Indeks",    "flagg": "🇺🇸", "søkeord": ["S&P 500", "S&P500"]},
    {"ticker": "IWDA.AS", "navn": "iShares MSCI World ETF",   "type": "fond", "sektor": "Global Indeks", "flagg": "🌍", "søkeord": ["MSCI World"]},
]

# Tom default — brukere velger selv hvilke instrumenter som er i porteføljen.
STANDARD_PORTEFOLJE_TICKERS = []


# ─── Periode-mapping fra UI til yfinance ────────────────────────────────────

PERIODER = {
    "1M": "1mo",
    "3M": "3mo",
    "6M": "6mo",
    "1Y": "1y",
    "3Y": "3y",
    "5Y": "5y",
}


# ─── Risiko & benchmark ─────────────────────────────────────────────────────

# Risikofri rente brukt i Sharpe-beregning. ~2% er en forsiktig USD-T-bill /
# norsk styringsrente-approksimasjon i 2026; juster om makro-bildet endrer seg.
RISIKOFRI_RENTE = 0.02

# Standard benchmark for bench-relativ avkastning. URTH = iShares MSCI World ETF.
DEFAULT_BENCH = "URTH"


# ─── Skatt (aksjonærmodellen, privatperson utenfor ASK) ─────────────────────
#
# Gevinst på aksjer/aksjefond beskattes etter aksjonærmodellen: skattepliktig
# gevinst oppjusteres med en faktor før alminnelig skattesats. Effektiv sats
# = SKATTESATS × OPPJUSTERINGSFAKTOR. For 2024–2026: 0,22 × 1,72 = 37,84 %.
# Skjermingsfradrag skjermer en del av gevinsten/utbyttet mot skatt.
# Verdiene fastsettes årlig — sjekk Skatteetaten hvis tallene endres.

SKATTESATS = 0.22              # Alminnelig inntekt
OPPJUSTERINGSFAKTOR = 1.72     # Oppjustering av aksjeinntekt (2024–2026)

# Skjermingsrenten fastsettes i etterkant av hvert inntektsår av Skatteetaten
# (i januar året etter). Default brukt i kalkulatoren når brukeren ikke oppgir
# egen sats. Offisielle satser: 2024 = 3,9 %, 2025 = 3,6 %.
SKJERMINGSRENTE_DEFAULT = 0.036    # Inntektsåret 2025


# ─── Nyhetskilder ───────────────────────────────────────────────────────────

# VADER er trent på engelsk, så norske scores er grove og reagerer mest på
# volum/polarisert språk.
RSS_KILDER = [
    ("E24", "https://e24.no/rss"),
]


# ─── Markedstermometer ──────────────────────────────────────────────────────

# Indekser, frykt-indeks, valuta og råvarer som påvirker norske og globale
# porteføljer. VIX-nivåer tolkes som rolig (<15) / normal / uro (>25) — det
# er en pragmatisk konsensus-grense.
MARKED_TICKERS = [
    {"ticker": "^GSPC",    "navn": "S&P 500",      "kategori": "Aksjer"},
    {"ticker": "^IXIC",    "navn": "Nasdaq",       "kategori": "Aksjer"},
    {"ticker": "^OSEAX",   "navn": "Oslo Børs",    "kategori": "Aksjer"},
    {"ticker": "^VIX",     "navn": "VIX (frykt)",  "kategori": "Volatilitet"},
    {"ticker": "USDNOK=X", "navn": "USD/NOK",      "kategori": "Valuta"},
    {"ticker": "EURNOK=X", "navn": "EUR/NOK",      "kategori": "Valuta"},
    {"ticker": "BZ=F",     "navn": "Brent Olje",   "kategori": "Råvarer"},
]


# ─── Fil-stier ──────────────────────────────────────────────────────────────
#
# Brukerspesifikke filer ligger under `data/` (gitignored). Hele katalogen
# bind-mountes i Docker — enkeltfil-mounts blokkerer atomic rename på Mac.

_PROSJEKT_ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_KATALOG  = os.environ.get("DATA_KATALOG") or os.path.join(_PROSJEKT_ROT, "data")
os.makedirs(DATA_KATALOG, exist_ok=True)

BEHOLDNING_FIL          = os.path.join(DATA_KATALOG, "beholdning.json")
BRUKER_INSTRUMENTER_FIL = os.path.join(DATA_KATALOG, "bruker_instrumenter.json")
BRUKER_PORTEFOLJE_FIL   = os.path.join(DATA_KATALOG, "bruker_portefolje.json")
