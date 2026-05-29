"""Aksje & Fond Analyse — entry point.

Run: python app.py  →  Open http://localhost:5001
"""

from analyse import create_app


app = create_app()


if __name__ == "__main__":
    print("\n" + "=" * 55)
    print("  📈  Aksje & Fond Analyse  —  starter...")
    print("=" * 55)
    print("  Åpne nettleseren og gå til:")
    print("  👉  http://localhost:5001")
    print("=" * 55 + "\n")
    app.run(debug=False, port=5001, host="0.0.0.0")
