"""Task Generator: generates TaskAssignment from merged spec analysis (fallback for Tech Lead)."""

from .agent import TaskGeneratorAgent
from .models import TaskGeneratorInput

__all__ = [
    "TaskGeneratorAgent",
    "TaskGeneratorInput",
]
