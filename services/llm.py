from langchain_community.llms import Ollama
from app.core.config import settings

def get_llm():
    kwargs = {
        "model": settings.ollama_model,
        "temperature": settings.ollama_temperature,
        "num_predict": settings.ollama_num_predict,
    }
    # If Ollama runs on another host/port
    if settings.ollama_base_url:
        kwargs["base_url"] = settings.ollama_base_url
    return Ollama(**kwargs)
