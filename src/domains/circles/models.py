"""Pydantic models for the circle domain."""

from datetime import datetime

from pydantic import BaseModel, Field


class CircleHealthRequest(BaseModel):
    circle_id: str


class CircleHealthResponse(BaseModel):
    circle_id: str
    score: float = Field(ge=0, le=100)
    confidence: float = Field(ge=0.0, le=1.0)
    factors: dict = {}
    model_version: str = "stub"
    computed_at: datetime
