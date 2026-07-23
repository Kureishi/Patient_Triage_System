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
