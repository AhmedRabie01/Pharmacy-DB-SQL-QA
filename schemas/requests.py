from pydantic import BaseModel, Field

class QuestionRequest(BaseModel):
    question: str = Field(..., description="Natural language question (Arabic/English).")

class SQLRunRequest(BaseModel):
    sql: str = Field(..., description="Raw T-SQL SELECT to execute.")
