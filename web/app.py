from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from functools import lru_cache
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import threading
import time
from typing import Any, Literal
from urllib.parse import quote
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

ROOT = Path(__file__).resolve().parents[1]
STATIC_ROOT = ROOT / "web" / "static"
RUN_ROOT = ROOT / "web_runs"
EXPERIMENT_ROOT = ROOT / "experiments"
PYTHON = ROOT / ".venv" / "bin" / "python"
RUN_ROOT.mkdir(exist_ok=True)

IDEATION_STAGES = ["queued", "ideation", "complete"]
EXPERIMENT_STAGES = [
    "queued",
    "setup",
    "experiments",
    "plots",
    "citations",
    "writeup",
    "review",
    "complete",
]

ARTIFACT_SUFFIXES = {
    ".json",
    ".md",
    ".txt",
    ".pdf",
    ".html",
    ".png",
    ".jpg",
    ".jpeg",
    ".csv",
    ".yaml",
    ".yml",
    ".tex",
    ".bib",
    ".log",
    ".py",
}
TEXT_ARTIFACT_SUFFIXES = ARTIFACT_SUFFIXES - {".pdf", ".png", ".jpg", ".jpeg"}
MAX_PREVIEW_BYTES = 2 * 1024 * 1024

COMMON_SKILL_ROOTS = (
    (Path.home() / ".agents" / "skills", "사용자 공용"),
    (Path.home() / ".codex" / "skills", "Codex 공용"),
    (Path.home() / ".codex" / "plugins" / "cache", "플러그인"),
    (Path("/etc/codex/skills"), "관리자 공용"),
)
PROJECT_SKILL_ROOTS = ((ROOT / ".agents" / "skills", "프로젝트 전용"),)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_slug(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9가-힣_-]+", "-", value.strip()).strip("-")
    return value[:48] or "research-topic"


def _frontmatter_value(text: str, key: str) -> str:
    parts = text.split("---", 2)
    frontmatter = parts[1] if len(parts) == 3 else text
    lines = frontmatter.splitlines()
    for index, line in enumerate(lines):
        if not line.startswith(f"{key}:"):
            continue
        raw = line.split(":", 1)[1].strip()
        if raw in {">", "|", ">-", "|-"}:
            continuation: list[str] = []
            for following in lines[index + 1 :]:
                if following and not following[0].isspace():
                    break
                if following.strip():
                    continuation.append(following.strip())
            return " ".join(continuation).strip()
        return raw.strip("'\"").strip()
    return ""


def _scan_skills(roots: tuple[tuple[Path, str], ...]) -> list[dict[str, str]]:
    skills: list[dict[str, str]] = []
    seen: set[Path] = set()
    for root, source in roots:
        if not root.exists():
            continue
        for skill_file in sorted(root.rglob("SKILL.md")):
            try:
                resolved = skill_file.resolve()
                if resolved in seen:
                    continue
                text = skill_file.read_text(encoding="utf-8")
            except OSError:
                continue
            seen.add(resolved)
            name = _frontmatter_value(text, "name") or skill_file.parent.name
            description = _frontmatter_value(text, "description")
            if not description:
                description = "설명 메타데이터가 없는 스킬입니다."
            skills.append(
                {
                    "name": name,
                    "description": description,
                    "source": source,
                }
            )
    return sorted(skills, key=lambda item: item["name"].casefold())


def list_skills() -> dict[str, Any]:
    common = _scan_skills(COMMON_SKILL_ROOTS)
    project = _scan_skills(PROJECT_SKILL_ROOTS)
    return {
        "common": common,
        "project": project,
        "common_count": len(common),
        "project_count": len(project),
    }


