FROM python:3.11-slim

# System deps — gcc for any wheels that need building; libffi is a common transitive dep.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libffi-dev && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first for better Docker layer caching —
# this layer only rebuilds when requirements.txt changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY *.py ./
COPY layers/ layers/
COPY assets/ assets/

# Data directory — Fly.io mounts a persistent volume here in production,
# so the SQLite DB and any historical exports survive restarts and deploys.
RUN mkdir -p /app/data
ENV PARCEL_SCOUT_DATA_DIR=/app/data

# Streamlit port
EXPOSE 8080

# Streamlit server flags:
#   --server.port 8080                 match EXPOSE + fly.toml internal_port
#   --server.address 0.0.0.0           listen on all interfaces so Fly can reach it
#   --server.headless true             skip the "email to sign up" prompt
#   --server.enableCORS false          disable CORS for the containerised environment
#   --browser.gatherUsageStats false   never phone home to streamlit.io
CMD ["streamlit", "run", "app.py", \
     "--server.port=8080", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--server.enableCORS=false", \
     "--browser.gatherUsageStats=false"]
