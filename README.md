# 📈 Aksje & Fond Analyse

> Lokal web-app for å analysere norske og internasjonale aksjer/fond — med risikomål, Monte Carlo-prognose, sentiment-analyse og porteføljekalkulator.

[![Python](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Flask](https://img.shields.io/badge/flask-3.x-lightgrey.svg)](https://flask.palletsprojects.com/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

---

## Hva er dette?

Et personlig analyseverktøy for **din egen portefølje**. Legg til de aksjene og fondene
du faktisk eier (eller vurderer å eie) og få:

1. **Risikoanalyse** — utover bare CAGR. Hvor mye kan du tape? Hvor korrelerte er fondene dine? Slår de benchmark?
2. **Monte Carlo-spareplan** — "kan jeg nå målet mitt med dagens sparing, eller må jeg justere?"
3. **Markedstemperatur og nyhetsbilde** uten å bytte mellom 5 ulike apper.

Bygget som lokal Flask-app fordi dine tall skal være dine — ingen lock-in, ingen kontodata til skyen.
Standard-katalogen i repoet inneholder kun universelle eksempler (Apple, Microsoft, SPY, MSCI World).
Egne instrumenter legger du til via **⚙️ Mine instrumenter**-fanen, og de lagres lokalt i
`bruker_instrumenter.json` (gitignored — ender ikke på GitHub).

## Highlights

- **Risikomål** — Sharpe-ratio, maks drawdown, volatilitet, bench-relativ avkastning mot MSCI World
- **Monte Carlo-kalkulator** med konfigurerbar glidebane (aksjer → renter over tid) for å modellere konkrete spareplaner
- **Korrelasjonsmatrise** på tvers av porteføljen — viser faktisk diversifisering, ikke bare antall fond
- **Sentiment-prognose** fra E24 + Yahoo Finance via VADER NLP
- **Markedstermometer** med VIX-tolkning, valuta, indekser og råvarer
- **Investeringsprognose** — log-normal Monte Carlo med p5/median/p95
- **Parallellisert datahenting** med TTL-cache → hele porteføljen på et par sekunder cold, millisekunder warm

## Tech stack

| Lag | Teknologi | Hvorfor |
|---|---|---|
| Backend | Python 3.9+, Flask 3 | Lett, kjente verktøy, ingen overhead |
| Data | yfinance, feedparser | Gratis markeds- og nyhetsdata |
| Statistikk | NumPy, Pandas | Vektorisert Monte Carlo (~20 000 simuleringer/sekund) |
| NLP | vaderSentiment | Rask, regelbasert sentiment-scoring |
| Frontend | Vanilla JS + Chart.js 4 | Ingen build-step, full kontroll |
| Caching | In-process TTL (info 5 min, history 15 min) | Reduserer Yahoo-rate-limit-risiko |
| Concurrency | `ThreadPoolExecutor` | Parallell datainnhenting på tvers av tickere |

## Skjermbilder

> 📸 **TODO:** Erstatt med ekte screenshots etter første kjøring.

```
docs/screenshots/
  portefolje.png       — Min portefølje med korrelasjonsmatrise
  detalj.png           — Detalj-visning med risiko-panel og drawdown-graf
  kalkulator.png       — Spare-kalkulator med glidebane og histogram
  nyheter.png          — Sentiment-analyse fra E24 + Yahoo
  marked.png           — Markedstermometer-bånd
```

## Kom i gang

### Krav
- Python 3.9 eller nyere
- Internettforbindelse (henter live data fra Yahoo Finance)

### Installasjon

**Mac / Linux:**
```bash
chmod +x start.sh
./start.sh
```

**Windows:** dobbeltklikk `start.bat`

**Manuelt:**
```bash
python -m venv venv
source venv/bin/activate    # Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

**Docker (anbefalt for kontinuerlig drift):**
```bash
cp .env.example .env     # sett UID/GID til `id -u` / `id -g` på Linux
docker compose up -d --build
```

To tjenester starter: webappen (gunicorn) og en bakgrunnsjobb som fyller
nyhetsloggen hver 4. time. Loggen er det eneste i appen som akkumulerer verdi
over tid — feedene er rullerende vinduer, så saker som ikke fanges forsvinner.

**Kjører du på Ubuntu, les [DEPLOY.md](DEPLOY.md)** — den dekker `UID`/`GID` mot
bind-mountet `data/` (den klassiske Linux-fella), tidssone, og at appen ikke har
autentisering.

Hentejobben kan også kjøres uten Docker, f.eks. fra cron eller systemd:
```bash
python -m analyse.hent              # én runde
python -m analyse.hent --loop 4h    # evig løkke
```

`data/`-mappen opprettes automatisk og bind-mountes inn i containeren —
personlige filer (beholdning, brukerinstrumenter, porteføljevalg) persisteres på tvers av container-restarts.

Åpne nettleseren på **http://localhost:5001**.

## Funksjoner

Appen har sju hovedfaner. To av dem samler flere verktøy under undertabs:
**Min portefølje** (Beholdning · Transaksjoner · Månedsrapport) og
**Kalkulator** (Sparemål · Prognose · Skatt).

> **Datavindu:** alle risikotall viser nå hvilken periode de bygger på, og advarer
> når historikken er kortere enn en full markedssyklus. Norske fond på Yahoo
> (`0P…`-tickere) har typisk bare 3–4 år, og da er volatilitet og drawdown
> systematisk undervurdert.

### 💼 Min portefølje → Beholdning
- Sparkline-graf per fond (1Y)
- Beholdnings-input (andeler + snittpris) lagret atomisk i `beholdning.json`
- Total verdi + gevinst på tvers
- **Korrelasjonsmatrise** med fargekodet heatmap og automatisk tolkning av snitt-korrelasjon
- Topp nyheter med sentiment-score per fond

> **Om avkastningstallene:** yfinance leverer utbyttejusterte sluttkurser
> (`auto_adjust=True` er default fra og med 0.2.51), så all avkastning i appen er
> **totalavkastning** — reinvestert utbytte og splitter er med. Målt på AAPL over to år
> utgjør utbyttet 1,29 prosentpoeng; for utbyttefond er avviket større.

### 💼 Min portefølje → Transaksjoner
- Registrer kjøp og salg; kostpris, beholdning og gevinst utledes automatisk
- **FIFO** (først inn, først ut) som norske skatteregler krever — salg spiser eldste lot først, og hvert salg får riktig inngangsverdi og eiertid
- Kjøpsgebyr inngår i inngangsverdien, salgsgebyr trekkes fra salgssummen
- **Pengevektet avkastning (XIRR)** per instrument — hva *du* har tjent, ikke hva fondet gjorde. Med månedlig sparing er de to sjelden like
- Skiller realisert og urealisert gevinst, summert per valuta
- **Beregn skatt direkte fra et realisert salg** — én knapp fyller inngangsverdi, salgssum og eierår inn i skattekalkulatoren, med en notis om hvor tallene kom fra. Eierår er antall *årsskifter* andelene var eid (det er 31.12-datoene som gir skjermingsfradrag), ikke antall 365-dagersperioder
- Lagres i `data/transaksjoner.json`. Additivt: har et instrument transaksjoner brukes de utledede tallene, ellers gjelder manuelt registrert beholdning som før

### 💼 Min portefølje → Månedsrapport
- Hvordan porteføljen gikk forrige kalendermåned — per instrument og totalt
- Vektet etter beholdning (markedsverdi) med kronebeløp, eller lik vekt i prosent
- Beste/svakeste instrument i måneden
- Graf over porteføljens utvikling de siste 30 dagene

### 📊 Oversikt
- Alle instrumentene dine (norske + internasjonale) lastes parallelt
- Filter: alle / aksjer / fond/ETF
- Kort med pris, dagsendring, markedsverdi, P/E, utbytte

### 📰 Nyheter & sentiment-prognose
- Aggregerer nyhetsoverskrifter fra ni RSS-kilder + Yahoo Finance per instrument
  - **Norske:** E24, DN, DN Børs, NRK
  - **Engelske:** CNBC Markets, CNBC Finance, MarketWatch, Yahoo Finance, Investing.com
  - **Google News-søk per instrument** — søker på instrumentets egne søkeord og finner treff måneder tilbake. Eneste kilde som gir dekning for norske fond, og den når overskrifter fra Finansavisen og finanswatch som ikke har åpen RSS
- Finansavisen, Hegnar og Kapital er utelatt som faste kilder — RSS-endepunktene ligger bak Zephr-paywall (404 etter redirect)
- VADER-sentiment scorer hver sak til positiv/nøytral/negativ
- Hete saker (siste 7 dager) markert
- "Topp 3 hete" — instrumenter med mest nyhetsstøy rangert etter ferskhet og intensitet

### 🎯 Treffsikkerhet — traff nyhetene?
- Hver nyhetssak lagres permanent i `data/nyhetslogg.json` med sentiment-etiketten sin, siden feedene bare rekker noen dager bakover
- Måler faktisk kursbevegelse fra siste sluttkurs **før** saken til sluttkurs 1, 3 eller 5 handelsdager etter
- **Treff** = positiv sak → kursen opp, eller negativ sak → kursen ned. Bevegelser under ±0,3 % regnes som flat og teller ikke
- Snitt kursendring etter positive vs. negative saker, og differansen mellom dem i prosentpoeng
- Per instrument + samlet fasit, med saksliste som viser hva som traff og hva som bommet
- Loggen fylles automatisk hver gang nyheter hentes — datagrunnlaget bygges opp over tid

> **Om språk og signal:** VADER er trent på engelsk. Målt på egen logg gir engelske kilder
> et retningssignal (positiv/negativ) i 70 % av sakene, norske i bare 5 % — resten scores
> nøytralt og teller ikke i treffsikkerheten. Norske kilder øker altså dekningen langt mer
> enn de øker antallet avgjorte saker.

### ⚖️ Sammenlign
- Normaliserer kursutvikling til 100 ved startdato
- Side-om-side opp til 6 instrumenter
- Periode 1M til 5Y

### 🧮 Kalkulator → Sparemål (glidebane)
- Live Monte Carlo (20 000 simuleringer) med slidere
- Aksjer/renter-mix konfigurerbart over tid
- Stresstest: påtving 25% krasj siste 6 mnd
- Sannsynlighet for å nå mål (100%, 80%, 50%)
- Median-bane, aksjeandel-utvikling og fordeling av sluttverdier

### 🧮 Kalkulator → Prognose
- Monte Carlo med log-normal månedlig avkastning
- Engangsinnskudd + valgfri månedlig sparing
- Persentiler: 5 (pessimistisk), 50 (forventet), 95 (optimistisk)
- 1, 3, 5 og 10 år
- `?seed=random` for ny simulering hver gang (default deterministisk)

### 🧮 Kalkulator → Skatt
- To modeller: **vanlig konto** (aksjonærmodellen) og **aksjesparekonto (ASK)**
- **Offisiell skjermingsrente per inntektsår** (2007–2025) hentet fra [Skatteetaten](https://www.skatteetaten.no/satser/skjermingsrente-for-aksjer-og-enkeltpersonforetak/). Satsen har variert fra 0,4 % (2016) til 3,9 % (2024), så én felles sats over flere eierår gir merkbart avvik. Kommer tallene fra et realisert salg, brukes riktig sats for hvert år automatisk og oppdelingen vises i en tabell
- Realisert gevinst/tap, skjermingsfradrag (renters rente på kostprisen) eller oppgi akkumulert skjerming direkte
- ASK: skattefritt uttak av innskudd, skatt kun på gevinst over innskudd, hele/delvise uttak
- Oppjustering (×1,72) og 22 % skatt → effektiv sats 37,84 %
- Full mellomregning, netto utbetalt og effektiv sats på faktisk gevinst

### 🌡️ Markedstermometer
- S&P 500, Nasdaq, Oslo Børs, VIX, USD/NOK, EUR/NOK, Brent
- VIX-tolkning: rolig (<15) / normal / uro (>25)

### 🤖 AI-assistent (valgfri)
- Chat-boble nederst til høyre som svarer på spørsmål om porteføljen din
- Drevet av Claude API, med porteføljekonteksten din (rapport, beholdning) som grunnlag
- **Av som standard** — gjør ingen API-kall og koster ingenting før du legger inn en nøkkel
- Aktiveres ved å sette `ANTHROPIC_API_KEY` i en `.env`-fil (se [`.env.example`](.env.example)). `.env` er gitignored — nøkkelen havner aldri på GitHub.

## API-referanse

| Endpoint | Metode | Beskrivelse |
|---|---|---|
| `/api/oversikt` | GET | Parallell hurtiginfo for alle instrumenter |
| `/api/detalj/<ticker>` | GET | Detaljert info for ett instrument |
| `/api/historikk/<ticker>/<periode>` | GET | OHLCV-historikk for chart |
| `/api/sammenlign/<tickers>/<periode>` | GET | Normalisert sammenligning |
| `/api/prognose/<ticker>/<belop>/<manedlig>` | GET | Monte Carlo investerings-prognose |
| `/api/risiko/<ticker>/<periode>` | GET | Sharpe, drawdown, vol, bench-relativ |
| `/api/korrelasjon` | GET | Korrelasjonsmatrise (default = portefølje) |
| `/api/marked` | GET | Markedstermometer (indekser, VIX, valuta, råvarer) |
| `/api/nyheter` | GET | Sentiment-analyse for alle instrumenter |
| `/api/transaksjoner` | GET/POST | Les alle, eller registrer én. Body: `{ticker, type, dato, antall, kurs, gebyr?}` |
| `/api/transaksjoner/<ticker>/<id>` | DELETE | Slett én transaksjon |
| `/api/skjermingsrenter` | GET | Offisielle skjermingsrenter per inntektsår |
| `/api/posisjoner` | GET | Utledet beholdning per ticker: FIFO-kostpris, realisert/urealisert gevinst, XIRR |
| `/api/treffsikkerhet` | GET | Sentiment vs. faktisk kurs. `?horisont=1\|3\|5`, `?terskel=0.3`, `?tickere=A,B`, `?oppdater=1` |
| `/api/portefolje` | GET | Min portefølje med 1Y historikk og nyheter |
| `/api/rapport` | GET | Månedsrapport: forrige måned + 30-dagers utvikling |
| `/api/chat/status` | GET | Om AI-assistenten er aktivert (API-nøkkel satt) |
| `/api/chat` | POST | Send samtale til Claude (krever `ANTHROPIC_API_KEY`) |
| `/api/portefolje-stats` | GET | Historisk vol og CAGR (lik vekt) |
| `/api/kalkulator` | POST | Konfigurerbar Monte Carlo med glidebane |
| `/api/skatt` | POST | Skatt på realisert gevinst (skjermingsfradrag, aksjonærmodellen) |
| `/api/skatt-ask` | POST | Skatt ved uttak fra aksjesparekonto (ASK) |
| `/api/beholdning` | GET/POST | Hent/lagre brukerens beholdning |
| `/api/instrumenter` | GET/POST | List alle / legg til nytt brukerinstrument |
| `/api/instrumenter/sjekk/<ticker>` | GET | Valider ticker mot Yahoo Finance (auto-fyll) |
| `/api/instrumenter/<ticker>` | DELETE | Fjern brukerlagt instrument |
| `/api/portefolje-tickere` | GET/POST | Hent/sett hvilke tickere som er "i porteføljen" |

### Eksempel: `POST /api/kalkulator`

```bash
curl -X POST http://localhost:5001/api/kalkulator \
  -H "Content-Type: application/json" \
  -d '{
    "start": 120000,
    "manedlig": 6000,
    "ar": 7,
    "mal": 1000000,
    "start_aksje": 1.0,
    "slutt_aksje": 0.2,
    "hold_aar": 5,
    "aksje_cagr": 0.08,
    "aksje_vol": 0.127
  }'
```

Returnerer p5/median/p95, P(≥mål), median-bane, aksjevekt-tidsserie og histogram.

## Arkitektur

```
┌─────────────────┐       ┌──────────────────────┐
│   Nettleser     │ ──▶   │   Flask (app.py)     │
│  (Chart.js)     │       │                      │
└─────────────────┘       │  ┌────────────────┐  │
                          │  │  TTL-cache     │  │
                          │  │  (info, hist)  │  │
                          │  └───────┬────────┘  │
                          │          │           │
                          │  ┌───────▼────────┐  │
                          │  │ ThreadPool     │  │
                          │  │ (parallel I/O) │  │
                          │  └───────┬────────┘  │
                          └──────────┼───────────┘
                                     │
           ┌─────────────┬──────────────┼──────────────┐
           │             │              │              │
           ▼             ▼              ▼              ▼
     ┌──────────┐  ┌──────────┐   ┌──────────┐   ┌──────────┐
     │ yfinance │  │   E24    │   │  VADER   │   │  Claude  │
     │  (Yahoo) │  │  (RSS)   │   │  (NLP)   │   │  (API*)  │
     └──────────┘  └──────────┘   └──────────┘   └──────────┘
                                          * valgfri AI-assistent
```

### Designvalg verdt å vite

- **TTL-cache lokalt i prosess** (ikke Redis): appen kjører lokalt, én bruker. Redis er overengineering.
- **Atomisk fil-skriving** for `beholdning.json` med tempfile + `os.replace`: tåler crashes uten korrupsjon.
- **Monte Carlo i NumPy**: 20 000 simuleringer × 84 måneder vektorisert til ~0.3s.
- **Deterministisk default-seed (42)**: samme input → samme prognose. `?seed=random` overstyrer.
- **Bench-relativ sammenligner kun på overlappende datoer** (`pd.DataFrame.dropna`): norske `0P...`-fond har annen datokalender enn US-ETF-er; bench vises ikke når overlapp er for lite.

## Legge til egne instrumenter

To måter:

1. **Via UI (anbefalt):** Åpne **⚙️ Mine instrumenter**-fanen, skriv inn Yahoo Finance-ticker,
   klikk *Sjekk* (auto-fyller navn/sektor/type fra Yahoo), justér og klikk *+ Legg til*.
   Marker hvilke som skal være "i porteføljen din" — disse vises under Min portefølje og
   brukes i korrelasjons-analyse. Lagres i `bruker_instrumenter.json` lokalt.

2. **Via konfig (for standard-eksempler):** Rediger `STANDARD_AKSJER` og `STANDARD_FOND` i
   `analyse/config.py`. Brukes for templates som skal deles.

Yahoo Finance-tickere:
- Norske aksjer: `EQNR.OL`, `DNB.OL`, `MOWI.OL` (suffiks `.OL`)
- Norske fond: `0P00000MVB.IR`-format (finn på fondets Yahoo-side under "Symbol")
- US ETF-er: `SPY`, `QQQ`, `IWDA.AS` (suffiks for europeiske børser)

## Tester

```bash
pip install -r requirements-dev.txt
pytest
```

185 tester over de rene regnemodulene — de som gir tall folk faktisk handler på:

| Fil | Dekker |
|---|---|
| `tests/test_skatt.py` | Aksjonærmodellen og ASK: skjerming som renters rente, skjerming som ikke kan skape tap, ubenyttet skjerming som går tapt ved realisasjon, oppjustert tapsfradrag, delvise og fulle ASK-uttak |
| `tests/test_kalkulator.py` | Glidebane og Monte Carlo: lukket-form-fasit ved vol = 0, determinisme per seed, at CAGR tolkes som median (ikke gjennomsnitt), at stresstesten trekker ned nøyaktig 25 % |
| `tests/test_treffsikkerhet.py` | Måling mot handelsdager (ikke kalenderdager), helgesaker, saker som venter på kursdata, terskel-grensetilfeller, aggregering per instrument og samlet |
| `tests/test_transaksjoner.py` | FIFO-lots (med eksplisitt vakt mot å skli tilbake til snittkostpris), gebyrhåndtering, salg over flere lots, salg uten dekning, eiertid per lot, XIRR mot kjente fasitverdier, og at skjermingsår teller årsskifter framfor 365-dagersperioder |
| `tests/test_hent.py` | Bakgrunnsjobben: intervall-parsing, at én feilende ticker ikke velter runden, exit-koder for systemd |
| `tests/test_risiko.py` | Drawdown og CAGR mot lukket form, Sharpe som `None` ved null volatilitet, og at datavindu-tersklene følger config |

Testene er hermetiske: ingen nettverkskall, og de rører ikke `data/`.
Stokastisk kode testes deterministisk der det går (vol = 0 mot lukket form) og
ellers på egenskaper som må holde uansett trekning.

Testene avdekket én reell feil, nå rettet: `glidebane_vekter` startet
nedtrappingen én måned for sent fordi `np.linspace` tar med start-endepunktet.
`test_glidebane_har_nøyaktig_hold_aar_på_startandelen` er regresjonsvakten.

## Veikart

- [x] Risikomål per instrument (Sharpe, drawdown, vol)
- [x] Korrelasjonsmatrise med tolkning
- [x] Markedstermometer
- [x] Monte Carlo-kalkulator med glidebane
- [x] Modulær arkitektur (Flask blueprints)
- [x] Docker-deploy
- [x] Brukeradministrerte instrumenter via UI (blank template-klar)
- [x] Test-suite (pytest) — 185 tester på skatt, kalkulator, risiko, treffsikkerhet, transaksjoner og hentejobben
- [x] Transaksjonslogg med FIFO-kostpris og pengevektet avkastning
- [ ] GitHub Actions CI
- [ ] Strukturert logging (JSON)
- [ ] Prometheus-metrics endpoint
- [ ] Eksport til CSV/Excel

## Ansvarsfraskrivelse

⚠️ Verktøyet er bygget for personlig analyse og er **ikke investeringsråd**. Historisk avkastning er ingen garanti for fremtidig avkastning. Monte Carlo-prognoser forutsetter at fortidens volatilitet og avkastning er representativ for fremtiden, hvilket de sjelden er. VADER-sentiment er trent på engelsk og scorer norske E24-overskrifter upresist. Bruk på eget ansvar.

## Lisens

[MIT](LICENSE) — gjør hva du vil, men på eget ansvar.
