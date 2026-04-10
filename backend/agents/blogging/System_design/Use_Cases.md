# Blogging Team — Use Cases

This document describes the actors, primary use cases, and detailed interaction sequences for the blogging agent suite.

---

## 1. Actors

| Actor | Type | Description |
|-------|------|-------------|
| **Human Author** | Primary | Content creator who initiates pipelines, provides feedback, selects titles, tells stories, and approves publications |
| **Angular UI** | System | Frontend client that renders progress, collects user inputs, and streams SSE events |
| **API Client** | System | Any HTTP client (CLI, script, integration) calling the REST API directly |
| **LLM Service** | Internal | Ollama/Claude inference backend used by all LLM-powered agents |
| **Temporal Server** | Internal | Durable workflow engine for long-running pipeline execution |
| **PostgreSQL** | Internal | Persistent store for job state, story bank, and integration credentials |
| **Medium.com** | External | Publishing platform; stats scraped via Playwright |
| **arXiv** | External | Academic paper repository searched during research |

---

## 2. Primary Use Cases

```mermaid
graph TD
    Author["Human Author"]
    UI["Angular UI"]
    APIClient["API Client"]

    subgraph "Blogging Team Use Cases"
        UC1["Run Full Pipeline"]
        UC2["Research & Review Only"]
        UC3["Review Draft & Provide Feedback"]
        UC4["Select Title"]
        UC5["Provide Story Input"]
        UC6["Answer Agent Questions"]
        UC7["Approve / Reject Publication"]
        UC8["Collect Medium Stats"]
        UC9["Monitor Pipeline Progress"]
        UC10["Restart Failed Job"]
    end

    Author --> UC1
    Author --> UC2
    Author --> UC3
    Author --> UC4
    Author --> UC5
    Author --> UC6
    Author --> UC7
    Author --> UC8
    Author --> UC10

    UI --> UC9
    APIClient --> UC1
    APIClient --> UC2
    APIClient --> UC8

    UC1 -->|includes| UC3
    UC1 -->|includes| UC4
    UC1 -->|includes| UC5
    UC1 -->|includes| UC6
    UC1 -->|includes| UC7
```

---

## 3. Use Case: Full Pipeline Execution

The primary use case — an author requests a complete blog post from brief to publishing-ready output.

### 3.1 Sequence Diagram

