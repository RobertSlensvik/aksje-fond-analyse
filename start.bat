@echo off
echo.
echo  ==============================================
echo   Aksje ^& Fond Analyse - installerer pakker...
echo  ==============================================
echo.
pip install -r requirements.txt
echo.
echo  Starter appen... Aapne http://localhost:5001
echo.
python app.py
pause
