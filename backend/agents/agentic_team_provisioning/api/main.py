"""FastAPI application for the Agentic Team Provisioning service."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import FastAPI, HTTPException

from agentic_team_provisioning.assistant.agent import ProcessDesignerAgent
from agentic_team_provisioning.assistant.store import AgenticTeamStore
from agentic_team_provisioning.models import (
    ConversationStateResponse,
    ConversationSummaryResponse,
    CreateConversationRequest,
    CreateTeamRequest,
    CreateTeamResponse,
    ProcessDefinition,
    SendMessageRequest,
    TeamDetailResponse,
    TeamSummary,
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Agentic Team Provisioning API",
    description="Create agentic teams and define their processes through conversation",
)

_store = AgenticTeamStore()
_agent = ProcessDesignerAgent()

GREETING = (
    "Hello! I'm your Process Designer assistant. I'll help you define a process "
    "for your team. Let's start — what process would you like to create? "
    "Tell me what it does at a high level, and we'll work through the details together."
)

DEFAULT_SUGGESTIONS = [
    "I want to define a customer onboarding process",
    "Help me create a content review workflow",
    "I need a process for handling support tickets",
]


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/health")
def health():
    return {"status": "ok", "service": "agentic-team-provisioning"}


# ---------------------------------------------------------------------------
# Teams
# ---------------------------------------------------------------------------


@app.post("/teams", response_model=CreateTeamResponse)
def create_team(req: CreateTeamRequest):
    team = _store.create_team(name=req.name, description=req.description)
    return CreateTeamResponse(
        team_id=team.team_id,
        name=team.name,
        description=team.description,
        created_at=team.created_at,
    )


@app.get("/teams", response_model=list[TeamSummary])
def list_teams():
    rows = _store.list_teams()
    return [TeamSummary(**r) for r in rows]


@app.get("/teams/{team_id}", response_model=TeamDetailResponse)
def get_team(team_id: str):
    team = _store.get_team(team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    return TeamDetailResponse(team=team)


# ---------------------------------------------------------------------------
# Processes (direct CRUD — processes can also be created via conversation)
# ---------------------------------------------------------------------------


@app.get("/teams/{team_id}/processes", response_model=list[ProcessDefinition])
def list_processes(team_id: str):
    team = _store.get_team(team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    return team.processes


@app.get("/processes/{process_id}", response_model=ProcessDefinition)
def get_process(process_id: str):
    process = _store.get_process(process_id)
    if not process:
        raise HTTPException(status_code=404, detail="Process not found")
    return process


# ---------------------------------------------------------------------------
# Conversations (chat-based process design)
# ---------------------------------------------------------------------------


def _build_state_response(
    conversation_id: str,
    team_id: str,
    process: Optional[ProcessDefinition],
    suggested_questions: list[str],
) -> ConversationStateResponse:
    messages = _store.get_messages(conversation_id)
    return ConversationStateResponse(
        conversation_id=conversation_id,
        team_id=team_id,
        messages=messages,
        current_process=process,
        suggested_questions=suggested_questions,
    )


@app.post("/conversations", response_model=ConversationStateResponse)
def create_conversation(req: CreateConversationRequest):
    # Validate team exists
    team = _store.get_team(req.team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    conversation_id = _store.create_conversation(team_id=req.team_id)

    if req.initial_message:
        # User sent an opening message — process it
        _store.append_message(conversation_id, "user", req.initial_message)

        reply, process, suggestions = _agent.respond(
            conversation_history=[],
            current_process=None,
            user_message=req.initial_message,
        )

        _store.append_message(conversation_id, "assistant", reply)
        if process:
            _store.save_process(req.team_id, process)
            _store.set_conversation_process(conversation_id, process.process_id)

        return _build_state_response(conversation_id, req.team_id, process, suggestions)

    # No initial message — just add the greeting
    _store.append_message(conversation_id, "assistant", GREETING)
    return _build_state_response(conversation_id, req.team_id, None, DEFAULT_SUGGESTIONS)


@app.post("/conversations/{conversation_id}/messages", response_model=ConversationStateResponse)
def send_message(conversation_id: str, req: SendMessageRequest):
    team_id = _store.get_conversation_team_id(conversation_id)
    if not team_id:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Load current process (if any)
    process_id = _store.get_conversation_process_id(conversation_id)
    current_process = _store.get_process(process_id) if process_id else None

    # Build conversation history pairs
    existing_messages = _store.get_messages(conversation_id)
    history = [(m.role, m.content) for m in existing_messages]

    # Record user message
    _store.append_message(conversation_id, "user", req.message)

    # Get LLM response
    reply, updated_process, suggestions = _agent.respond(
        conversation_history=history,
        current_process=current_process,
        user_message=req.message,
    )

    _store.append_message(conversation_id, "assistant", reply)

    # Persist process updates
    effective_process = current_process
    if updated_process:
        _store.save_process(team_id, updated_process)
        _store.set_conversation_process(conversation_id, updated_process.process_id)
        effective_process = updated_process

    return _build_state_response(conversation_id, team_id, effective_process, suggestions)


@app.get("/conversations/{conversation_id}", response_model=ConversationStateResponse)
def get_conversation(conversation_id: str):
    team_id = _store.get_conversation_team_id(conversation_id)
    if not team_id:
        raise HTTPException(status_code=404, detail="Conversation not found")

    process_id = _store.get_conversation_process_id(conversation_id)
    process = _store.get_process(process_id) if process_id else None

    return _build_state_response(conversation_id, team_id, process, [])


@app.get("/teams/{team_id}/conversations", response_model=list[ConversationSummaryResponse])
def list_conversations(team_id: str):
    team = _store.get_team(team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    rows = _store.list_conversations(team_id)
    return [ConversationSummaryResponse(**r) for r in rows]
