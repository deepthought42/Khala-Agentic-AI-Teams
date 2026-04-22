"""Thin asyncio wrapper around ``docker run``/``docker inspect``/``docker rm``.

Module-level coroutines (not a class) so tests can patch them cleanly via
``patch("agent_provisioning_team.sandbox.provisioner.run_container", ...)``.
Mirrors the shape of ``agent_sandbox/compose.py`` but talks to ``docker``
directly rather than ``docker compose`` — Phase 2 runs one ephemeral
container per agent, not a long-lived compose service.

The hardening flags from issue #255 (cap-drop, read-only, security-opt,
resource caps, loopback-bound ports) are assembled here rather than in the
shared ``tool_agents/docker_provisioner.py`` so the existing tool stays
unchanged for the non-sandbox provisioning path.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re

from .state import sandbox_image, sandbox_network

logger = logging.getLogger(__name__)

# Host env vars forwarded into the sandbox so the loaded agent can reach
# Postgres / the LLM service. Intentionally narrow — sandbox secret isolation
# is #257.
_FORWARDED_ENV = (
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_DB",
    "LLM_PROVIDER",
    "LLM_BASE_URL",
    "LLM_MODEL",
    "OLLAMA_API_KEY",
    "ANTHROPIC_API_KEY",
)

_CONTAINER_NAME_RE = re.compile(r"[^a-zA-Z0-9_.-]+")


class DockerError(RuntimeError):
    """Raised when a docker CLI invocation exits non-zero."""


def _fail(argv: list[str], rc: int, stderr: str) -> DockerError:
    return DockerError(f"docker failed (exit {rc}): {' '.join(argv)}\n{stderr[:500]}")


def container_name_for(agent_id: str) -> str:
    """Deterministic, DNS-safe container name for ``agent_id``.

    Docker requires ``[a-zA-Z0-9][a-zA-Z0-9_.-]*`` — dots in agent ids like
    ``blogging.planner`` are fine, but any other non-[A-Za-z0-9_.-] char is
    replaced with ``-``.
    """
    safe = _CONTAINER_NAME_RE.sub("-", agent_id).strip("-")
    return f"khala-sbx-{safe or 'agent'}"


async def _exec(cmd: list[str], *, timeout_s: int = 30) -> tuple[int, str, str]:
    logger.debug("exec: %s", " ".join(cmd))
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise DockerError(f"docker timed out after {timeout_s}s: {' '.join(cmd)}") from None
    return (
        proc.returncode or 0,
        stdout_b.decode("utf-8", errors="replace"),
        stderr_b.decode("utf-8", errors="replace"),
    )


def _build_run_argv(*, agent_id: str, container_name: str) -> list[str]:
    """Assemble the hardened ``docker run`` argument vector for a sandbox.

    Kept as a pure function so tests can assert on the exact flags without
    invoking subprocess.
    """
    argv: list[str] = [
        "docker",
        "run",
        "-d",
        "--rm",
        "--name",
        container_name,
        "--hostname",
        container_name,
        "--network",
        sandbox_network(),
        # `127.0.0.1::8090` binds to loopback only; Docker picks a free host port.
        "-p",
        "127.0.0.1::8090",
        "--cpus=1.0",
        "--memory=1g",
        "--pids-limit=512",
        "--ulimit",
        "nproc=1024",
        "--ulimit",
        "nofile=4096",
        "--security-opt=no-new-privileges:true",
        "--security-opt=seccomp=default",
        "--cap-drop=ALL",
        "--read-only",
        "--tmpfs",
        "/tmp",
        "--tmpfs",
        "/run",
        # Phase 1 entrypoint binds the sandbox to exactly this agent id.
        "-e",
        f"SANDBOX_AGENT_ID={agent_id}",
    ]
    for key in _FORWARDED_ENV:
        value = os.environ.get(key)
        if value is not None:
            argv.extend(["-e", f"{key}={value}"])
    argv.append(sandbox_image())
    return argv


async def run_container(agent_id: str, container_name: str) -> str:
    """Start a hardened sandbox for ``agent_id`` and return its container id.

    Caller is responsible for polling ``/health`` before treating the sandbox
    as ready — this coroutine returns as soon as the Docker daemon accepts
    the container, not when uvicorn is listening.
    """
    argv = _build_run_argv(agent_id=agent_id, container_name=container_name)
    rc, stdout, stderr = await _exec(argv, timeout_s=60)
    if rc != 0:
        raise _fail(argv, rc, stderr or stdout)
    container_id = stdout.strip()
    if not container_id:
        raise _fail(argv, rc, "docker run printed no container id")
    return container_id


async def inspect_host_port(container_id: str) -> int:
    """Resolve the host-side loopback port that maps to the sandbox's ``8090/tcp``."""
    argv = [
        "docker",
        "inspect",
        "--format",
        '{{ (index (index .NetworkSettings.Ports "8090/tcp") 0).HostPort }}',
        container_id,
    ]
    rc, stdout, stderr = await _exec(argv)
    if rc != 0:
        raise _fail(argv, rc, stderr or stdout)
    port_str = stdout.strip()
    if not port_str.isdigit():
        raise _fail(argv, rc, f"could not parse host port from {stdout!r}")
    return int(port_str)


async def is_running(container_id: str) -> bool:
    """Return True iff ``docker inspect`` reports the container as running.

    Missing / removed containers return False (not an error).
    """
    rc, stdout, _ = await _exec(
        ["docker", "inspect", "--format", "{{.State.Running}}", container_id],
    )
    return rc == 0 and stdout.strip().lower() == "true"


async def stop_container(container_id: str) -> None:
    """Stop and remove ``container_id``. Idempotent; missing container is not an error.

    ``docker rm -f`` stops running containers before removing them, so a single
    call covers both the happy path and the zombie-container case.
    """
    await _exec(["docker", "rm", "-f", container_id])
