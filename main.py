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

import config
from llm_backends import get_backend
from pdf_utils import extract_text_from_pdf, generate_recommendation_pdf
from graph import build_graph
from db import init_db, log_event


def process_one(app, backend, conn, pdf_path: str, output_dir: str):
    patient_id = os.path.splitext(os.path.basename(pdf_path))[0]
    print(f"\n--- Processing {pdf_path} (patient_id={patient_id}) ---")

    raw_text = extract_text_from_pdf(pdf_path)

    initial_state = {
        "patient_id": patient_id,
        "source_file": os.path.basename(pdf_path),
        "raw_text": raw_text,
        "pending_queue": [],
        "current_case": None,
        "retry_counts": {},
        "all_classifications": [],
        "verdicts": [],
        "escalations": [],
        "audit_log": [],
    }

    final_state = app.invoke(initial_state, config={"recursion_limit": 100})

    log_event(conn, patient_id, os.path.basename(pdf_path), "-", "run_complete",
               f"{len(final_state['verdicts'])} resolved, {len(final_state['escalations'])} escalated")

    out_path = os.path.join(output_dir, f"{patient_id}_recommendation.pdf")
    generate_recommendation_pdf(
        out_path,
        patient_id=patient_id,
        source_file=os.path.basename(pdf_path),
        verdicts=[v.model_dump() for v in final_state["verdicts"]],
        escalations=[e.model_dump() for e in final_state["escalations"]],
        audit_log=final_state["audit_log"],
    )
    print(f"  -> wrote {out_path}")
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
    for pdf_path in pdf_files:
        try:
            process_one(app, backend, conn, pdf_path, args.output_dir)
            successes += 1
        except Exception as e:
            failures += 1
            print(f"  !! FAILED on {pdf_path}: {e}")
            traceback.print_exc()

    print(f"\nDone. {successes} succeeded, {failures} failed. Output in: {args.output_dir}")


if __name__ == "__main__":
    main()
