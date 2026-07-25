"""
Local web UI / service for the triage system.

- Upload patient report PDFs
- Enqueue processing jobs onto a durable, SQLite-backed queue
- A single persistent background worker (worker.run_worker_loop) consumes
  that queue for the lifetime of the process -- jobs survive a restart
  (see db.recover_interrupted_jobs), and keep progressing even if no
  browser tab is open watching them.
- View any input report or generated recommendation inline in the browser,
  using the browser's native PDF viewer inside an <iframe> -- no extra
  JS library needed, works in Chrome/Firefox/Edge/Safari out of the box.

Run with: p-tri-ui
Single-machine, single-process design: no auth, and the SQLite job queue
assumes one worker thread. See README ("Running as a persistent service")
before exposing this beyond localhost or scaling it out.
"""
import os
import uuid
import threading
from werkzeug.utils import secure_filename
from flask import Flask, render_template, request, redirect, url_for, send_file, flash, jsonify

from .. import config
from ..llm_backends import get_backend
from ..graph import build_graph
from .. import db as db_module
from ..worker import run_worker_loop


def _safe_pdf_path(base_dir: str, filename: str) -> str:
    """Prevent path traversal: only allow a bare filename within base_dir."""
    name = secure_filename(filename)
    path = os.path.join(base_dir, name)
    if not name.lower().endswith(".pdf") or not os.path.abspath(path).startswith(os.path.abspath(base_dir)):
        raise ValueError("Invalid filename")
    return path


def create_app():
    app = Flask(__name__)
    app.secret_key = os.environ.get("TRIAGE_UI_SECRET", "dev-local-only")

    input_dir = os.path.abspath(os.environ.get("TRIAGE_INPUT_DIR", config.DEFAULT_INPUT_DIR))
    output_dir = os.path.abspath(os.environ.get("TRIAGE_OUTPUT_DIR", config.DEFAULT_OUTPUT_DIR))
    os.makedirs(input_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    backend_name = os.environ.get("TRIAGE_LLM_BACKEND", config.DEFAULT_BACKEND)
    backend = get_backend(backend_name)
    graph_app = build_graph(backend)
    conn = db_module.init_db()

    # Requeue anything left "running" from a previous crash, then start the
    # persistent worker. This thread runs for the life of the process,
    # independent of any single HTTP request.
    recovered = db_module.recover_interrupted_jobs(conn)
    if recovered:
        print(f"Recovered {recovered} job(s) interrupted by a previous shutdown/crash.")
    threading.Thread(
        target=run_worker_loop, args=(conn, graph_app, input_dir, output_dir), daemon=True,
    ).start()

    def list_pdfs(d):
        return sorted(f for f in os.listdir(d) if f.lower().endswith(".pdf"))

    @app.route("/")
    def index():
        inputs = list_pdfs(input_dir)
        outputs = list_pdfs(output_dir)
        has_recommendation = {
            os.path.splitext(o)[0].removesuffix("_recommendation") for o in outputs
        }
        return render_template(
            "index.html",
            inputs=inputs,
            outputs=outputs,
            has_recommendation=has_recommendation,
            backend_name=backend_name,
        )

    @app.route("/upload", methods=["POST"])
    def upload():
        files = [f for f in request.files.getlist("report") if f and f.filename]
        if not files:
            flash("Please choose one or more .pdf files to upload.", "error")
            return redirect(url_for("index"))

        saved, skipped = [], []
        for file in files:
            # webkitdirectory uploads send a relative path (e.g. "myfolder/report.pdf");
            # secure_filename collapses that to a safe bare filename.
            original_name = file.filename
            if not original_name.lower().endswith(".pdf"):
                skipped.append(original_name)
                continue
            name = secure_filename(os.path.basename(original_name))
            if not name:
                skipped.append(original_name)
                continue
            file.save(os.path.join(input_dir, name))
            saved.append(name)

        if saved:
            flash(f"Uploaded {len(saved)} report(s): {', '.join(saved)}.", "ok")
        if skipped:
            flash(f"Skipped {len(skipped)} non-PDF file(s).", "error")
        return redirect(url_for("index"))

    @app.route("/jobs/enqueue", methods=["POST"])
    def jobs_enqueue():
        """
        Enqueues processing jobs onto the durable queue and returns
        immediately -- the actual work happens in the background worker,
        not in this request. Body: {"filenames": [...]}  (omit/empty to
        mean "everything currently pending").
        """
        payload = request.get_json(silent=True) or {}
        requested = payload.get("filenames")

        if requested:
            filenames = [secure_filename(f) for f in requested if f]
        else:
            inputs = list_pdfs(input_dir)
            outputs = list_pdfs(output_dir)
            already_done = {os.path.splitext(o)[0].removesuffix("_recommendation") for o in outputs}
            filenames = [f for f in inputs if os.path.splitext(f)[0] not in already_done]

        filenames = [f for f in filenames if os.path.isfile(os.path.join(input_dir, f))]
        if not filenames:
            return jsonify({"total": 0})

        batch_id = uuid.uuid4().hex
        for f in filenames:
            db_module.enqueue_job(conn, batch_id, f)

        return jsonify({"batch_id": batch_id, "total": len(filenames)})

    @app.route("/jobs/status/<batch_id>")
    def jobs_status(batch_id):
        return jsonify(db_module.batch_status(conn, batch_id))

    @app.route("/view/<kind>/<path:filename>")
    def view(kind, filename):
        base = input_dir if kind == "input" else output_dir
        try:
            path = _safe_pdf_path(base, filename)
        except ValueError:
            return "Invalid file", 400
        if not os.path.isfile(path):
            return "Not found", 404
        # inline (not as_attachment) so the browser renders it instead of downloading it;
        # download_name gives the browser a real filename to fall back on if the PDF's
        # own Title metadata is missing.
        return send_file(path, mimetype="application/pdf", download_name=os.path.basename(path))

    return app


def main():
    app = create_app()
    port = int(os.environ.get("PORT", 5000))
    print(f"Patient Triage UI running at http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", port=port, debug=False)


if __name__ == "__main__":
    main()
