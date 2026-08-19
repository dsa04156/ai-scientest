"""Codex CLI adapter for running AI Scientist with ChatGPT/Codex auth."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from types import SimpleNamespace
from typing import Any


def is_codex_model(model: str) -> bool:
    return model == "codex" or model.startswith("codex/")


def _requested_model(model: str) -> str | None:
    if model.startswith("codex/"):
        return model.split("/", 1)[1]
    return os.environ.get("AI_SCIENTIST_CODEX_MODEL") or None


def _reasoning_effort() -> str:
    effort = os.environ.get("AI_SCIENTIST_CODEX_REASONING_EFFORT", "xhigh").lower()
    allowed = {"none", "low", "medium", "high", "xhigh", "max"}
    if effort not in allowed:
        raise ValueError(
            "AI_SCIENTIST_CODEX_REASONING_EFFORT must be one of "
            + ", ".join(sorted(allowed))
        )
    return effort


def _strict_output_schema(schema: Any) -> Any:
    """Return a Codex-compatible strict JSON schema without mutating the caller."""
    if isinstance(schema, list):
        return [_strict_output_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema

    normalized = {
        key: _strict_output_schema(value) for key, value in schema.items()
    }
    properties = normalized.get("properties")
    if isinstance(properties, dict):
        normalized["additionalProperties"] = False
        normalized["required"] = list(properties)
    return normalized


def _render_content(content: Any, image_dir: Path) -> tuple[str, list[str]]:
    if isinstance(content, str):
        return content, []
    if not isinstance(content, list):
        return json.dumps(content, ensure_ascii=False), []

    text_parts: list[str] = []
    image_paths: list[str] = []
    for index, item in enumerate(content):
        if not isinstance(item, dict):
            text_parts.append(str(item))
            continue
        if item.get("type") == "text":
            text_parts.append(str(item.get("text", "")))
            continue
        if item.get("type") != "image_url":
            text_parts.append(json.dumps(item, ensure_ascii=False))
            continue

        image_url = item.get("image_url", {})
        url = (
            image_url.get("url", "") if isinstance(image_url, dict) else str(image_url)
        )
        if url.startswith("data:image/") and ";base64," in url:
            header, encoded = url.split(",", 1)
            suffix = header.split("/", 1)[1].split(";", 1)[0]
            suffix = "jpg" if suffix == "jpeg" else suffix
            with tempfile.NamedTemporaryFile(
                dir=image_dir,
                prefix=f"image_{index}_",
                suffix=f".{suffix}",
                delete=False,
            ) as image_file:
                image_file.write(base64.b64decode(encoded))
                image_paths.append(image_file.name)
        elif url:
            image_paths.append(url)
    return "\n".join(text_parts), image_paths


def run_codex(
    *,
    system_message: Any = None,
    user_message: Any = None,
    messages: list[dict[str, Any]] | None = None,
    model: str = "codex",
    output_schema: dict[str, Any] | None = None,
    timeout_seconds: int | None = None,
) -> str:
    """Run one isolated, non-interactive Codex turn and return its final message."""
    executable = shutil.which("codex")
    if executable is None:
        raise RuntimeError("codex CLI was not found in PATH")

    with tempfile.TemporaryDirectory(prefix="ai-scientist-codex-") as tmp:
        tmp_path = Path(tmp)
        isolated_codex_home = tmp_path / "codex-home"
        isolated_codex_home.mkdir()
        source_codex_home = Path(
            os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))
        )
        source_auth = source_codex_home / "auth.json"
        if source_auth.is_file():
            shutil.copy2(source_auth, isolated_codex_home / "auth.json")
        source_skills = source_codex_home / "skills"
        if source_skills.is_dir():
            (isolated_codex_home / "skills").symlink_to(
                source_skills, target_is_directory=True
            )
        prompt_parts: list[str] = []
        image_paths: list[str] = []

        if system_message:
            rendered, images = _render_content(system_message, tmp_path)
            prompt_parts.append(f"# System instructions\n{rendered}")
            image_paths.extend(images)

        for message in messages or []:
            role = str(message.get("role", "user")).title()
            rendered, images = _render_content(message.get("content", ""), tmp_path)
            prompt_parts.append(f"# {role}\n{rendered}")
            image_paths.extend(images)

        if user_message:
            rendered, images = _render_content(user_message, tmp_path)
            prompt_parts.append(f"# User\n{rendered}")
            image_paths.extend(images)

        if output_schema is not None:
            prompt_parts.append(
                "Return only a JSON object matching the required output schema."
            )

        output_path = tmp_path / "last-message.txt"
        command = [
            executable,
            "exec",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--sandbox",
            "read-only",
            "--skip-git-repo-check",
            "--color",
            "never",
            "-C",
            str(tmp_path),
            "-o",
            str(output_path),
        ]

        requested_model = _requested_model(model)
        if requested_model:
            command.extend(["--model", requested_model])
        command.extend(["-c", f'model_reasoning_effort="{_reasoning_effort()}"'])
        for image_path in image_paths:
            command.extend(["--image", image_path])
        if output_schema is not None:
            schema_path = tmp_path / "output-schema.json"
            schema_path.write_text(
                json.dumps(_strict_output_schema(output_schema)), encoding="utf-8"
            )
            command.extend(["--output-schema", str(schema_path)])
        command.append("-")

        timeout = (
            timeout_seconds
            if timeout_seconds is not None
            else int(os.environ.get("AI_SCIENTIST_CODEX_TIMEOUT", "1200"))
        )
        child_env = os.environ.copy()
        child_env["CODEX_HOME"] = str(isolated_codex_home)
        child_env["PWD"] = str(tmp_path)
        child_env["OLDPWD"] = str(tmp_path)
        # A nested CLI run must not inherit the parent Codex conversation.
        child_env.pop("CODEX_THREAD_ID", None)
        result = subprocess.run(
            command,
            input="\n\n".join(prompt_parts),
            text=True,
            capture_output=True,
            cwd=tmp_path,
            env=child_env,
            timeout=timeout,
            check=False,
        )
        if result.returncode != 0:
            details = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(f"codex exec failed ({result.returncode}): {details}")
        if output_path.exists():
            return output_path.read_text(encoding="utf-8").strip()
        return result.stdout.strip()


class CodexClient:
    """Small OpenAI-client-compatible facade used by the existing VLM paths."""

    def __init__(self, model: str = "codex"):
        self.model = model
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create_chat_completion)
        )

    def _create_chat_completion(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str | None = None,
        n: int = 1,
        **_: Any,
    ) -> Any:
        outputs = [
            run_codex(messages=messages, model=model or self.model) for _ in range(n)
        ]
        return SimpleNamespace(
            model=model or self.model,
            created=int(time.time()),
            choices=[
                SimpleNamespace(message=SimpleNamespace(content=output))
                for output in outputs
            ],
            usage=SimpleNamespace(
                prompt_tokens=0,
                completion_tokens=0,
                completion_tokens_details=None,
            ),
        )
