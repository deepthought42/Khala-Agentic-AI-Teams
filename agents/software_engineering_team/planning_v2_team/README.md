# Planning V2 Team

The Planning V2 Team is a standalone 3-layer planning system that produces comprehensive project plans from specifications. It uses 8 specialized tool agents organized across 6 workflow phases.

## Architecture

```mermaid
graph TB
    subgraph Layer1 [Layer 1: Product Lead]
        PL[PlanningV2ProductLead]
    end
    
    subgraph Layer2 [Layer 2: Planning Agent]
        PA[PlanningV2PlanningAgent]
    end
    
    subgraph Layer3 [Layer 3: Tool Agents]
        SD[System Design]
        ARCH[Architecture]
        US[User Story]
        DEV[DevOps]
        UI[UI Design]
        UX[UX Design]
        TC[Task Classification]
        TD[Task Dependency]
    end
    
    PL --> PA
    PA --> SD & ARCH & US & DEV & UI & UX & TC & TD
```

### Three-Layer Structure

| Layer | Component | Responsibility |
|-------|-----------|----------------|
| 1 | `PlanningV2ProductLead` | Spec intake, inspiration handling, optional Product Analysis integration |
| 2 | `PlanningV2PlanningAgent` | Orchestrates tool agents across 6 phases |
| 3 | Tool Agents (8) | Specialized planning tasks (design, architecture, stories, etc.) |

## Workflow Phases

```mermaid
stateDiagram-v2
    [*] --> SpecReview
    SpecReview --> Planning
    Planning --> Implementation
    Implementation --> Review
    Review --> ProblemSolving: Issues Found
    Review --> Deliver: Passed
    ProblemSolving --> Implementation
    Deliver --> [*]
```

### Phase Details

| Phase | Purpose | Tool Agents Involved |
|-------|---------|---------------------|
| **Spec Review** | Analyze specification for gaps, issues, and open questions | System Design, Architecture |
| **Planning** | Generate high-level design, architecture, milestones | System Design, Architecture, User Story, DevOps, UI Design |
| **Implementation** | Create detailed task breakdown, user stories, file structure | All 8 agents |
| **Review** | Verify consistency, completeness, spec alignment | System Design, Architecture, User Story, Task Dependency |
| **Problem Solving** | Resolve issues identified in review | System Design, Architecture, User Story |
| **Deliver** | Finalize plan, commit artifacts | System Design, Architecture, User Story |

The Review → Problem Solving → Implementation cycle repeats up to 5 times until review passes.

## Tool Agents

| Agent | Phases | Purpose |
|-------|--------|---------|
| **System Design** | All | Overall system architecture and component design |
| **Architecture** | All | Technical architecture, patterns, infrastructure |
| **User Story** | Planning, Implementation, Review, Problem Solving, Deliver | User stories, acceptance criteria |
| **DevOps** | Planning, Implementation | CI/CD, deployment, infrastructure-as-code |
| **UI Design** | Planning, Implementation | Visual design, component library, styling |
| **UX Design** | Implementation | User experience, flows, accessibility |
| **Task Classification** | Implementation | Categorize tasks by type (frontend, backend, devops, etc.) |
| **Task Dependency** | Review | Analyze dependencies between tasks |

## Usage

### Programmatic

```python
from shared.llm import LLMClient
from planning_v2_team.orchestrator import PlanningV2ProductLead
from pathlib import Path

llm = LLMClient()
lead = PlanningV2ProductLead(llm)

result = lead.run_workflow(
    spec_content="# My Project\n\nDescription of what to build...",
    repo_path=Path("/path/to/repo"),
    inspiration_content="Optional moodboard or reference content",
    use_product_analysis=True,  # Optional: run Product Analysis first
)

if result.success:
    print(f"Planning complete: {result.summary}")
    print(f"Final spec: {result.final_spec_content}")
else:
    print(f"Planning failed: {result.failure_reason}")
```

### With Job Updates