class IdeationRequest(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    keywords: str = Field(default="", max_length=300)
    abstract: str = Field(min_length=20, max_length=6000)
    generations: int = Field(default=1, ge=1, le=10)
    reflections: int = Field(default=2, ge=1, le=10)


class ExperimentRequest(BaseModel):
    idea_path: str
    idea_index: int = Field(default=0, ge=0)
    writeup: bool = True
    review: bool = True
    citation_rounds: int = Field(default=5, ge=0, le=30)

    @field_validator("idea_path")
    @classmethod
    def validate_idea_path(cls, value: str) -> str:
        if not value.endswith(".json"):
            raise ValueError("idea_path must be a JSON file")
        return value


class Job:
    def __init__(
        self,
        job_id: str,
        kind: Literal["ideation", "experiment"],
        title: str,
        command: list[str],
        run_dir: Path,
    ) -> None:
        self.id = job_id
        self.kind = kind
        self.title = title
        self.command = command
        self.run_dir = run_dir
        self.status = "queued"
        self.stage = "queued"
        self.topology_step = "intake"
        self.created_at = utc_now()
        self.started_at: str | None = None
        self.finished_at: str | None = None
        self.return_code: int | None = None
        self.logs: list[dict[str, Any]] = []
        self.process: subprocess.Popen[str] | None = None
        self.output_dir: str | None = None
        self._lock = threading.Lock()
        self._sequence = 0

    @property
    def stages(self) -> list[str]:
        return IDEATION_STAGES if self.kind == "ideation" else EXPERIMENT_STAGES

    def add_log(self, text: str, stream: str = "stdout") -> None:
        clean = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text).rstrip()
        if not clean:
            return
        with self._lock:
            self._sequence += 1
            self.logs.append(
                {
                    "seq": self._sequence,
                    "time": utc_now(),
                    "stream": stream,
                    "text": clean,
                }
            )
            if len(self.logs) > 4000:
                self.logs = self.logs[-4000:]
        self._infer_stage(clean)

    def _infer_stage(self, line: str) -> None:
        lowered = line.lower()
        if self.kind == "ideation":
            if (
                "generating proposal" in lowered
                or "starting idea generation" in lowered
            ):
                self.stage = "ideation"
                self.topology_step = "hypothesis"
            if (
                "action: searchsemanticscholar" in lowered
                or "action: searchkurate" in lowered
                or "[literature survey] start" in lowered
                or "[literature survey] lane" in lowered
            ):
                self.topology_step = "literature"
            elif (
                "response status code" in lowered
                or "codex web search returned" in lowered
                or "[literature survey] complete" in lowered
            ):
                self.topology_step = "reflection"
            elif "action: finalizeidea" in lowered:
                self.topology_step = "finalize"
            return
        topology_patterns = [
            ("review", ("paper found at", "paper review", "reviewing paper")),
            ("writeup", ("writeup attempt", "write-up", "writing paper")),
            ("citations", ("citation", "gather_citations")),
            ("plots", ("aggregate", "aggregator", "number of figures")),
            ("ablation", ("starting main stage: 4", "ablation")),
            ("creative", ("starting main stage: 3", "creative_research")),
            ("tuning", ("starting main stage: 2", "baseline_tuning")),
            ("initial", ("starting main stage: 1", "initial_implementation")),
            ("setup", ("results will be saved", "loaded ")),
        ]
        for topology_step, needles in topology_patterns:
            if any(needle in lowered for needle in needles):
                self.topology_step = topology_step
                break
        stage_patterns = [
            ("review", ("paper found at", "paper review", "reviewing paper")),
            ("writeup", ("writeup attempt", "write-up", "writing paper")),
            ("citations", ("citation", "gather_citations")),
            ("plots", ("aggregate", "aggregator", "number of figures")),
            (
                "experiments",
                (
                    "generating code",
                    "current stage",
                    "current main stage",
                    "starting main stage",
                    "starting run",
                ),
            ),
            ("setup", ("results will be saved", "loaded ")),
        ]
        for stage, needles in stage_patterns:
            if any(needle in lowered for needle in needles):
                current = self.stages.index(self.stage)
                target = self.stages.index(stage)
                if target >= current:
                    self.stage = stage
                break
        match = re.search(r"Results will be saved in (.+)$", line)
        if match:
            self.output_dir = match.group(1).strip()

    def snapshot(self, include_logs: bool = False, after: int = 0) -> dict[str, Any]:
        with self._lock:
            logs = [entry for entry in self.logs if entry["seq"] > after]
        current_index = (
            self.stages.index(self.stage) if self.stage in self.stages else 0
        )
        denominator = max(1, len(self.stages) - 1)
        data = {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "status": self.status,
            "stage": self.stage,
            "topology_step": self.topology_step,
            "stages": self.stages,
            "model": os.getenv("AI_SCIENTIST_CODEX_MODEL", "gpt-5.6-sol"),
            "reasoning_effort": os.getenv(
                "AI_SCIENTIST_CODEX_REASONING_EFFORT", "xhigh"
            ),
            "progress": round(current_index / denominator * 100),
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "return_code": self.return_code,
            "output_dir": self.output_dir,
            "last_sequence": self._sequence,
        }
        if include_logs:
            data["logs"] = logs
        return data

    def persist(self) -> None:
        payload = self.snapshot(include_logs=True)
        payload["command"] = self.command
        (self.run_dir / "job.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )


class JobManager:
    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._restore_archived_jobs()

    def _restore_archived_jobs(self) -> None:
        for manifest in sorted(RUN_ROOT.glob("*/job.json")):
            try:
                payload = json.loads(manifest.read_text(encoding="utf-8"))
                kind = payload.get("kind")
                if kind not in {"ideation", "experiment"}:
                    continue
                job = Job(
                    str(payload["id"]),
                    kind,
                    str(payload.get("title", manifest.parent.name)),
                    [str(item) for item in payload.get("command", [])],
                    manifest.parent,
                )
                for field in (
                    "status",
                    "stage",
                    "topology_step",
                    "created_at",
                    "started_at",
                    "finished_at",
                    "return_code",
                    "output_dir",
                ):
                    if field in payload:
                        setattr(job, field, payload[field])
                if "topology_step" not in payload and (
                    job.status == "completed" or job.stage == "complete"
                ):
                    job.topology_step = "complete"
                job.logs = [
                    entry
                    for entry in payload.get("logs", [])
                    if isinstance(entry, dict)
                ]
                job._sequence = max(
                    [int(entry.get("seq", 0)) for entry in job.logs] or [0]
                )
                if job.status in {"queued", "running", "stopping"}:
                    job.status = "stopped"
                    job.finished_at = job.finished_at or utc_now()
                    job.add_log(
                        "[workbench] 서버 재시작으로 이전 실행이 종료된 상태로 복원되었습니다.",
                        "system",
                    )
                self.jobs[job.id] = job
            except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue

    def active_job(self) -> Job | None:
        return next(
            (job for job in self.jobs.values() if job.status in {"queued", "running"}),
            None,
        )

    def create(
        self,
        kind: Literal["ideation", "experiment"],
        title: str,
        command: list[str],
        run_dir: Path,
        output_dir: str | None = None,
    ) -> Job:
        with self._lock:
            active = self.active_job()
            if active:
                raise HTTPException(
                    409, f"이미 실행 중인 연구가 있습니다: {active.title}"
                )
            job = Job(run_dir.name, kind, title, command, run_dir)
            job.output_dir = output_dir
            self.jobs[job.id] = job
        job.persist()
        threading.Thread(target=self._run, args=(job,), daemon=True).start()
        return job

    def _run(self, job: Job) -> None:
        job.status = "running"
        job.started_at = utc_now()
        job.stage = "ideation" if job.kind == "ideation" else "setup"
        job.topology_step = "hypothesis" if job.kind == "ideation" else "setup"
        job.add_log(f"[workbench] {job.title} 실행을 시작합니다.", "system")
        job.persist()
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        try:
            job.process = subprocess.Popen(
                job.command,
                cwd=ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                start_new_session=True,
            )
            assert job.process.stdout is not None
            for line in job.process.stdout:
                job.add_log(line)
            job.return_code = job.process.wait()
            if job.status == "stopping":
                job.status = "stopped"
                job.add_log("[workbench] 사용자가 실행을 중지했습니다.", "system")
            elif job.return_code == 0:
                job.status = "completed"
                job.stage = "complete"
                job.topology_step = "complete"
                job.add_log("[workbench] 연구 실행이 완료되었습니다.", "system")
            else:
                job.status = "failed"
                job.add_log(
                    f"[workbench] 프로세스가 코드 {job.return_code}로 종료되었습니다.",
                    "system",
                )
        except Exception as error:
            job.status = "failed"
            job.add_log(f"[workbench] 실행 오류: {error}", "system")
        finally:
            job.finished_at = utc_now()
            job.persist()

    def stop(self, job: Job) -> None:
        if job.status not in {"queued", "running"}:
            raise HTTPException(409, "중지할 수 있는 상태가 아닙니다.")
        job.status = "stopping"
        process = job.process
        if process and process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            deadline = time.monotonic() + 5
            while process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.1)
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)


