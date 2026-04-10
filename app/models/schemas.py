from pydantic import BaseModel
from typing import Literal


class CategoryFinding(BaseModel):
    name: str
    status: Literal["PASS", "WARN", "FAIL"]
    findings: list[str]


class AnalysisResult(BaseModel):
    risk_score: Literal["LOW", "MEDIUM", "HIGH"]
    overall_score: int
    categories: list[CategoryFinding]
    summary: str


class ChatRequest(BaseModel):
    message: str
    document_context: str = ""


class SessionCreated(BaseModel):
    session_id: str
    document_name: str
