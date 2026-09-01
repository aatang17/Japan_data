"""DuckDB connection and the generic Observatory core schema.

Nothing in this schema is Japan- or CPI-specific: datasets, sources,
source_artifacts, releases, series, observations. Dataset-specific
semantics (which series is "headline", how a file is parsed) live in
the per-dataset adapter, never here.
"""
import pathlib
import threading

import duckdb

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
DB_PATH = DATA_DIR / "observatory.duckdb"

SCHEMA = """
CREATE SEQUENCE IF NOT EXISTS seq_artifact START 1;
CREATE SEQUENCE IF NOT EXISTS seq_release START 1;
CREATE SEQUENCE IF NOT EXISTS seq_series START 1;

CREATE TABLE IF NOT EXISTS datasets (
    slug        TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    country     TEXT NOT NULL,
    agency      TEXT NOT NULL,
    agency_ja   TEXT,
    base        TEXT,               -- e.g. '2020=100'
    frequency   TEXT NOT NULL,      -- 'monthly'
    description TEXT
);

CREATE TABLE IF NOT EXISTS sources (
    source_id   TEXT PRIMARY KEY,   -- stable external id, e.g. e-Stat statInfId
    dataset     TEXT NOT NULL REFERENCES datasets(slug),
    name        TEXT NOT NULL,
    name_ja     TEXT,
    url         TEXT NOT NULL,
    license_note TEXT
);

CREATE TABLE IF NOT EXISTS source_artifacts (
    artifact_id  BIGINT PRIMARY KEY DEFAULT nextval('seq_artifact'),
    source_id    TEXT NOT NULL REFERENCES sources(source_id),
    url          TEXT NOT NULL,
    retrieved_at TIMESTAMP NOT NULL,
    sha256       TEXT NOT NULL,
    path         TEXT NOT NULL,
    bytes        BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS releases (
    release_id    BIGINT PRIMARY KEY DEFAULT nextval('seq_release'),
    dataset       TEXT NOT NULL REFERENCES datasets(slug),
    artifact_id   BIGINT NOT NULL REFERENCES source_artifacts(artifact_id),
    label         TEXT NOT NULL,
    latest_period DATE NOT NULL,
    ingested_at   TIMESTAMP NOT NULL,
    status        TEXT NOT NULL,    -- 'published' | 'superseded' | 'rejected'
    validation    TEXT              -- JSON summary of the gates that ran
);

CREATE TABLE IF NOT EXISTS series (
    series_id  BIGINT PRIMARY KEY DEFAULT nextval('seq_series'),
    dataset    TEXT NOT NULL REFERENCES datasets(slug),
    code       TEXT NOT NULL,       -- official item/group code
    name_en    TEXT NOT NULL,
    name_ja    TEXT,
    unit       TEXT NOT NULL,       -- 'index'
    weight_per_10000 DOUBLE,
    sort_order INTEGER,
    -- FALSE once a source stops publishing a series. Series rows are never
    -- deleted: series_id is the stable identity that vintage history and any
    -- external reference hang off, so it must outlive the series itself.
    active     BOOLEAN DEFAULT TRUE,
    UNIQUE (dataset, code)
);

CREATE TABLE IF NOT EXISTS observations (
    series_id  BIGINT NOT NULL REFERENCES series(series_id),
    period     DATE NOT NULL,       -- first day of the reference month
    value      DOUBLE NOT NULL,     -- missing months are absent, never 0
    release_id BIGINT NOT NULL REFERENCES releases(release_id),
    PRIMARY KEY (series_id, period)
);

-- Point-in-time history: what each observation was worth at each release.
--
-- APPEND-ONLY. Nothing in the codebase may UPDATE or DELETE a row here; a
-- revision is a new row carrying the release that introduced it. This table
-- is the commercial asset (see CLAUDE.md, Ingest Guardrails 2) -- `observations`
-- above is only the live view of it, kept separate so the serving path stays
-- a plain lookup.
--
-- Change-only: a release writes a row for a (series, period) it introduces or
-- changes, not for one it merely republishes unchanged. The value as of any
-- date is therefore the newest row at or before that date, which is why a
-- withdrawn observation needs an explicit NULL tombstone rather than silence.
CREATE TABLE IF NOT EXISTS observation_vintages (
    series_id  BIGINT NOT NULL REFERENCES series(series_id),
    period     DATE NOT NULL,
    value      DOUBLE,              -- NULL = withdrawn by this release
    release_id BIGINT NOT NULL REFERENCES releases(release_id),
    PRIMARY KEY (series_id, period, release_id)
);
"""

# Applied to existing database files, which were created before the columns
# above existed. Each statement must be safe to re-run on every open.
# DuckDB will not add a column with a NOT NULL constraint, so `active` is
# nullable and back-filled here; ingest always writes it explicitly.
MIGRATIONS = [
    "ALTER TABLE series ADD COLUMN IF NOT EXISTS active BOOLEAN DEFAULT TRUE",
    "UPDATE series SET active = TRUE WHERE active IS NULL",
]


def connect(read_only=False):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH), read_only=read_only)
    if not read_only:
        con.execute(SCHEMA)
        for statement in MIGRATIONS:
            con.execute(statement)
    return con


# --- the API's shared reader -------------------------------------------------

_READER = None
_READER_VERSION = None
_READER_LOCK = threading.Lock()


def file_version():
    """Identity of the database file — changes when ingest rewrites it.

    Used as the cache stamp for served responses, so a new release invalidates
    everything derived from the old one without any explicit bookkeeping.
    """
    try:
        st = DB_PATH.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def read_cursor():
    """A cursor on the process-wide read-only connection.

    One connection per process rather than one per request: in production
    data/ is a network-mounted volume, so opening the file costs a round trip
    and throws away DuckDB's page cache each time. A cursor is ~0.1ms against
    ~4ms for a fresh connection, and siblings are safe to use from the
    threadpool FastAPI runs sync endpoints on.

    The connection is reopened if the file changes underneath it. Note that
    holding it open blocks a *writer* in another process: run ingest before
    the server, as start.sh does, not alongside it.
    """
    global _READER, _READER_VERSION
    version = file_version()
    with _READER_LOCK:
        if _READER is None or _READER_VERSION != version:
            if _READER is not None:
                _READER.close()
                _READER = None
            _READER = duckdb.connect(str(DB_PATH), read_only=True)
            _READER_VERSION = version
        return _READER.cursor()
