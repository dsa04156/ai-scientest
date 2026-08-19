import json
import time

from ai_scientist.codex_cli import CodexClient, run_codex

from .utils import FunctionSpec, OutputType


def get_ai_client(model: str, **_: object) -> CodexClient:
    return CodexClient(model)


def query(
    system_message,
    user_message,
    func_spec: FunctionSpec | None = None,
    **model_kwargs,
) -> tuple[OutputType, float, int, int, dict]:
    model = model_kwargs.get("model", "codex")
    started = time.time()
    output = run_codex(
        system_message=system_message,
        user_message=user_message,
        model=model,
        output_schema=func_spec.json_schema if func_spec else None,
    )
    elapsed = time.time() - started
    if func_spec is not None:
        output = json.loads(output)
    return output, elapsed, 0, 0, {"model": model, "provider": "codex-cli"}
