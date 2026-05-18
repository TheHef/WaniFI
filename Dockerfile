FROM node:20-alpine AS frontend
WORKDIR /build
COPY package.json package-lock.json* ./
RUN npm ci --prefer-offline
COPY tailwind.config.js ./
COPY app/templates ./app/templates
COPY app/static ./app/static
RUN npx tailwindcss -i app/static/css/input.css -o app/static/css/tailwind.css --minify \
 && cp node_modules/alpinejs/dist/cdn.min.js app/static/js/alpine.min.js \
 && cp node_modules/chart.js/dist/chart.umd.min.js app/static/js/chart.min.js

FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/
COPY --from=frontend /build/app/static/css/tailwind.css ./app/static/css/tailwind.css
COPY --from=frontend /build/app/static/js/alpine.min.js  ./app/static/js/alpine.min.js
COPY --from=frontend /build/app/static/js/chart.min.js   ./app/static/js/chart.min.js
ENV PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    PORT=8000
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:${PORT}/healthz || exit 1
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
