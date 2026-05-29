"""Lagring og lesing av brukerens beholdning (andeler + snittpris per ticker)."""

import json
import os
import tempfile
import threading

from .config import BEHOLDNING_FIL


_LOCK = threading.Lock()


def les_beholdning():
    """Returner {ticker: {andeler, snittpris}}. Tom dict hvis fil mangler."""
    if not os.path.exists(BEHOLDNING_FIL):
        return {}
    try:
        with open(BEHOLDNING_FIL, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except (OSError, json.JSONDecodeError):
        return {}


def skriv_beholdning(data):
    """Atomisk skriving: temp-fil → rename. Sikrer mot korrupsjon ved crash."""
    with _LOCK:
        katalog = os.path.dirname(BEHOLDNING_FIL)
        fd, tmp = tempfile.mkstemp(dir=katalog, prefix=".beholdning_", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, BEHOLDNING_FIL)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
