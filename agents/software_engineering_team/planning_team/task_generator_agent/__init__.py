"""Task Generator: generates TaskAssignment from merged spec analysis (fallback for Tech Lead)."""

from .agent import ESCALATION_KEY, TaskGeneratorAgent
from .models import TaskGeneratorInput

__all__ = [
    "ESCALATION_KEY",
    "TaskGeneratorAgent",
    "TaskGeneratorInput",
]
