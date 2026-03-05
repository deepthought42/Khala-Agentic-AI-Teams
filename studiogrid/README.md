# StudioGrid Team

Strands scaffold for a design-system multi-agent workflow.

## Quick start

```bash
cd studiogrid
cp .env.example .env
docker compose up --build
```

Run CLI:

```bash
PYTHONPATH=src python -m studiogrid.main run start --project-name Demo --intake examples/intake.json
```

## Registry CLI

List registered agents:

```bash
PYTHONPATH=src python -m studiogrid.main registry list
```

Find assisting agents for a task and prefer same-team agents when `--requesting-agent` is set:

```bash
PYTHONPATH=src python -m studiogrid.main registry find \
  --problem "Need accessibility review for updated dashboard" \
  --skills accessibility_review \
  --requesting-agent design_lead
```

List teams currently available for orchestrator selection:

```bash
PYTHONPATH=src python -m studiogrid.main team list --available-only
```
