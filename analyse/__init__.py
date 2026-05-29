"""Aksje & Fond Analyse — Flask app factory."""

import os

from flask import Flask


def create_app():
    """Bygg Flask-applikasjonen og registrer alle blueprints.

    Bruker template/static-mapper fra prosjektrot, slik at vi kan ha en
    enkeltkilde for HTML uten å duplisere oppsett.
    """
    rot = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app = Flask(
        __name__,
        template_folder=os.path.join(rot, "templates"),
        static_folder=os.path.join(rot, "static") if os.path.isdir(os.path.join(rot, "static")) else None,
    )

    from .routes import bp
    app.register_blueprint(bp)

    return app
