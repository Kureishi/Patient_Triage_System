"""
The persistent worker loop behind the web UI's job queue.

This is what makes p-tri-ui a "service" rather than a request/response
script: this loop is started once, when the process comes up, and keeps
consuming queued jobs for as long as the process is alive -- independent of
whether any browser tab is open or polling. If the process is restarted,
anything still 'queued' in the database picks up right where it left off,
and anything caught mid-'running' from a previous crash gets requeued by
db.recover_interrupted_jobs() at startup.
"""
import os
import time
import traceback

from . import db
from .pipeline import process_report


def run_worker_loop(conn, graph_app, input_dir: str, output_dir: str,
                     poll_interval: float = 0.5, stop_event=None):
    while stop_event is None or not stop_event.is_set():
        job = db.claim_next_job(conn)
        if job is None:
            time.sleep(poll_interval)
            continue

        source_path = os.path.join(input_dir, job["source_filename"])
        try:
            out_path = process_report(graph_app, source_path, output_dir, conn)
            db.mark_job_succeeded(conn, job["id"], os.path.basename(out_path))
        except Exception as e:
            traceback.print_exc()
            db.mark_job_failed(conn, job["id"], e)
