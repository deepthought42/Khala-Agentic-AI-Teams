"""Tests for unified API shutdown.

Shutdown hooks were removed when the architecture moved to per-team containers.
Each team container handles its own shutdown via its entrypoint.
"""
