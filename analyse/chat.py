"""AI-assistent (Claude) for porteføljespørsmål.

Av som standard: uten ANTHROPIC_API_KEY gjøres ingen API-kall, og ingenting
koster noe. Nøkkelen leses fra miljøvariabel (legg den i .env — som er
gitignored — eller sett den i shell-et). `anthropic`-pakken importeres lazy,
så appen kjører fint selv om pakken ikke er installert ennå.
"""

import datetime as dt
import os
import threading
import time


# Haiku er rimeligst og raskt nok til en chat-assistent. Overstyr med env.
MODELL = os.environ.get("CLAUDE_MODELL", "claude-haiku-4-5-20251001")
MAKS_TOKENS = 1024
MAKS_MELDINGER = 20            # Begrens historikk som sendes (kostnadskontroll)

INSTRUKSJON = (
    "Du er en hjelpsom assistent integrert i en norsk aksje- og fondsanalyse-app. "
    "Svar kort og konkret på norsk (bokmål). Du kan svare på spørsmål om brukerens "
    "portefølje, fond, aksjer, risiko, skatt (norsk aksjonærmodell/ASK) og generell "
    "sparing. Bruk tallene i porteføljekonteksten når de er relevante. "
    "Du gir ikke bindende investeringsråd — minn om at historisk avkastning ikke "
    "garanterer fremtidig, og at brukeren selv er ansvarlig for sine valg. "
    "Hvis du mangler data, si det heller enn å gjette."
)

# Liten TTL-cache for porteføljekonteksten (unngå å hente yfinance på hver melding).
_KONTEKST_CACHE = {"tekst": None, "ts": 0.0}
_KONTEKST_TTL = 300
_LOCK = threading.Lock()


def chat_konfigurert():
    """True hvis en API-nøkkel er satt. Styrer om boblen er aktiv i UI-et."""
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _bygg_kontekst():
    """Kompakt tekstkontekst om brukerens portefølje. Feiler aldri hardt."""
    nå = time.time()
    with _LOCK:
        if _KONTEKST_CACHE["tekst"] is not None and nå - _KONTEKST_CACHE["ts"] < _KONTEKST_TTL:
            return _KONTEKST_CACHE["tekst"]

    linjer = [f"Dagens dato: {dt.date.today().isoformat()}."]
    try:
        from .rapport import lag_rapport
        r = lag_rapport()
        if r.get("tom"):
            linjer.append("Brukeren har ingen instrumenter i porteføljen ennå.")
        else:
            t = r["total"]
            linje = f"Månedsrapport ({r['maned_navn']}): total avkastning {t['avkastning_pct']} %"
            if r["har_beholdning"] and t.get("verdi_kr") is not None:
                linje += f", total verdi {t['verdi_kr']:.0f} kr, verdiendring {t['endring_kr']:.0f} kr"
            linjer.append(linje + ".")
            linjer.append("Beholdning og avkastning forrige måned per instrument:")
            for i in r["instrumenter"]:
                d = f"  - {i['navn']} ({i['ticker']}): avkastning {i['avkastning_pct']} %"
                if i.get("vekt_pct") is not None:
                    d += f", vekt {i['vekt_pct']} %"
                if i.get("verdi_kr") is not None:
                    d += f", verdi {i['verdi_kr']:.0f} kr"
                linjer.append(d)
    except Exception as e:
        linjer.append(f"(Kunne ikke hente porteføljedata akkurat nå: {e})")

    tekst = "\n".join(linjer)
    with _LOCK:
        _KONTEKST_CACHE["tekst"] = tekst
        _KONTEKST_CACHE["ts"] = nå
    return tekst


def chat_svar(meldinger):
    """Send samtalehistorikk til Claude og returner svaret.

    `meldinger`: liste av {"role": "user"|"assistant", "content": str}.
    Returnerer {"svar": str} eller {"feil": str}.
    """
    if not chat_konfigurert():
        return {"feil": "AI-assistenten er ikke aktivert (mangler ANTHROPIC_API_KEY).",
                "konfigurert": False}
    try:
        import anthropic
    except ImportError:
        return {"feil": "Pakken 'anthropic' er ikke installert. Kjør: pip install anthropic"}

    # Rens og begrens historikken.
    rene = []
    for m in meldinger[-MAKS_MELDINGER:]:
        rolle = m.get("role")
        innhold = (m.get("content") or "").strip()
        if rolle in ("user", "assistant") and innhold:
            rene.append({"role": rolle, "content": innhold})
    if not rene or rene[-1]["role"] != "user":
        return {"feil": "Siste melding må komme fra brukeren."}

    try:
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        resp = client.messages.create(
            model=MODELL,
            max_tokens=MAKS_TOKENS,
            # Prompt caching: instruksjon + kontekst caches på tvers av meldinger
            # i samme samtale, så bare nye meldinger koster fullt.
            system=[
                {"type": "text", "text": INSTRUKSJON},
                {"type": "text",
                 "text": "Porteføljekontekst:\n" + _bygg_kontekst(),
                 "cache_control": {"type": "ephemeral"}},
            ],
            messages=rene,
        )
        tekst = "".join(blokk.text for blokk in resp.content if blokk.type == "text")
        return {"svar": tekst.strip() or "(tomt svar)", "modell": MODELL}
    except Exception as e:
        return {"feil": f"Feil mot Claude API: {e}"}