```mermaid
sequenceDiagram
    actor Author
    participant UI as Angular UI
    participant API as Blogging API
    participant JS as Job Store
    participant Pipeline as Pipeline Orchestrator
    participant RA as Research Agent
    participant PA as Planning Agent
    participant WA as Writer Agent
    participant GW as Ghost Writer
    participant CE as Copy Editor
    participant Val as Validators
    participant FC as Fact Check Agent
    participant CA as Compliance Agent
    participant Pub as Publication Agent

    Author->>UI: Submit brief, audience, tone, profile
    UI->>API: POST /jobs {brief, audience, ...}
    API->>JS: create_blog_job(job_id)
    API-->>UI: {job_id}
    UI->>API: GET /stream/{job_id} (SSE)

    Note over Pipeline: Phase 1: PLANNING (0-15%)
    API->>Pipeline: run_blog_full_pipeline_job()
    Pipeline->>RA: run(ResearchBriefInput)
    RA-->>Pipeline: ResearchAgentOutput
    Pipeline->>PA: run(PlanningInput)

    loop Refine until acceptable
        PA->>PA: Generate/refine ContentPlan
        PA->>PA: Check requirements_analysis
    end

    PA-->>Pipeline: PlanningPhaseResult
    Pipeline-->>UI: SSE {phase: planning, progress: 15}

    Note over Pipeline: Phase 2: DRAFT_INITIAL (15-30%)
    Pipeline->>WA: draft_from_planning(WriterInput)
    WA-->>Pipeline: WriterOutput (draft_v1)

    opt Story placeholders detected
        Pipeline->>GW: elicit_stories(StoryGap[])
        loop Per story gap
            GW-->>UI: SSE {waiting_for_story_input}
            Author->>UI: Provide story details
            UI->>API: POST /job/{id}/story-message
            API->>GW: deliver user message
        end
        GW-->>Pipeline: StoryElicitationResult[]
        Pipeline->>WA: Regenerate draft with stories
    end

    Pipeline-->>UI: SSE {phase: draft_initial, progress: 30}

    Note over Pipeline: Phase 3: DRAFT_REVIEW (30-45%)
    opt Uncertainty questions detected
        Pipeline-->>UI: SSE {waiting_for_answers, pending_questions}
        Author->>UI: Provide answers
        UI->>API: POST /job/{id}/answers
        Pipeline->>WA: revise_from_user_feedback()
    end

    Pipeline-->>UI: SSE {waiting_for_draft_feedback, draft_preview}
    Author->>UI: Review draft, provide feedback
    UI->>API: POST /job/{id}/draft-feedback
    Pipeline->>WA: revise_from_user_feedback()
    Pipeline-->>UI: SSE {phase: draft_review, progress: 45}

    Note over Pipeline: Phase 4: COPY_EDIT (45-60%)
    loop Copy edit iterations
        Pipeline->>CE: run(CopyEditorInput)
        CE-->>Pipeline: CopyEditorOutput {feedback_items}
        alt Editor approves
            Pipeline->>Pipeline: Break loop
        else Feedback provided
            Pipeline->>WA: revise_from_feedback(ReviseWriterInput)
            WA-->>Pipeline: WriterOutput (revised)
        end
    end
    Pipeline-->>UI: SSE {phase: copy_edit, progress: 60}

    Note over Pipeline: Phase 5-6: FACT_CHECK + COMPLIANCE (60-82%)
    Pipeline->>Val: run_validators(draft)
    Val-->>Pipeline: ValidatorReport
    Pipeline->>FC: run(draft)
    FC-->>Pipeline: FactCheckReport
    Pipeline->>CA: run(draft, brand_spec, validator_report)
    CA-->>Pipeline: ComplianceReport

    alt All gates PASS
        Pipeline-->>UI: SSE {phase: compliance, progress: 82}
    else Any gate FAIL
        Note over Pipeline: Phase 7: REWRITE_LOOP (82-90%)
        loop Max rewrite iterations
            Pipeline->>WA: revise_from_feedback(required_fixes)
            Pipeline->>Val: re-run validators
            Pipeline->>FC: re-run fact check
            Pipeline->>CA: re-run compliance
        end
    end

    Note over Pipeline: Phase 8: TITLE_SELECTION (90-96%)
    Pipeline-->>UI: SSE {waiting_for_title_selection, title_choices}
    Author->>UI: Select preferred title
    UI->>API: POST /job/{id}/title-selection

    Note over Pipeline: Phase 9: FINALIZE (96-100%)
    Pipeline->>Pipeline: Generate PublishingPack
    Pipeline->>JS: complete_blog_job()
    Pipeline-->>UI: SSE {phase: finalize, progress: 100, status: COMPLETED}
```

---

## 4. Use Case: Human Collaboration Points

The pipeline pauses at multiple points for human input. Each pause sets a `waiting_for_*` flag on the job record and resumes when the corresponding API endpoint receives input.

### 4.1 Title Selection

```mermaid
sequenceDiagram
    actor Author
    participant UI as Angular UI
    participant API as Blogging API
    participant JS as Job Store
    participant Pipeline as Pipeline

    Pipeline->>JS: update(waiting_for_title_selection=true, title_choices=[...])
    JS-->>UI: SSE {title_choices: [{title, probability, scoring}]}
    UI->>Author: Display title candidates with scores

    Note over Author: Reviews titles:<br/>curiosity_gap, specificity,<br/>audience_fit, seo_potential,<br/>emotional_pull

    Author->>UI: Select preferred title
    UI->>API: POST /job/{id}/title-selection {selected_title}
    API->>JS: submit_title_selection(job_id, title)
    JS->>Pipeline: Resume with selected title
    Pipeline->>Pipeline: Continue to FINALIZE phase
```

### 4.2 Story Elicitation (Multi-turn Interview)

