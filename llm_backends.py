"""
Swappable LLM backend layer.

All agents call `backend.complete(system_prompt, user_prompt)` and get back
a string. Agents are responsible for asking the model to return JSON and
parsing it (see utils.extract_json). Swapping backends never touches agent
logic -- that's the point.

Supported backends:
  - "anthropic": Claude via the Anthropic API
  - "lmstudio":   any local model served by LM Studio's OpenAI-compatible
                  server (Settings -> Developer -> Start Server in LM Studio)
  - "mock":       deterministic canned responses, used for offline testing
                  of the graph wiring without any model running
"""
from __future__ import annotations
from abc import ABC, abstractmethod
import json
import config


class LLMBackend(ABC):
    @abstractmethod
    def complete(self, system_prompt: str, user_prompt: str) -> str:
        ...


class AnthropicBackend(LLMBackend):
    def __init__(self, model: str = None, api_key: str = None):
        import anthropic
        self.model = model or config.ANTHROPIC_MODEL
        self.client = anthropic.Anthropic(api_key=api_key or config.ANTHROPIC_API_KEY)

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=1500,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return "".join(block.text for block in resp.content if block.type == "text")


class LMStudioBackend(LLMBackend):
    """LM Studio's local server speaks the OpenAI chat completions API."""

    def __init__(self, base_url: str = None, model: str = None):
        from openai import OpenAI
        self.model = model or config.LM_STUDIO_MODEL
        self.client = OpenAI(
            base_url=base_url or config.LM_STUDIO_BASE_URL,
            api_key="lm-studio",  # unused but required by the client
        )

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )
        return resp.choices[0].message.content


class MockBackend(LLMBackend):
    """
    Deterministic backend for testing the graph without a live model.
    Looks at keywords in the prompt to decide which canned JSON to return.
    """

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        if "Return a JSON list of ailments" in system_prompt:
            return json.dumps([
                {
                    "ailment_type": "chest pain with shortness of breath",
                    "specialty": "cardiology",
                    "severity": "severe",
                    "symptoms": ["chest pain", "shortness of breath", "sweating"],
                    "reasoning": "Presentation is consistent with possible acute cardiac event."
                },
                {
                    "ailment_type": "mild seasonal skin rash",
                    "specialty": "dermatology",
                    "severity": "minor",
                    "symptoms": ["itchy rash", "redness on forearm"],
                    "reasoning": "Localized, non-spreading rash consistent with mild contact dermatitis."
                }
            ])
        if "determine a treatment plan" in system_prompt:
            return json.dumps({
                "resolved": True,
                "treatment_plan": "Administer aspirin, obtain ECG and troponin levels, "
                                  "admit for cardiac monitoring, cardiology consult within the hour.",
                "reasoning": "Findings are consistent with acute coronary syndrome protocol."
            })
        return json.dumps({"resolved": True, "treatment_plan": "General supportive care.", "reasoning": "Mock fallback."})


def get_backend(name: str = None) -> LLMBackend:
    name = (name or config.DEFAULT_BACKEND).lower()
    if name == "anthropic":
        return AnthropicBackend()
    if name == "lmstudio":
        return LMStudioBackend()
    if name == "mock":
        return MockBackend()
    raise ValueError(f"Unknown LLM backend: {name}")
