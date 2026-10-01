"""
RateSift Agent Playground - Isolated Agent Copy Package
Enables testing agent training ideas, prompt variations, and rule adherence in the IDE.
Zero website launch or database modifications required.
"""
from .rate_agent import RateSiftAgent
from .rules_spec import RATESIFT_32_RULES
from .agent_prompts import AGENT_TRAINING_VARIANTS

__all__ = ["RateSiftAgent", "RATESIFT_32_RULES", "AGENT_TRAINING_VARIANTS"]
