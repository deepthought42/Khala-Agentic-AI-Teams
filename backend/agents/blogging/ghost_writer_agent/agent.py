"""
Ghost writer story elicitation agent.

Scans a ContentPlan for sections where a personal story would strengthen the post,
then conducts a multi-turn conversational interview with the author to surface
specific anecdotes, failures, and concrete moments. The gathered material is compiled
into first-person narrative snippets passed to the draft agent.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional

from shared.content_plan import ContentPlan

from llm_service.interface import LLMClient

from .models import StoryElicitationResult, StoryGap

logger = logging.getLogger(__name__)

POLL_INTERVAL = 20  # seconds between job-store polls
MAX_ROUNDS = 5  # soft cap for pre-draft interviews (user can still be asked more)
MAX_ROUNDS_POST_DRAFT = 50  # hard safety cap for post-draft interviews (effectively unlimited)

_FIND_GAPS_SYSTEM = """\
You are a curious, enthusiastic ghost writer who loves hearing people's real stories.
You're reviewing a blog post outline to find the 1–3 spots where a personal story
from the author would make the piece come alive — the kind of moment that makes a
reader think "oh, they've actually been through this."

For each spot you find, write an opening question as if you're a friend who just
heard the topic come up and genuinely wants to hear the story. Your question should:
  - Sound natural and warm — like you're chatting over coffee, not conducting an interview
  - Ask about a specific kind of moment or experience (not a vague "tell me about your experience with X")
  - NOT mention the blog post, the content plan, section titles, or any internal structure
  - NOT ask for numbers, metrics, or frameworks — just ask for the story
  - Use phrases like "I'd love to hear about a time you..." or "Have you ever had one
    of those moments where..." or "What's the story behind..."

