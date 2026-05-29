"""Tall- og prosent-formattering for visning."""


def fmt_tall(v, desimaler=2):
    """Formater tall med tusenskille og fast antall desimaler. Returner '–' ved None."""
    if v is None:
        return "–"
    try:
        return f"{float(v):,.{desimaler}f}"
    except (TypeError, ValueError):
        return "–"


def fmt_store(v):
    """Formater store tall som Bio/Mrd/M med korte enheter."""
    if v is None:
        return "–"
    try:
        v = float(v)
        if v >= 1e12:
            return f"{v/1e12:.2f} Bio"
        if v >= 1e9:
            return f"{v/1e9:.2f} Mrd"
        if v >= 1e6:
            return f"{v/1e6:.2f} M"
        return fmt_tall(v)
    except (TypeError, ValueError):
        return "–"


def fmt_utbytte(yield_raw):
    """Formater dividendYield som prosent.

    Yahoo gir noen ganger dividendYield som desimal (0.025), andre ganger som
    prosent (2.5). Heuristikk: hvis verdien er < 1, anta desimal og × 100.
    """
    if not yield_raw:
        return "–"
    try:
        v = float(yield_raw)
        if v < 1:
            v *= 100
        return f"{v:.2f}%"
    except (TypeError, ValueError):
        return "–"
