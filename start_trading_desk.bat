@echo off
title Blockstone Capital AI Trading Desk
echo Starting Blockstone Capital AI Trading Desk...
echo.
python -m uvicorn crypto_trading_desk.api.app:app --host 127.0.0.1 --port 8000
pause
