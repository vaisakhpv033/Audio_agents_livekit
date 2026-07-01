from pydantic import BaseModel, Field, ConfigDict

class CriteriaScore(BaseModel):
    model_config = ConfigDict(extra='forbid')
    
    score: int = Field(..., description="Score from 1 to 10")
    reason: str = Field(..., description="Short explanation or evidence for the score")

class QAReportCard(BaseModel):
    model_config = ConfigDict(extra='forbid')
    
    scenario_practiced: str = Field(..., description="Brief summary of customer profile and situation")
    overall_score: int = Field(..., description="Overall score from 1 to 100")
    
    # Criteria evaluation
    rapport: CriteriaScore = Field(...)
    discovery: CriteriaScore = Field(...)
    product_knowledge: CriteriaScore = Field(...)
    communication: CriteriaScore = Field(...)
    objection_handling: CriteriaScore = Field(...)
    recommendation_quality: CriteriaScore = Field(...)
    compliance: CriteriaScore = Field(...)
    closing: CriteriaScore = Field(...)
    
    positives: list[str] = Field(..., description="List of strongest behaviors observed (empty list if none)")
    improvement_areas: list[str] = Field(..., description="List of the most important weaknesses/improvements")
    missed_opportunities: list[str] = Field(..., description="List of important questions that should have been asked")
    compliance_issues: list[str] = Field(..., description="List of compliance concerns/violations (empty list if none)")
    coaching_recommendations: list[str] = Field(..., description="3 specific coaching recommendations")
    readiness_assessment: str = Field(..., description="Readiness assessment (must be one of: 'Not Ready', 'Needs Significant Coaching', 'Developing', 'Ready With Supervision', 'Production Ready')")
    readiness_reasoning: str = Field(..., description="Detailed reasoning for the readiness assessment")

class ReportPayload(BaseModel):
    job_id: str
    room_id: str
    room: str
    started_at: str | None = None
    ended_at: str
    summary: dict | str | None = None
    chat_history: dict | None = None
    customer_name: str | None = None
    agent_type: str | None = None
    sales_rep: str | None = None
    scenario: str | None = None
