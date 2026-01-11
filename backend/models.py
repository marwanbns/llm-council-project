from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class CouncilStage(str, Enum):
    PENDING = "pending"
    FIRST_OPINIONS = "first_opinions"
    REVIEW_RANKING = "review_ranking"
    CHAIRMAN_SYNTHESIS = "chairman_synthesis"
    COMPLETED = "completed"
    ERROR = "error"


class LLMStatus(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    BUSY = "busy"
    ERROR = "error"


# Ici c'est les requêtes

class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=10000, description="User question sent to the council")


class ConfigUpdateRequest(BaseModel):
    council_members: Optional[List[Dict]] = None
    chairman: Optional[Dict] = None


# La réponse reçu

class LLMNodeInfo(BaseModel):
    name: str
    host: str
    port: int
    model: str
    is_chairman: bool = False
    status: LLMStatus = LLMStatus.OFFLINE
    latency_ms: Optional[float] = None


class FirstOpinionResponse(BaseModel):
    llm_name: str
    model: str
    response: str
    latency_ms: float
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    token_count: Optional[int] = None


class ReviewScore(BaseModel):
    reviewer_name: str
    reviewed_name: str
    original_name: str
    score: int = Field(..., ge=1, le=10)
    reasoning: str
    accuracy_score: int = Field(..., ge=1, le=10)
    insight_score: int = Field(..., ge=1, le=10)


class ReviewRoundResponse(BaseModel):
    reviews: List[ReviewScore]
    rankings: Dict[str, float]  # On associe le nom du LLMà son score
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ChairmanSynthesis(BaseModel):
    chairman_name: str
    model: str
    final_response: str
    reasoning_summary: str
    latency_ms: float
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class CouncilSession(BaseModel):
    session_id: str
    query: str
    stage: CouncilStage = CouncilStage.PENDING
    first_opinions: List[FirstOpinionResponse] = Field(default_factory=list)
    review_results: Optional[ReviewRoundResponse] = None
    chairman_synthesis: Optional[ChairmanSynthesis] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    total_latency_ms: Optional[float] = None
    error_message: Optional[str] = None


class HealthCheckResponse(BaseModel):
    status: str
    nodes: List[LLMNodeInfo]
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class CouncilStatusResponse(BaseModel):
    active_sessions: int
    total_sessions: int
    council_members: List[LLMNodeInfo]
    chairman: LLMNodeInfo
    system_status: str