```mermaid
sequenceDiagram
    actor Author
    participant UI as Angular UI
    participant API as Blogging API
    participant JS as Job Store
    participant GW as Ghost Writer Agent

    Note over GW: Scans draft for [Author: ...] placeholders
    GW->>JS: update(story_gaps=[{section, context, seed_question}])

    loop For each story gap
        GW->>JS: update(waiting_for_story_input=true, current_gap_idx=N)
        JS-->>UI: SSE {story_gap: {section_title, seed_question}}
        UI->>Author: Display interview question

        loop Multi-turn interview (max rounds)
            Author->>UI: Share story detail
            UI->>API: POST /job/{id}/story-message {message}
            API->>JS: submit_story_user_message(job_id, gap_idx, message)
            GW->>GW: Process response, generate follow-up
            GW-->>UI: Follow-up question or "story complete"
        end

        GW->>GW: Compile narrative from conversation
        GW->>JS: Save story to story bank (Postgres)
    end

    GW-->>Pipeline: StoryElicitationResult[] for all gaps
```

### 4.3 Draft Feedback with Guideline Updates

```mermaid
sequenceDiagram
    actor Author
    participant UI as Angular UI
    participant API as Blogging API
    participant JS as Job Store
    participant Pipeline as Pipeline
    participant WA as Writer Agent

    Pipeline->>JS: update(waiting_for_draft_feedback=true, draft_for_review=draft)
    JS-->>UI: SSE {draft_preview, waiting_for_draft_feedback}
    UI->>Author: Display draft for review

    Author->>UI: Provide feedback + optional guideline update request
    UI->>API: POST /job/{id}/draft-feedback {approved, feedback, guideline_updates_requested}
    API->>JS: submit_draft_feedback(job_id, UserDraftFeedback)

    alt Guideline updates requested
        Pipeline->>Pipeline: Analyze feedback for style guide improvements
        Pipeline->>Pipeline: Reload writing guidelines
        Pipeline->>Pipeline: Rebuild Writer + Editor agents with new guidelines
        Pipeline->>JS: update(guideline_updates_applied=true)
    end

    Pipeline->>WA: revise_from_user_feedback(draft, feedback)
    WA-->>Pipeline: Revised WriterOutput

    alt Author approved
        Pipeline->>Pipeline: Proceed to copy edit
    else Author not satisfied
        Pipeline->>JS: update(waiting_for_draft_feedback=true)
        Note over Author: Another review round
    end
```

### 4.4 Uncertainty Question Resolution

```mermaid
sequenceDiagram
    actor Author
    participant UI as Angular UI
    participant API as Blogging API
    participant JS as Job Store
    participant Pipeline as Pipeline
    participant WA as Writer Agent

    WA->>Pipeline: DraftReviewResult {uncertainty_questions: [...]}
    Pipeline->>JS: update(waiting_for_answers=true, pending_questions=[...])
    JS-->>UI: SSE {pending_questions: [{question_id, question, context, section}]}
    UI->>Author: Display questions with section context

    Author->>UI: Provide answers
    UI->>API: POST /job/{id}/answers {question_id: answer, ...}
    API->>JS: submit_blog_answers(job_id, answers)

    Pipeline->>WA: revise_from_user_feedback(draft, answers)
    WA-->>Pipeline: Revised draft with answers incorporated
    Pipeline->>Pipeline: Continue pipeline
```

---

## 5. Use Case: Publication Workflow

```mermaid
sequenceDiagram
    actor Author
    participant UI as Angular UI
    participant API as Blogging API
    participant Pub as Publication Agent
    participant FS as File System

    Note over Pub: Draft passes all gates

    Pub->>Pub: submit_draft(SubmitDraftInput)
    Pub->>FS: Write to blog_posts/pending/{slug}/
    Pub-->>UI: PublicationSubmission {state: awaiting_approval}

    alt Author approves
        Author->>UI: Approve publication
        UI->>API: POST /job/{id}/approve
        API->>Pub: approve(submission_id)

        par Platform formatting
            Pub->>Pub: format_for_medium()
            Pub->>Pub: format_for_devto()
            Pub->>Pub: format_for_substack()
        end

        Pub->>FS: Write to blog_posts/{slug}/
        Note over FS: final.md<br/>medium.md<br/>devto.md<br/>substack.md

        Pub-->>UI: ApprovalResult {folder_path, platform_paths}

    else Author rejects
        Author->>UI: Reject with feedback
        UI->>API: POST /job/{id}/reject {feedback}
        API->>Pub: reject(submission_id, feedback)
        Pub->>Pub: Collect rejection feedback

        opt Revision requested
            Pub->>Pub: Revision loop with Writer + Copy Editor
            Pub-->>UI: RevisionLoopResult
            Note over Author: Re-review revised draft
        end
    end
```

