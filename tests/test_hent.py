"""Tester for bakgrunnsjobben som fyller nyhetsloggen.

Ingen nettverkskall: `hent_nyheter_for` monkeypatches, så testene måler
orkestreringen — at én feilende ticker ikke velter runden, og at
intervall-parsingen avviser tull.
"""

import pytest

from analyse import hent as H


# ─── Intervall-parsing ──────────────────────────────────────────────────────

@pytest.mark.parametrize("tekst, sekunder", [
    ("4h", 14_400), ("6h", 21_600), ("30m", 1_800), ("1d", 86_400),
    ("900", 900), ("2H", 7_200), (" 4h ", 14_400),
])
def test_parse_intervall(tekst, sekunder):
    assert H.parse_intervall(tekst) == sekunder


@pytest.mark.parametrize("tekst", ["abc", "", "4x", "-1h", "h4"])
def test_parse_intervall_avviser_tull(tekst):
    with pytest.raises(ValueError, match="Ugyldig intervall"):
        H.parse_intervall(tekst)


@pytest.mark.parametrize("tekst", ["30s", "59", "1"])
def test_parse_intervall_avviser_for_kort(tekst):
    """Under 60 s er meningsløst — RSS-cachen er på 10 minutter."""
    with pytest.raises(ValueError, match="meningsløst"):
        H.parse_intervall(tekst)


# ─── Runde-orkestrering ─────────────────────────────────────────────────────

@pytest.fixture
def tre_instrumenter(monkeypatch):
    katalog = [{"ticker": "A", "navn": "A", "type": "aksje"},
               {"ticker": "B", "navn": "B", "type": "aksje"},
               {"ticker": "C", "navn": "C", "type": "fond"}]
    monkeypatch.setattr(H, "alle_instrumenter", lambda: katalog)
    monkeypatch.setattr(H, "logg_status",
                        lambda: {"saker_totalt": 0, "tickere": 0, "eldste_sak": None})
    return katalog


def test_runde_henter_alle_instrumenter(tre_instrumenter, monkeypatch):
    hentet = []
    monkeypatch.setattr(H, "hent_nyheter_for", lambda i: hentet.append(i["ticker"]))
    monkeypatch.setattr(H, "saker_for", lambda tk: [])
    nye, feil = H.kjor_en_runde()
    assert hentet == ["A", "B", "C"]
    assert feil == 0


def test_én_feilende_ticker_velter_ikke_runden(tre_instrumenter, monkeypatch):
    def hent(item):
        if item["ticker"] == "B":
            raise RuntimeError("Yahoo svarte ikke")
    monkeypatch.setattr(H, "hent_nyheter_for", hent)
    monkeypatch.setattr(H, "saker_for", lambda tk: [])
    nye, feil = H.kjor_en_runde()
    assert feil == 1            # B feilet, A og C gikk gjennom


def test_nye_saker_telles(tre_instrumenter, monkeypatch):
    # Simuler at loggen vokser med 2 saker per ticker
    tilstand = {"A": 0, "B": 0, "C": 0}
    monkeypatch.setattr(H, "hent_nyheter_for",
                        lambda i: tilstand.__setitem__(i["ticker"], 2))
    monkeypatch.setattr(H, "saker_for", lambda tk: [None] * tilstand[tk])
    nye, feil = H.kjor_en_runde()
    assert nye == 6
    assert feil == 0


def test_tom_katalog_er_ikke_feil(monkeypatch):
    monkeypatch.setattr(H, "alle_instrumenter", lambda: [])
    assert H.kjor_en_runde() == (0, 0)


# ─── main() og exit-koder ───────────────────────────────────────────────────

def test_main_returnerer_0_ved_delvis_suksess(tre_instrumenter, monkeypatch):
    def hent(item):
        if item["ticker"] == "B":
            raise RuntimeError("nede")
    monkeypatch.setattr(H, "hent_nyheter_for", hent)
    monkeypatch.setattr(H, "saker_for", lambda tk: [])
    # Delvis feil skal ikke få systemd til å gi opp jobben
    assert H.main([]) == 0


def test_main_returnerer_1_når_alt_feiler(tre_instrumenter, monkeypatch):
    monkeypatch.setattr(H, "hent_nyheter_for",
                        lambda i: (_ for _ in ()).throw(RuntimeError("nettverk nede")))
    monkeypatch.setattr(H, "saker_for", lambda tk: [])
    assert H.main([]) == 1


def test_main_avviser_ugyldig_loop_intervall(tre_instrumenter, capsys):
    assert H.main(["--loop", "tull"]) == 2
    assert "Ugyldig intervall" in capsys.readouterr().err
