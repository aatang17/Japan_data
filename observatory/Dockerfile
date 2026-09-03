FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY web ./web
COPY seed ./seed
# The EDINET extractors run here now, not only on a laptop. They are what
# turns the capture jobs' archive into the served equity tables, and keeping
# them out of the image is exactly how the 5% filings went four weeks stale in
# August 2026 while the archive kept growing. Code and the filer registry
# only — the raw archive itself lives in the bucket.
COPY equity ./equity
COPY start.sh ./
RUN chmod +x start.sh

# data/ is a mounted volume in production: the DuckDB file and the raw
# source archive must survive redeploys.
ENV PYTHONUNBUFFERED=1

# The extractors default to a laptop's archive path, which does not exist
# here. Point them at the volume: only the daily-list cache and the bucket
# listing are written there (a few MB), never the filings themselves, which
# stay in the bucket and are streamed as needed.
ENV EDINET_ARCHIVE_ROOT=/app/data/edinet-cache
ENV EDINET_LISTING_CACHE=/app/data/edinet-cache/listing

CMD ["./start.sh"]
