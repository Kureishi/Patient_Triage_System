"""
Central configuration for the patient triage multi-agent system.
"""
import os

# ---- Severity levels, ordered worst -> best for priority queue sorting ----
SEVERITY_ORDER = {"severe": 0, "major": 1, "minor": 2}
SEVERITY_LEVELS = ["severe", "major", "minor"]

# ---- Specialty taxonomy (~15 common specialties + general fallback) ----
SPECIALTIES = [
    "general_medicine",
    "cardiology",
    "neurology",
    "pulmonology",
    "gastroenterology",
    "endocrinology",
    "nephrology",
    "orthopedics",
    "dermatology",
    "psychiatry",
    "oncology",
    "infectious_disease",
    "rheumatology",
    "otolaryngology",  # ENT
    "ophthalmology",
    "urology",
    "obstetrics_gynecology",
    "emergency_medicine",
]

# ---- Reassessment loop safety valve ----
MAX_REASSESSMENT_ATTEMPTS = 3

# ---- LLM backend configuration (swappable) ----
# backend: "anthropic" | "lmstudio" | "mock"
DEFAULT_BACKEND = os.environ.get("TRIAGE_LLM_BACKEND", "lmstudio")

ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# LM Studio exposes an OpenAI-compatible local server, default port 1234.
LM_STUDIO_BASE_URL = os.environ.get("LM_STUDIO_BASE_URL", "http://localhost:1234/v1")
LM_STUDIO_MODEL = os.environ.get("LM_STUDIO_MODEL", "local-model")  # whatever you loaded in LM Studio

# ---- I/O ----
DEFAULT_INPUT_DIR = "input_reports"
DEFAULT_OUTPUT_DIR = "output_recommendations"
DB_PATH = "triage_cases.db"

# ---- Job store backend (swappable, single-machine vs multi-machine) ----
# "sqlite" (default): single-machine, in-process worker thread (worker.py).
# "postgres": durable job/case store usable from multiple machines at once.
DB_BACKEND = os.environ.get("TRIAGE_DB_BACKEND", "sqlite").lower()
DATABASE_URL = os.environ.get("DATABASE_URL", "")  # e.g. postgresql://user:pass@host:5432/patient_triage

# ---- Queue backend (how jobs get dispatched to a worker) ----
# "local" (default): the in-process worker thread in web/app.py.
# "distributed": jobs are pushed onto Redis via RQ and picked up by one or
# more `rq worker` processes, possibly running on other machines.
QUEUE_BACKEND = os.environ.get("TRIAGE_QUEUE_BACKEND", "local").lower()
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
RQ_QUEUE_NAME = os.environ.get("TRIAGE_RQ_QUEUE", "patient_triage")
