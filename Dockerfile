# Stage 1: Build the React Frontend
# Vite 8 and the current React Router release require Node 20.19+.
# Node 22 also avoids the npm 10 issue observed in the Node 20 Alpine image.
FROM node:22-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# Stage 2: Build Python backend dependencies
FROM python:3.11-slim AS backend-builder
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Stage 3: Final Runtime Image
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
# The official Python slim image already includes CA certificates and useradd.
# Avoid an apt-get step here so image builds do not depend on a host mirror.
RUN useradd --create-home appuser
# Copy installed python dependencies
COPY --from=backend-builder --chown=appuser:appuser /root/.local /home/appuser/.local
ENV PATH=/home/appuser/.local/bin:$PATH
# Copy backend code
COPY --chown=appuser:appuser . .
# Copy built frontend assets
COPY --from=frontend-builder --chown=appuser:appuser /app/frontend/dist /app/frontend/dist
RUN chown -R appuser:appuser /app
USER appuser
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