manager = JobManager()
app = FastAPI(title="AI Scientist Workbench", version="1.0.0")


def resolve_inside_root(relative: str) -> Path:
    candidate = (ROOT / relative).resolve()
    if candidate != ROOT and ROOT not in candidate.parents:
        raise HTTPException(400, "허용되지 않은 경로입니다.")
    return candidate


def _command_option(command: list[str], option: str) -> str | None:
    try:
        index = command.index(option)
    except ValueError:
        return None
    return command[index + 1] if index + 1 < len(command) else None


def _find_resume_experiment(job: Job) -> Path | None:
    candidates: list[Path] = []
    if job.output_dir:
        candidates.append(resolve_inside_root(job.output_dir))

    idea_arg = _command_option(job.command, "--load_ideas")
    idea_index_arg = _command_option(job.command, "--idea_idx")
    if idea_arg is not None and idea_index_arg is not None:
        try:
            ideas = json.loads(resolve_inside_root(idea_arg).read_text(encoding="utf-8"))
            idea_name = str(ideas[int(idea_index_arg)]["Name"])
            for experiment_dir in EXPERIMENT_ROOT.iterdir():
                idea_file = experiment_dir / "idea.json"
                if not idea_file.is_file():
                    continue
                saved_idea = json.loads(idea_file.read_text(encoding="utf-8"))
                if str(saved_idea.get("Name")) == idea_name:
                    candidates.append(experiment_dir)
        except (OSError, ValueError, IndexError, KeyError, TypeError, json.JSONDecodeError):
            pass

    recoverable = []
    for candidate in candidates:
        checkpoints = list(candidate.glob("logs/*/stage_*/checkpoint.pkl"))
        if checkpoints:
            recoverable.append((max(path.stat().st_mtime for path in checkpoints), candidate))
    return max(recoverable, default=(0, None), key=lambda item: item[0])[1]


