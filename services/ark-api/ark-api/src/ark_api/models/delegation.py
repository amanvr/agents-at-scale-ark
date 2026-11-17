"""Models for the delegation gateway: a sandboxed agent delegating to an agent/team."""
from typing import Optional

from pydantic import BaseModel


class DelegateRequest(BaseModel):
    """A sandboxed agent's request to delegate to another agent or team."""
    callerAgent: str
    callerNamespace: str
    targetType: str  # "agent" | "team"
    targetName: str
    targetNamespace: str = ""
    input: str
    conversationId: Optional[str] = None
    chain: str = ""  # JSON list of "<ns>/<agent>" ancestors, for cycle/depth limits


class DelegateResponse(BaseModel):
    result: str
