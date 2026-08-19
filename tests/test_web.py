import json
from pathlib import Path
import shutil
import subprocess
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from web.app import EXPERIMENT_ROOT, ROOT, Job, JobManager, _find_resume_experiment, app, manager


class WebWorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.created_job_ids = []

    def tearDown(self):
        for job_id in self.created_job_ids:
            job = manager.jobs.pop(job_id, None)
            if job:
                shutil.rmtree(job.run_dir, ignore_errors=True)

    def test_home_and_health_are_available(self):
        home = self.client.get("/")
        self.assertEqual(home.status_code, 200)
        self.assertIn("Research Workbench", home.text)
        self.assertIn('href="/guide.html"', home.text)
        self.assertIn('id="idea-summary"', home.text)
        self.assertIn('id="idea-summary-button"', home.text)
        self.assertIn('id="idea-decision-title"', home.text)
        self.assertIn('id="experiment-summary"', home.text)
        self.assertIn('id="result-summary-button"', home.text)
        self.assertIn("NAIS Science", home.text)
        self.assertIn("CONNECTED", home.text)
        self.assertIn("research-hub.192.168.0.56.nip.io", home.text)
        self.assertIn('class="workbench-content"', home.text)
        self.assertIn('class="launch-deck"', home.text)
        self.assertIn('id="ideation-launch-preview"', home.text)
        self.assertIn('id="experiment-launch-preview"', home.text)
        self.assertIn('id="topology-readout"', home.text)
        self.assertIn("실험 전 추천", (ROOT / "web/static/app.js").read_text())
        self.assertIn("idea-candidate-rating", (ROOT / "web/static/app.js").read_text())
        self.assertIn('data-idea-preview="${index}"', (ROOT / "web/static/app.js").read_text())
        self.assertIn("button.dataset.ideaPreview", (ROOT / "web/static/app.js").read_text())
        self.assertIn("formatIdeaPreviewHeader", (ROOT / "web/static/app.js").read_text())
        self.assertIn("target.getBoundingClientRect().top - documentView.getBoundingClientRect().top", (ROOT / "web/static/app.js").read_text())
        self.assertNotIn("setIdeaCardExpanded", (ROOT / "web/static/app.js").read_text())
        topology_source = (ROOT / "web/static/app.js").read_text()
        self.assertIn("PARALLEL LITERATURE SCOUTS", topology_source)
        self.assertIn("반증 조사원", topology_source)
        self.assertIn("topology-stage-group", topology_source)
        self.assertIn("updateLaunchPreviews", topology_source)
        self.assertIn("bindTopologyInteractions", topology_source)
        self.assertIn('["ArrowRight", "ArrowDown"]', topology_source)
        self.assertIn('const isCurrentNode = ["is-current", "is-failed"].includes(stateClass);', topology_source)
        self.assertNotIn('style="left:${node.x}px;top:${node.y}px"', topology_source)

        guide = self.client.get("/guide.html")
        self.assertEqual(guide.status_code, 200)
        self.assertIn("사카나 AI Scientist-v2만 그대로 돌린 것이 아닙니다", guide.text)
        self.assertIn("우리 통합·운영 레이어", guide.text)
        self.assertIn("다른 오픈소스와 외부 서비스", guide.text)
        self.assertIn("AIDE", guide.text)

        health = self.client.get("/api/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["status"], "ok")
        self.assertEqual(health.json()["codex_model"], "gpt-5.6-sol")
        self.assertEqual(health.json()["codex_reasoning_effort"], "xhigh")
        self.assertIn("research-topology", home.text)
        styles = (ROOT / "web/static/styles.css").read_text(encoding="utf-8")
        self.assertIn("color-scheme: light", styles)
        self.assertNotIn("color-scheme: dark", styles)
        self.assertIn("--platform-blue: #0071e3", styles)
        self.assertIn("--rack-ink: #0b1716", styles)
        self.assertIn("background: var(--rack-ink)", styles)
        self.assertIn("--type-body: 18px", styles)
        self.assertIn("--workflow-edge: #8ea49f", styles)
        self.assertIn(".topology-node em {", styles)
        self.assertIn(".topology-map {", styles)
        self.assertIn(".launch-deck {", styles)
        self.assertIn(".topology-node.is-selected", styles)
        self.assertIn(".artifact-viewer[open] .reader-shell", styles)
        self.assertIn("--instrument-text: #effaf6;", styles)
        self.assertIn("--instrument-line: rgba(185, 244, 223, .12);", styles)
        self.assertIn("border-color: var(--platform-blue);", styles)
        self.assertIn("background: var(--success-green);", styles)
        self.assertNotIn(".topology-node { position: absolute", styles)
        self.assertIn(".run-actions { flex: 0 0 auto;", styles)
        self.assertIn("display: flex", styles)
        self.assertNotIn(".idea-candidate.is-expanded", styles)
        self.assertIn(".result-table { min-width: 960px; font-size: var(--type-label); }", styles)
        self.assertIn("Main workbench owns vertical scrolling", styles)
        self.assertIn(".terminal { height: 388px; overflow: hidden;", styles)
        self.assertIn(".artifact-list, .history-list { max-height: none; overflow: visible;", styles)

    def test_job_selection_supports_shareable_direct_links(self):
        source = (ROOT / "web/static/app.js").read_text(encoding="utf-8")
        self.assertIn(
            'new URLSearchParams(window.location.search).get("job")', source
        )
        self.assertIn("window.history.replaceState", source)

    def test_idea_catalog_contains_valid_json_arrays(self):
        response = self.client.get("/api/ideas")
        self.assertEqual(response.status_code, 200)
        files = response.json()["files"]
        self.assertGreater(len(files), 0)
        self.assertTrue(all(item["path"].endswith(".json") for item in files))

    def test_skill_catalog_separates_common_and_project_scopes(self):
        response = self.client.get("/api/skills")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("common", payload)
        self.assertIn("project", payload)
        self.assertEqual(payload["common_count"], len(payload["common"]))
        self.assertEqual(payload["project_count"], len(payload["project"]))
        self.assertGreater(payload["common_count"], 0)

        home = self.client.get("/")
        self.assertNotIn("사용 가능한 연구 스킬", home.text)

    def test_ideation_job_exposes_progress_logs_and_artifact(self):
        def fake_run(job: Job):
            job.status = "running"
            job.stage = "ideation"
            job.started_at = "2026-08-12T00:00:00+00:00"
            job.add_log("Generating proposal 1/1")
            artifact = job.run_dir / "web-test-idea.json"
            artifact.write_text(json.dumps([{"Name": "web_test"}]), encoding="utf-8")
            job.status = "completed"
            job.stage = "complete"
            job.return_code = 0
            job.finished_at = "2026-08-12T00:00:01+00:00"
            job.persist()

        with patch.object(manager, "_run", side_effect=fake_run):
            response = self.client.post(
                "/api/jobs/ideation",
                json={
                    "title": "Web workbench integration test",
                    "keywords": "testing",
                    "abstract": "A sufficiently detailed test abstract for validating the workbench job flow.",
                    "generations": 1,
                    "reflections": 1,
                },
            )
        self.assertEqual(response.status_code, 202)
        job_id = response.json()["id"]
        self.created_job_ids.append(job_id)

        for _ in range(20):
            detail = self.client.get(f"/api/jobs/{job_id}").json()
            if detail["status"] == "completed":
                break
            time.sleep(0.01)
        self.assertEqual(detail["stage"], "complete")
        self.assertEqual(detail["progress"], 100)
        self.assertTrue(
            any("Generating proposal" in log["text"] for log in detail["logs"])
        )
        self.assertTrue(
            any(file["name"] == "web-test-idea.json" for file in detail["files"])
        )
        artifact = next(
            file for file in detail["files"] if file["name"] == "web-test-idea.json"
        )
        self.assertEqual(artifact["kind"], "json")
        preview = self.client.get(artifact["preview_url"])
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.json()["kind"], "json")
        self.assertIn("web_test", preview.json()["content"])

        events = self.client.get(f"/api/jobs/{job_id}/events")
        self.assertEqual(events.status_code, 200)
        self.assertIn("Generating proposal 1/1", events.text)

    def test_stop_terminates_only_the_job_process_group(self):
        run_dir = ROOT / "web_runs" / "stop-test"
        run_dir.mkdir(parents=True, exist_ok=True)
        job = Job("stop-test", "experiment", "Stop test", ["sleep", "30"], run_dir)
        job.status = "running"
        job.process = subprocess.Popen(["sleep", "30"], start_new_session=True)
        try:
            manager.stop(job)
            self.assertEqual(job.status, "stopping")
            self.assertIsNotNone(job.process.poll())
        finally:
            if job.process.poll() is None:
                job.process.kill()
            shutil.rmtree(run_dir, ignore_errors=True)

    def test_rejects_invalid_payload_and_file_traversal(self):
        invalid = self.client.post(
            "/api/jobs/ideation",
            json={"title": "x", "abstract": "too short"},
        )
        self.assertEqual(invalid.status_code, 422)

        traversal = self.client.get("/api/files/../../etc/passwd")
        self.assertIn(traversal.status_code, {400, 403, 404})

    def test_stage_inference_never_moves_backwards(self):
        run_dir = ROOT / "web_runs" / "stage-test"
        run_dir.mkdir(parents=True, exist_ok=True)
        job = Job("stage-test", "experiment", "Stage test", ["true"], run_dir)
        try:
            job.stage = "writeup"
            job.add_log("Starting run test")
            self.assertEqual(job.stage, "writeup")
            job.add_log("Paper review completed.")
            self.assertEqual(job.stage, "review")
            self.assertEqual(job.topology_step, "review")
        finally:
            shutil.rmtree(run_dir, ignore_errors=True)

    def test_topology_tracks_bfts_substages(self):
        run_dir = ROOT / "web_runs" / "topology-test"
        run_dir.mkdir(parents=True, exist_ok=True)
        job = Job("topology-test", "experiment", "Topology test", ["true"], run_dir)
        try:
            job.stage = "setup"
            job.add_log("Starting main stage: 1")
            self.assertEqual(job.topology_step, "initial")
            self.assertEqual(job.stage, "experiments")
            job.add_log("Starting main stage: 3")
            self.assertEqual(job.topology_step, "creative")
            snapshot = job.snapshot()
            self.assertEqual(snapshot["topology_step"], "creative")
            self.assertEqual(snapshot["reasoning_effort"], "xhigh")
        finally:
            shutil.rmtree(run_dir, ignore_errors=True)

    def test_experiment_job_exposes_a_decision_brief_from_best_complete_result(self):
        import numpy as np

        run_dir = ROOT / "web_runs" / "result-summary-test"
        experiment_dir = EXPERIMENT_ROOT / "result-summary-test"
        result_dir = experiment_dir / "logs/0-run/experiment_results/experiment_clean"
        run_dir.mkdir(parents=True, exist_ok=True)
        result_dir.mkdir(parents=True, exist_ok=True)
        metric_names = np.array(
            ["paired_risk_constrained_harness_regret", "coverage"]
        )
        variants = np.array(
            ["full_heteroscedastic", "uncalibrated", "fixed_route"]
        )
        comparisons = {}
        for dataset, adaptive, fixed, delta, delta_ci in (
            ("gsm8k", 0.0012, 0.0028, 0.0016, 0.0006),
            ("mbpp", 0.0150, 0.0140, -0.0010, 0.0024),
            ("hotpot_qa", 0.0167, 0.0146, -0.0021, 0.0031),
        ):
            comparisons[dataset] = {
                "variants": variants,
                "metric_names": metric_names,
                "test_mean": np.array(
                    [[adaptive, 0.92], [0.44, 0.01], [fixed, 0.92]]
                ),
                "test_95ci": np.array(
                    [[0.0005, 0.03], [0.03, 0.01], [0.0007, 0.03]]
                ),
                "paired_effects": {
                    "fixed_route": {
                        "paired_risk_constrained_harness_regret": {
                            "mean": delta,
                            "ci95": delta_ci,
                        }
                    }
                },
            }
        payload = {
            "configuration": {
                "datasets": np.array(["gsm8k", "mbpp", "hotpot_qa"]),
                "planned_seeds": np.array([11, 23, 37, 51, 71]),
                "successful_seeds": np.array([11, 23, 37, 51, 71]),
                "outcome_provenance": "simulated",
            },
            "completion": {
                "stage_complete": True,
                "enough_results": True,
                "all_components_classified": True,
                "result_counts": {("gsm8k", "full"): 5},
            },
            "comparisons": comparisons,
            "component_classifications": {
                "conformal_risk_calibration": {"overall": "beneficial"},
                "adaptive_routing": {"overall": "dataset-dependent"},
                "verify": {"overall": "beneficial"},
            },
            "failed_jobs": [],
        }
        np.save(result_dir / "experiment_data.npy", payload, allow_pickle=True)
        (result_dir / "suite_test_ablation_primary_metric.png").write_bytes(b"png")
        job = Job(
            "result-summary-test", "experiment", "Result summary", ["true"], run_dir
        )
        job.status = "stopped"
        job.stage = "plots"
        job.output_dir = str(experiment_dir.relative_to(ROOT))
        manager.jobs[job.id] = job
        self.created_job_ids.append(job.id)
        try:
            response = self.client.get(f"/api/jobs/{job.id}")
            self.assertEqual(response.status_code, 200)
            summary = response.json()["result_summary"]
            self.assertEqual(summary["scope"], "partial")
            self.assertEqual(summary["successful_seed_count"], 5)
            self.assertEqual(len(summary["comparisons"]), 3)
            self.assertEqual(summary["comparisons"][0]["verdict"], "adaptive_better")
            self.assertEqual(summary["comparisons"][1]["verdict"], "inconclusive")
            self.assertEqual(
                summary["one_line_conclusion"],
                "시뮬레이션상 적응형 효과는 데이터셋별로 달랐고, "
                "Conformal 보정은 유효했습니다.",
            )
            self.assertEqual(len(summary["plots"]), 1)
            self.assertIn("시뮬레이션", " ".join(summary["limitations"]))
        finally:
            shutil.rmtree(experiment_dir, ignore_errors=True)

    def test_ideation_topology_tracks_multisource_survey(self):
        run_dir = ROOT / "web_runs" / "literature-topology-test"
        run_dir.mkdir(parents=True, exist_ok=True)
        job = Job("literature-topology-test", "ideation", "Survey", ["true"], run_dir)
        try:
            job.add_log("[Literature Survey] start query='harness' lanes=arxiv,kurate")
            self.assertEqual(job.topology_step, "literature")
            job.add_log("[Literature Survey] lane source=kurate status=ok hits=2")
            self.assertEqual(job.topology_step, "literature")
            job.add_log(
                "[Literature Survey] complete status=partial sources_ok=3/4 unique_papers=8"
            )
            self.assertEqual(job.topology_step, "reflection")
        finally:
            shutil.rmtree(run_dir, ignore_errors=True)

    def test_finds_latest_checkpoint_for_stopped_experiment(self):
        idea_dir = ROOT / "web_runs" / "restart-idea-test"
        experiment_dir = EXPERIMENT_ROOT / "restart-checkpoint-test"
        idea_dir.mkdir(parents=True, exist_ok=True)
        checkpoint = experiment_dir / "logs" / "0-run" / "stage_2" / "checkpoint.pkl"
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        idea_path = idea_dir / "ideas.json"
        idea = {"Name": "restart_checkpoint_test", "Title": "Restart test"}
        idea_path.write_text(json.dumps([idea]), encoding="utf-8")
        (experiment_dir / "idea.json").write_text(json.dumps(idea), encoding="utf-8")
        checkpoint.write_bytes(b"checkpoint")
        job = Job(
            "restart-job-test",
            "experiment",
            "Restart test",
            [
                str(ROOT / ".venv/bin/python"),
                "launch_scientist_bfts.py",
                "--load_ideas",
                str(idea_path.relative_to(ROOT)),
                "--idea_idx",
                "0",
            ],
            idea_dir,
        )
        try:
            self.assertEqual(_find_resume_experiment(job), experiment_dir)
        finally:
            shutil.rmtree(idea_dir, ignore_errors=True)
            shutil.rmtree(experiment_dir, ignore_errors=True)

    def test_archived_job_is_restored_from_manifest(self):
        run_dir = ROOT / "web_runs" / "restore-test"
        run_dir.mkdir(parents=True, exist_ok=True)
        job = Job("restore-test", "ideation", "Restore test", ["true"], run_dir)
        job.status = "completed"
        job.stage = "complete"
        job.persist()
        try:
            restored = JobManager()
            self.assertIn("restore-test", restored.jobs)
            self.assertEqual(restored.jobs["restore-test"].status, "completed")
        finally:
            shutil.rmtree(run_dir, ignore_errors=True)

    def test_legacy_completed_archive_restores_completed_topology(self):
        run_dir = ROOT / "web_runs" / "legacy-topology-test"
        run_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "id": "legacy-topology-test",
            "kind": "ideation",
            "title": "Legacy topology test",
            "command": ["true"],
            "status": "completed",
            "stage": "complete",
            "logs": [],
        }
        (run_dir / "job.json").write_text(json.dumps(manifest), encoding="utf-8")
        try:
            restored = JobManager()
            self.assertEqual(
                restored.jobs["legacy-topology-test"].topology_step, "complete"
            )
        finally:
            shutil.rmtree(run_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
