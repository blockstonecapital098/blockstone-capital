FROM python:3.11-slim

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Expose default port
EXPOSE 8000

# Start the application dynamically evaluating $PORT (works on Render, Railway, Koyeb, Docker)
CMD ["sh", "-c", "uvicorn crypto_trading_desk.api.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
