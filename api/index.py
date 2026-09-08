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

from crypto_trading_desk.api.app import app
