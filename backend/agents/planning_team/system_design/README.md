# System Design

Design documents for this team. The platform convention for this folder is:

| File | Purpose |
|---|---|
| `architecture.md` | Static architecture: layered component diagram, architectural principles, key design decisions. |
| `system_design.md` | Detailed system design: module layout, domain model, API surface, persistence, configuration. |
| `use_cases.md` | Actors and numbered use cases with triggers, preconditions, and main flows. |
| `flow_charts.md` | Sequence and flow diagrams for every runtime path. |
| `agent_anatomy.md` | Per-phase Input→Agent→Output diagrams and the coordinator/adapter seam (`AGENT_ANATOMY.md` conformance). |
| `FEATURE_SPEC_<slug>.md` | Pre-implementation proposals for new user-facing features. |
| `planning_hitl_temporal_contract.md` | The Temporal signal/wait + answer-callback primitive for clarification-question HITL. |
| `FEATURE_SPEC_hitl_answer_callback_adapter.md` | Decision record for the answer-callback adapter's exhausted-budget default path and its never-fabricate contract: the options weighed, the one taken, and the tasks carried out. |
| `README.md` | This file — team-specific index of the documents above. |

All diagrams use Mermaid. See `accessibility_audit_team`, `branding_team`,
`investment_team`, `startup_advisor`, and `agentic_team_provisioning` for
worked examples.
