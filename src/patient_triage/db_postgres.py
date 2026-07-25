"""
Postgres-backed job store -- same interface as db_sqlite.py, used when
config.DB_BACKEND == "postgres" (see the db.py facade).

In the distributed deployment (Postgres + Redis/RQ), Postgres is the durable
record of what jobs exist and their status; RQ (backed by Redis) is what
actually dispatches each job to a worker process, possibly on a different
machine. That split matters for claim_next_job(): in the local/SQLite mode,
our own worker loop polls this table to decide what to run next, so it needs
an atomic "claim" operation. In the Postgres/RQ mode, RQ has already decided
which worker runs which job (that's its whole purpose as a broker), so we
don't strictly need atomic claiming here -- but claim_next_job() is kept for
interface parity / for anyone running a poll-based worker against Postgres
without RQ, and it uses `FOR UPDATE SKIP LOCKED`, which is the standard,
correct way to let multiple Postgres readers claim distinct rows safely.
"""
import time
import uuid
import threading

try:
    import psycopg2
    import psycopg2.extras
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "Postgres support requires the 'scale' extra: pip install patient-triage[scale]"
    ) from e

from . import config

# As in db_sqlite.py: guards concurrent use of one shared connection object
# within a single process (e.g. the Flask app's request-handling threads).
# Different processes/machines each get their own connection, so this lock
# doesn't need to (and can't) coordinate across machines -- Postgres's own
# row-level locking (see FOR UPDATE SKIP LOCKED below) handles that.
_lock = threading.Lock()


def init_db(dsn: str = None):
    dsn = dsn or config.DATABASE_URL
    if not dsn:
        raise ValueError(
            "DATABASE_URL is not set. Set it to a Postgres connection string, "
            "e.g. postgresql://user:pass@host:5432/patient_triage"
        )
    conn = psycopg2.connect(dsn)
    conn.autocommit = False
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS case_events (
                id SERIAL PRIMARY KEY,
                patient_id TEXT,
                source_file TEXT,
                case_id TEXT,
                event TEXT,
                detail TEXT,
                ts DOUBLE PRECISION
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                batch_id TEXT NOT NULL,
                source_filename TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                output_filename TEXT,
                error TEXT,
                created_at DOUBLE PRECISION NOT NULL,
                started_at DOUBLE PRECISION,
                finished_at DOUBLE PRECISION
            )
        """)
    conn.commit()
    return conn


def log_event(conn, patient_id, source_file, case_id, event, detail=""):
    with _lock:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO case_events (patient_id, source_file, case_id, event, detail, ts) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                (patient_id, source_file, case_id, event, detail, time.time()),
            )
        conn.commit()


# ---- Job queue -----------------------------------------------------------

def enqueue_job(conn, batch_id: str, source_filename: str) -> str:
    job_id = uuid.uuid4().hex
    with _lock:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO jobs (id, batch_id, source_filename, status, created_at) "
                "VALUES (%s,%s,%s,'queued',%s)",
                (job_id, batch_id, source_filename, time.time()),
            )
        conn.commit()
    return job_id


def get_job(conn, job_id: str):
    with _lock:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, batch_id, source_filename, status FROM jobs WHERE id=%s", (job_id,)
            )
            row = cur.fetchone()
    if row is None:
        return None
    return {"id": row[0], "batch_id": row[1], "source_filename": row[2], "status": row[3]}


def claim_next_job(conn):
    """
    Atomically claim the oldest queued job using FOR UPDATE SKIP LOCKED, so
    this is safe even with several processes (on several machines) polling
    the same table concurrently -- each gets a distinct row, none block on
    each other. Returns {"id":..., "source_filename":...} or None.
    """
    with _lock:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, source_filename FROM jobs
                WHERE status='queued'
                ORDER BY created_at
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            """)
            row = cur.fetchone()
            if row is None:
                conn.commit()
                return None
            job_id, source_filename = row
            cur.execute(
                "UPDATE jobs SET status='running', started_at=%s WHERE id=%s",
                (time.time(), job_id),
            )
        conn.commit()
        return {"id": job_id, "source_filename": source_filename}


def mark_job_running(conn, job_id: str):
    with _lock:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE jobs SET status='running', started_at=%s WHERE id=%s",
                (time.time(), job_id),
            )
        conn.commit()


def mark_job_succeeded(conn, job_id: str, output_filename: str):
    with _lock:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE jobs SET status='succeeded', output_filename=%s, finished_at=%s WHERE id=%s",
                (output_filename, time.time(), job_id),
            )
        conn.commit()


def mark_job_failed(conn, job_id: str, error) -> None:
    with _lock:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE jobs SET status='failed', error=%s, finished_at=%s WHERE id=%s",
                (str(error), time.time(), job_id),
            )
        conn.commit()


def recover_interrupted_jobs(conn) -> int:
    """
    For the poll-based worker path (no RQ): requeue anything stuck 'running'
    from a previous crash. If you're using RQ, prefer RQ's own `Retry` /
    `job_timeout` for crash recovery (see tasks.py) -- this is here mainly
    for interface parity and for anyone running Postgres without RQ.
    """
    with _lock:
        with conn.cursor() as cur:
            cur.execute("UPDATE jobs SET status='queued', started_at=NULL WHERE status='running'")
            count = cur.rowcount
        conn.commit()
        return count


def batch_status(conn, batch_id: str) -> dict:
    with _lock:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status, source_filename, error FROM jobs WHERE batch_id=%s",
                (batch_id,),
            )
            rows = cur.fetchall()

    succeeded = [r[1] for r in rows if r[0] == "succeeded"]
    failed = [f"{r[1]} ({r[2]})" for r in rows if r[0] == "failed"]
    running_files = [r[1] for r in rows if r[0] == "running"]
    still_pending = any(r[0] in ("queued", "running") for r in rows)

    return {
        "total": len(rows),
        "current": len(succeeded) + len(failed),
        "current_file": running_files[0] if running_files else None,
        "succeeded": succeeded,
        "failed": failed,
        "running": still_pending,
    }
