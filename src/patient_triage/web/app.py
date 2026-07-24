"""
Minimal local web UI for the triage system.

- Upload patient report PDFs
- Trigger processing (runs the same graph as the CLI, via pipeline.process_report)
- View any input report or generated recommendation inline in the browser,
  using the browser's native PDF viewer inside an <iframe> -- no extra
  JS library needed, works in Chrome/Firefox/Edge/Safari out of the box.

Run with: p-tri-ui
This is a local single-user tool -- not hardened for multi-user or
internet-facing deployment (see README before exposing it beyond localhost).
"""
import os
from werkzeug.utils import secure_filename
from flask import Flask, render_template, request, redirect, url_for, send_file, flash

from .. import config
from ..llm_backends import get_backend
from ..graph import build_graph
from ..db import init_db
from ..pipeline import process_report


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
    conn = init_db()

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
        file = request.files.get("report")
        if not file or not file.filename.lower().endswith(".pdf"):
            flash("Please choose a .pdf file to upload.", "error")
            return redirect(url_for("index"))
        name = secure_filename(file.filename)
        file.save(os.path.join(input_dir, name))
        flash(f"Uploaded {name}.", "ok")
        return redirect(url_for("index"))

    @app.route("/process/<path:filename>", methods=["POST"])
    def process(filename):
        try:
            pdf_path = _safe_pdf_path(input_dir, filename)
        except ValueError:
            flash("Invalid file.", "error")
            return redirect(url_for("index"))
        if not os.path.isfile(pdf_path):
            flash(f"{filename} not found.", "error")
            return redirect(url_for("index"))
        try:
            out_path = process_report(graph_app, pdf_path, output_dir, conn)
            flash(f"Generated recommendation: {os.path.basename(out_path)}", "ok")
        except Exception as e:
            flash(f"Failed to process {filename}: {e}", "error")
        return redirect(url_for("index"))

    @app.route("/view/<kind>/<path:filename>")
    def view(kind, filename):
        base = input_dir if kind == "input" else output_dir
        try:
            path = _safe_pdf_path(base, filename)
        except ValueError:
            return "Invalid file", 400
        if not os.path.isfile(path):
            return "Not found", 404
        # inline (not as_attachment) so the browser renders it instead of downloading it
        return send_file(path, mimetype="application/pdf")

    return app


def main():
    app = create_app()
    port = int(os.environ.get("PORT", 5000))
    print(f"Patient Triage UI running at http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", port=port, debug=False)


if __name__ == "__main__":
    main()
