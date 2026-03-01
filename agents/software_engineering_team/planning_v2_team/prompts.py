"""
Prompts for planning-v2 phases and tool agent orchestration.

No reuse from planning_team. Tool agents have their own embedded prompts.
These prompts are used by the orchestrator and phase implementations.

Note: This team expects a pre-validated specification - no spec review prompts
are included. Use the Product Requirements Analysis agent for spec validation.
"""

# ---------------------------------------------------------------------------
# Phase-level prompts (used by orchestrator phases)
# ---------------------------------------------------------------------------

PLANNING_PROMPT = """You are a Product Planning expert. Using the spec and any prior review, produce a comprehensive product plan.

Create a structured plan covering all aspects of the product. Respond with a JSON object only, with these exact keys:

- "goals_vision": string (the product's goals and vision statement)
- "constraints_limitations": string (technical and business constraints)
- "key_features": list of strings (main features to be implemented)
- "milestones": list of strings (project milestones with deliverables)
- "architecture": string (high-level architecture overview)
- "maintainability": string (code quality, testing, and maintenance considerations)
- "security": string (security requirements and considerations)
- "file_system": string (proposed file/folder structure)
- "styling": string (UI/UX styling guidelines and design system)
- "dependencies": list of strings (external libraries and dependencies)
- "microservices": string (microservices breakdown if applicable, or "N/A" for monolithic)
- "others": string (additional notes, edge cases, or considerations)
- "summary": string (overall planning summary)

Spec excerpt:
---
{spec_content}
---

Prior review summary (if any): {review_summary}
"""

REVIEW_PROMPT = """You are reviewing planning assets for cohesion and alignment with the spec.

Respond with a JSON object only:
- "passed": boolean (true if assets are cohesive and align with spec)
- "issues": list of strings (any issues found)
- "summary": string

Spec excerpt:
---
{spec_content}
---

Artifacts to review:
---
{artifacts}
---
"""

PROBLEM_SOLVING_PROMPT = """You are a problem-solving expert. Given review issues, suggest fixes.

Respond with a JSON object only:
- "fixes_applied": list of strings (description of each fix)
- "resolved": boolean
- "summary": string

Review issues: {issues}
"""

PROBLEM_SOLVING_SINGLE_ISSUE_PROMPT = """You are a planning expert fixing a specific issue in the planning artifacts.

ISSUE TO FIX:
---
{issue}
---

SPECIFICATION EXCERPT:
---
{spec_excerpt}
---

CURRENT PLANNING ARTIFACTS:
---
{current_artifacts}
---

Analyze this specific issue and provide a fix. If the issue requires updating a planning artifact file, provide the complete updated file content.

Respond with a JSON object only:
{{
  "root_cause": "explanation of why this issue exists",
  "fix_description": "description of the fix being applied",
  "resolved": true or false,
  "file_updates": {{
    "plan/filename.md": "complete updated file content if needed"
  }}
}}

If no file updates are needed (issue is informational or already addressed), set "file_updates" to an empty object and explain in "fix_description".
"""

# ---------------------------------------------------------------------------
# Orchestration prompts (for coordinating tool agents)
# ---------------------------------------------------------------------------

TOOL_AGENT_COORDINATION_PROMPT = """You are coordinating multiple planning tool agents.

Current phase: {phase}
Active tool agents: {active_agents}

Spec:
---
{spec_content}
---

Prior results:
{prior_results}

Determine what each tool agent should focus on for this phase.

Respond with JSON:
{{
  "agent_instructions": [
    {{"agent": "system_design", "focus": "what to focus on"}},
    {{"agent": "architecture", "focus": "what to focus on"}}
  ],
  "summary": "coordination summary"
}}
"""

DELIVERABLES_CONSOLIDATION_PROMPT = """You are consolidating planning deliverables from multiple tool agents.

Tool agent outputs:
---
{tool_agent_outputs}
---

Create a unified summary and identify any conflicts or gaps.

Respond with JSON:
{{
  "consolidated_summary": "unified summary of all outputs",
  "conflicts": ["any conflicts between agent outputs"],
  "gaps": ["any remaining gaps"],
  "next_steps": ["recommended next steps"]
}}
"""