def resolve_artifact(file_path: str) -> Path:
    path = resolve_inside_root(file_path)
    allowed_roots = [RUN_ROOT.resolve(), (ROOT / "experiments").resolve()]
    if not any(root == path or root in path.parents for root in allowed_roots):
        raise HTTPException(403, "열람할 수 없는 파일입니다.")
    if not path.is_file():
        raise HTTPException(404, "파일을 찾을 수 없습니다.")
    if path.suffix.lower() not in ARTIFACT_SUFFIXES:
        raise HTTPException(415, "미리보기를 지원하지 않는 파일 형식입니다.")
    return path


def artifact_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return "pdf"
    if suffix in {".png", ".jpg", ".jpeg"}:
        return "image"
    if suffix == ".json":
        return "json"
    if suffix == ".md":
        return "markdown"
    if suffix in {".py", ".tex", ".bib", ".yaml", ".yml", ".html"}:
        return "code"
    return "text"


DATASET_LABELS = {
    "gsm8k": "GSM8K",
    "mbpp": "MBPP",
    "hotpot_qa": "HotpotQA",
}

MODULE_LABELS = {
    "heteroscedastic_uncertainty": "이분산 불확실성",
    "conformal_risk_calibration": "Conformal 보정",
    "adaptive_routing": "적응형 라우팅",
    "plan": "계획",
    "verify": "검증",
    "search": "검색",
    "memory": "메모리",
    "debate": "토론",
}


def _plain_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _matrix_number(matrix: Any, row: int, column: int) -> float | None:
    try:
        value = matrix[row][column]
        return float(value)
    except (IndexError, KeyError, TypeError, ValueError):
        return None


