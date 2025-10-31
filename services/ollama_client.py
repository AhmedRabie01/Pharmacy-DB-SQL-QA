# app/services/ollama_client.py
import os
import json
import requests
from typing import Any, Dict, Optional


def _ollama_base_url() -> str:
    # you can change this with OLLAMA_BASE_URL in env
    return os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")


def generate_with_metrics(
    prompt: str,
    model: Optional[str] = None,
    timeout_seconds: float = 12.0,
    num_predict: int = 128,
    stop: Optional[list[str]] = None,
) -> Dict[str, Any]:
    """
    Call Ollama /api/generate and handle streaming JSON safely.
    If Ollama is unreachable or returns malformed JSON,
    we return {"text": "", "error": "..."}.
    """
    base = _ollama_base_url().rstrip("/")
    url = f"{base}/api/generate"

    payload: Dict[str, Any] = {
        "model": model or os.getenv("OLLAMA_MODEL", "llama3"),
        "prompt": prompt,
        "stream": True,  # ollama streams by default
        "options": {
            "num_predict": num_predict,
        },
    }
    if stop:
        payload["stop"] = stop

    try:
        resp = requests.post(url, json=payload, stream=True, timeout=timeout_seconds)
    except Exception as e:
        print(f"[ollama_client] cannot connect to Ollama: {e}")
        return {"text": "", "error": str(e)}

    if resp.status_code != 200:
        err = f"Ollama HTTP {resp.status_code}: {resp.text[:200]}"
        print(f"[ollama_client] bad status: {err}")
        return {"text": "", "error": err}

    full_text = []
    total_duration_ms = 0
    model_name = None
    prompt_eval_count = 0
    eval_count = 0

    for line in resp.iter_lines(decode_unicode=True):
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as je:
            # this is the exact error you saw: "Extra data: line 2..."
            # we will not crash the whole app because of this
            print(f"[ollama_client] JSON decode error on line: {je} | line={line!r}")
            return {"text": "".join(full_text), "error": str(je)}

        # collect text
        if "response" in obj and obj["response"]:
            full_text.append(obj["response"])

        # collect metrics if present
        if "model" in obj and not model_name:
            model_name = obj["model"]
        if "total_duration" in obj:
            total_duration_ms = int(obj["total_duration"] / 1_000_000)
        if "prompt_eval_count" in obj:
            prompt_eval_count = int(obj["prompt_eval_count"])
        if "eval_count" in obj:
            eval_count = int(obj["eval_count"])

    final_text = "".join(full_text).strip()
    return {
        "text": final_text,
        "model": model_name,
        "total_duration_ms": total_duration_ms,
        "prompt_eval_count": prompt_eval_count,
        "eval_count": eval_count,
    }
