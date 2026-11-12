FROM node:22-bookworm-slim@sha256:4b150b48b4116e2a22f2c39cc27025fbf4f153e2078fd3b14d159fdb5c7279da AS web-build
WORKDIR /build/apps/web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web/ ./
RUN npm run build

FROM python:3.13-slim-bookworm@sha256:281d39ff02e3b389401586134ff9e6572954687822a58055ec07a60ded4e0b7f AS api-build
WORKDIR /build
COPY requirements.lock.txt ./
COPY apps/api/ ./apps/api/
RUN python -m pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.lock.txt ./apps/api

FROM python:3.13-slim-bookworm@sha256:281d39ff02e3b389401586134ff9e6572954687822a58055ec07a60ded4e0b7f AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY --from=api-build /wheels /wheels
RUN python -m pip install --no-cache-dir --no-index --find-links=/wheels mandate-api \
    && rm -rf /wheels \
    && groupadd --gid 10001 mandate \
    && useradd --uid 10001 --gid mandate --no-create-home mandate
COPY --from=web-build --chown=mandate:mandate /build/apps/web/dist /app/apps/web/dist
COPY --chown=mandate:mandate eval_results.json /app/eval_results.json
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; port = os.environ.get('PORT', '8000'); urllib.request.urlopen(f'http://127.0.0.1:{port}/api/ready', timeout=3)"
CMD ["sh", "-c", "exec python -m uvicorn mandate.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
