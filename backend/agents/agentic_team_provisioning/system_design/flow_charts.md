# Flow Charts

> These flows animate the static structures in [`../designs/Agentic-team-architecture.png`](../designs/Agentic-team-architecture.png) and [`../designs/AgenticTeamApiInteractionsArchitecture.png`](../designs/AgenticTeamApiInteractionsArchitecture.png). Each sequence diagram's participant list uses the exact labels from those PNGs (`Actor`, `UI`, `API Layer`, `Orchestrator Agent`, `Agents pool`, `Processes pool`, `File System`, `Database`, `Job Tracking`, `Question Tracking`) so the reader can map every lifeline back to a box in the PNG.

## 1. Sequence — Conversational team design (animates UC1)

Participants correspond to: `Actor` (PNG #2 stick figure), `UI` (PNG #2 monitor), `API Layer · User Requests` (PNG #2 box), `Orchestrator Agent` (PNG #1 middle box), `LLM Service` (external, dashed in our architecture diagram), `Agents pool` (PNG #1 bottom-left), `Processes pool` (PNG #1 bottom-right), `Database` (PNG #2 cylinder).

```mermaid
sequenceDiagram
    autonumber
    participant EndUser as Actor
    participant UI
    participant API as "API Layer · User Requests"
    participant Orch as "Orchestrator Agent"
    participant LLM as "LLM Service"
    participant Agents as "Agents pool"
    participant Procs as "Processes pool"
    participant DB as "Database"

    EndUser->>UI: Type - design a customer onboarding team
    UI->>API: POST /conversations/{id}/messages
    API->>Orch: send_message(conversation_id, body)
    Orch->>DB: get_messages(conversation_id)
    DB-->>Orch: history[]
    Orch->>DB: get_conversation_process_id + get_process
    DB-->>Orch: current_process (or None)
    Orch->>DB: append_message(role=user)
    Orch->>LLM: ProcessDesignerAgent.respond(history, current_process, user_message, current_agents)
    LLM-->>Orch: reply + agents_json + process_json + suggestions
    Orch->>DB: append_message(role=assistant)
    Orch->>Agents: _save_agents_from_llm → store.save_team_agents
    Orch->>Procs: store.save_process (if process_json)
    Orch->>Orch: _after_process_saved → schedule_provision_step_agents
    Orch-->>API: ConversationStateResponse
    API-->>UI: messages[], current_process, suggested_questions
    UI-->>EndUser: chat reply + refreshed roster + process diagram
```

Source: [`api/main.py:389-424`](../api/main.py), [`assistant/agent.py`](../assistant/agent.py), [`assistant/store.py`](../assistant/store.py), [`agent_env_provisioning.py:53-85`](../agent_env_provisioning.py).

## 2. Sequence — Agent environment provisioning bridge (animates UC4)

```mermaid
sequenceDiagram
    autonumber
    participant Orch as "Orchestrator Agent"
    participant Store as "Database (agent_env_provisions)"
    participant Thread as "Daemon thread<br/>(prov-{agent_id[:24]})"
    participant APT as "Agent Provisioning Team"

    Note over Orch: After every process save<br/>(_after_process_saved)
    Orch->>Orch: schedule_provision_step_agents(team_id, process, store)
    loop for each step.agents
        Orch->>Orch: stable_key = process_id:step_id:agent_name
        Orch->>Orch: prov_id = make_provisioning_agent_id(...)
        Orch->>Store: try_begin_agent_env_provision(...)
        Store-->>Orch: should_run (bool)
        alt should_run
            Orch->>Thread: _spawn_provision_thread(...)
            Thread->>APT: ProvisioningOrchestrator.run_workflow(prov_id, manifest, STANDARD)
            APT-->>Thread: result.success + optional error
            alt success
                Thread->>Store: mark_agent_env_provision_finished(success=True)
            else failure
                Thread->>Store: mark_agent_env_provision_finished(success=False, error_message=...)
            end
        else already running
            Note over Orch: deduplicated — no new thread
        end
    end
```

Source: [`agent_env_provisioning.py:53-129`](../agent_env_provisioning.py), [`api/main.py:464-471`](../api/main.py) (status read path).

## 3. Sequence — Asset upload (animates the `Assets → File System` edge from PNG #2)

```mermaid
sequenceDiagram
    autonumber
    participant EndUser as Actor
    participant UI
    participant API as "API Layer · Assets"
    participant Orch as "Orchestrator Agent"
    participant FS as "File System"

    EndUser->>UI: Select file, click upload
    UI->>API: POST /teams/{team_id}/assets (multipart)
    API->>Orch: upload_team_asset(team_id, file)
    Orch->>Orch: _get_infra_or_404(team_id)
    Orch->>Orch: _safe_asset_name(file.filename)
    Orch->>FS: dest.write_bytes(await file.read())
    FS-->>Orch: stat (size, mtime)
    Orch-->>API: AssetInfo(name, size_bytes, modified_at)
    API-->>UI: 200 AssetInfo
    UI-->>EndUser: File appears in asset list
```

Note: `FS` is rooted at `$AGENT_CACHE/provisioned_teams/{team_id}/assets/` (see `infrastructure.py`).

Source: [`api/main.py:559-612`](../api/main.py), [`infrastructure.py`](../infrastructure.py).

## 4. Sequence — Form record write (animates the `Form Information → Database` edge from PNG #2)

```mermaid
sequenceDiagram
    autonumber
    participant EndUser as Actor
    participant UI
    participant API as "API Layer · Form Information"
    participant Orch as "Orchestrator Agent"
    participant FormStore as "TeamFormStore"
    participant DB as "Database — team.db"

    EndUser->>UI: Submit form
    UI->>API: POST /teams/{team_id}/forms/{form_key}
    API->>Orch: create_team_form_record(team_id, form_key, req.data)
    Orch->>Orch: _get_infra_or_404(team_id)
    Orch->>FormStore: form_store.create_record(form_key, data)
    FormStore->>DB: INSERT INTO form_data (record_id, form_key, data_json, created_at, updated_at)
    DB-->>FormStore: OK
    FormStore-->>Orch: record dict
    Orch-->>API: FormRecord
    API-->>UI: 201 FormRecord
```

Note: `FormStore` is `TeamFormStore` from `infrastructure.py`; `DB` is the per-team SQLite at `$AGENT_CACHE/provisioned_teams/{team_id}/team.db` in WAL mode.

Source: [`api/main.py:635-640`](../api/main.py), [`infrastructure.py:30-80`](../infrastructure.py).

## 5. Flowchart — Roster validation (animates UC2)

```mermaid
flowchart TD
    Start["validate_roster(team)"]
    Start --> BuildMap["roster_map = {agent.agent_name: agent}<br/>used_agent_names = ∅"]
    BuildMap --> LoopP{"for proc in team.processes"}
    LoopP -->|next proc| CheckSteps{"proc.steps empty?"}
    CheckSteps -->|yes| GapUnstaffed1["gap: unstaffed_step (no steps)"]
    CheckSteps -->|no| LoopS{"for step in proc.steps"}
    LoopS -->|next step| StepAgents{"step.agents empty?"}
    StepAgents -->|yes| GapUnstaffed2["gap: unstaffed_step"]
    StepAgents -->|no| LoopSA{"for sa in step.agents"}
    LoopSA --> AddUsed["used_agent_names.add(sa.agent_name)"]
    AddUsed --> InRoster{"sa.agent_name in roster_map?"}
    InRoster -->|no| GapUnrostered["gap: unrostered_agent"]
    InRoster -->|yes| LoopSA
    GapUnrostered --> LoopSA
    GapUnstaffed2 --> LoopS
    LoopS -->|done| LoopP
    LoopP -->|done| UnusedCheck["_check_unused_agents<br/>(only if team.processes)"]
    UnusedCheck --> LoopUnused{"for name in sorted(roster_map)"}
    LoopUnused -->|name not in used| GapUnused["gap: unused_agent"]
    LoopUnused -->|done| DepthCheck["_check_roster_depth(team.agents)"]
    DepthCheck --> LoopDepth{"for a in agents"}
    LoopDepth -->|"missing == 4 (skills, capabilities, tools, expertise)"| GapIncomplete["gap: incomplete_profile"]
    LoopDepth -->|"missing >= 3"| GapSparse["gap: sparse_profile"]
    LoopDepth -->|done| Aggregate["is_fully_staffed = len(gaps) == 0<br/>summary = _build_summary(...)"]
    Aggregate --> Result["RosterValidationResult(is_fully_staffed, agent_count, process_count, gaps, summary)"]

    classDef good fill:#e6f4ea,stroke:#188038
    classDef bad fill:#fce8e6,stroke:#c5221f
    class Result good
    class GapUnstaffed1,GapUnstaffed2,GapUnrostered,GapUnused,GapIncomplete,GapSparse bad
```

Source: [`roster_validation.py:23-151`](../roster_validation.py).

## 6. Flowchart — Pipeline test run (animates UC9)

```mermaid
flowchart TD
    Start["POST /teams/{id}/test-pipeline/runs"]
    Start --> Locate["Locate ProcessDefinition in team.processes"]
    Locate --> Create["_test_store.create_pipeline_run<br/>(status=RUNNING)"]
    Create --> Spawn["PipelineRunner.start_run<br/>→ thread: pipeline-{run_id[:16]}"]
    Spawn --> Execute["_execute(run_id, team_agents, process, resume_event)"]
    Execute --> Walk{"for step in DAG"}
    Walk -->|ACTION| RunAction["build_agent(...) → call_agent(input) → PipelineStepResult"]
    Walk -->|DECISION| EvalCond["evaluate step.condition → pick next step_id"]
    Walk -->|PARALLEL_SPLIT| Fan["enqueue children in parallel"]
    Walk -->|PARALLEL_JOIN| Merge["wait for all parents"]
    Walk -->|SUBPROCESS| Nest["recurse into sub-process"]
    Walk -->|WAIT| Pause["status=WAITING_FOR_INPUT<br/>human_prompt=step.description<br/>resume_event.wait()"]

    Pause --> Resume{"POST .../input OR cancel?"}
    Resume -->|input| Resumed["submit_human_input:<br/>human_inputs[run_id]=input<br/>status=running<br/>event.set()"]
    Resume -->|cancel| Cancelled["cancel_run:<br/>status=CANCELLED<br/>event.set()"]
    Resumed --> Walk
    RunAction --> Walk
    EvalCond --> Walk
    Fan --> Walk
    Merge --> Walk
    Nest --> Walk

    Walk -->|done| Finish["status=COMPLETED<br/>finished_at=now"]
    Walk -.->|exception| Fail["status=FAILED<br/>error=str(e)"]
    Cancelled --> End["End"]
    Finish --> End
    Fail --> End
```

Source: [`runtime/pipeline_runner.py:33-120+`](../runtime/pipeline_runner.py), [`api/main.py:858-933`](../api/main.py), `StepType` in [`models.py:24-32`](../models.py), `PipelineRunStatus` in [`models.py:57-64`](../models.py).

## 7. State — `PipelineRunStatus`

```mermaid
stateDiagram-v2
    [*] --> RUNNING : start_run
    RUNNING --> WAITING_FOR_INPUT : WAIT step reached
    WAITING_FOR_INPUT --> RUNNING : submit_human_input
    RUNNING --> COMPLETED : DAG exhausted
    RUNNING --> FAILED : exception
    RUNNING --> CANCELLED : cancel_run
    WAITING_FOR_INPUT --> CANCELLED : cancel_run
    COMPLETED --> [*]
    FAILED --> [*]
    CANCELLED --> [*]
```

Source: [`models.py:57-64`](../models.py), [`runtime/pipeline_runner.py:58-71`](../runtime/pipeline_runner.py).

## 8. State — `TeamMode`

```mermaid
stateDiagram-v2
    [*] --> DEVELOPMENT : POST /teams
    DEVELOPMENT --> TESTING : PUT /teams/{id}/mode (mode=testing)
    TESTING --> DEVELOPMENT : PUT /teams/{id}/mode (mode=development)
    TESTING --> TESTING : Test chat / pipeline runs
    DEVELOPMENT --> DEVELOPMENT : Chat / process edits / provisioning
```

Source: [`models.py:43-47`](../models.py), [`api/main.py:670-677`](../api/main.py).

---

### PNG-box → participant cross-reference

| PNG box (legacy) | Appears in these diagrams as |
|---|---|
| PNG #2 `Actor` (stick figure) | §1, §3, §4 lifeline `Actor` |
| PNG #2 `UI` (monitor) | §1, §3, §4 lifeline `UI` |
| PNG #2 `API Layer` | §1 `API Layer · User Requests`, §3 `API Layer · Assets`, §4 `API Layer · Form Information` |
| PNG #2 `Agentic Team` = PNG #1 `Orchestrator Agent` | §1-§4 lifeline `Orchestrator Agent` |
| PNG #2 `File System` | §3 `File System` |
| PNG #2 `Database` | §1, §4 `Database` |
| PNG #1 `Agents` pool | §1 `Agents pool` |
| PNG #1 `Processes` pool | §1 `Processes pool` |
| PNG #1 `Job Tracking` / `Question Tracking` | Referenced in UC5 (use_cases.md) — no dedicated sequence here since they're simple `JobServiceClient` wrappers |
