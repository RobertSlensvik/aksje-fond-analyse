"""Aksje & Fond Analyse — Flask app factory."""

import os

from flask import Flask


def _last_env():
    """Les en eventuell .env-fil i prosjektrot inn i os.environ.

    Enkel parser (KEY=VALUE, # for kommentar) så vi slipper en ekstra
    avhengighet. Eksisterende miljøvariabler overstyres ikke.
    """
    rot = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sti = os.path.join(rot, ".env")
    if not os.path.exists(sti):
        return
    try:
        with open(sti, "r", encoding="utf-8") as f:
            for linje in f:
                linje = linje.strip()
                if not linje or linje.startswith("#") or "=" not in linje:
                    continue
                nokkel, _, verdi = linje.partition("=")
                nokkel = nokkel.strip()
                verdi = verdi.strip().strip('"').strip("'")
                if nokkel and nokkel not in os.environ:
                    os.environ[nokkel] = verdi
    except OSError:
        pass


def create_app():
    """Bygg Flask-applikasjonen og registrer alle blueprints.

    Bruker template/static-mapper fra prosjektrot, slik at vi kan ha en
    enkeltkilde for HTML uten å duplisere oppsett.
    """
    _last_env()
    rot = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app = Flask(
        __name__,
        template_folder=os.path.join(rot, "templates"),
        static_folder=os.path.join(rot, "static") if os.path.isdir(os.path.join(rot, "static")) else None,
    )

    from .routes import bp
    app.register_blueprint(bp)

    return app
