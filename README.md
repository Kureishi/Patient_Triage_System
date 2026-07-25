# Patient Report Triage — Multi-Agent System

A LangGraph-based multi-agent pipeline that ingests patient report PDFs,
classifies ailments by specialty and severity, routes them to specialist
agents in priority order, and loops unresolved cases back to intake for
reassessment (with a safety cap that escalates to human review instead of
looping forever). Outputs one recommendation PDF per input report.

**This is a decision-support prototype, not a diagnostic device.** Any real
deployment would need clinical validation, human sign-off on every plan,
and regulatory review before touching real patient care.

## Architecture

```
                    ┌─────────────┐
                    │   intake    │  Agent 1 (Delegator)
                    │ classify +  │  - parses report text
                    │ build queue │  - extracts ailments, specialty, severity
                    └──────┬──────┘
                           │ (queue sorted severe → major → minor)
                           ▼
                    ┌─────────────┐
              ┌────▶│  pop_next   │
              │     └──────┬──────┘
              │            ▼
              │     ┌─────────────┐
              │     │ specialist  │  Agent 2..N (one per specialty)
              │     │  consult    │  - produces treatment plan, OR
              │     └──────┬──────┘  - flags "can't determine"
              │            │
              │   resolved/escalated   unresolved (retries left)
              │            │                  │
              │            ▼                  ▼
              │     queue empty?        ┌─────────────┐
              │      /        \         │  reassess   │  back to Agent 1
              │   yes          no       │ (re-classify│  with specialist's
              │    │            │       │ w/ feedback)│  feedback
              │    ▼            └───────┴──────┬──────┘
              │ ┌─────────┐                     │
              └─┤ compose │◀────────────────────┘ (pushed back into queue)
                └────┬────┘
                     ▼
                    END → PDF written
```

The reassessment loop is a genuine cycle in the graph, capped
at `MAX_REASSESSMENT_ATTEMPTS` (default 3) per case — after that, the case is
escalated to "requires human physician review" instead of looping forever.

Multiple ailments from one report are processed in **severity-priority
order** (severe → major → minor).

## Setup

Install the package (this registers the `p-tri` and `p-tri-ui` commands on your PATH):

```bash
pip install patient-triage
```

Or, if you've cloned this project instead:
```bash
pip install .            # from inside this project folder
# or, for local development with live-reload on code changes:
pip install -e .
```

`p-tri` is exactly `python main.py` from earlier — same CLI, same flags —
just installed as a proper command instead of a script you invoke by path.

### LLM backend (swappable — pick one via `--backend`)

