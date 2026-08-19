const $ = (selector) => document.querySelector(selector);

function setLamp(selector, on) {
  const lamp = $(selector);
  lamp.classList.toggle("is-on", on);
  lamp.classList.toggle("is-off", !on);
}

async function loadRuntime() {
  try {
    const [healthResponse, jobsResponse] = await Promise.all([
      fetch("/api/health"),
      fetch("/api/jobs"),
    ]);
    if (!healthResponse.ok || !jobsResponse.ok) throw new Error("runtime unavailable");

    const health = await healthResponse.json();
    const { jobs = [] } = await jobsResponse.json();
    const active = jobs.find((job) => job.id === health.active_job);

    $("#guide-model").textContent = health.codex_model || "—";
    $("#guide-reasoning").textContent = health.codex_reasoning_effort || "—";
    $("#guide-runtime").textContent = health.codex_available && health.gpu_available ? "READY" : "CHECK";
    setLamp("#guide-runtime-lamp", Boolean(health.codex_available && health.gpu_available));

    if (active) {
      $("#guide-job").textContent = active.status.toUpperCase();
      $("#guide-active-run").textContent = active.id;
      $("#guide-active-stage").textContent = `${active.stage} · ${active.progress}%`;
      setLamp("#guide-job-lamp", active.status === "running");
    } else {
      $("#guide-job").textContent = "IDLE";
      $("#guide-active-run").textContent = "없음";
      $("#guide-active-stage").textContent = "대기";
      setLamp("#guide-job-lamp", false);
    }
  } catch {
    $("#guide-runtime").textContent = "OFFLINE";
    $("#guide-job").textContent = "UNKNOWN";
    $("#guide-active-run").textContent = "연결 안 됨";
    setLamp("#guide-runtime-lamp", false);
    setLamp("#guide-job-lamp", false);
  }
}

loadRuntime();
