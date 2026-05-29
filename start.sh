#!/bin/bash
echo ""
echo "=============================================="
echo "  Aksje & Fond Analyse"
echo "=============================================="
echo ""

# Opprett virtuelt miljø hvis det ikke finnes
if [ ! -d "venv" ]; then
  echo "  Oppretter virtuelt miljø (gjøres kun én gang)..."
  python3 -m venv venv
fi

# Aktiver miljøet
source venv/bin/activate

# Installer/oppdater pakker
echo "  Installerer pakker..."
pip install -q -r requirements.txt

echo ""
echo "  Klar! Aapne nettleseren paa:"
echo "  http://localhost:5001"
echo ""
echo "  (Trykk Ctrl+C for aa stoppe)"
echo ""

python3 app.py
