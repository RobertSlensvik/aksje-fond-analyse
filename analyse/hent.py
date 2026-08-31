"""Bakgrunnsjobb som fyller nyhetsloggen — uavhengig av webserveren.

Nyhetsloggen er det eneste i appen som akkumulerer verdi over tid: feedene er
rullerende vinduer, så en sak som ikke blir fanget forsvinner. For tett dekkede
tickere (AAPL, SPY) rekker én henting bare ~11 dager bakover, og et hull blir
permanent. Derfor bør hentingen skje jevnlig, og den trenger ikke at noen ser
på en nettside.

Bruk:
    python -m analyse.hent                 # én runde, avslutt
    python -m analyse.hent --loop 4h       # evig løkke, hver 4. time
    python -m analyse.hent --loop 900      # sekunder går også

Skriver til stdout med tidsstempel, slik at `journalctl` og `docker logs` blir
lesbare. Exit-kode 0 selv om enkelte instrumenter feiler — delvis suksess skal
ikke få systemd til å gi opp jobben. Kun total feil gir exit 1.
"""

import argparse
import datetime as dt
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from .instrumenter import alle_instrumenter
from .nyheter import hent_nyheter_for
from .nyhetslogg import logg_status, saker_for


def _logg(melding):
    """Én linje med UTC-tidsstempel — leses av journalctl/docker logs."""
    stempel = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{stempel}] {melding}", flush=True)


def parse_intervall(tekst):
    """Godta '4h', '30m', '900' eller '1d' → sekunder. Kaster ValueError."""
    m = re.fullmatch(r"(\d+)\s*([smhd]?)", str(tekst).strip().lower())
    if not m:
        raise ValueError(f"Ugyldig intervall: {tekst!r} (bruk f.eks. 4h, 30m, 900)")
    tall, enhet = int(m.group(1)), m.group(2)
    faktor = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}[enhet]
    sekunder = tall * faktor
    if sekunder < 60:
        raise ValueError("Intervall under 60 sekunder er meningsløst — "
                         "RSS-cachen er på 10 minutter uansett")
    return sekunder


def kjor_en_runde():
    """Hent nyheter for alle instrumenter parallelt. Returnerer (nye_saker, antall_feil)."""
    instrumenter = alle_instrumenter()
    if not instrumenter:
        _logg("Ingen instrumenter registrert — ingenting å hente.")
        return 0, 0

    # Tell antall loggede saker per ticker FØR henting, slik at vi kan rapportere nytt.
    for_antall = {item["ticker"]: len(saker_for(item["ticker"])) for item in instrumenter}

    futures = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = {ex.submit(hent_nyheter_for, item): item for item in instrumenter}

    nye_totalt = 0
    feil = 0
    for future, item in futures.items():
        ticker = item["ticker"]
        try:
            future.result()
            etter = len(saker_for(ticker))
            nye = etter - for_antall[ticker]
            nye_totalt += nye
            _logg(f"  {ticker}: {nye:+d} nye (totalt {etter})")
        except Exception as e:                      # noqa: BLE001 — én ticker skal
            feil += 1                               # ikke velte hele runden
            _logg(f"  {ticker}: FEIL — {type(e).__name__}: {e}")

    status = logg_status()
    _logg(f"Runde ferdig: {nye_totalt} nye saker, {feil} feil. "
          f"Loggen har nå {status['saker_totalt']} saker over {status['tickere']} tickere.")
    return nye_totalt, feil


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="python -m analyse.hent",
        description="Fyll nyhetsloggen. Kjør som cron/systemd-timer, eller med --loop.",
    )
    p.add_argument("--loop", metavar="INTERVALL",
                   help="Kjør i evig løkke med dette intervallet (f.eks. 4h, 30m, 900)")
    args = p.parse_args(argv)

    if not args.loop:
        _logg("Henter nyheter (én runde)…")
        _, feil = kjor_en_runde()
        # Alt feilet → sannsynligvis nettverks- eller konfigurasjonsproblem.
        return 1 if feil and feil == len(alle_instrumenter()) else 0

    try:
        sekunder = parse_intervall(args.loop)
    except ValueError as e:
        print(f"Feil: {e}", file=sys.stderr)
        return 2

    _logg(f"Starter i løkke — henter hvert {sekunder} sekund "
          f"({sekunder / 3600:.1f} timer). Avbryt med Ctrl+C.")
    while True:
        try:
            kjor_en_runde()
        except Exception as e:                       # noqa: BLE001
            _logg(f"Uventet feil i runden: {type(e).__name__}: {e}")
        _logg(f"Sover til neste runde ({sekunder}s)…")
        try:
            time.sleep(sekunder)
        except KeyboardInterrupt:
            _logg("Avbrutt — avslutter.")
            return 0


if __name__ == "__main__":
    sys.exit(main())
