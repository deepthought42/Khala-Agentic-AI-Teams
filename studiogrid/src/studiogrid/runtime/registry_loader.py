from __future__ import annotations

import re
from pathlib import Path

import yaml


class RegistryLoader:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._registry = None

    def _load(self) -> dict:
        if self._registry is None:
            with (self.root / "workflows" / "agent_registry.yaml").open("r", encoding="utf-8") as f:
                self._registry = yaml.safe_load(f)
        return self._registry

    def get_agent(self, agent_id: str) -> dict:
        agents = self._load().get("agents", {})
        return agents[agent_id]

    def load_prompt(self, prompt_file: str) -> str:
        return (self.root / prompt_file).read_text(encoding="utf-8")

    def list_agents(self) -> list[dict]:
        agents = self._load().get("agents", {})
        return [self._agent_payload(agent_id, agent_cfg) for agent_id, agent_cfg in agents.items()]

    def list_teams(self, available_only: bool = False) -> list[dict]:
        teams = self._load().get("teams", {})
        payload = []
        for team_id, team_cfg in teams.items():
            availability = team_cfg.get("availability", "unknown")
            if available_only and availability != "available":
                continue
            payload.append(
                {
                    "team_id": team_id,
                    "description": team_cfg.get("description", ""),
                    "availability": availability,
                    "agents": team_cfg.get("agents", []),
                }
            )
        return payload

    def find_assisting_agents(
        self,
        problem_description: str,
        required_skills: list[str] | None = None,
        requesting_agent_id: str | None = None,
        limit: int = 5,
    ) -> dict:
        required = {skill.lower() for skill in (required_skills or [])}
        problem_tokens = self._tokenize(problem_description)
        team_members = self._team_members(requesting_agent_id) if requesting_agent_id else set()

        ranked = []
        for agent_id, agent_cfg in self._load().get("agents", {}).items():
            agent_skills = {skill.lower() for skill in agent_cfg.get("skills", [])}
            if required and not required.issubset(agent_skills):
                continue

            keywords = {kw.lower() for kw in agent_cfg.get("keywords", [])}
            skill_score = len(required.intersection(agent_skills))
            keyword_score = len(problem_tokens.intersection(keywords))
            team_affinity_score = 2 if agent_id in team_members else 0
            score = (skill_score * 3) + keyword_score + team_affinity_score

            if required and score == 0:
                continue

            ranked.append(
                {
                    **self._agent_payload(agent_id, agent_cfg),
                    "score": score,
                    "is_same_team": agent_id in team_members,
                }
            )

        ranked.sort(key=lambda item: (item["is_same_team"], item["score"], item["agent_id"]), reverse=True)
        return {
            "requesting_agent_id": requesting_agent_id,
            "required_skills": sorted(required),
            "matches": ranked[:limit],
            "should_spawn_sub_agents": len(ranked) == 0,
        }

    def _team_members(self, agent_id: str) -> set[str]:
        teams = self._load().get("teams", {})
        for team_cfg in teams.values():
            members = set(team_cfg.get("agents", []))
            if agent_id in members:
                return members
        return set()

    def _agent_payload(self, agent_id: str, agent_cfg: dict) -> dict:
        return {
            "agent_id": agent_id,
            "description": agent_cfg.get("description", ""),
            "skills": agent_cfg.get("skills", []),
            "actions": agent_cfg.get("actions", []),
            "keywords": agent_cfg.get("keywords", []),
            "resources": agent_cfg.get("resources", []),
            "schemas": agent_cfg.get("schemas", {}),
        }

    def _tokenize(self, text: str) -> set[str]:
        return {token.lower() for token in re.findall(r"[a-zA-Z0-9_]+", text or "")}
