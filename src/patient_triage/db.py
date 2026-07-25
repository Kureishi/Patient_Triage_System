"""
Facade over the two job-store backends. Every other module imports this
(`from . import db` / `from .. import db`) and calls db.init_db(),
db.enqueue_job(), etc. without needing to know or care which backend is
selected -- that's controlled entirely by config.DB_BACKEND
(TRIAGE_DB_BACKEND env var: "sqlite" (default) or "postgres").
"""
from . import config

if config.DB_BACKEND == "postgres":
    from .db_postgres import (  # noqa: F401
        init_db,
        log_event,
        enqueue_job,
        get_job,
        claim_next_job,
        mark_job_running,
        mark_job_succeeded,
        mark_job_failed,
        recover_interrupted_jobs,
        batch_status,
    )
else:
    from .db_sqlite import (  # noqa: F401
        init_db,
        log_event,
        enqueue_job,
        get_job,
        claim_next_job,
        mark_job_running,
        mark_job_succeeded,
        mark_job_failed,
        recover_interrupted_jobs,
        batch_status,
    )
