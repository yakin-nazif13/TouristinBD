# Phase 12 — one image serving both the API and the interface.
#
# The SQLite database is *built during the image build* from the committed
# pipeline artifacts in data/, so the container starts with a ready database and
# needs no volume, no external DB service and no network at runtime.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8000

WORKDIR /app

COPY requirements-api.txt ./
RUN pip install --no-cache-dir -r requirements-api.txt

# Only what the service needs: the app, the interface, the pipeline artifacts
# and the build/verify scripts. .dockerignore keeps the heavy extras out.
COPY backend/ ./backend/
COPY frontend/ ./frontend/
COPY scripts/ ./scripts/
COPY data/ ./data/

# Fail the build rather than shipping an image whose database is broken.
RUN python scripts/build_phase8_database.py \
    && python scripts/test_phase8_api.py \
    && python scripts/test_phase9_chat.py \
    && python scripts/test_phase10_itinerary.py \
    && python scripts/test_phase11_frontend.py

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os,urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/health').status==200 else 1)"

CMD ["python", "-m", "backend.main"]