def summarize_experiment_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Reduce a trusted experiment_data.npy payload to a small UI-safe brief."""
    comparisons = payload.get("comparisons")
    configuration = payload.get("configuration")
    if not isinstance(comparisons, dict) or not isinstance(configuration, dict):
        return None

    rows: list[dict[str, Any]] = []
    metric_name = "paired_risk_constrained_harness_regret"
    for dataset in _plain_list(configuration.get("datasets")):
        dataset_key = str(dataset)
        comparison = comparisons.get(dataset_key)
        if not isinstance(comparison, dict):
            continue
        variants = [str(item) for item in _plain_list(comparison.get("variants"))]
        metrics = [str(item) for item in _plain_list(comparison.get("metric_names"))]
        required = {"full_heteroscedastic", "fixed_route"}
        if not required.issubset(variants) or metric_name not in metrics:
            continue
        adaptive_index = variants.index("full_heteroscedastic")
        fixed_index = variants.index("fixed_route")
        metric_index = metrics.index(metric_name)
        coverage_index = metrics.index("coverage") if "coverage" in metrics else None
        uncalibrated_index = (
            variants.index("uncalibrated") if "uncalibrated" in variants else None
        )
        adaptive_mean = _matrix_number(
            comparison.get("test_mean"), adaptive_index, metric_index
        )
        fixed_mean = _matrix_number(
            comparison.get("test_mean"), fixed_index, metric_index
        )
        adaptive_ci95 = _matrix_number(
            comparison.get("test_95ci"), adaptive_index, metric_index
        )
        fixed_ci95 = _matrix_number(
            comparison.get("test_95ci"), fixed_index, metric_index
        )
        paired = (
            comparison.get("paired_effects", {})
            .get("fixed_route", {})
            .get(metric_name, {})
        )
        delta = float(paired["mean"]) if "mean" in paired else None
        delta_ci95 = float(paired["ci95"]) if "ci95" in paired else None
        verdict = "inconclusive"
        if delta is not None and delta_ci95 is not None:
            if delta - delta_ci95 > 0:
                verdict = "adaptive_better"
            elif delta + delta_ci95 < 0:
                verdict = "fixed_better"
        rows.append(
            {
                "dataset": dataset_key,
                "dataset_label": DATASET_LABELS.get(dataset_key, dataset_key),
                "adaptive_mean": adaptive_mean,
                "adaptive_ci95": adaptive_ci95,
                "fixed_mean": fixed_mean,
                "fixed_ci95": fixed_ci95,
                "delta_fixed_minus_adaptive": delta,
                "delta_ci95": delta_ci95,
                "verdict": verdict,
                "adaptive_coverage": (
                    _matrix_number(
                        comparison.get("test_mean"), adaptive_index, coverage_index
                    )
                    if coverage_index is not None
                    else None
                ),
                "uncalibrated_coverage": (
                    _matrix_number(
                        comparison.get("test_mean"),
                        uncalibrated_index,
                        coverage_index,
                    )
                    if coverage_index is not None and uncalibrated_index is not None
                    else None
                ),
            }
        )

    if not rows:
        return None

    classifications = payload.get("component_classifications", {})
    modules = []
    if isinstance(classifications, dict):
        for name, result in classifications.items():
            if not isinstance(result, dict):
                continue
            modules.append(
                {
                    "name": str(name),
                    "label": MODULE_LABELS.get(str(name), str(name)),
                    "classification": str(result.get("overall", "unknown")),
                }
            )

    adaptive_wins = sum(row["verdict"] == "adaptive_better" for row in rows)
    fixed_wins = sum(row["verdict"] == "fixed_better" for row in rows)
    inconclusive = len(rows) - adaptive_wins - fixed_wins
    if adaptive_wins == len(rows):
        headline = "적응형 라우팅이 모든 데이터셋에서 더 나았습니다."
        routing_conclusion = "적응형 라우팅이 전 데이터셋에서 우세했고"
    elif fixed_wins == len(rows):
        headline = "고정 라우팅이 모든 데이터셋에서 더 나았습니다."
        routing_conclusion = "고정 라우팅이 전 데이터셋에서 우세했고"
    else:
        headline = "적응형 라우팅의 보편적 우위는 확인되지 않았습니다."
        routing_conclusion = "적응형 효과는 데이터셋별로 달랐고"

    completion = payload.get("completion", {})
    planned_seeds = _plain_list(configuration.get("planned_seeds"))
    successful_seeds = _plain_list(configuration.get("successful_seeds"))
    outcome_provenance = str(configuration.get("outcome_provenance", "unknown"))
    calibration = classifications.get("conformal_risk_calibration", {})
    calibration_class = (
        str(calibration.get("overall", "unknown"))
        if isinstance(calibration, dict)
        else "unknown"
    )
    calibration_conclusions = {
        "beneficial": "Conformal 보정은 유효했습니다",
        "dataset-dependent": "Conformal 보정 효과도 데이터셋별로 달랐습니다",
        "neutral": "Conformal 보정의 뚜렷한 효과는 없었습니다",
        "harmful": "Conformal 보정은 성능을 악화했습니다",
    }
    conclusion_prefix = "시뮬레이션상 " if outcome_provenance == "simulated" else ""
    one_line_conclusion = conclusion_prefix + headline
    if calibration_class in calibration_conclusions:
        one_line_conclusion = (
            conclusion_prefix
            + routing_conclusion
            + ", "
            + calibration_conclusions[calibration_class]
            + "."
        )
    return {
        "headline": headline,
        "one_line_conclusion": one_line_conclusion,
        "interpretation": (
            f"95% CI 기준 적응형 우위 {adaptive_wins}개, 고정형 우위 {fixed_wins}개, "
            f"판단 보류 {inconclusive}개 데이터셋입니다."
        ),
        "primary_metric": "Paired risk-constrained harness regret (RCCOR)",
        "lower_is_better": True,
        "comparisons": rows,
        "modules": modules,
        "datasets": [row["dataset_label"] for row in rows],
        "planned_seed_count": len(planned_seeds),
        "successful_seed_count": len(successful_seeds),
        "outcome_provenance": outcome_provenance,
        "stage_complete": bool(
            isinstance(completion, dict) and completion.get("stage_complete")
        ),
    }


def _experiment_payload_score(payload: dict[str, Any]) -> tuple[int, ...]:
    completion = payload.get("completion", {})
    if not isinstance(completion, dict):
        completion = {}
    counts = completion.get("result_counts", {})
    total_results = (
        sum(int(value) for value in counts.values()) if isinstance(counts, dict) else 0
    )
    return (
        int(bool(completion.get("stage_complete"))),
        int(bool(completion.get("enough_results"))),
        int(bool(completion.get("all_components_classified"))),
        len(payload.get("comparisons", {}))
        if isinstance(payload.get("comparisons"), dict)
        else 0,
        total_results,
        -len(payload.get("failed_jobs", []))
        if isinstance(payload.get("failed_jobs"), list)
        else 0,
    )


@lru_cache(maxsize=32)
def _cached_experiment_summary(
    signatures: tuple[tuple[str, int, int], ...],
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        import numpy as np
    except ImportError:
        return None, None

    best: tuple[tuple[int, ...], dict[str, Any], Path] | None = None
    for path_string, _mtime_ns, _size in signatures:
        path = Path(path_string)
        try:
            payload = np.load(path, allow_pickle=True).item()
        except (OSError, ValueError, TypeError):
            continue
        if not isinstance(payload, dict):
            continue
        summary = summarize_experiment_payload(payload)
        if summary is None:
            continue
        candidate = (_experiment_payload_score(payload), summary, path)
        if best is None or candidate[0] > best[0]:
            best = candidate
    if best is None:
        return None, None
    return best[1], str(best[2].parent.relative_to(ROOT))


def experiment_result_summary(
    job: Job, files: list[dict[str, Any]]
) -> dict[str, Any] | None:
    if job.kind != "experiment" or not job.output_dir:
        return None
    output = resolve_inside_root(job.output_dir)
    if not output.exists():
        return None
    signatures = tuple(
        sorted(
            (str(path), path.stat().st_mtime_ns, path.stat().st_size)
            for path in output.rglob("experiment_data.npy")
            if path.is_file()
        )
    )
    if not signatures:
        return None
    base, source_directory = _cached_experiment_summary(signatures)
    if base is None or source_directory is None:
        return None

    plot_suffixes = (
        "test_ablation_primary_metric.png",
        "variant_constraint_dashboard.png",
    )
    plots = [
        {
            **file,
            "view_url": f"/api/views/{quote(str(file['path']))}",
        }
        for file in files
        if str(file.get("path", "")).startswith(f"{source_directory}/")
        and str(file.get("name", "")).endswith(plot_suffixes)
    ]

    limitations = []
    if base["outcome_provenance"] == "simulated":
        limitations.append(
            "정답·비용·지연 결과는 실제 LLM 호출이 아니라 시뮬레이션으로 생성했습니다."
        )
    if job.status in {"stopped", "failed"}:
        limitations.append(
            "실행이 중단되어 인용 수집·논문 작성·동료 심사까지 완료되지 않았습니다."
        )
    limitations.append(
        "현재 수치는 파이프라인과 가설 검증용 중간 증거이며 실제 모델 성능의 최종 결론은 아닙니다."
    )
    return {
        **base,
        "scope": "partial" if job.status != "completed" else "complete",
        "job_status": job.status,
        "job_stage": job.stage,
        "source_directory": source_directory,
        "plots": plots[:2],
        "limitations": limitations,
    }


def list_idea_files() -> list[dict[str, Any]]:
    paths = list((ROOT / "ai_scientist" / "ideas").glob("*.json"))
    paths.extend(RUN_ROOT.glob("**/*.json"))
    choices: list[dict[str, Any]] = []
    for path in sorted(set(paths), key=lambda item: item.stat().st_mtime, reverse=True):
        if path.name == "job.json":
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, list):
                continue
            choices.append(
                {
                    "path": str(path.relative_to(ROOT)),
                    "name": path.stem,
                    "count": len(payload),
                    "ideas": [
                        {
                            "index": index,
                            "title": idea.get(
                                "Title", idea.get("Name", f"Idea {index + 1}")
                            ),
                            "name": idea.get("Name", ""),
                        }
                        for index, idea in enumerate(payload)
                        if isinstance(idea, dict)
                    ],
                }
            )
        except (OSError, json.JSONDecodeError):
            continue
    return choices


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "codex_available": bool(os.environ.get("PATH"))
        and subprocess.call(
            ["bash", "-lc", "command -v codex >/dev/null"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        == 0,
        "gpu_available": subprocess.call(
            ["bash", "-lc", "command -v nvidia-smi >/dev/null"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        == 0,
        "codex_model": os.getenv("AI_SCIENTIST_CODEX_MODEL", "gpt-5.6-sol"),
        "codex_reasoning_effort": os.getenv(
            "AI_SCIENTIST_CODEX_REASONING_EFFORT", "xhigh"
        ),
        "active_job": manager.active_job().id if manager.active_job() else None,
    }


@app.get("/api/ideas")
def ideas() -> dict[str, Any]:
    return {"files": list_idea_files()}


@app.get("/api/skills")
def skills() -> dict[str, Any]:
    return list_skills()


@app.get("/api/jobs")
def jobs() -> dict[str, Any]:
    ordered = sorted(
        manager.jobs.values(), key=lambda job: job.created_at, reverse=True
    )
    return {"jobs": [job.snapshot() for job in ordered]}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str, after: int = 0) -> dict[str, Any]:
    job = manager.jobs.get(job_id)
    if not job:
        raise HTTPException(404, "실행 기록을 찾을 수 없습니다.")
    data = job.snapshot(include_logs=True, after=max(0, after))
    files = job_files(job)
    data["files"] = files
    data["result_summary"] = experiment_result_summary(job, files)
    return data


@app.post("/api/jobs/ideation", status_code=202)
def start_ideation(payload: IdeationRequest) -> dict[str, Any]:
    job_id = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    run_dir = RUN_ROOT / job_id
    run_dir.mkdir(parents=True)
    topic_path = run_dir / f"{clean_slug(payload.title)}.md"
    topic_path.write_text(
        "\n".join(
            [
                f"# Title\n{payload.title}",
                f"# Keywords\n{payload.keywords or 'machine learning, automated science'}",
                f"# TL;DR\n{payload.abstract[:300]}",
                f"# Abstract\n{payload.abstract}",
            ]
        ),
        encoding="utf-8",
    )
    command = [
        str(PYTHON),
        "-u",
        "ai_scientist/perform_ideation_temp_free.py",
        "--model",
        "codex",
        "--workshop-file",
        str(topic_path.relative_to(ROOT)),
        "--max-num-generations",
        str(payload.generations),
        "--num-reflections",
        str(payload.reflections),
    ]
    return manager.create("ideation", payload.title, command, run_dir).snapshot()


@app.post("/api/jobs/experiment", status_code=202)
def start_experiment(payload: ExperimentRequest) -> dict[str, Any]:
    idea_path = resolve_inside_root(payload.idea_path)
    allowed = {item["path"] for item in list_idea_files()}
    if payload.idea_path not in allowed or not idea_path.is_file():
        raise HTTPException(400, "선택한 아이디어 파일을 사용할 수 없습니다.")
    data = json.loads(idea_path.read_text(encoding="utf-8"))
    if payload.idea_index >= len(data):
        raise HTTPException(400, "아이디어 인덱스가 범위를 벗어났습니다.")
    idea = data[payload.idea_index]
    title = idea.get("Title", idea.get("Name", idea_path.stem))
    job_id = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    run_dir = RUN_ROOT / job_id
    run_dir.mkdir(parents=True)
    command = [
        str(PYTHON),
        "-u",
        "launch_scientist_bfts.py",
        "--load_ideas",
        payload.idea_path,
        "--idea_idx",
        str(payload.idea_index),
        "--num_cite_rounds",
        str(payload.citation_rounds),
    ]
    if not payload.writeup:
        command.append("--skip_writeup")
    if not payload.review:
        command.append("--skip_review")
    return manager.create("experiment", title, command, run_dir).snapshot()


@app.post("/api/jobs/{job_id}/stop")
def stop_job(job_id: str) -> dict[str, Any]:
    job = manager.jobs.get(job_id)
    if not job:
        raise HTTPException(404, "실행 기록을 찾을 수 없습니다.")
    manager.stop(job)
    return job.snapshot()


@app.post("/api/jobs/{job_id}/restart", status_code=202)
def restart_job(job_id: str) -> dict[str, Any]:
    previous = manager.jobs.get(job_id)
    if not previous:
        raise HTTPException(404, "실행 기록을 찾을 수 없습니다.")
    if previous.kind != "experiment":
        raise HTTPException(409, "전체 연구 실행만 체크포인트에서 재시작할 수 있습니다.")
    if previous.status not in {"failed", "stopped"}:
        raise HTTPException(409, "실패하거나 중지된 실행만 재시작할 수 있습니다.")

    experiment_dir = _find_resume_experiment(previous)
    if experiment_dir is None:
        raise HTTPException(409, "재시작 가능한 완료 단계 체크포인트가 없습니다.")

    command = list(previous.command)
    command.extend(
        ["--resume-experiment-dir", str(experiment_dir.relative_to(ROOT))]
    )
    new_job_id = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    run_dir = RUN_ROOT / new_job_id
    run_dir.mkdir(parents=True)
    resumed = manager.create(
        "experiment",
        previous.title,
        command,
        run_dir,
        output_dir=str(experiment_dir.relative_to(ROOT)),
    )
    return resumed.snapshot()


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str) -> StreamingResponse:
    if job_id not in manager.jobs:
        raise HTTPException(404, "실행 기록을 찾을 수 없습니다.")

    async def stream():
        last_sequence = 0
        last_signature = ""
        while True:
            job = manager.jobs[job_id]
            payload = job.snapshot(include_logs=True, after=last_sequence)
            last_sequence = payload["last_sequence"]
            files = job_files(job)
            payload["files"] = files
            payload["result_summary"] = experiment_result_summary(job, files)
            signature = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            if signature != last_signature:
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                last_signature = signature
            if job.status in {"completed", "failed", "stopped"}:
                break
            await asyncio.sleep(0.7)

    return StreamingResponse(stream(), media_type="text/event-stream")


def job_files(job: Job) -> list[dict[str, Any]]:
    roots = [job.run_dir]
    if job.output_dir:
        output = resolve_inside_root(job.output_dir)
        if output.exists():
            roots.append(output)
    files: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for base in roots:
        for path in base.rglob("*") if base.exists() else []:
            if (
                not path.is_file()
                or path.suffix.lower() not in ARTIFACT_SUFFIXES
                or path in seen
            ):
                continue
            seen.add(path)
            relative = str(path.relative_to(ROOT))
            files.append(
                {
                    "name": path.name,
                    "path": relative,
                    "size": path.stat().st_size,
                    "url": f"/api/files/{quote(relative)}",
                    "preview_url": f"/api/previews/{quote(relative)}",
                    "kind": artifact_kind(path),
                }
            )
    return sorted(files, key=lambda item: item["name"])


@app.get("/api/files/{file_path:path}")
def download_file(file_path: str) -> FileResponse:
    path = resolve_artifact(file_path)
    return FileResponse(path, filename=path.name)


@app.get("/api/previews/{file_path:path}")
def preview_file(file_path: str) -> dict[str, Any]:
    path = resolve_artifact(file_path)
    kind = artifact_kind(path)
    relative = str(path.relative_to(ROOT))
    payload: dict[str, Any] = {
        "name": path.name,
        "path": relative,
        "size": path.stat().st_size,
        "kind": kind,
        "download_url": f"/api/files/{quote(relative)}",
    }
    if kind in {"pdf", "image"}:
        payload["view_url"] = f"/api/views/{quote(relative)}"
        return payload

    raw = path.read_bytes()
    payload["truncated"] = len(raw) > MAX_PREVIEW_BYTES
    payload["content"] = raw[:MAX_PREVIEW_BYTES].decode("utf-8", errors="replace")
    return payload


@app.get("/api/views/{file_path:path}")
def view_file(file_path: str) -> FileResponse:
    path = resolve_artifact(file_path)
    if artifact_kind(path) not in {"pdf", "image"}:
        raise HTTPException(415, "인라인 보기를 지원하지 않는 파일 형식입니다.")
    return FileResponse(path)


app.mount("/", StaticFiles(directory=STATIC_ROOT, html=True), name="static")
