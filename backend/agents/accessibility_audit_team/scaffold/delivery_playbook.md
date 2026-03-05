# Inclusive Experience Agency Delivery Playbook

## Delivery Principles
1. **Truth over tool output:** Automated scans are directional, not final truth.
2. **Evidence before escalation:** Every high-severity claim must be reproducible.
3. **Standards confidence matters:** WCAG mappings require explicit confidence and rationale.
4. **Fix-ready reporting:** Findings are not complete without acceptance criteria.

## Standard Engagement Cadence

### Phase 0 — Intake (APL)
- Confirm scope, environments, auth constraints, timelines, and non-goals.
- Generate `AuditPlan`, `CoverageMatrix`, and run config.

### Phase 1 — Discovery (WAS/MAS + REE + QCR)
- Run lane-specific scans and manual walkthroughs.
- Draft findings with initial evidence references.
- Cluster duplicates and normalize naming before verification.

### Phase 2 — Verification (ATS + SLMS + RA)
- Validate impact through assistive technology scripts and manual checks.
- Confirm WCAG + Section 508 mapping quality.
- Add remediation recipes, acceptance criteria, and re-test scripts.

### Phase 3 — Report Packaging (QCR + APL)
- Enforce final quality bar and confidence thresholds.
- Produce executive summary, backlog, and remediation roadmap.

### Phase 4 — Retest (Optional)
- Execute fix verification for targeted findings.
- Close findings with evidence or reopen with delta notes.

## Quality Gates
- No finding reaches report stage without required evidence, impact statement, and standards mapping.
- Critical and high findings must include an explicit user impact path and blocker rationale.
- Duplicates are merged into patterns prior to final reporting.
