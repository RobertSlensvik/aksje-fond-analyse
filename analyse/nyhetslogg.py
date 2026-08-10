"""Permanent logg over nyhetssaker med sentiment, per ticker.

Yahoo og E24 viser bare et ferskt vindu med saker. For å kunne måle om
sentiment faktisk traff, må sakene lagres når vi ser dem — ellers forsvinner
de ut av feeden før kursen rekker å bevege seg. Loggen fylles automatisk hver
gang nyheter hentes, og beskjæres til de siste NYHETSLOGG_MAKS_DAGER dagene.
"""

import json
import os
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from .config import (
    NYHETSLOGG_FIL,
    NYHETSLOGG_MAKS_DAGER,
    NYHETSLOGG_MAKS_PER_TICKER,
)


_LOCK = threading.RLock()


def parse_dato(rå):
    """Parse ISO-8601 eller RFC-822 til tz-aware UTC-datetime. None ved feil."""
    if not rå or not isinstance(rå, str):
        return None
    try:
        d = datetime.fromisoformat(rå.strip().replace("Z", "+00:00"))
    except ValueError:
        try:
            d = parsedate_to_datetime(rå.strip())
        except (TypeError, ValueError):
            return None
    if d is None:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def _nokkel(sak):
    """Dedupe-nøkkel: normalisert tittel + publiseringsdag."""
    tittel = " ".join((sak.get("tittel") or "").lower().split())
    dag = (sak.get("dato") or "")[:10]
    return f"{dag}|{tittel}"


def les_logg():
    """Returner {ticker: [saker]}. Tom dict hvis filen mangler eller er korrupt."""
    if not os.path.exists(NYHETSLOGG_FIL):
        return {}
    try:
        with open(NYHETSLOGG_FIL, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _skriv_logg(data):
    """Atomisk skriving: temp-fil → rename."""
    katalog = os.path.dirname(NYHETSLOGG_FIL)
    fd, tmp = tempfile.mkstemp(dir=katalog, prefix=".nyhetslogg_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1, ensure_ascii=False)
        os.replace(tmp, NYHETSLOGG_FIL)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _beskjaer(saker):
    """Behold nyeste saker innenfor tids- og antallsgrensen."""
    grense = datetime.now(timezone.utc) - timedelta(days=NYHETSLOGG_MAKS_DAGER)
    ferske = []
    for s in saker:
        d = parse_dato(s.get("dato"))
        if d is None or d >= grense:
            ferske.append(s)
    ferske.sort(key=lambda s: s.get("dato") or "", reverse=True)
    return ferske[:NYHETSLOGG_MAKS_PER_TICKER]


def logg_saker(ticker, saker):
    """Slå nye saker inn i loggen for én ticker. Skriver kun ved endring.

    Saker uten publiseringsdato får dagens tidspunkt og markeres med
    `dato_antatt`, slik at treffsikkerhet-beregningen kan vekte dem lavere.
    """
    if not ticker or not saker:
        return 0

    nå = datetime.now(timezone.utc).isoformat()
    with _LOCK:
        logg = les_logg()
        eksisterende = logg.get(ticker, [])
        if not isinstance(eksisterende, list):
            eksisterende = []
        sett = {_nokkel(s) for s in eksisterende}

        nye = []
        for s in saker:
            tittel = (s.get("tittel") or "").strip()
            if not tittel:
                continue
            dato = s.get("dato") or ""
            dato_antatt = False
            parsed = parse_dato(dato)
            if parsed is None:
                dato, dato_antatt = nå, True
            else:
                dato = parsed.isoformat()
            post = {
                "tittel":  tittel,
                "dato":    dato,
                "kilde":   s.get("kilde", ""),
                "url":     s.get("url", ""),
                "score":   s.get("score", 0.0),
                "etikett": s.get("etikett", "nøytral"),
                "logget":  nå,
            }
            if dato_antatt:
                post["dato_antatt"] = True
            n = _nokkel(post)
            if n in sett:
                continue
            sett.add(n)
            nye.append(post)

        if not nye:
            return 0

        logg[ticker] = _beskjaer(eksisterende + nye)
        try:
            _skriv_logg(logg)
        except OSError:
            return 0
        return len(nye)


def saker_for(ticker):
    """Alle loggede saker for én ticker, nyeste først."""
    saker = les_logg().get(ticker, [])
    return saker if isinstance(saker, list) else []


def logg_status():
    """Oppsummering av loggen: antall saker og eldste dato per ticker."""
    logg = les_logg()
    totalt = sum(len(v) for v in logg.values() if isinstance(v, list))
    eldste = None
    for saker in logg.values():
        for s in saker if isinstance(saker, list) else []:
            d = parse_dato(s.get("dato"))
            if d and (eldste is None or d < eldste):
                eldste = d
    return {
        "tickere":       len(logg),
        "saker_totalt":  totalt,
        "eldste_sak":    eldste.isoformat() if eldste else None,
    }
