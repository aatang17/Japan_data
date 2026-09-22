FROM python:3.12-slim

WORKDIR /app

# pdftotext, for the banks' Basel III rate-risk tables: those exist only
# inside each bank's own disclosure PDF (equity/irrbb_collect.py).
RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils \
    && rm -rf /var/lib/apt/lists/*

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
# Hand-typed party curation. The live store is data/admin/parties.json on the
# volume; this is the git-committed copy, and it seeds an ABSENT store on a
# fresh volume. Left out of the image, the admin console comes up with zero
# profiles on a machine that has never had them — which is exactly what it did
# on the first deploy that shipped the registry.
COPY curation ./curation
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

# How deep the container digs each night. Every extractor resumes from a
# watermark and so only ever walks FORWARD: a database built forward from the
# day an extractor was written stays as shallow as its first run, however deep
# the archive behind it is, and no freshness check can see it — the 5% filings
# sat at fourteen weeks with 74,000 filings in the bucket. With this set, each
# nightly run also reads this many archive days below its own floor until it
# reaches the bottom, and a cold start takes one slice instead of the whole
# archive with the port closed. Forty days is about ten minutes of the refresh
# window for every extractor together, and reaches the floor of a five-year
# archive in roughly a month. Set to 0 to go back to forward-only.
ENV EQUITY_CATCH_UP_DAYS=40

CMD ["./start.sh"]
