import json
import re


def extract_json(text: str):
    """
    LLMs (especially local ones via LM Studio) often wrap JSON in prose or
    ```json fences. Strip that off and parse. Raises ValueError if no JSON
    object/array can be found.
    """
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    # find first [ or { and matching close, in case of leading prose
    match = re.search(r"[\[{].*[\]}]", text, re.DOTALL)
    if match:
        text = match.group(0)
    return json.loads(text)
