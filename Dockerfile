# Stage 1: Build frontend
FROM node:20-slim AS frontend
WORKDIR /app/web
COPY web/package.json web/package-lock.json* ./
RUN npm ci --no-audit
COPY web/ ./
RUN npm run build

# Stage 2: Python runtime
FROM python:3.11-slim
WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ && \
    rm -rf /var/lib/apt/lists/*

# Python deps (split for better caching)
COPY requirements.prod.txt ./
RUN pip install --no-cache-dir -r requirements.prod.txt

# App code
COPY scanner/ ./scanner/
COPY sentiment/ ./sentiment/
COPY portfolio/ ./portfolio/
COPY api/ ./api/
COPY cli/ ./cli/
COPY main.py config.yaml ./

# Frontend build artifacts
COPY --from=frontend /app/web/dist ./web/dist

# Data directories
RUN mkdir -p logs results

EXPOSE 8000

CMD ["uvicorn", "api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