```python
def update_job(**kwargs):
    print(f"Progress: {kwargs.get('progress', 0)}%")
    print(f"Phase: {kwargs.get('current_phase', 'unknown')}")
    print(f"Status: {kwargs.get('status_text', '')}")

result = lead.run_workflow(
    spec_content=spec,
    repo_path=repo,
    job_updater=update_job,
    job_id="job-123",  # Enables open questions support
)
```

## Open Questions Flow

When the Spec Review phase identifies ambiguities, it generates structured open questions:

```python
class OpenQuestion(BaseModel):
    id: str                      # Unique identifier
    question_text: str           # The question
    context: str                 # Why this matters
    options: List[QuestionOption]  # 2-3 options with rationale
```

Each option includes:
- `label`: Display text
- `is_default`: Recommended choice
- `rationale`: Why this option is suggested
- `confidence`: AI confidence score (0.0-1.0)

The workflow pauses after Planning if open questions exist, waiting for user answers (up to 1 hour timeout).

## Output Artifacts

The workflow creates/updates files in `{repo_path}/plan/`:

| File | Content |
|------|---------|
| `product_spec.md` | Final validated specification |
| `architecture.md` | System architecture document |
| `tech_stack.md` | Technology choices and rationale |
| `file_structure.md` | Project file/folder layout |
| `user_stories.md` | Complete user stories |
| `task_breakdown.md` | Task hierarchy (Initiatives → Epics → Stories → Tasks) |
| `devops_plan.md` | CI/CD and deployment strategy |
| `ui_design.md` | UI/UX design guidelines |

## Models

### Phase Results

```python
SpecReviewResult      # Issues, gaps, open questions
PlanningPhaseResult   # Goals, architecture, milestones, dependencies
ImplementationPhaseResult  # Assets created/updated
ReviewPhaseResult     # Pass/fail with issues
ProblemSolvingPhaseResult  # Fixes applied
DeliverPhaseResult    # Final spec content
```

### Workflow Result

```python
class PlanningV2WorkflowResult(BaseModel):
    success: bool
    current_phase: Optional[Phase]
    summary: str
    failure_reason: str
    spec_review_result: Optional[SpecReviewResult]
    planning_result: Optional[PlanningPhaseResult]
    implementation_result: Optional[ImplementationPhaseResult]
    review_result: Optional[ReviewPhaseResult]
    problem_solving_result: Optional[ProblemSolvingPhaseResult]
    deliver_result: Optional[DeliverPhaseResult]
    user_answers: Dict[str, Any]
    final_spec_content: Optional[str]
```

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `MAX_REVIEW_ITERATIONS` | Max review → problem-solving cycles | 5 |
| `OPEN_QUESTIONS_TIMEOUT` | Seconds to wait for user answers | 3600 |
| `OPEN_QUESTIONS_POLL_INTERVAL` | Seconds between answer checks | 5 |

## Directory Structure

```
planning_v2_team/
├── orchestrator.py        # PlanningV2ProductLead, PlanningV2PlanningAgent
├── models.py              # Phase, ToolAgentKind, all result models
├── prompts.py             # LLM prompts for phases
├── phases/
│   ├── iterative_spec_review.py  # Spec Review with open questions
│   ├── planning.py        # Planning phase
│   ├── implementation.py  # Implementation phase
│   ├── review.py          # Review phase
│   ├── problem_solving.py # Problem-solving phase
│   └── deliver.py         # Deliver phase
└── tool_agents/
    ├── system_design/     # System Design tool agent
    ├── architecture/      # Architecture tool agent
    ├── user_story/        # User Story tool agent
    ├── devops/            # DevOps tool agent
    ├── ui_design/         # UI Design tool agent
    ├── ux_design/         # UX Design tool agent
    ├── task_classification/  # Task Classification tool agent
    └── task_dependency/   # Task Dependency tool agent
```

## Integration with SE Team

Planning V2 can be integrated with the Software Engineering Team orchestrator:

1. SE Team receives a job request
2. If `use_planning_v2=True`, delegates to Planning V2
3. Planning V2 produces artifacts in `plan/`
4. SE Team reads plan and proceeds to execution

The `skip_spec_review` flag allows skipping the iterative review when the spec has already been validated by the Product Requirements Analysis agent.