---

## 6. Use Case: Medium Stats Collection

```mermaid
sequenceDiagram
    actor Author
    participant UI as Angular UI
    participant API as Blogging API
    participant MSA as Medium Stats Agent
    participant IntStore as Integration Store
    participant PW as Playwright Browser

    Author->>UI: Request Medium stats
    UI->>API: POST /medium-stats-async

    API->>IntStore: Check medium integration eligible
    IntStore-->>API: (eligible, error_message)

    alt Not eligible
        API-->>UI: 503 Integration not configured
    else Eligible
        API->>IntStore: resolve_medium_stats_storage_state()

        alt Storage state exists
            IntStore-->>MSA: storage_state dict
        else No storage state
            IntStore->>IntStore: Load Google browser credentials (Postgres)
            IntStore->>PW: Auto-login to Medium via Google
            PW-->>IntStore: New storage_state
            IntStore-->>MSA: storage_state dict
        end

        MSA->>PW: Launch Chromium (headless)
        PW->>PW: Navigate to medium.com/me/stats
        PW->>PW: Scrape stats table
        PW-->>MSA: Raw stats data
        MSA->>MSA: Parse into MediumStatsReport
        MSA-->>API: MediumStatsReport
        API-->>UI: {posts: [{title, url, stats}]}
    end
```

---

## 7. Use Case: Research & Review Only

A lightweight use case for exploring a topic without full pipeline execution.

```mermaid
sequenceDiagram
    actor Author
    participant API as Blogging API
    participant RA as Research Agent
    participant PA as Planning Agent

    Author->>API: POST /research-and-review {brief, audience, tone, max_results}

    API->>RA: run(ResearchBriefInput)
    Note over RA: Web search + arXiv search<br/>Source ranking + synthesis
    RA-->>API: ResearchAgentOutput

    API->>PA: run(PlanningInput)
    Note over PA: Generate ContentPlan<br/>Refine loop until acceptable
    PA-->>API: PlanningPhaseResult

    API-->>Author: {title_choices, outline, compiled_document, notes}

    opt work_dir provided
        API->>API: Persist research_packet.md, content_plan.json, outline.md
    end
```

---

## 8. API Endpoint Mapping

| Use Case | Method | Endpoint | Request Body | Response |
|----------|--------|----------|-------------|----------|
| Run full pipeline (sync) | POST | `/full-pipeline` | `FullPipelineRequest` | `FullPipelineResponse` |
| Create async job | POST | `/jobs` | `FullPipelineRequest` | `{job_id}` |
| Poll job status | GET | `/job/{id}` | — | `BlogJobStatusResponse` |
| Stream progress (SSE) | GET | `/stream/{job_id}` | — | SSE events |
| Select title | POST | `/job/{id}/title-selection` | `{selected_title}` | 200 OK |
| Submit draft feedback | POST | `/job/{id}/draft-feedback` | `UserDraftFeedback` | 200 OK |
| Send story message | POST | `/job/{id}/story-message` | `{message}` | 200 OK |
| Skip story gap | POST | `/job/{id}/skip-story` | — | 200 OK |
| Submit answers | POST | `/job/{id}/answers` | `{question_id: answer}` | 200 OK |
| Approve publication | POST | `/job/{id}/approve` | — | `ApprovalResult` |
| Reject publication | POST | `/job/{id}/reject` | `{feedback}` | `RejectionResponse` |
| Research & review | POST | `/research-and-review` | `{brief, audience, ...}` | `{title_choices, outline, ...}` |
| Medium stats (sync) | POST | `/medium-stats` | `MediumStatsRequest` | `MediumStatsReport` |
| Medium stats (async) | POST | `/medium-stats-async` | `MediumStatsRequest` | `{job_id}` |
| Restart job | POST | `/restart/{id}` | — | 200 OK |
| Delete job | DELETE | `/job/{id}` | — | 200 OK |
| Health check | GET | `/health` | — | `{status, brand_spec_configured}` |
