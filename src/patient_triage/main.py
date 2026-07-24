#!/usr/bin/env python3
"""
Batch folder processor for the patient triage multi-agent system.

Usage:
    python main.py --input-dir input_reports --output-dir output_recommendations --backend lmstudio
    python main.py --backend anthropic --model claude-sonnet-4-6
    python main.py --backend mock            # offline test run, no LLM needed

Each PDF in --input-dir is processed independently through the graph and
produces one recommendation PDF in --output-dir.
"""
import argparse
import os
import sys
import glob
import traceback

from tqdm import tqdm

from . import config
from .llm_backends import get_backend
from .pdf_utils import extract_text_from_pdf
from .graph import build_graph
from .db import init_db, log_event
from .pipeline import process_report


def process_one(app, backend, conn, pdf_path: str, output_dir: str):
    patient_id = os.path.splitext(os.path.basename(pdf_path))[0]
    out_path = process_report(app, pdf_path, output_dir, conn)
    return out_path


def main():
    parser = argparse.ArgumentParser(description="Patient report triage batch processor")
    parser.add_argument("--input-dir", default=config.DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", default=config.DEFAULT_OUTPUT_DIR)
    parser.add_argument("--backend", default=config.DEFAULT_BACKEND,
                         choices=["anthropic", "lmstudio", "mock"])
    parser.add_argument("--model", default=None, help="override model name for the chosen backend")
    args = parser.parse_args()

    os.makedirs(args.input_dir, exist_ok=True)
    os.makedirs(args.output_dir, exist_ok=True)

    if args.model:
        if args.backend == "anthropic":
            config.ANTHROPIC_MODEL = args.model
        elif args.backend == "lmstudio":
            config.LM_STUDIO_MODEL = args.model

    backend = get_backend(args.backend)
    app = build_graph(backend)
    conn = init_db()

    pdf_files = sorted(glob.glob(os.path.join(args.input_dir, "*.pdf")))
    if not pdf_files:
        print(f"No PDF files found in {args.input_dir}. Place patient report PDFs there and re-run.")
        sys.exit(0)

    successes, failures = 0, 0
    progress = tqdm(pdf_files, desc="Processing reports", unit="report")
    for pdf_path in progress:
        progress.set_postfix_str(os.path.basename(pdf_path))
        try:
            out_path = process_one(app, backend, conn, pdf_path, args.output_dir)
            progress.write(f"  -> wrote {out_path}")
            successes += 1
        except Exception as e:
            failures += 1
            progress.write(f"  !! FAILED on {pdf_path}: {e}")
            traceback.print_exc()

    print(f"\nDone. {successes} succeeded, {failures} failed. Output in: {args.output_dir}")


if __name__ == "__main__":
    main()
