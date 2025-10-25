# app/services/ollama_client.py
from __future__ import annotations

import time
import re
from typing import Any, Dict, Optional, Union
import httpx

from app.core.config import settings

# ---------- duration parsing ----------
_DUR_RX = re.compile(r"(?i)(\d+(?:\.\d+)?)(ms|s|m|h)")

def _parse_duration_to_seconds(val: Any, default_seconds: float) -> float:
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return float(val)
    s = (str(val or "")).strip().lower()
    if not s:
        return float(default_seconds)
    pos = 0
    total = 0.0
    for m in _DUR_RX.finditer(s):
        if m.start() != pos and pos != 0:
            break
        num = float(m.group(1))
        unit = m.group(2)
        total += {"ms": num/1000, "s": num, "m": num*60, "h": num*3600}[unit]
        pos = m.end()
    if total == 0.0:
        try:
            return float(s)
        except Exception:
            return float(default_seconds)
    return total

def _httpx_timeout(total_seconds: float) -> httpx.Timeout:
    total = float(total_seconds)
    return httpx.Timeout(
        connect=min(6.0, total),
        read=total,
        write=min(8.0, total),
        pool=total,
    )

def _base_url() -> str:
    return (getattr(settings, "ollama_base_url", None) or "http://127.0.0.1:11434").rstrip("/")

def _keep_alive() -> str:
    ka = getattr(settings, "ollama_keep_alive", None) or getattr(settings, "OLLAMA_KEEP_ALIVE", None)
    return (ka or "5m").strip()

# ---------- public ----------
def generate_with_metrics(
    prompt: str,
    stop: Optional[list[str]] = None,
    num_predict: Optional[int] = None,
    timeout_seconds: Optional[Union[int, float, str]] = None,
    base_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Call Ollama /api/generate with strict timeout.
    On error/timeouts, fall back to LangChain's Ollama with same timeout.
    Returns: {text, model, prompt_eval_count, eval_count, total_duration_ms}
    """
    model = getattr(settings, "ollama_model", None) or "codellama:7b"
    temperature = float(getattr(settings, "ollama_temperature", 0.0))
    numpred = int(num_predict if num_predict is not None else getattr(settings, "ollama_num_predict", 96))
    num_ctx = int(getattr(settings, "ollama_num_ctx", 1024))
    top_k = int(getattr(settings, "ollama_top_k", 20))
    top_p = float(getattr(settings, "ollama_top_p", 0.9))
    repeat_penalty = float(getattr(settings, "ollama_repeat_penalty", 1.1))

    base = (base_url or getattr(settings, "ollama_base_url", None) or "http://127.0.0.1:11434").rstrip("/")
    keep_alive = _keep_alive()

    default_total = _parse_duration_to_seconds(
        getattr(settings, "ollama_timeout", None) or getattr(settings, "OLLAMA_TIMEOUT", None) or "25s",
        25.0,
    )
    total_timeout = _parse_duration_to_seconds(timeout_seconds, default_total) if timeout_seconds is not None else default_total

    payload: Dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "keep_alive": keep_alive,
        "options": {
            "temperature": temperature,
            "num_predict": numpred,
            "num_ctx": num_ctx,
            "top_k": top_k,
            "top_p": top_p,
            "repeat_penalty": repeat_penalty,
        },
    }
    if stop:
        payload["stop"] = stop

    url = f"{base}/api/generate"

    t0 = time.perf_counter()
    try:
        with httpx.Client(timeout=_httpx_timeout(total_timeout)) as cli:
            resp = cli.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            txt = data.get("response") or data.get("text") or ""
            td = data.get("total_duration")
            total_ms = (td // 1_000_000) if isinstance(td, int) else int((time.perf_counter() - t0) * 1000)
            return {
                "text": txt,
                "model": data.get("model"),
                "prompt_eval_count": int(data.get("prompt_eval_count", 0)),
                "eval_count": int(data.get("eval_count", 0)),
                "total_duration_ms": total_ms,
            }
    except Exception as e_http:
        # Fallback to LangChain's Ollama (same timeout)
        try:
            from langchain_community.llms import Ollama as LC_Ollama
            lc = LC_Ollama(
                model=model,
                temperature=temperature,
                num_predict=numpred,
                base_url=base,
                request_timeout=max(8, int(total_timeout)),
            )
            t1 = time.perf_counter()
            text = lc.invoke(prompt, stop=stop)
            total_ms = int((time.perf_counter() - t1) * 1000)
            return {
                "text": text or "",
                "model": model,
                "prompt_eval_count": 0,
                "eval_count": 0,
                "total_duration_ms": total_ms,
            }
        except Exception as e_lc:
            raise RuntimeError(f"Ollama request failed: {e_http}") from e_lc
