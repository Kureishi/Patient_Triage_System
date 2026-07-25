import sqlite3
import time
import uuid
import threading
from . import config

# Guards all access to the shared connection: SQLite connections aren't
# safe for concurrent use across threads even with check_same_thread=False,
# and this connection is shared between Flask's request threads and the
# background worker thread.
_lock = threading.Lock()


def init_db(path: str = None):
    path = path or config.DB_PATH
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS case_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id TEXT,
            source_file TEXT,
            case_id TEXT,
            event TEXT,
            detail TEXT,
            ts REAL
        )
    """)
    # The persistent job queue behind the web UI's "Process"/"Process All"
    # buttons. Living in SQLite (rather than an in-memory dict) means job
    # state survives a service restart -- anything left "queued" is still
    # queued when the process comes back up, and recover_interrupted_jobs()
    # requeues anything that was "running" when the process went down.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            batch_id TEXT NOT NULL,
            source_filename TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',  -- queued | running | succeeded | failed
            output_filename TEXT,
            error TEXT,
            created_at REAL NOT NULL,
            started_at REAL,
            finished_at REAL
        )
    """)
    conn.commit()
    return conn


def log_event(conn, patient_id, source_file, case_id, event, detail=""):
    with _lock:
        conn.execute(
            "INSERT INTO case_events (patient_id, source_file, case_id, event, detail, ts) VALUES (?,?,?,?,?,?)",
            (patient_id, source_file, case_id, event, detail, time.time()),
        )
        conn.commit()


# ---- Job queue -----------------------------------------------------------

def enqueue_job(conn, batch_id: str, source_filename: str) -> str:
    job_id = uuid.uuid4().hex
    with _lock:
        conn.execute(
            "INSERT INTO jobs (id, batch_id, source_filename, status, created_at) VALUES (?,?,?,'queued',?)",
            (job_id, batch_id, source_filename, time.time()),
        )
        conn.commit()
    return job_id


def claim_next_job(conn):
    """
    Atomically claim the oldest queued job (transactional, so this stays
    correct even if more than one worker/process is polling). Returns
    {"id": ..., "source_filename": ...} or None if the queue is empty.
    """
    with _lock:
        cur = conn.execute(
            "SELECT id, source_filename FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1"
        )
        row = cur.fetchone()
        if row is None:
            return None
        job_id, source_filename = row
        conn.execute(
            "UPDATE jobs SET status='running', started_at=? WHERE id=? AND status='queued'",
            (time.time(), job_id),
        )
        conn.commit()
        return {"id": job_id, "source_filename": source_filename}


def get_job(conn, job_id: str):
    with _lock:
        row = conn.execute(
            "SELECT id, batch_id, source_filename, status FROM jobs WHERE id=?", (job_id,)
        ).fetchone()
    if row is None:
        return None
    return {"id": row[0], "batch_id": row[1], "source_filename": row[2], "status": row[3]}


def mark_job_running(conn, job_id: str):
    with _lock:
        conn.execute(
            "UPDATE jobs SET status='running', started_at=? WHERE id=?",
            (time.time(), job_id),
        )
        conn.commit()


def mark_job_succeeded(conn, job_id: str, output_filename: str):
    with _lock:
        conn.execute(
            "UPDATE jobs SET status='succeeded', output_filename=?, finished_at=? WHERE id=?",
            (output_filename, time.time(), job_id),
        )
        conn.commit()


def mark_job_failed(conn, job_id: str, error) -> None:
    with _lock:
        conn.execute(
            "UPDATE jobs SET status='failed', error=?, finished_at=? WHERE id=?",
            (str(error), time.time(), job_id),
        )
        conn.commit()


def recover_interrupted_jobs(conn) -> int:
    """
    Call once at service startup. Any job still marked 'running' means the
    process died mid-job last time -- requeue those rather than leaving them
    stuck forever.
    """
    with _lock:
        cur = conn.execute("UPDATE jobs SET status='queued', started_at=NULL WHERE status='running'")
        conn.commit()
        return cur.rowcount


def batch_status(conn, batch_id: str) -> dict:
    with _lock:
        rows = conn.execute(
            "SELECT status, source_filename, error FROM jobs WHERE batch_id=?",
            (batch_id,),
        ).fetchall()

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
