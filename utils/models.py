from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class Urgency(str, Enum):
    EMERGENCY = "EMERGENCY"
    ROUTINE = "ROUTINE"
    UNKNOWN = "UNKNOWN"


class ServiceType(str, Enum):
    PLUMBING = "plumbing"
    HVAC = "hvac"
    CLEANING = "cleaning"
    ELECTRICAL = "electrical"
    OTHER = "other"


@dataclass
class JobContext:
    """Shared context object passed between bots by the orchestrator."""
    customer_name: Optional[str] = None
    customer_email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    service_type: Optional[ServiceType] = None
    problem_description: Optional[str] = None
    urgency: Urgency = Urgency.UNKNOWN
    preferred_time: Optional[str] = None
    timezone: Optional[str] = None
    conversation_history: list = field(default_factory=list)

    def to_summary(self) -> str:
        parts = []
        if self.customer_name:
            parts.append(f"Customer: {self.customer_name}")
        if self.customer_email:
            parts.append(f"Email: {self.customer_email}")
        if self.phone:
            parts.append(f"Phone: {self.phone}")
        if self.address:
            parts.append(f"Address: {self.address}")
        if self.service_type:
            parts.append(f"Service: {self.service_type.value}")
        if self.problem_description:
            parts.append(f"Problem: {self.problem_description}")
        if self.urgency != Urgency.UNKNOWN:
            parts.append(f"Urgency: {self.urgency.value}")
        if self.preferred_time:
            parts.append(f"Preferred time: {self.preferred_time}")
        if self.timezone:
            parts.append(f"Timezone: {self.timezone}")
        return "\n".join(parts) if parts else "No details collected yet."

    def conversation_transcript(self) -> str:
        lines = []
        for msg in self.conversation_history:
            role = "Customer" if msg["role"] == "user" else "HomeBot"
            lines.append(f"{role}: {msg['content']}")
        return "\n\n".join(lines) if lines else "No transcript available."
