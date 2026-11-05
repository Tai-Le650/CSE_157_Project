FROM node:24-slim AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.14-slim
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    OPENBLAS_NUM_THREADS=1 \
    OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    MALLOC_ARENA_MAX=2
RUN useradd --create-home --uid 1000 app
WORKDIR /app
COPY requirements-hosted.txt ./
RUN pip install -r requirements-hosted.txt
COPY backend/ backend/
COPY src/imu_utils.py src/imu_utils.py
COPY --from=frontend /build/frontend/dist frontend/dist
RUN python -m compileall -q backend src
USER app
EXPOSE 10000
CMD ["python", "backend/run.py", "--hosted"]
