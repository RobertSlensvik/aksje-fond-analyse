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

# Terskler for hvor mye historikk et risikotall bør bygge på før det er verdt å
# stole på. En full markedssyklus regnes gjerne som 7–10 år; under det mangler
# vinduet typisk et ordentlig fall. Norske fond på Yahoo (0P…-tickere) har ofte
# bare 3–4 år, og da blir volatilitet og drawdown systematisk undervurdert.
DATAVINDU_KORT_AR        = 10.0
DATAVINDU_SVAERT_KORT_AR = 3.0


# ─── Skatt (aksjonærmodellen, privatperson utenfor ASK) ─────────────────────
#
# Gevinst på aksjer/aksjefond beskattes etter aksjonærmodellen: skattepliktig
# gevinst oppjusteres med en faktor før alminnelig skattesats. Effektiv sats
# = SKATTESATS × OPPJUSTERINGSFAKTOR. For 2024–2026: 0,22 × 1,72 = 37,84 %.
# Skjermingsfradrag skjermer en del av gevinsten/utbyttet mot skatt.
# Verdiene fastsettes årlig — sjekk Skatteetaten hvis tallene endres.

SKATTESATS = 0.22              # Alminnelig inntekt
OPPJUSTERINGSFAKTOR = 1.72     # Oppjustering av aksjeinntekt (2024–2026)

# Offisielle skjermingsrenter for AKSJER, per inntektsår. Hentet fra
# Skatteetaten: https://www.skatteetaten.no/satser/skjermingsrente-for-aksjer-og-enkeltpersonforetak/
#
# NB: Skatteetaten publiserer to satser per år. Tallene her er satsen for
# personlige aksjonærer og deltakere i ansvarlig selskap — IKKE «maksimal
# skjermingsrente for enkeltpersonforetak», som er høyere (2024: 4,9 % mot
# 3,9 %). Bland dem ikke.
#
# Renten fastsettes i januar året etter inntektsåret, så inneværende år mangler
# alltid. Skatteetatens årsvelger går tilbake til 2007.
SKJERMINGSRENTER = {
    2007: 0.033, 2008: 0.038, 2009: 0.013, 2010: 0.016, 2011: 0.015,
    2012: 0.011, 2013: 0.011, 2014: 0.009, 2015: 0.006, 2016: 0.004,
    2017: 0.007, 2018: 0.008, 2019: 0.013, 2020: 0.006, 2021: 0.005,
    2022: 0.017, 2023: 0.032, 2024: 0.039, 2025: 0.036,
}

# Brukt for år uten offisiell sats (inneværende år, og før 2007). Settes til
# siste kjente sats — en bedre gjetning enn null, men fortsatt en gjetning.
SISTE_KJENTE_SKJERMINGSAR = max(SKJERMINGSRENTER)
SKJERMINGSRENTE_DEFAULT   = SKJERMINGSRENTER[SISTE_KJENTE_SKJERMINGSAR]


# ─── Nyhetskilder ───────────────────────────────────────────────────────────

# VADER er trent på engelsk, så norske scores er grove og reagerer mest på
# volum/polarisert språk.
#
# Redaksjonelle feeder som hentes i sin helhet og matches mot instrumentenes
# søkeord. Norske kilder navngir norske selskaper; de engelske er tatt med
# fordi VADER er trent på engelsk og scorer dem langt mer presist.
#
# Finansavisen, Hegnar og Kapital er bevisst utelatt — RSS-endepunktene deres
# ligger bak Zephr-paywall og svarer 404 etter redirect.

RSS_KILDER = [
    # Norske
    ("E24",           "https://e24.no/rss"),
    ("DN Børs",       "https://services.dn.no/api/feed/rss/bors"),
    ("DN",            "https://services.dn.no/api/feed/rss/"),
    ("NRK",           "https://www.nrk.no/norge/toppsaker.rss"),
    # Engelske
    ("CNBC Markets",  "https://www.cnbc.com/id/20910258/device/rss/rss.html"),
    ("CNBC Finance",  "https://www.cnbc.com/id/10000664/device/rss/rss.html"),
    ("MarketWatch",   "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
    ("Yahoo Finance", "https://finance.yahoo.com/news/rssindex"),
    ("Investing.com", "https://www.investing.com/rss/news_25.rss"),
]

# ─── Google News-søk per instrument ─────────────────────────────────────────
#
# De redaksjonelle feedene over er rullerende vinduer på 10–40 saker, så
# navngitte fond dukker nesten aldri opp i dem. Google News søker derimot på
# instrumentets egne søkeord og finner treff måneder tilbake — det er den
# eneste kilden som gir dekning for norske fond. Sakene er allerede filtrert
# av søket, så de slipper søkeord-matchingen de andre kildene går gjennom.

GOOGLE_NEWS_AKTIV = True
GOOGLE_NEWS_URL   = "https://news.google.com/rss/search?q={q}&hl={hl}&gl={gl}&ceid={gl}:{hl}"

# Flagg → (språk, land) for Google News-lokale.
# Norske instrumenter søker på norsk, alt annet på engelsk — VADER er trent på
# engelsk, så internasjonal dekning scores uansett mer presist på engelsk.
GOOGLE_NEWS_LOKALE: dict[str, tuple[str, str]] = {
    "🇳🇴": ("no", "NO"),
}
GOOGLE_NEWS_LOKALE_DEFAULT = ("en", "US")

# Per søkeord. Sakene loggføres i sin helhet, men bare de ferskeste vises i
# Nyheter-fanen — ellers ville måneder gamle treff dratt dagens sentiment.
GOOGLE_NEWS_MAKS = 15


# ─── Treffsikkerhet (sentiment vs. faktisk kursutvikling) ───────────────────
#
# Hver nyhetssak logges med sentiment-score, og kursen etterpå måles for å se
# om "positiv nyhet" faktisk ga oppgang. Horisontene er antall handelsdager
# etter siste sluttkurs FØR saken ble publisert — 1 dag fanger den umiddelbare
# reaksjonen, 5 dager om bevegelsen holdt seg.

TREFF_HORISONTER = [1, 3, 5]
TREFF_HORISONT_DEFAULT = 3

# Bevegelser mindre enn dette regnes som "flat" og teller verken som treff
# eller bom — daglig støy på ±0,3 % sier ingenting om nyheten traff.
TREFF_TERSKEL_PCT = 0.3

# Loggen beskjæres for å ikke vokse i det uendelige.
NYHETSLOGG_MAKS_DAGER      = 365
NYHETSLOGG_MAKS_PER_TICKER = 400


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
NYHETSLOGG_FIL          = os.path.join(DATA_KATALOG, "nyhetslogg.json")
TRANSAKSJONER_FIL       = os.path.join(DATA_KATALOG, "transaksjoner.json")
