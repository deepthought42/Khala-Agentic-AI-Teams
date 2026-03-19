# Product Requirements Analysis Team — PRD Gap Analysis

## Scope and method

This analysis compares the **current Product Requirements Analysis (PRA) workflow in this repository** with the content expected in a complete PRD (who/what/where/why/how), aligned to standard PRD best practices.

## What the PRA team currently does

From code review of the PRA agent and prompts:

1. Runs iterative spec review to find issues/gaps/questions.
2. Focuses heavily on technical constraint drilling (infrastructure/frontend/backend/database/auth).
3. Auto-answers and applies clarifications to the spec.
4. Cleans/validates the spec.
5. Generates a markdown PRD from cleaned spec + answered questions.
6. Saves output under `plan/product_analysis/validated_spec.md` and `product_requirements_document.md`.

## Gap matrix: current vs needed for a real PRD

| PRD area (who/what/where/why/how) | Current PRA coverage | Gap | Impact | What is needed |
|---|---|---|---|---|
| **Why: strategic context** (business objective, market problem, urgency, strategic fit) | Partially implied by source spec; not enforced as required sections | No required checks/prompts for explicit strategic context | Teams can build correct software for unclear business intent | Add mandatory sections and validation checks for business objective, market/customer problem, and strategy linkage |
| **Who: customer and stakeholder definition** (personas, segments, buyer vs user, stakeholder map) | PRD prompt mentions "primary personas" but no mandatory extraction/validation | Personas can be absent and still pass cleanup | Solution may optimize for wrong user | Require persona table, stakeholder owners, and user segment assumptions with confidence |
| **Where: operating context** (platforms, channels, geographies, environments, compliance jurisdictions) | Strong on hosting/deployment technology; weak on user/channel/geography context | "Where users experience the product" is not systematically captured | Missed channel constraints and localization/compliance needs | Add required "Operating Context" section: channels, devices, geo/language, deployment environment, regulatory region |
| **What: feature scope and behavior** (functional requirements, user stories, edge behavior) | Functional requirements are requested in PRD prompt | No requirement schema (IDs, priority, rationale, acceptance test linkage) | Ambiguous requirements and traceability gaps | Require structured requirement entries: ID, user value, behavior, acceptance criteria, priority, dependency |
| **How: delivery approach** (UX approach, architecture boundaries, milestones, release plan) | Strong technical stack constraints; no explicit release/milestone template | PRD can omit release sequencing and rollout | Planning/execution lacks phased plan | Add release plan sections: milestones, phased scope, rollout strategy, launch checklist |
| **Success metrics / outcomes** | Prompt asks for KPIs but cleanup does not enforce measurable quality | Non-measurable goals can pass | Hard to evaluate success post-launch | Enforce metric quality checks: baseline, target, timeframe, owner, instrumentation source |
| **Non-functional requirements quality** | Prompt lists performance/reliability/security/observability | No explicit SLO/SLA/SLI format enforcement | NFRs may be vague ("fast", "secure") | Add required NFR template with measurable thresholds and test methods |
| **Dependencies and cross-team impact** | Not a first-class output section | External dependencies often implicit | Delivery risk hidden until late | Require dependency register: team/system dependency, owner, due date, risk |
| **Assumptions, risks, trade-offs** | Prompt includes risks/assumptions/open questions section | No quantitative risk scoring or mitigation ownership requirement | Risks are documented but not managed | Require risk table with likelihood/impact/mitigation/owner/trigger |
| **Open questions governance** | Questions asked/answered during iteration | Remaining open questions not required to have closure plan | Unresolved blockers can drift into build phase | Require unresolved-question log with decision owner and due date |
| **Out of scope / non-goals** | Mentioned in overview guidance | Not validated as mandatory | Scope creep likely | Add mandatory out-of-scope list + anti-goals |
| **Design and UX definition depth** | "Target users & journeys" suggested | No required UX artifacts or decision criteria | UI implementation divergence across teams | Require UX requirements section: key flows, states, accessibility bar, content/system constraints |
| **Data and analytics instrumentation** | Not explicit beyond observability mention | Event taxonomy and analytics plan absent | Cannot validate user outcomes | Add measurement plan: events, properties, funnels, dashboards, owner |
| **Lifecycle and operations** (support, runbooks, incident expectations) | Observability appears in NFR guidance only | Operability not required for launch readiness | Post-launch reliability/support gaps | Add operational readiness section: support model, alerts, runbooks, escalation |
| **Document governance** (version, approvers, decision log) | Artifacts are written to disk; no PRD metadata standard | No formal approval/workflow metadata inside PRD | Auditability and accountability gaps | Add PRD header with owner, approvers, status, revision history, linked decisions |

## Repository-specific evidence for the gaps

- The review and question system is optimized for implementation constraints and clarification loops, especially technology decisions across five constraint domains, but does not force business/market/user completeness dimensions.
- The PRD prompt is a good start but acts as "guidance," not a strict schema with pass/fail checks.
- The cleanup stage validates clarity/structure/actionability generally, but not completeness against a required PRD checklist.

## Implemented solution: PRD completeness gate

The `_generate_prd_document` method now enforces completeness by:

1. Checking the generated PRD for required section headings (`PRD_REQUIRED_SECTIONS`).
2. If sections are missing, running a second LLM pass with `PRD_COMPLETENESS_REPAIR_PROMPT` to fill them in.
3. Logging a warning if sections remain missing after repair.

### Required sections checked

- Executive Summary
- Problem Statement
- Goals and Non-Goals
- Personas and Target Users
- User Stories and Use Cases
- Requirements
- Scope
- Risks, Assumptions, Dependencies
- Rollout Plan
- Acceptance Criteria

## Short conclusion

The current PRA process is strongest at clarifying *implementation constraints* and producing a coherent markdown artifact, but it does not yet guarantee a fully decision-ready PRD across the complete who/what/where/why/how dimensions. The completeness gate (section validation + repair pass) addresses the most critical gaps, ensuring that required PRD sections are always present in the final output.
