@echo off
echo ==========================================
echo DealerIntel Setup Protocol Initiated...
echo ==========================================
echo.
echo Verifying system requirements (this may take a moment on the first run)...
python -m pip install streamlit pandas plotly --quiet

echo.
echo Booting DealerIntel Live Dashboard...
python -m streamlit run app.py

pause