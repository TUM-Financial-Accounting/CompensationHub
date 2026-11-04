"""data/raw for hosted deploys built from GitHub. The raw files are not in git, so a copy of the
folder is kept as one tar.gz in Postgres (DATABASE_URL) and unpacked at startup when the machine
has no data/raw. Upload the local folder after changing it:

    DATABASE_URL=<Railway Postgres DATABASE_PUBLIC_URL> uv run python -m app.rawdata
"""

import io
import os
import tarfile

import psycopg

from .panel import RAW

TABLE = """CREATE TABLE IF NOT EXISTS raw_data (
    id int PRIMARY KEY,
    tar bytea NOT NULL,
    saved timestamptz NOT NULL DEFAULT now())"""


def restore() -> None:
    """Unpack the stored data/raw if there is none here; a local data/raw always wins."""
    url = os.getenv("DATABASE_URL")
    if RAW.is_dir() or not url:
        return
    with psycopg.connect(url, connect_timeout=5) as db:
        db.execute(TABLE)
        row = db.execute("SELECT tar FROM raw_data WHERE id = 1").fetchone()
    if row is None:
        raise RuntimeError("No data/raw here and none stored in Postgres: run `python -m app.rawdata`.")
    with tarfile.open(fileobj=io.BytesIO(row[0])) as tar:
        tar.extractall(RAW.parent, filter="data")


def upload() -> None:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        tar.add(RAW, arcname=RAW.name)
    with psycopg.connect(os.environ["DATABASE_URL"]) as db:
        db.execute(TABLE)
        db.execute("INSERT INTO raw_data (id, tar) VALUES (1, %s) ON CONFLICT (id) "
                   "DO UPDATE SET tar = EXCLUDED.tar, saved = now()", (buf.getvalue(),))
    print(f"Stored {RAW} in Postgres ({len(buf.getvalue()) // 1024} kB).")


if __name__ == "__main__":
    upload()
