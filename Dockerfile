# Container image for the AI Prescription Digitizer.
# Build & Run:
#   docker build -t rx-digitizer .
#   docker run --rm -p 7860:7860 --env-file .env -v rx-records:/app/records rx-digitizer
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code and data
COPY app.py evaluate.py ./
COPY rxcore ./rxcore
COPY web ./web
COPY data ./data

# Setup non-root app user and storage directories
RUN useradd --create-home app && mkdir -p records uploads && chown -R app:app /app
USER app

ENV HOST=0.0.0.0 PORT=7860 PYTHONUNBUFFERED=1
EXPOSE 7860

# Single worker with multithreading keeps in-memory reviews coherent
CMD ["gunicorn", "--bind", "0.0.0.0:7860", "--workers", "1", "--threads", "4", "--timeout", "180", "app:create_app()"]
