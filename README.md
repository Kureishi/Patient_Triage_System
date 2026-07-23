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

The reassessment loop is a genuine cycle in the graph (requirement 4), capped
at `MAX_REASSESSMENT_ATTEMPTS` (default 3) per case — after that, the case is
escalated to "requires human physician review" instead of looping forever.

Multiple ailments from one report are processed in **severity-priority
order** (severe → major → minor), satisfying requirement (3).

## Setup

Install the package (this registers the `p-tri` command on your PATH):

```bash
pip install .            # from inside this project folder
# or, for local development with live-reload on code changes:
pip install -e .
```

`p-tri` is exactly `python main.py` from earlier — same CLI, same flags —
just installed as a proper command instead of a script you invoke by path.

A pre-built wheel is also included at `dist/patient_triage-0.1.0-py3-none-any.whl`,
installable directly with:
```bash
pip install dist/patient_triage-0.1.0-py3-none-any.whl
```

### LLM backend (swappable — pick one via `--backend`)

- **`lmstudio`** (default): point at a local model served by
  [LM Studio](https://lmstudio.ai/)'s built-in OpenAI-compatible server
  (Settings → Developer → Start Server, default `http://localhost:1234/v1`).
  Free, runs entirely locally. Set `LM_STUDIO_MODEL` env var to match
  whatever model you've loaded in LM Studio.
- **`anthropic`**: uses the Claude API. Requires `ANTHROPIC_API_KEY` env var.
- **`mock`**: deterministic canned responses, no model required — useful for
  testing the graph wiring offline.

## Usage

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
pyproject.toml                    packaging metadata + the `p-tri` entry point
src/patient_triage/
    config.py                     specialties, severity levels, retry limits, backend config
    schemas.py                    Pydantic/TypedDict data contracts between agents
    llm_backends.py               swappable LLM backend (anthropic / lmstudio / mock)
    utils.py                      JSON extraction helper for LLM outputs
    pdf_utils.py                  PDF text extraction + recommendation PDF generation
    db.py                         SQLite audit logging
    graph.py                      LangGraph wiring (the cyclic state machine)
    main.py                       CLI batch entry point (this is what `p-tri` runs)
    agents/delegator.py           Agent 1: classify + reassess
    agents/specialist.py          Agent 2..N: per-specialty consultation
generate_samples.py                dev helper: regenerates the 5 sample reports
```

## Extending

- **Scanned/image PDFs**: `extract_text_from_pdf` raises if no text layer is
  found. Add OCR (`pytesseract` + `pdf2image`) as a fallback if your reports
  come from scanners.
- **New specialties**: add to `SPECIALTIES` in `config.py` — no other code
  changes needed, since the specialist agent is generic and parameterized
  by specialty name.
- **Persistent service later**: `graph.py` and `agents/` are already
  decoupled from the CLI in `main.py`, so wrapping `build_graph()` in a
  FastAPI endpoint + queue (e.g. Celery/RQ backed by the existing SQLite —
  or Postgres at that point) is a relatively small step from here.
