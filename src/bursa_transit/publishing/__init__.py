"""M0.1 has no publication capability."""
from dataclasses import dataclass

@dataclass(frozen=True)
class PublicationDecision:
    allowed: bool
    reason: str

def publication_decision() -> PublicationDecision:
    return PublicationDecision(False, "M0.1: official publication is not implemented or authorized")
