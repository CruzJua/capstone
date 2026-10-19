from typing import List, Literal
from pydantic import BaseModel, Field

class SupportResponse(BaseModel):
    answer: str = Field(description="Direct, grounded answer to the customer inquiry")
    cited_sources: List[str] = Field(default_factory=list, description="List of source file names cited")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score between 0.0 and 1.0")
    action: Literal["answer", "escalate"] = Field(description="Action decision: answer or escalate")
