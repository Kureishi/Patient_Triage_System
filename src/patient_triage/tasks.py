"""
The RQ-callable task function. RQ (via Redis) dispatches calls to this
function across however many `rq worker patient_triage` processes you have
running -- possibly on different machines, each pointed at the same
DATABASE_URL (Postgres) and the same shared input/output directory (e.g. an
NFS mount at the same path on every machine).

Run a worker with:
    rq worker patient_triage --url $REDIS_URL

The triage graph (LLM backend + LangGraph) is expensive to build, so each
worker process builds it once and reuses it across every task it handles,
rather than rebuilding it per job.
"""
import os

from . import config, db
from .llm_backends import get_backend
from .graph import build_graph
from .pipeline import process_report

_graph_app_cache = None


def _get_graph_app():
    global _graph_app_cache
    if _graph_app_cache is None:
        backend = get_backend(config.DEFAULT_BACKEND)
        _graph_app_cache = build_graph(backend)
    return _graph_app_cache


def process_job_task(job_id: str):
    """
    Runs one queued job end to end: look up which file it points to, run it
    through the triage graph, and record the result. This is the function
    RQ workers actually call -- one invocation per job, regardless of which
    machine picks it up.
    """
    conn = db.init_db()
    job = db.get_job(conn, job_id)
    if job is None:
        return

    input_dir = os.path.abspath(os.environ.get("TRIAGE_INPUT_DIR", config.DEFAULT_INPUT_DIR))
    output_dir = os.path.abspath(os.environ.get("TRIAGE_OUTPUT_DIR", config.DEFAULT_OUTPUT_DIR))
    os.makedirs(output_dir, exist_ok=True)
    source_path = os.path.join(input_dir, job["source_filename"])

    db.mark_job_running(conn, job_id)
    try:
        graph_app = _get_graph_app()
        out_path = process_report(graph_app, source_path, output_dir, conn)
        db.mark_job_succeeded(conn, job_id, os.path.basename(out_path))
    except Exception as e:
        db.mark_job_failed(conn, job_id, e)
        raise  # re-raise so RQ's own retry/failure tracking also sees it
