"""
Utilities for parsing LLM responses when structured JSON parsing fails.

When the LLM returns raw content (e.g. {"content": "..."}), extract file paths
and bodies from markdown code blocks so agents can still produce files.
"""

from __future__ import annotations

import json
import re
from typing import Dict


# Extensions we treat as file paths (backend + frontend)
_PATH_EXTENSIONS = (
    ".py", ".ts", ".html", ".scss", ".css", ".json", ".md", ".yaml", ".yml",
    ".js", ".spec.ts",
)


def _looks_like_path(line: str) -> bool:
    """True if the line looks like a file path (has / or known extension)."""
    s = line.strip()
    if not s or len(s) > 200:
        return False
    if "/" in s:
        return True
    return any(s.endswith(ext) for ext in _PATH_EXTENSIONS)


def extract_files_from_content(content: str) -> Dict[str, str]:
    """
    Parse markdown code blocks from raw LLM content and build a files dict.

    Supports:
    - Raw or wrapped JSON: content starting with { or containing a single {...} with "files"
    - ```path/to/file.ext\\n<content>
    - ```\\npath/to/file.ext\\n<content>  (first line is path)
    - ```json\\n{...}  (try to parse as JSON with "files" key)
    - ```lang\\n<content>  (single block: infer path from extension)

    Returns a dict of path -> content. May be empty if nothing could be parsed.
    """
    if not content or not content.strip():
        return {}

    files: Dict[str, str] = {}
    stripped = content.strip()

    # Try to parse content as JSON: find first "files"-bearing object (model may wrap JSON in text)
    start = stripped.find("{")
    if start != -1:
        depth = 0
        end = -1
        for i in range(start, len(stripped)):
            if stripped[i] == "{":
                depth += 1
            elif stripped[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end != -1:
            try:
                parsed = json.loads(stripped[start : end + 1])
                if isinstance(parsed, dict) and parsed.get("files") and isinstance(parsed["files"], dict):
                    for k, v in parsed["files"].items():
                        if isinstance(k, str) and isinstance(v, str) and k and v.strip():
                            files[k] = v
                    if files:
                        return files
            except (json.JSONDecodeError, TypeError):
                pass

    # Try JSON inside markdown code block - model might have wrapped the whole response in a code block
    json_match = re.search(r"```(?:json)?\s*\n([\s\S]*?)```", content, re.IGNORECASE)
    if json_match:
        try:
            parsed = json.loads(json_match.group(1).strip())
            if isinstance(parsed, dict) and parsed.get("files"):
                f = parsed["files"]
                if isinstance(f, dict):
                    for k, v in f.items():
                        if isinstance(k, str) and isinstance(v, str) and k and v.strip():
                            files[k] = v
                    if files:
                        return files
        except (json.JSONDecodeError, TypeError):
            pass

    # Find all fenced code blocks: ```(lang_or_path)?\n(body)```
    pattern = re.compile(r"```([^\n]*)\n([\s\S]*?)```", re.MULTILINE)
    for match in pattern.finditer(content):
        info = match.group(1).strip()
        body = match.group(2)
        if not body:
            continue

        lines = body.split("\n")
        path: str | None = None
        body_start = 0

        # First line might be the path
        if info and _looks_like_path(info):
            path = info.strip()
            body_start = 0
        elif lines and _looks_like_path(lines[0]):
            path = lines[0].strip()
            body_start = 1
        elif info and any(info.endswith(ext) for ext in _PATH_EXTENSIONS):
            path = info.strip()
            body_start = 0
        elif lines:
            # Check for path comment: // path: src/foo.ts or # path: app/foo.py
            first = lines[0].strip()
            path_prefix = ("path:", "file:", "filepath:")
            for prefix in path_prefix:
                if prefix in first.lower():
                    idx = first.lower().find(prefix)
                    rest = first[idx + len(prefix) :].strip().strip("'\"").strip()
                    if rest and _looks_like_path(rest):
                        path = rest
                        body_start = 1
                        break
                    break

        if path and path not in files:
            content_str = "\n".join(lines[body_start:]).rstrip()
            if content_str:
                files[path] = content_str

    return files
