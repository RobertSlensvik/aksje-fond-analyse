# Kjøre på Ubuntu med Docker

Oppsettet består av to containere:

| Tjeneste | Hva den gjør |
|---|---|
| `analyse` | Webappen (gunicorn på port 5001) |
| `henter` | Fyller nyhetsloggen hver 4. time, uavhengig av webappen |

Den andre finnes fordi nyhetsloggen er det eneste i appen som akkumulerer verdi
over tid. Feedene er rullerende vinduer — for tett dekkede tickere (AAPL, SPY)
rekker én henting bare ~11 dager bakover, så et hull blir permanent.

> **Testet:** bygget for `linux/amd64` og kjørt begge tjenestene, verifisert at
> webappen svarer, at hentejobben skriver til det monterte volumet, og at
> `BIND_ADDR=127.0.0.1` faktisk stenger ut LAN-tilgang.
> **Ikke testet på ekte Ubuntu:** jeg hadde bare macOS tilgjengelig, og Docker
> Desktop maskerer uid-oppførselen for bind-mounts (se punkt 3). Verifiser det
> steget selv.

---

## 1. Systempakker

```bash
sudo apt update
sudo apt install -y docker.io docker-compose-v2 git
sudo usermod -aG docker "$USER"        # logg ut og inn etterpå
```

Sjekk at det virker uten `sudo`:

```bash
docker run --rm hello-world
```

## 2. Tidssone

Uten dette kjører maskinen i UTC, og `date.today()` bommer på kvelden norsk
tid: et kjøp registrert 00:30 blir avvist som «framtidig dato», og
månedsrapporten bytter måned et døgn for sent.

```bash
sudo timedatectl set-timezone Europe/Oslo
timedatectl                            # kontroller
```

Containerne setter `TZ` selv (default `Europe/Oslo`), men host bør stemme også.

## 3. Hent koden og sett opp `.env`

```bash
git clone <repo-url> aksje-fond-analyse
cd aksje-fond-analyse
cp .env.example .env
```

**Dette er det viktigste steget på Linux.** `data/` bind-mountes inn i
containeren, og container-brukeren må ha samme uid/gid som eieren av katalogen
på host. Ellers nektes skriving, og appen kan ikke lagre beholdning eller
transaksjoner.

```bash
id -u    # → f.eks. 1000
id -g    # → f.eks. 1000
```

Skriv verdiene inn i `.env`:

```ini
UID=1000
GID=1000
```

Docker Desktop på macOS/Windows mapper dette automatisk, så feilen dukker
**bare** opp på Linux. Er uid feil, ser du `PermissionError` i `docker compose
logs analyse` når du prøver å lagre noe.

## 4. Start

```bash
docker compose up -d --build
docker compose ps
```

Forventet:

```
NAME                          SERVICE   STATUS                    PORTS
aksje-fond-analyse-analyse-1  analyse   Up (healthy)              0.0.0.0:5001->5001/tcp
aksje-fond-analyse-henter-1   henter    Up
```

`henter` har med vilje ingen healthcheck — den kjører ingen webserver, og ville
ellers blitt stemplet «unhealthy» for alltid.

Åpne `http://<maskinens-ip>:5001`.

## 5. Sikkerhet — les dette før du eksponerer appen

**Appen har ingen autentisering.** Ingen innlogging, ingen CSRF-beskyttelse.
Hvem som helst som når porten kan se porteføljen din og legge inn eller slette
transaksjoner. På en maskin som står på døgnet rundt er det en reell eksponering.

Tre nivåer, velg etter nettverket ditt:

**a) Kun via SSH-tunnel** — tryggest. Appen er utilgjengelig utenfra.

```ini
# .env
BIND_ADDR=127.0.0.1
```

```bash
# fra din egen maskin
ssh -L 5001:localhost:5001 bruker@server
# åpne http://localhost:5001 lokalt
```

**b) Slipp inn bare din egen maskin** — praktisk på hjemmenettverk.

```ini
BIND_ADDR=0.0.0.0
```

```bash
sudo ufw default deny incoming
sudo ufw allow ssh
sudo ufw allow from 192.168.1.42 to any port 5001 proto tcp
sudo ufw enable
```

**c) Nginx med basic auth foran** — hvis du vil nå den fra mobil. Sett
`BIND_ADDR=127.0.0.1` så bare nginx kommer til, og terminer TLS der.

Standarden i `.env.example` er `0.0.0.0`, altså åpent på nettverket. Det er
valgt fordi alternativet gjør appen utilgjengelig uten tunnel på en headless
maskin, noe som lett oppleves som at den er ødelagt. Men det er *ditt* valg —
ta det bevisst.

## 6. Drift

```bash
docker compose logs -f analyse          # webapp-logg
docker compose logs -f henter           # hentejobben
docker compose restart henter           # tving en ny hentesyklus
docker compose down                     # stopp
docker compose up -d --build            # etter kodeendringer
```

Hentejobben logger én linje per instrument per runde:

```
[2026-08-10 15:36:41]   AAPL: +24 nye (totalt 24)
[2026-08-10 15:36:46] Runde ferdig: 136 nye saker, 0 feil.
```

Én ticker som feiler velter ikke runden. Exit-kode blir bare 1 hvis *alle*
feiler, som regel nettverksproblem.

Vil du hente sjeldnere eller oftere:

```ini
HENT_INTERVALL=6h     # godtar 4h, 30m, 900 (sekunder), 1d
```

Under 60 sekunder avvises — RSS-cachen er på 10 minutter uansett. Én runde er
~37 HTTP-kall, så hver 4. time er ~222 kall i døgnet. Det er langt under noe
rate-limit hos Yahoo.

## 7. Sikkerhetskopi

Alt av dine data ligger i `data/` som ren JSON:

```bash
tar czf backup-$(date +%F).tar.gz data/
```

| Fil | Innhold |
|---|---|
| `beholdning.json` | Andeler og snittpris |
| `bruker_instrumenter.json` | Dine aksjer/fond |
| `bruker_portefolje.json` | Hvilke som er i porteføljen |
| `transaksjoner.json` | Kjøp og salg (grunnlag for FIFO og skatt) |
| `nyhetslogg.json` | Nyhetshistorikk — den som ikke kan gjenskapes |

`nyhetslogg.json` er den eneste som ikke kan bygges opp igjen. De andre kan du
skrive inn på nytt.

## 8. Uten AI

Appen trenger ingen AI-modell. Chatboblen er den eneste funksjonen som bruker
en, og uten `ANTHROPIC_API_KEY` er den grå og deaktivert — resten fungerer
uendret. Vil du droppe pakken helt, stryk `anthropic` fra `requirements.txt`
før du bygger; den importeres lazy, så appen bryr seg ikke om den mangler.

## Feilsøking

| Symptom | Årsak |
|---|---|
| `PermissionError` i loggen ved lagring | `UID`/`GID` i `.env` matcher ikke eieren av `data/` (punkt 3) |
| `python3 -m venv` feiler (uten Docker) | mangler `apt install python3-venv` |
| Kjøp «i dag» avvises som framtidig dato | tidssone er UTC (punkt 2) |
| `henter` står som «unhealthy» | gammel compose-fil uten `healthcheck: disable` |
| Navnekollisjon på container | gammel compose-fil med hardkodet `container_name` |
| Alle kurser tomme | ingen utgående nett, eller Yahoo nede — appen degraderer pent, henger ikke |
