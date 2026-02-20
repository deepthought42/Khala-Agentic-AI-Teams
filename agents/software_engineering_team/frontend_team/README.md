# Frontend Team

Frontend sub-orchestration for the software engineering team. Runs the full pipeline from design through implementation, quality gates, and build/release for each frontend task.

## Agent Roster

| Agent | Role |
|-------|------|
| **UX Designer** | User flows, interaction patterns, and experience design from task and spec |
| **UI Designer** | Visual design and component specs; consumes UX output |
| **Design System** | Component library alignment and consistency |
| **Frontend Architect** | Technical architecture decisions (structure, patterns, state management) |
| **Feature Agent** | Implementation (FrontendExpertAgent); generates Angular/TypeScript code |
| **UX Engineer** | Polish pass: micro-interactions, consistency, UX refinement |
| **Performance Engineer** | Bundle size, rendering optimization, performance review |
| **Build/Release** | CI/CD and release planning; writes `plan/frontend_build_release.md` |
| **Accessibility Agent** | WCAG 2.2 compliance; reviews frontend per task |

## Pipeline Order

```
UX Designer → UI Designer → Design System → Frontend Architect → Feature Implementation → UX Engineer → Performance Engineer → Build/Release
```

Design phase (UX → UI → Design System) is **skipped for lightweight tasks** (fix, patch, refactor, etc.) to speed up implementation-only work.

## Quality Gates Integration

The frontend workflow invokes cross-cutting agents from [quality_gates/](../quality_gates/README.md):

- **Code Review** – Spec/standards/acceptance criteria
- **QA Expert** – Bugs, unit/integration tests, README
- **Cybersecurity Expert** – Frontend security checklist (CSP, token storage, PKCE, sanitization)
- **Accessibility Expert** – WCAG 2.2, keyboard nav, screen reader behavior
- **Acceptance Verifier** – Per-criterion evidence
- **DbC Comments** – Pre/postconditions on public APIs

## Lightweight Task Path

Tasks with keywords like `fix`, `resolve`, `update`, `patch`, `refactor` and short descriptions skip the design phase. The orchestrator goes directly to Frontend Architect → Feature Implementation → quality gates.

## See Also

- [Software Engineering Team README](../README.md) – Full SDLC, orchestrator, and run instructions
- [Quality Gates](../quality_gates/README.md) – Cross-cutting review agents