Return a JSON array of objects. Each object has:
  - "section_title": exact title of the section (for internal tracking only — the author won't see this)
  - "section_context": one sentence explaining what the section covers and why a story fits
  - "seed_question": your friendly opening question

Return [] if no personal story opportunities exist (e.g. purely technical reference post).
Return at most 3 — pick the highest-impact spots.
"""

_EVALUATE_SYSTEM = """\
You are a ghost writer who's been chatting with the author to surface a personal
story for their blog post. You genuinely enjoy hearing people's stories and you
have a knack for knowing when there's more to tell.

Your job: decide whether the author has shared enough for you to write a compelling
first-person narrative, or whether you should keep the conversation going.

There are THREE possible outcomes:

1. **sufficient** — you have what you need for a great story:
  - A specific moment or situation (not just "I've done that kind of thing")
  - What actually happened — the key actions, decisions, or turning points
  - Why it mattered — the outcome, lesson, or how things changed
  - Enough texture to make a reader feel like they were there

2. **no_experience** — the author clearly doesn't have a story for this:
  - They said "skip", "no experience", "pass", "I haven't done that", or similar
  - Respect this immediately — don't push

3. **insufficient** — the author is sharing but you sense there's more:
  - They're being vague or general ("yeah I've dealt with that")
  - The story is missing the juicy parts — what went wrong, how they figured it out, what surprised them
  - You don't know the context yet (was this a side project? client work? their day job?)
  - There's no clear ending — what happened as a result?

When asking follow-ups (insufficient only), be a curious friend, not an interviewer:
  - If you don't know the context yet, ask naturally: "Was this something you built on
    your own, or were you working with a team / for a client?"
  - Dig for the interesting parts: "Wait, what happened next?" / "No way — how did
    they react?" / "OK so what made you try that approach?"
  - If the story is at a company: ask about team dynamics, stakeholders, what leadership thought
  - If it's a personal/fun project: ask what sparked the idea, what was the most surprising part
  - If it's client work: ask about the client's reaction, constraints you were working with
  - Don't ask for numbers or metrics directly — if they come up naturally, great

Also identify the **story context** when you can tell:
  - "personal" — a side project, hobby, something done for fun or learning
  - "client" — work done for a client or customer
  - "employer" — work done as an employee at a company
  - null if unclear yet

Respond in JSON:
{
  "sufficient": true/false,
  "no_experience": true/false,
  "story_context": "personal" | "client" | "employer" | null,
  "follow_up": "If insufficient: a single conversational follow-up question. Otherwise: null.",
  "narrative": "If sufficient: a 2–5 sentence first-person narrative as if the author wrote it. Make it vivid and specific — lead with the moment, include what they did and why, and end with how it turned out. Use only real details from the conversation. Otherwise: null."
}
"""


_NO_EXPERIENCE_PHRASES = frozenset(
    {
        "skip",
        "no experience",
        "no relevant experience",
        "n/a",
        "none",
        "pass",
        "i don't have",
        "i haven't",
        "i have no",
        "i can't think of",
        "nothing comes to mind",
        "not applicable",
        "i don't have a story",
        "no story",
    }
)


def _is_no_experience(message: str) -> bool:
    """Return True if the user's message indicates they have no relevant experience."""
    text = message.strip().lower().rstrip(".!?")
    if text in _NO_EXPERIENCE_PHRASES:
        return True
    return any(phrase in text for phrase in _NO_EXPERIENCE_PHRASES)


class GhostWriterElicitationAgent:
    """
    Identifies story gaps in a content plan and conducts conversational interviews
    to elicit personal anecdotes from the author.
    """

    def __init__(self, llm_client: LLMClient) -> None:
        self.llm_client = llm_client

    def find_story_gaps(self, content_plan: ContentPlan) -> List[StoryGap]:
        """
        Analyse the content plan and return sections where a personal story would help.
        Returns at most 3 gaps.

        First checks the planning agent's ``story_opportunity`` fields — if the planner
        already identified story opportunities, those are converted directly to gaps
        without an extra LLM call. Falls back to LLM gap-finding only when the plan
        has no story_opportunity fields populated.
        """
        # Check if the planning agent already identified story opportunities
        plan_gaps = self._extract_gaps_from_plan(content_plan)
        if plan_gaps:
            logger.info(
                "Ghost writer: using %s story gap(s) from planning agent's story_opportunity fields",
                len(plan_gaps),
            )
            return plan_gaps[:3]

        # Fallback: use LLM to find gaps (for plans without story_opportunity fields)
        return self._find_gaps_via_llm(content_plan)

    def _extract_gaps_from_plan(self, content_plan: ContentPlan) -> List[StoryGap]:
        """Convert planning agent's story_opportunity fields to StoryGap objects."""
        gaps = []
        for sec in sorted(content_plan.sections, key=lambda s: s.order):
            opp = getattr(sec, "story_opportunity", None)
            if not opp:
                continue
            seed = self._generate_friendly_seed(opp)
            gaps.append(
                StoryGap(
                    section_title=sec.title,
                    section_context=f"{sec.coverage_description} — Story needed: {opp}",
                    seed_question=seed,
                )
            )
        return gaps

    def _generate_friendly_seed(self, story_opportunity: str) -> str:
        """Use the LLM to turn a story_opportunity description into a warm, conversational question."""
        prompt = (
            f"Story opportunity description: {story_opportunity}\n\n"
            "Write a single, warm opening question to ask the author about this — as if you're a "
            "friend who just heard the topic come up and genuinely wants to hear the story. "
            "Do NOT mention the blog post, the section, or any internal structure. "
            "Keep it casual and specific. One or two sentences max."
        )
        try:
            result = self.llm_client.complete(
                prompt,
                system_prompt=(
                    "You are a friendly ghost writer. Write exactly one conversational question. "
                    "No preamble, no quotes, just the question."
                ),
            )
            return (result or "").strip().strip('"')
        except Exception as e:
            logger.warning("Ghost writer friendly seed generation failed, using fallback: %s", e)
            return f"I'd love to hear about a time you dealt with {story_opportunity}. What comes to mind?"

    def _find_gaps_via_llm(self, content_plan: ContentPlan) -> List[StoryGap]:
        """Fallback: use LLM to identify story gaps when plan lacks story_opportunity fields."""
        outline_text = self._plan_to_text(content_plan)
        prompt = f"Content plan:\n\n{outline_text}\n\nIdentify story gaps."

        try:
            response = self.llm_client.complete(
                prompt,
                system_prompt=_FIND_GAPS_SYSTEM,
            )
            raw = (response or "").strip()
            start = raw.find("[")
            end = raw.rfind("]") + 1
            if start == -1 or end == 0:
                logger.warning("Ghost writer: no JSON array in gap-finding response")
                return []
            data = json.loads(raw[start:end])
            gaps = []
            for item in data[:3]:
                gaps.append(
                    StoryGap(
                        section_title=item.get("section_title", ""),
                        section_context=item.get("section_context", ""),
                        seed_question=item.get("seed_question", ""),
                    )
                )
            logger.info("Ghost writer: found %s story gap(s) via LLM", len(gaps))
            return gaps
        except Exception as e:
            logger.warning("Ghost writer find_story_gaps failed: %s", e)
            return []

    def conduct_interview(
        self,
        gap: StoryGap,
        job_id: str,
        gap_index: int,
        job_updater: Optional[Callable[..., None]] = None,
        max_rounds: int = MAX_ROUNDS,
    ) -> StoryElicitationResult:
        """
        Conduct a multi-turn interview for a single story gap.

        Posts questions to the job store, waits **indefinitely** for each user
        response, evaluates sufficiency, and compiles a first-person STAR
        narrative when ready.

        The interview ends when one of these happens:
        1. The LLM evaluates the material as **sufficient** → returns narrative.
        2. The LLM (or direct phrase detection) identifies a **no_experience**
           response → returns skipped=True, narrative=None.
        3. The user explicitly skips via the UI (gap index advanced).
        4. The job is cancelled/failed.
        5. Safety cap (*max_rounds*) is reached → compiles from history.

        The pipeline must have already posted the seed question and set
        ``waiting_for_story_input=True`` before calling this method.
        """
        from shared.blog_job_store import (
            add_story_agent_message,
            get_blog_job,
            is_waiting_for_story_input,
        )

        conversation: List[Dict[str, str]] = [{"role": "agent", "content": gap.seed_question}]
        detected_context: Optional[str] = None

        for round_num in range(max_rounds):
            # ── Wait indefinitely for the user to respond ────────────────
            while is_waiting_for_story_input(job_id):
                job_data = get_blog_job(job_id)
                if job_data and job_data.get("status") in ("failed", "cancelled"):
                    return StoryElicitationResult(
                        gap=gap, narrative=None, skipped=True, rounds_used=round_num
                    )
                if job_data and job_data.get("current_story_gap_index", 0) > gap_index:
                    return StoryElicitationResult(
                        gap=gap, narrative=None, skipped=True, rounds_used=round_num
                    )
                time.sleep(POLL_INTERVAL)

            # Check if user skipped via UI
            job_data = get_blog_job(job_id)
            if job_data and job_data.get("current_story_gap_index", 0) > gap_index:
                return StoryElicitationResult(
                    gap=gap, narrative=None, skipped=True, rounds_used=round_num + 1
                )

            # Get user's last message
            history = (job_data or {}).get("story_chat_history", [])
            user_messages = [
                m
                for m in history
                if m.get("role") == "user" and m.get("gap_index", gap_index) == gap_index
            ]
            last_user_msg = user_messages[-1]["content"] if user_messages else ""

            # ── Quick check: did user say "skip" / "no experience"? ──────
            if _is_no_experience(last_user_msg):
                logger.info(
                    "Ghost writer: user indicated no experience for '%s'", gap.section_title
                )
                return StoryElicitationResult(
                    gap=gap, narrative=None, skipped=True, rounds_used=round_num + 1
                )

            conversation.append({"role": "user", "content": last_user_msg})

            # ── Evaluate with LLM ────────────────────────────────────────
            evaluation = self._evaluate_response(gap, conversation)

            # Track story context as it's detected
            if evaluation.get("story_context"):
                detected_context = evaluation["story_context"]

            # Outcome 1: no_experience flagged by LLM
            if evaluation.get("no_experience"):
                logger.info("Ghost writer: LLM detected no-experience for '%s'", gap.section_title)
                return StoryElicitationResult(
                    gap=gap, narrative=None, skipped=True, rounds_used=round_num + 1
                )

            # Outcome 2: sufficient material for a compelling story
            if evaluation.get("sufficient"):
                narrative = evaluation.get("narrative")
                logger.info(
                    "Ghost writer: sufficient story collected for '%s' after %s round(s)",
                    gap.section_title,
                    round_num + 1,
                )
                return StoryElicitationResult(
                    gap=gap,
                    narrative=narrative,
                    skipped=False,
                    rounds_used=round_num + 1,
                    story_context=detected_context,
                )

            # Outcome 3: insufficient — ask follow-up (loop continues)
            follow_up = evaluation.get("follow_up")
            if not follow_up:
                # LLM couldn't generate a follow-up — compile from what we have
                narrative = self._compile_from_history(gap, conversation, detected_context)
                if narrative:
                    return StoryElicitationResult(
                        gap=gap,
                        narrative=narrative,
                        skipped=False,
                        rounds_used=round_num + 1,
                        story_context=detected_context,
                    )
                break

            conversation.append({"role": "agent", "content": follow_up})
            add_story_agent_message(job_id, follow_up, gap_index)

        # Safety cap reached — compile whatever we have
        logger.info(
            "Ghost writer: round cap reached for '%s', compiling from history", gap.section_title
        )
        narrative = self._compile_from_history(gap, conversation, detected_context)
        return StoryElicitationResult(
            gap=gap, narrative=narrative, skipped=False, rounds_used=max_rounds, story_context=detected_context
        )

    def _evaluate_response(
        self,
        gap: StoryGap,
        conversation: List[Dict[str, str]],
    ) -> Dict[str, Any]:
        """Use the LLM to evaluate whether the conversation has enough material."""
        context_block = (
            f"Section: {gap.section_title}\n"
            f"Context: {gap.section_context}\n\n"
            "Conversation so far:\n"
        )
        for msg in conversation:
            role = "Ghost writer" if msg["role"] == "agent" else "Author"
            context_block += f"{role}: {msg['content']}\n"

        try:
            response = self.llm_client.complete(
                context_block,
                system_prompt=_EVALUATE_SYSTEM,
            )
            raw = (response or "").strip()
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start == -1 or end == 0:
                return {"sufficient": False, "follow_up": None, "narrative": None}
            return json.loads(raw[start:end])
        except Exception as e:
            logger.warning("Ghost writer evaluate_response failed: %s", e)
            return {"sufficient": False, "follow_up": None, "narrative": None}

    def _compile_from_history(
        self,
        gap: StoryGap,
        conversation: List[Dict[str, str]],
        story_context: Optional[str] = None,
    ) -> Optional[str]:
        """Compile a narrative from the conversation even if evaluation didn't produce one."""
        user_content = " ".join(
            m["content"] for m in conversation if m["role"] == "user" and m.get("content")
        )
        if not user_content.strip():
            return None

        tone_hint = ""
        if story_context == "personal":
            tone_hint = (
                "This was a personal or side project — keep the tone lighter and enthusiastic. "
                "Highlight curiosity, experimentation, and what made it fun or interesting. "
            )
        elif story_context == "client":
            tone_hint = (
                "This was client work — convey professional credibility while keeping it human. "
                "Highlight the constraints, the client relationship, and the delivered result. "
            )
        elif story_context == "employer":
            tone_hint = (
                "This happened at the author's company — emphasize the team dynamic, "
                "organizational context, and the author's specific contribution. "
            )

        prompt = (
            f"Section context: {gap.section_context}\n\n"
            f"Author's raw responses: {user_content}\n\n"
            f"{tone_hint}"
            "Write a 2–5 sentence first-person narrative as if the author wrote it. "
            "Make it vivid and specific — open with the moment or situation, include what "
            "they actually did and why, and close with how it turned out. "
            "Use 'I' voice. Include real details and numbers only if the author provided them. "
            "Do not invent anything."
        )
        try:
            return self.llm_client.complete(
                prompt,
                system_prompt=(
                    "You are a skilled ghost writer who turns casual conversation into "
                    "compelling first-person narratives. Write like a great storyteller, "
                    "not a report generator."
                ),
            )
        except Exception as e:
            logger.warning("Ghost writer compile_from_history failed: %s", e)
            return None

    @staticmethod
    def _plan_to_text(plan: ContentPlan) -> str:
        lines = [f"Topic/thesis: {plan.overarching_topic}"]
        if plan.narrative_flow:
            lines.append(f"Narrative flow: {plan.narrative_flow}")
        for section in plan.sections:
            lines.append(f"\nSection: {section.title}")
            if section.coverage_description:
                lines.append(f"  Coverage: {section.coverage_description}")
        return "\n".join(lines)
