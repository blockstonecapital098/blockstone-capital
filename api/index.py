"""
Vercel serverless function entrypoint for Blockstone Capital AI Trading Desk.
"""
import os
import sys

# Add project root to sys.path so modules resolve on Vercel
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

try:
    from crypto_trading_desk.api.app import app
except Exception as exc:
    import traceback
    err_tb = traceback.format_exc()
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse

    app = FastAPI(title="Blockstone Capital Diagnostic")

    @app.get("/{full_path:path}", response_class=HTMLResponse)
    async def catch_all(full_path: str = ""):
        return f"""
        <html>
        <head><title>Startup Diagnostic</title></head>
        <body style="background:#0b1220;color:#ff3b5c;font-family:monospace;padding:30px;">
            <h2>⚠️ Blockstone Capital Startup Diagnostic</h2>
            <pre style="background:#060911;color:#00ff9d;padding:20px;border-radius:8px;border:1px solid #233558;white-space:pre-wrap;">
{err_tb}
            </pre>
        </body>
        </html>
        """
