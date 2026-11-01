FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    EJS_DATA_DIR=/data EJS_SEEN_PATH=/data/seen_jobs.json EJS_BOARDS_FILE=/config/boards.yaml
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[ui]" && useradd -m -u 10001 ejs && mkdir -p /data /config && chown ejs /data
USER ejs
VOLUME ["/data"]
ENTRYPOINT ["executive-job-search"]
CMD ["run"]
