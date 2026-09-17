"""Regenerate template.py from dashboard.html."""
import pathlib

src = pathlib.Path("crypto_trading_desk/api/templates/dashboard.html")
dst = pathlib.Path("crypto_trading_desk/api/templates/template.py")

html = src.read_text(encoding="utf-8")

# Normalise line endings to LF
html = html.replace("\r\n", "\n")

# Escape backslashes first, then single quotes, then newlines
escaped = html.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")

output = f"DASHBOARD_HTML = '{escaped}'\n"
dst.write_text(output, encoding="utf-8")
print(f"template.py regenerated: {len(output):,} chars")