- **`lmstudio`** (default): point at a local model served by
  [LM Studio](https://lmstudio.ai/)'s built-in OpenAI-compatible server
  (Settings → Developer → Start Server, default `http://localhost:1234/v1`).
  Free, runs entirely locally. Set `LM_STUDIO_MODEL` env var to match
  whatever model you've loaded in LM Studio.
- **`anthropic`**: uses the Claude API. Requires `ANTHROPIC_API_KEY` env var.
- **`mock`**: deterministic canned responses, no model required — useful for
  testing the graph wiring offline.

## Web UI

For a visual alternative to the CLI, `p-tri-ui` runs a small local Flask
server where you can upload reports, trigger processing, and view any PDF
— input report or generated recommendation — inline in the browser (using
the browser's native PDF viewer, no extra JS library required).

```bash
p-tri-ui                                    # http://127.0.0.1:5000
TRIAGE_LLM_BACKEND=anthropic PORT=8080 p-tri-ui   # override backend / port
```

What it does:
- **Upload** — choose one or more PDF files, or select an entire folder (via
  the "Or choose a whole folder" option), and upload them all in one go.
  Non-PDF files in a folder selection are silently skipped.
- **Process** — click "Process" next to any un-processed report to run it
  through the same graph the CLI uses (shared code path — see `pipeline.py`),
  or click **Process All** to run every un-processed report in one click.
- **View** — click any input report or generated recommendation to load it
  in the right-hand pane, titled with its actual name (not "(anonymous)").

**Note:** the "Input reports" and "Recommendations" lists are just a live
directory listing of `input_reports/` and `output_recommendations/` relative
to wherever you launch `p-tri`/`p-tri-ui` from (or `TRIAGE_INPUT_DIR` /
`TRIAGE_OUTPUT_DIR` if set) — there's no database behind it. This repo ships
with the 5 sample reports from `generate_samples.py` already sitting in
`input_reports/`, so they'll show up on first launch until you delete them
or run everything from a different working directory.

This is a local, single-machine service — the SQLite job queue assumes a
single worker thread, and there's no auth yet (see "Running as a persistent
service" below for what changes if you take this further).

## Running as a persistent service

`p-tri-ui` isn't just a request/response script — it runs a persistent
background worker (`worker.run_worker_loop`) for the lifetime of the
process, consuming a durable, SQLite-backed job queue (`db.py`'s `jobs`
table). This is what makes it a *service* rather than a dev tool:

- **Submitting work is decoupled from doing the work.** Clicking "Process"
  or "Process All" hits `POST /jobs/enqueue`, which just inserts row(s) into
  the `jobs` table and returns immediately — the actual triage graph runs
  in the background worker thread, not in the HTTP request.
- **Jobs survive a restart.** Job state lives in SQLite, not in a Python
  dict. If you stop and restart `p-tri-ui`, anything still `queued` is
  still queued; anything caught mid-`running` from a crash gets requeued by
  `db.recover_interrupted_jobs()` at startup (verified: killing the process
  mid-job and restarting it against the same database picks the job back
  up and finishes it).
- **Work continues without anyone watching.** The worker loop polls the
  queue on its own timer — a submitted job gets processed whether or not a
  browser tab is open polling `/jobs/status/<batch_id>` for progress.

**Deploying it as a long-running process** (still single-machine): run it
under a process supervisor so it survives reboots/crashes and restarts
automatically, e.g. a `systemd` unit:
```ini
[Unit]
Description=Patient Triage UI
After=network.target

[Service]
ExecStart=/usr/local/bin/p-tri-ui
Environment=TRIAGE_LLM_BACKEND=anthropic
Restart=on-failure
WorkingDirectory=/path/to/your/data

[Install]
WantedBy=multi-user.target
```
Flask's built-in dev server (what `p-tri-ui` runs today) says as much in
its own startup warning — for anything beyond local use, put it behind a
production WSGI server instead, e.g. `gunicorn --workers 1 'patient_triage.web.app:create_app()'`.
Keep `--workers 1`: the job queue is correct with more (job-claiming is a
proper transaction, so two workers won't double-process the same job), but
a single process keeps one clear background worker thread rather than one
per process.

**If you outgrow SQLite** (multiple machines, high job volume, or you want
concurrent writers without the current single-connection lock): the job
queue's SQL is plain and portable — swapping `db.py`'s `sqlite3` calls for
`psycopg2` against Postgres is a fairly mechanical change, since the schema
and query shapes don't rely on SQLite-specific features. At that point,
also worth moving from thread-based polling to a real queue (Redis + RQ)
so you can run worker processes on separate machines instead of one
in-process thread.

## CLI Usage

```bash
# Put patient report PDFs in input_reports/, then:
p-tri --backend lmstudio
p-tri --backend anthropic --model claude-sonnet-4-6
p-tri --backend mock              # offline test, no LLM needed

# Custom folders:
p-tri --input-dir my_reports --output-dir my_recommendations
```

Each `<name>.pdf` in the input folder produces `<name>_recommendation.pdf`
in the output folder, containing:
- Resolved specialist treatment plans (with clinical reasoning)
- Any cases escalated to human physician review, and why
- A full audit trail of every classification / reassessment step, for a
  physician to sanity-check the AI's reasoning

A SQLite log (`triage_cases.db`) records a summary of every run for later
auditing.

## Project layout

```
pyproject.toml                    packaging metadata + the `p-tri`/`p-tri-ui` entry points
src/patient_triage/
    config.py                     specialties, severity levels, retry limits, backend config
    schemas.py                    Pydantic/TypedDict data contracts between agents
    llm_backends.py               swappable LLM backend (anthropic / lmstudio / mock)
    utils.py                      JSON extraction helper for LLM outputs
    pdf_utils.py                  PDF text extraction + recommendation PDF generation
    db.py                         SQLite audit logging
    graph.py                      LangGraph wiring (the cyclic state machine)
    pipeline.py                   shared "process one report" logic (used by CLI + UI)
    worker.py                     persistent background worker loop (consumes the job queue)
    main.py                       CLI batch entry point (this is what `p-tri` runs)
    agents/delegator.py           Agent 1: classify + reassess
    agents/specialist.py          Agent 2..N: per-specialty consultation
    web/app.py                    Flask web UI (this is what `p-tri-ui` runs)
    web/templates/index.html      upload form, file lists, PDF viewer pane
    web/static/style.css          UI styling
generate_samples.py                dev helper: regenerates the 5 sample reports
```

## Extending

- **Scanned/image PDFs**: `extract_text_from_pdf` raises if no text layer is
  found. Add OCR (`pytesseract` + `pdf2image`) as a fallback if your reports
  come from scanners.
- **New specialties**: add to `SPECIALTIES` in `config.py` — no other code
  changes needed, since the specialist agent is generic and parameterized
  by specialty name.
- **Persistent service**: done — see "Running as a persistent service" above
  for the durable job queue and background worker.
- **Multi-machine scale**: swap SQLite for Postgres and the in-process
  worker thread for Redis + RQ workers on separate machines (see the note
  at the end of the persistent-service section above).
