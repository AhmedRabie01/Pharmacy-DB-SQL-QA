from typing import List, Any, Optional, Dict
from pydantic import BaseModel

class QueryResponse(BaseModel):
    route: str
    sql: str
    columns: List[str]
    rows: List[Dict[str, Any]]
    summary_ar: str
    # Agents-only
    plan: Optional[str] = None
    # Metrics
    model: Optional[str] = None
    llm_prompt_tokens: Optional[int] = 0
    llm_eval_tokens: Optional[int] = 0
    llm_total_tokens: Optional[int] = 0
    llm_duration_ms: Optional[int] = 0
    total_ms: Optional[int] = 0

class PresetsList(BaseModel):
    presets: dict

class PresetRunResponse(QueryResponse):
    preset_name: str
