const state = {
  selectedJob: null,
  jobs: [],
  ideas: [],
  eventSource: null,
  jobPollTimer: null,
  lastSequence: 0,
  logCount: 0,
  elapsedTimer: null,
  artifacts: [],
  ideaSummaryJob: null,
  mode: "ideation",
  topologySelection: null,
  topologyContext: null,
};

const STORAGE_KEY = "ai-scientist-workbench-state-v1";
const draftFields = [
  "topic-title",
  "topic-abstract",
  "topic-keywords",
  "generation-count",
  "reflection-count",
  "idea-file",
  "idea-index",
  "include-writeup",
  "include-review",
  "citation-rounds",
];

function loadWorkbenchState() {
  try {
    return JSON.parse(window.localStorage.getItem(STORAGE_KEY) || "{}") || {};
  } catch (_) {
    return {};
  }
}

function saveWorkbenchState(patch) {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...loadWorkbenchState(), ...patch }));
  } catch (_) {
    // The workbench remains usable when browser storage is unavailable.
  }
}

function saveDraft() {
  const draft = {};
  draftFields.forEach((id) => {
    const field = $(`#${id}`);
    if (!field) return;
    draft[id] = field.type === "checkbox" ? field.checked : field.value;
  });
  saveWorkbenchState({ draft });
}

function prefersReducedMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function setTextWithMotion(element, value) {
  if (!element || element.textContent === String(value)) return;
  element.textContent = value;
  if (prefersReducedMotion() || !element.animate) return;
  element.getAnimations().forEach((animation) => animation.cancel());
  element.animate(
    [{ opacity: .38, transform: "translateY(3px)" }, { opacity: 1, transform: "none" }],
    { duration: 220, easing: "cubic-bezier(.23,1,.32,1)" },
  );
}

function updateLaunchPreviews() {
  const title = $("#topic-title")?.value.trim() || "";
  const abstract = $("#topic-abstract")?.value.trim() || "";
  const generations = Number($("#generation-count")?.value || 1);
  const reflections = Number($("#reflection-count")?.value || 1);
  const ideationReady = title.length >= 3 && abstract.length >= 20;
  const ideationPreview = $("#ideation-launch-preview");
  ideationPreview?.classList.toggle("is-ready", ideationReady);
  setTextWithMotion($("#ideation-ready-label"), ideationReady ? "탐색 준비 완료" : "입력 대기");
  setTextWithMotion($("#ideation-preview-question"), title || "연구 질문을 입력하면 실행 설계가 여기에 보입니다.");
  setTextWithMotion($("#ideation-preview-candidates"), generations);
  setTextWithMotion($("#ideation-preview-reflections"), reflections);
  const breadth = generations >= 5 || reflections >= 5 ? "넓은 탐색" : generations >= 3 || reflections >= 2 ? "비교 탐색" : "빠른 탐색";
  setTextWithMotion($("#ideation-preview-depth"), breadth);

  const ideaFile = $("#idea-file")?.value || "";
  const selectedIdea = $("#idea-index")?.selectedOptions?.[0]?.textContent?.trim() || "";
  const citations = Math.max(0, Number($("#citation-rounds")?.value || 0));
  const writeup = Boolean($("#include-writeup")?.checked);
  const review = Boolean($("#include-review")?.checked);
  const experimentPreview = $("#experiment-launch-preview");
  experimentPreview?.classList.toggle("is-ready", Boolean(ideaFile));
  setTextWithMotion($("#experiment-ready-label"), ideaFile ? "실행 준비 완료" : "선택 대기");
  setTextWithMotion($("#experiment-preview-title"), ideaFile && selectedIdea ? selectedIdea : "실행할 아이디어를 선택하면 연구 경로가 여기에 보입니다.");
  setTextWithMotion($("#experiment-preview-citations"), citations);
  setTextWithMotion($("#experiment-preview-review"), review ? "ON" : "OFF");
  const outputs = [writeup ? "논문" : null, review ? "동료 평가" : null].filter(Boolean).join(" · ") || "코드 · 지표";
  setTextWithMotion($("#experiment-preview-output"), outputs);
}

function restoreDraft(ids = draftFields) {
  const draft = loadWorkbenchState().draft || {};
  ids.forEach((id) => {
    const field = $(`#${id}`);
    if (!field || !(id in draft)) return;
    if (field.type === "checkbox") {
      field.checked = Boolean(draft[id]);
    } else if (field.tagName !== "SELECT" || [...field.options].some((option) => option.value === String(draft[id]))) {
      field.value = String(draft[id]);
    }
  });
}

const stageLabels = {
  queued: ["대기", "요청 준비"],
  ideation: ["가설", "아이디어 탐색"],
  setup: ["준비", "환경 구성"],
  experiments: ["실험", "트리 탐색"],
  plots: ["시각화", "증거 집계"],
  citations: ["문헌", "인용 수집"],
  writeup: ["논문", "원고 작성"],
  review: ["평가", "동료 검토"],
  complete: ["완료", "산출물 정리"],
};

const topologyDefinitions = {
  ideation: {
    order: ["intake", "hypothesis", "literature", "reflection", "finalize", "complete"],
    nodes: [
      { id: "intake", label: "연구 질문", meta: "INPUT · 주제와 제약" },
      { id: "hypothesis", label: "탐색 질문", meta: "QUERY · 제목과 키워드" },
      { id: "bibliographic", stage: "literature", label: "서지·원문 검색", meta: "S2 + arXiv" },
      { id: "kurate", stage: "literature", label: "발견 신호", meta: "KURATE · 보조" },
      { id: "primary-scout", stage: "literature", label: "원문 조사원", meta: "CODEX · 선행연구" },
      { id: "adversarial-scout", stage: "literature", label: "반증 조사원", meta: "CODEX · 부정 결과" },
      { id: "reflection", label: "비교·가설 생성", meta: "CODEX · 단순성/신규성" },
      { id: "finalize", label: "아이디어 확정", meta: "FinalizeIdea · JSON" },
      { id: "complete", label: "증거 보관", meta: "SURVEY + IDEA JSON" },
    ],
    segments: [
      { nodes: ["intake"] },
      { nodes: ["hypothesis"] },
      { label: "PARALLEL LITERATURE SCOUTS", note: "4개 독립 조사 레인", variant: "parallel", nodes: ["bibliographic", "kurate", "primary-scout", "adversarial-scout"] },
      { nodes: ["reflection"] },
      { nodes: ["finalize"] },
      { nodes: ["complete"] },
    ],
  },
  experiment: {
    order: ["intake", "setup", "initial", "tuning", "creative", "ablation", "plots", "citations", "writeup", "review", "complete"],
    nodes: [
      { id: "intake", label: "아이디어", meta: "INPUT · 가설 선택" },
      { id: "setup", label: "실험 준비", meta: "PYTHON · 작업공간" },
      { id: "initial", label: "초기 구현", meta: "BFTS · 후보 생성" },
      { id: "tuning", label: "베이스라인 튜닝", meta: "BFTS · 점수 개선" },
      { id: "creative", label: "창의적 실험", meta: "BFTS · 대안 탐색" },
      { id: "ablation", label: "Ablation", meta: "BFTS · 기여 검증" },
      { id: "plots", label: "증거 집계", meta: "MATPLOTLIB · 플롯" },
      { id: "citations", label: "인용 수집", meta: "S2 API · BibTeX" },
      { id: "writeup", label: "논문 작성", meta: "CODEX · LaTeX" },
      { id: "review", label: "동료 평가", meta: "CODEX VLM · 심사" },
      { id: "complete", label: "연구 패키지", meta: "PDF · 코드 · 지표" },
    ],
    segments: [
      { nodes: ["intake"] },
      { nodes: ["setup"] },
      { label: "BFTS SEARCH LOOP", note: "4단계 반복 개선", variant: "sequence", nodes: ["initial", "tuning", "creative", "ablation"] },
      { nodes: ["plots"] },
      { label: "EVIDENCE TO PAPER", note: "인용·작성·검토", variant: "sequence", nodes: ["citations", "writeup", "review"] },
      { nodes: ["complete"] },
    ],
  },
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function toast(message, error = false) {
  const element = document.createElement("div");
  element.className = `toast${error ? " is-error" : ""}`;
  element.textContent = message;
  $("#toast-region").append(element);
  window.setTimeout(() => element.remove(), 4200);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || "요청을 처리하지 못했습니다.");
  return data;
}

function setMode(mode) {
  const ideation = mode === "ideation";
  state.mode = ideation ? "ideation" : "experiment";
  saveWorkbenchState({ mode: state.mode });
  $("#ideation-tab").classList.toggle("is-active", ideation);
  $("#experiment-tab").classList.toggle("is-active", !ideation);
  $("#ideation-tab").setAttribute("aria-selected", String(ideation));
  $("#experiment-tab").setAttribute("aria-selected", String(!ideation));
  $("#ideation-panel").hidden = !ideation;
  $("#experiment-panel").hidden = ideation;
  const activePanel = ideation ? $("#ideation-panel") : $("#experiment-panel");
  if (!prefersReducedMotion() && activePanel?.animate) {
    activePanel.getAnimations().forEach((animation) => animation.cancel());
    activePanel.animate(
      [{ opacity: .55, transform: "translateY(6px) scale(.997)" }, { opacity: 1, transform: "none" }],
      { duration: 240, easing: "cubic-bezier(.23,1,.32,1)" },
    );
  }
  updateLaunchPreviews();
}

async function loadHealth() {
  try {
    const health = await api("/api/health");
    setSystemStatus("codex", health.codex_available);
    setSystemStatus("gpu", health.gpu_available);
    $("#model-status").textContent = health.codex_model;
    $("#reasoning-status").textContent = health.codex_reasoning_effort;
    $("#topology-runtime").textContent = `${health.codex_model} · ${health.codex_reasoning_effort}`;
  } catch (error) {
    setSystemStatus("codex", false);
    setSystemStatus("gpu", false);
  }
}

function setSystemStatus(name, available) {
  $(`#${name}-lamp`).className = `status-lamp ${available ? "is-on" : "is-off"}`;
  $(`#${name}-status`).textContent = available ? "Ready" : "Offline";
}

async function loadIdeas() {
  const data = await api("/api/ideas");
  state.ideas = data.files;
  const select = $("#idea-file");
  if (!state.ideas.length) {
    select.innerHTML = '<option value="">생성된 아이디어가 없습니다</option>';
    updateIdeaOptions();
    return;
  }
  select.innerHTML = state.ideas
    .map((file) => `<option value="${escapeHtml(file.path)}">${escapeHtml(file.name)} · ${file.count}개</option>`)
    .join("");
  restoreDraft(["idea-file"]);
  updateIdeaOptions();
  restoreDraft(["idea-index", "include-writeup", "include-review", "citation-rounds"]);
  updateLaunchPreviews();
}

function updateIdeaOptions() {
  const file = state.ideas.find((item) => item.path === $("#idea-file").value);
  const select = $("#idea-index");
  if (!file?.ideas?.length) {
    select.innerHTML = '<option value="0">사용 가능한 아이디어가 없습니다</option>';
    updateLaunchPreviews();
    return;
  }
  select.innerHTML = file.ideas
    .map((idea) => `<option value="${idea.index}">${escapeHtml(idea.title)}</option>`)
    .join("");
  updateLaunchPreviews();
}

async function loadJobs(selectActive = true) {
  const data = await api("/api/jobs");
  state.jobs = data.jobs;
  renderHistory();
  if (selectActive && !state.selectedJob && state.jobs.length) {
    const requestedJobId = new URLSearchParams(window.location.search).get("job");
    const requested = state.jobs.find((job) => job.id === requestedJobId);
    const savedJobId = loadWorkbenchState().selectedJob;
    const saved = state.jobs.find((job) => job.id === savedJobId);
    const active = state.jobs.find((job) => ["queued", "running", "stopping"].includes(job.status));
    await selectJob(requested?.id || saved?.id || active?.id || state.jobs[0].id);
  }
}

function renderHistory() {
  const container = $("#history-list");
  if (!state.jobs.length) {
    container.innerHTML = '<div class="small-empty">실행 기록이 없습니다.</div>';
    return;
  }
  container.innerHTML = state.jobs
    .map((job) => `
      <button type="button" class="history-item${job.id === state.selectedJob ? " is-selected" : ""}" data-job="${job.id}">
        <span class="history-status ${escapeHtml(job.status)}"></span>
        <span class="history-copy"><strong>${escapeHtml(job.title)}</strong><span>${job.kind === "ideation" ? "아이디어 생성" : "전체 연구"} · ${formatDate(job.created_at)}</span></span>
        <span class="download-mark">›</span>
      </button>`)
    .join("");
  $$("[data-job]").forEach((button) => button.addEventListener("click", () => selectJob(button.dataset.job)));
}

async function selectJob(jobId) {
  if (state.selectedJob !== jobId) state.topologySelection = null;
  state.selectedJob = jobId;
  saveWorkbenchState({ selectedJob: jobId });
  const directUrl = new URL(window.location.href);
  directUrl.searchParams.set("job", jobId);
  window.history.replaceState({}, "", directUrl);
  state.lastSequence = 0;
  state.logCount = 0;
  clearTerminal();
  renderHistory();
  stopJobSync();
  const detail = await api(`/api/jobs/${jobId}`);
  renderJob(detail, true);
  if (["queued", "running", "stopping"].includes(detail.status)) connectEvents(jobId);
}

function stopJobSync() {
  if (state.eventSource) state.eventSource.close();
  state.eventSource = null;
  if (state.jobPollTimer) window.clearTimeout(state.jobPollTimer);
  state.jobPollTimer = null;
}

function scheduleJobPoll(jobId, delay = 2000) {
  if (state.jobPollTimer) window.clearTimeout(state.jobPollTimer);
  state.jobPollTimer = window.setTimeout(() => pollJob(jobId), delay);
}

async function pollJob(jobId) {
  if (state.selectedJob !== jobId) return;
  try {
    const job = await api(`/api/jobs/${jobId}?after=${state.lastSequence}`);
    if (state.selectedJob !== jobId) return;
    renderJob(job, false);
    if (["queued", "running", "stopping"].includes(job.status)) {
      scheduleJobPoll(jobId);
    } else {
      stopJobSync();
      await Promise.all([loadJobs(false), loadIdeas()]);
    }
  } catch (_) {
    if (state.selectedJob === jobId) scheduleJobPoll(jobId, 3000);
  }
}

function connectEvents(jobId) {
  const source = new EventSource(`/api/jobs/${jobId}/events`);
  state.eventSource = source;
  scheduleJobPoll(jobId);
  source.onmessage = (event) => {
    const job = JSON.parse(event.data);
    if (state.selectedJob !== jobId) return;
    renderJob(job, false);
    if (!["queued", "running", "stopping"].includes(job.status)) {
      stopJobSync();
      loadJobs(false);
      loadIdeas();
    } else {
      scheduleJobPoll(jobId);
    }
  };
  source.onerror = () => {
    source.close();
    if (state.eventSource === source) state.eventSource = null;
    pollJob(jobId);
  };
}

function renderJob(job, replaceLogs) {
  $("#active-title").textContent = job.title;
  const runState = $("#run-state");
  runState.textContent = job.status.toUpperCase();
  runState.className = `run-state is-${job.status}`;
  $("#progress-bar").style.width = `${job.progress}%`;
  const canStop = ["queued", "running", "stopping"].includes(job.status);
  const canRestart = job.kind === "experiment" && ["failed", "stopped"].includes(job.status);
  const canViewIdeaSummary = job.kind === "ideation" && job.status === "completed";
  const canViewResultSummary = job.kind === "experiment" && Boolean(job.result_summary);
  $("#stop-button").hidden = !canStop;
  $("#quick-stop-button").hidden = !canStop;
  $("#restart-button").hidden = !canRestart;
  $("#idea-summary-button").hidden = !canViewIdeaSummary;
  $("#result-summary-button").hidden = !canViewResultSummary;
  $("#stop-button").disabled = job.status === "stopping";
  $("#quick-stop-button").disabled = job.status === "stopping";
  renderTopology(job);
  if (replaceLogs) clearTerminal();
  appendLogs(job.logs || []);
  renderArtifacts(job.files || []);
  renderExperimentSummary(job);
  renderIdeaSummary(job);
  startElapsed(job.started_at, job.finished_at);
  state.lastSequence = job.last_sequence || state.lastSequence;
}

function renderTopology(job) {
  const definition = topologyDefinitions[job.kind || "ideation"];
  const fallbackStep = job.stage === "experiments" ? "initial" : job.stage;
  const currentStep = (job.status === "completed" || job.stage === "complete")
    ? "complete"
    : job.topology_step || fallbackStep || "intake";
  const currentIndex = Math.max(0, definition.order.indexOf(currentStep));
  const isFailed = ["failed", "stopped"].includes(job.status);
  const stepState = (step) => {
    const index = definition.order.indexOf(step);
    if (job.status === "completed" && index <= currentIndex) return "is-done";
    if (index < currentIndex) return "is-done";
    if (index === currentIndex) return isFailed ? "is-failed" : "is-current";
    return "";
  };
  const nodeState = (node) => stepState(node.stage || node.id);
  const nodesById = Object.fromEntries(definition.nodes.map((node) => [node.id, node]));
  const nodeNumbers = new Map(definition.nodes.map((node, index) => [node.id, String(index + 1).padStart(2, "0")]));
  const renderNode = (nodeId) => {
    const node = nodesById[nodeId];
    const stateClass = nodeState(node);
    const isCurrentNode = ["is-current", "is-failed"].includes(stateClass);
    const stateLabel = stateClass === "is-current" ? "실행 중" : stateClass === "is-done" ? "완료" : stateClass === "is-failed" ? "중단" : "대기";
    return `<button type="button" class="topology-node ${stateClass}" data-step="${node.id}" aria-pressed="false" aria-label="${escapeHtml(node.label)} · ${stateLabel}"${isCurrentNode ? ' aria-current="step"' : ""}>
      <div class="topology-node-head"><span class="topology-index">${nodeNumbers.get(node.id)}</span><em>${stateLabel}</em></div>
      <div class="topology-copy"><strong>${escapeHtml(node.label)}</strong><span>${escapeHtml(node.meta)}</span></div>
    </button>`;
  };
  const segmentState = (segment) => {
    const states = segment.nodes.map((nodeId) => nodeState(nodesById[nodeId]));
    if (states.includes("is-failed")) return "is-failed";
    if (states.includes("is-current")) return "is-current";
    if (states.every((stateClass) => stateClass === "is-done")) return "is-done";
    return "";
  };
  $("#topology-runtime").textContent = `${job.model || "gpt-5.6-sol"} · ${job.reasoning_effort || "xhigh"}`;
  $("#research-topology").className = `research-topology is-${job.kind || "ideation"}`;
  const segments = definition.segments.map((segment, index) => {
    const isGroup = segment.nodes.length > 1;
    const stage = isGroup
      ? `<section class="topology-stage topology-stage-group topology-stage-${segment.variant || "sequence"}">
          <header><div><span>${escapeHtml(segment.label)}</span><strong>${escapeHtml(segment.note)}</strong></div><b>${segment.nodes.length} LANES</b></header>
          <div class="topology-stage-body">${segment.nodes.map(renderNode).join("")}</div>
        </section>`
      : `<div class="topology-stage topology-stage-node">${renderNode(segment.nodes[0])}</div>`;
    const nextSegment = definition.segments[index + 1];
    if (!nextSegment) return stage;
    return `${stage}<div class="topology-connector ${segmentState(nextSegment)}" aria-hidden="true"><span></span></div>`;
  }).join("");
  $("#research-topology").innerHTML = `<div class="topology-map">${segments}</div>`;
  const currentNode = definition.nodes.find((node) => node.id === currentStep)
    || definition.nodes.find((node) => node.stage === currentStep)
    || definition.nodes[0];
  state.topologyContext = { definition, currentStep: currentNode.id };
  bindTopologyInteractions();
  const selectedStep = definition.nodes.some((node) => node.id === state.topologySelection)
    ? state.topologySelection
    : currentNode.id;
  selectTopologyNode(selectedStep, { emphasize: Boolean(state.topologySelection) });
  window.requestAnimationFrame(() => {
    const viewport = $("#research-topology");
    const focusNode = viewport.querySelector('[aria-current="step"]') || [...viewport.querySelectorAll("[data-step]")].find((node) => node.dataset.step === currentStep);
    const mobileLayout = window.matchMedia("(max-width: 700px)").matches;
    if (focusNode && !mobileLayout && job.status !== "completed") {
      viewport.scrollLeft = Math.max(0, focusNode.offsetLeft - (viewport.clientWidth - focusNode.offsetWidth) / 2);
    } else {
      viewport.scrollLeft = 0;
    }
  });
}

function topologyNodeState(button) {
  if (button.classList.contains("is-current")) return "실행 중";
  if (button.classList.contains("is-done")) return "완료";
  if (button.classList.contains("is-failed")) return "중단";
  return "대기";
}

function selectTopologyNode(step, { focus = false, emphasize = true } = {}) {
  const context = state.topologyContext;
  const viewport = $("#research-topology");
  if (!context || !viewport) return;
  const button = viewport.querySelector(`[data-step="${CSS.escape(step)}"]`);
  const node = context.definition.nodes.find((item) => item.id === step);
  if (!button || !node) return;
  const map = viewport.querySelector(".topology-map");
  map?.classList.toggle("has-selection", emphasize);
  viewport.querySelectorAll("[data-step]").forEach((item) => {
    const selected = emphasize && item === button;
    item.classList.toggle("is-selected", selected);
    item.setAttribute("aria-pressed", String(selected));
  });
  const index = context.definition.nodes.indexOf(node) + 1;
  setTextWithMotion($("#topology-readout-index"), String(index).padStart(2, "0"));
  setTextWithMotion($("#topology-readout-title"), node.label);
  setTextWithMotion($("#topology-readout-meta"), node.meta);
  setTextWithMotion($("#topology-readout-state"), topologyNodeState(button));
  if (focus) {
    const mobile = window.matchMedia("(max-width: 700px)").matches;
    if (mobile) {
      button.scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth", block: "center" });
    } else {
      viewport.scrollTo({
        left: Math.max(0, button.offsetLeft - (viewport.clientWidth - button.offsetWidth) / 2),
        behavior: prefersReducedMotion() ? "auto" : "smooth",
      });
    }
  }
}

function bindTopologyInteractions() {
  const viewport = $("#research-topology");
  if (!viewport || !state.topologyContext) return;
  const buttons = [...viewport.querySelectorAll("[data-step]")];
  buttons.forEach((button, index) => {
    button.addEventListener("click", () => {
      state.topologySelection = button.dataset.step;
      selectTopologyNode(button.dataset.step);
    });
    button.addEventListener("keydown", (event) => {
      const forward = ["ArrowRight", "ArrowDown"].includes(event.key);
      const backward = ["ArrowLeft", "ArrowUp"].includes(event.key);
      if (!forward && !backward) return;
      event.preventDefault();
      const nextIndex = Math.min(buttons.length - 1, Math.max(0, index + (forward ? 1 : -1)));
      const next = buttons[nextIndex];
      next.focus();
      state.topologySelection = next.dataset.step;
      selectTopologyNode(next.dataset.step);
    });
  });
  $("#topology-current-button").onclick = () => {
    state.topologySelection = state.topologyContext.currentStep;
    selectTopologyNode(state.topologyContext.currentStep, { focus: true });
  };
}

function clearTerminal() {
  $("#terminal").innerHTML = "";
  $("#terminal").hidden = true;
  $("#terminal-empty").hidden = false;
  state.logCount = 0;
  $("#log-count").textContent = "0 lines";
}

function appendLogs(logs) {
  if (!logs.length) return;
  const terminal = $("#terminal");
  $("#terminal-empty").hidden = true;
  terminal.hidden = false;
  const nearBottom = terminal.scrollHeight - terminal.scrollTop - terminal.clientHeight < 80;
  const fragment = document.createDocumentFragment();
  logs.forEach((log) => {
    if (terminal.querySelector(`[data-seq="${log.seq}"]`)) return;
    const line = document.createElement("div");
    line.className = `log-line${log.stream === "system" ? " is-system" : ""}`;
    line.dataset.seq = log.seq;
    line.innerHTML = `<span class="log-time">${formatTime(log.time)}</span><span class="log-seq">${String(log.seq).padStart(2, "0")}</span><span class="log-text">${escapeHtml(log.text)}</span>`;
    fragment.append(line);
    state.logCount += 1;
  });
  terminal.append(fragment);
  $("#log-count").textContent = `${state.logCount} lines`;
  if (nearBottom) terminal.scrollTop = terminal.scrollHeight;
}

function renderArtifacts(files) {
  state.artifacts = files;
  $("#artifact-count").textContent = files.length;
  const container = $("#artifact-list");
  if (!files.length) {
    container.innerHTML = '<div class="small-empty">생성된 아이디어, 플롯, PDF가 이곳에 표시됩니다.</div>';
    return;
  }
  container.innerHTML = files
    .map((file, index) => {
      const extension = file.name.split(".").pop();
      return `<button class="artifact-item" type="button" data-artifact-index="${index}"><span class="file-mark">${escapeHtml(extension)}</span><span class="artifact-copy"><strong>${escapeHtml(file.name)}</strong><span>${formatBytes(file.size)} · ${artifactKindLabel(file.kind)}</span></span><span class="download-mark">읽기</span></button>`;
    })
    .join("");
  $$('[data-artifact-index]').forEach((button) => button.addEventListener("click", () => openArtifact(files[Number(button.dataset.artifactIndex)])));
}

function formatResultNumber(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  const number = Number(value);
  if (number === 0) return "0";
  if (Math.abs(number) < 0.001) return number.toExponential(2);
  return number.toFixed(4);
}

function renderExperimentSummary(job) {
  const section = $("#experiment-summary");
  const content = $("#experiment-summary-content");
  const summary = job.result_summary;
  if (job.kind !== "experiment" || !summary) {
    section.hidden = true;
    return;
  }

  const scope = summary.scope === "complete" ? "완료 결과" : "중간 결과";
  const scopeElement = $("#experiment-summary-scope");
  scopeElement.textContent = scope;
  scopeElement.className = `summary-scope is-${summary.scope}`;
  const provenanceLabel = summary.outcome_provenance === "simulated" ? "시뮬레이션" : summary.outcome_provenance;
  const verdictLabels = {
    adaptive_better: "적응형 우위",
    fixed_better: "고정형 우위",
    inconclusive: "판단 보류",
  };
  const moduleLabels = {
    beneficial: "효과 있음",
    "dataset-dependent": "데이터셋 의존",
    neutral: "차이 없음",
    harmful: "악화",
    unknown: "미분류",
  };
  const comparisons = summary.comparisons || [];
  const calibratedCoverage = comparisons.map((row) => row.adaptive_coverage).filter((value) => Number.isFinite(value));
  const uncalibratedCoverage = comparisons.map((row) => row.uncalibrated_coverage).filter((value) => Number.isFinite(value));
  const coverageCopy = calibratedCoverage.length && uncalibratedCoverage.length
    ? `보정 적용 ${(Math.min(...calibratedCoverage) * 100).toFixed(1)}–${(Math.max(...calibratedCoverage) * 100).toFixed(1)}% · 미적용 ${(Math.min(...uncalibratedCoverage) * 100).toFixed(1)}–${(Math.max(...uncalibratedCoverage) * 100).toFixed(1)}%`
    : "보정 유무에 따른 coverage를 비교했습니다.";
  const tableRows = comparisons.map((row) => `<tr>
    <th scope="row">${escapeHtml(row.dataset_label)}</th>
    <td>${formatResultNumber(row.adaptive_mean)} <small>±${formatResultNumber(row.adaptive_ci95)}</small></td>
    <td>${formatResultNumber(row.fixed_mean)} <small>±${formatResultNumber(row.fixed_ci95)}</small></td>
    <td class="delta-value">${row.delta_fixed_minus_adaptive >= 0 ? "+" : ""}${formatResultNumber(row.delta_fixed_minus_adaptive)} <small>±${formatResultNumber(row.delta_ci95)}</small></td>
    <td><span class="result-verdict is-${escapeHtml(row.verdict)}">${escapeHtml(verdictLabels[row.verdict] || row.verdict)}</span></td>
  </tr>`).join("");
  const modules = (summary.modules || []).map((module) => `<li><span>${escapeHtml(module.label)}</span><strong class="is-${escapeHtml(module.classification)}">${escapeHtml(moduleLabels[module.classification] || module.classification)}</strong></li>`).join("");
  const plots = (summary.plots || []).map((plot) => `<button class="result-plot" type="button" data-result-plot="${escapeHtml(plot.path)}">
    <img src="${escapeHtml(plot.view_url)}" alt="${escapeHtml(plot.name)}" loading="lazy" />
    <span><strong>${plot.name.endsWith("primary_metric.png") ? "핵심 지표 비교" : "제약 충족 대시보드"}</strong><small>${escapeHtml(plot.name)}</small></span>
  </button>`).join("");
  const limitations = (summary.limitations || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("");

  content.innerHTML = `<div class="result-one-line">
    <span>한줄 결론</span>
    <strong>${escapeHtml(summary.one_line_conclusion || summary.headline)}</strong>
  </div>
  <div class="result-brief-lead">
    <article class="result-verdict-card">
      <span class="result-kicker">CURRENT VERDICT</span>
      <h3>${escapeHtml(summary.headline)}</h3>
      <p>${escapeHtml(summary.interpretation)}</p>
      <div class="result-facts">
        <span><strong>${summary.successful_seed_count}/${summary.planned_seed_count}</strong> seeds</span>
        <span><strong>${comparisons.length}</strong> datasets</span>
        <span><strong>${escapeHtml(provenanceLabel)}</strong> outcomes</span>
      </div>
    </article>
    <aside class="calibration-callout">
      <span>STRONGEST SIGNAL</span>
      <strong>Conformal 보정은 필수에 가깝습니다.</strong>
      <p>${escapeHtml(coverageCopy)}</p>
    </aside>
  </div>
  <div class="result-section">
    <div class="result-section-heading"><div><span>PRIMARY COMPARISON</span><h3>적응형 vs 고정형 라우팅</h3></div><p>${escapeHtml(summary.primary_metric)} · 낮을수록 좋음</p></div>
    <div class="result-table-scroll"><table class="result-table"><thead><tr><th>데이터셋</th><th>적응형 RCCOR</th><th>고정형 RCCOR</th><th>Δ 고정−적응형</th><th>95% CI 판단</th></tr></thead><tbody>${tableRows}</tbody></table></div>
  </div>
  <div class="result-detail-grid">
    <section class="result-section module-section"><div class="result-section-heading"><div><span>COMPONENT READOUT</span><h3>구성요소 기여</h3></div></div><ul class="module-readout">${modules}</ul></section>
    <section class="result-section evidence-section"><div class="result-section-heading"><div><span>ACTUAL OUTPUT</span><h3>대표 플롯</h3></div></div><div class="result-plots">${plots || '<p class="result-empty">표시할 플롯이 없습니다.</p>'}</div></section>
  </div>
  <footer class="result-caveats">
    <div><span>해석 한계</span><ul>${limitations}</ul></div>
    <code>${escapeHtml(summary.source_directory)}</code>
  </footer>`;
  section.hidden = false;
  $$('[data-result-plot]').forEach((button) => button.addEventListener("click", () => {
    const artifact = state.artifacts.find((file) => file.path === button.dataset.resultPlot);
    if (artifact) openArtifact(artifact);
  }));
}

function ideaField(idea, ...keys) {
  for (const key of keys) {
    if (idea[key] !== undefined && idea[key] !== null) return idea[key];
  }
  return "";
}

async function prepareExperiment(ideaPath, ideaIndex) {
  if (!state.ideas.some((item) => item.path === ideaPath)) await loadIdeas();
  const file = state.ideas.find((item) => item.path === ideaPath);
  if (!file) return toast("이 아이디어 파일을 실험 목록에서 찾지 못했습니다.", true);

  $("#idea-file").value = ideaPath;
  updateIdeaOptions();
  $("#idea-index").value = String(ideaIndex);
  setMode("experiment");
  saveDraft();
  $("#workspace").scrollIntoView({ behavior: "smooth", block: "start" });
  toast("선택한 후보를 전체 연구 입력에 넣었습니다.");
}

async function renderIdeaSummary(job) {
  const section = $("#idea-summary");
  const list = $("#idea-candidate-list");
  if (job.kind !== "ideation" || job.status !== "completed") {
    section.hidden = true;
    return;
  }

  const files = job.files || [];
  const recommendationFile = files.find((file) => file.name.endsWith(".recommendations.json"));
  const ideaFile = files.find((file) => file.kind === "json" && file.name !== "job.json" && !file.name.endsWith(".recommendations.json"));
  if (!ideaFile) {
    section.hidden = true;
    return;
  }

  section.hidden = false;
  const summarySignature = `${job.id}:${ideaFile.size}:${recommendationFile?.size || 0}`;
  if (state.ideaSummaryJob === summarySignature) return;
  state.ideaSummaryJob = summarySignature;
  list.innerHTML = '<div class="idea-summary-loading">후보 정리본을 불러오는 중입니다…</div>';

  try {
    const [preview, recommendationPreview] = await Promise.all([
      api(ideaFile.preview_url),
      recommendationFile ? api(recommendationFile.preview_url) : Promise.resolve(null),
    ]);
    if (state.selectedJob !== job.id) return;
    const ideas = JSON.parse(preview.content);
    if (!Array.isArray(ideas) || !ideas.length) throw new Error("후보 배열이 비어 있습니다.");
    const recommendation = recommendationPreview ? JSON.parse(recommendationPreview.content) : null;
    const assessments = new Map(
      (Array.isArray(recommendation?.assessments) ? recommendation.assessments : [])
        .map((assessment) => [Number(assessment.idea_index), assessment]),
    );
    const recommendedIndex = Number.isInteger(recommendation?.recommended_index)
      ? recommendation.recommended_index
      : null;
    const recommendedIdea = recommendedIndex === null ? null : ideas[recommendedIndex];
    if (recommendedIdea) {
      const recommendedTitle = ideaField(recommendedIdea, "Title", "title", "Name") || `후보 ${recommendedIndex + 1}`;
      $("#idea-decision-label").textContent = "실험 전 추천 · 낮은 신뢰도";
      $("#idea-decision-title").textContent = `먼저 검증할 후보: ${recommendedTitle}`;
      $("#idea-decision-copy").textContent = recommendation.summary || "제안서의 신규성·반증 가능성·실행 가능성·실험 엄밀성을 비교한 우선순위입니다.";
    } else {
      $("#idea-decision-label").textContent = "현재 결론";
      $("#idea-decision-title").textContent = "비교 가능한 가설 후보를 확보했습니다.";
      $("#idea-decision-copy").textContent = "추천 평가는 아직 없으며, 실험 전이라 최종 연구 결론은 정하지 않습니다.";
    }
    $("#idea-summary-count").textContent = ideas.length;
    list.innerHTML = ideas.map((idea, index) => {
      const title = ideaField(idea, "Title", "title", "Name") || `후보 ${index + 1}`;
      const name = ideaField(idea, "Name", "name") || `candidate-${index + 1}`;
      const hypothesis = ideaField(idea, "Short Hypothesis", "Short_Hypothesis", "Hypothesis", "Abstract") || "가설 요약이 없습니다.";
      const experiments = ideaField(idea, "Experiments", "experiments");
      const risks = ideaField(idea, "Risk Factors and Limitations", "Risk_Factors_and_Limitations", "Risks", "risks");
      const experimentCount = Array.isArray(experiments) ? experiments.length : experiments ? 1 : 0;
      const riskCount = Array.isArray(risks) ? risks.length : risks ? 1 : 0;
      const assessment = assessments.get(index);
      const axes = assessment?.scores || {};
      const isRecommended = recommendedIndex === index;
      const rating = assessment ? `<div class="idea-candidate-rating" aria-label="실험 전 추천도 ${assessment.score}점">
          <div class="idea-rating-head"><span>실험 전</span><strong>${escapeHtml(assessment.score)}<small>/100</small></strong></div>
          <em>${escapeHtml(assessment.verdict)}</em>
          <div class="idea-rating-axes" aria-label="추천도 세부 기준">
            <span title="신규성">신규 ${escapeHtml(axes.novelty)}</span><span title="반증 가능성">반증 ${escapeHtml(axes.falsifiability)}</span>
            <span title="실행 가능성">실행 ${escapeHtml(axes.feasibility)}</span><span title="실험 엄밀성">엄밀 ${escapeHtml(axes.experimental_rigor)}</span>
          </div>
        </div>` : `<div class="idea-candidate-rating is-pending"><span>추천 평가 없음</span><p>제안서 비교 평가가 생성되지 않았습니다.</p></div>`;
      const rationale = assessment ? `<p class="idea-recommendation-rationale"><strong>추천 근거</strong>${escapeHtml(assessment.rationale)}</p>` : "";
      return `<article class="idea-candidate${isRecommended ? " is-recommended" : ""}" data-idea-card="${index}">
        <div class="idea-candidate-index"><span>GENERATED ORDER</span></div>
        <div class="idea-candidate-copy"><span>${escapeHtml(name)}${isRecommended ? " · PRIORITY" : ""}</span><h3>${escapeHtml(title)}</h3><p>${escapeHtml(hypothesis)}</p><div class="idea-candidate-facts"><span>${experimentCount}개 실험 계획</span><span>${riskCount}개 위험 요인</span></div>${rationale}</div>
        ${rating}
        <div class="idea-candidate-actions">
          <button class="secondary-button idea-preview-button" type="button" data-idea-preview="${index}">크게 보기<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M6 3h7v7M13 3 5 11M11 13H3V5" /></svg></button>
          <button class="primary-button" type="button" data-idea-run="${index}">이 후보로 실험</button>
        </div>
      </article>`;
    }).join("");
    $$('[data-idea-preview]').forEach((button) => button.addEventListener("click", () => openArtifact(ideaFile, Number(button.dataset.ideaPreview))));
    $$('[data-idea-card]').forEach((card) => card.addEventListener("click", (event) => {
      if (event.target.closest("button, a") || window.getSelection()?.toString()) return;
      openArtifact(ideaFile, Number(card.dataset.ideaCard));
    }));
    $$('[data-idea-run]').forEach((button) => button.addEventListener("click", () => prepareExperiment(ideaFile.path, Number(button.dataset.ideaRun))));
  } catch (error) {
    if (state.selectedJob !== job.id) return;
    list.innerHTML = `<div class="idea-summary-loading is-error">정리본을 읽지 못했습니다: ${escapeHtml(error.message)}</div>`;
  }
}

function artifactKindLabel(kind) {
  return { markdown: "문서", json: "구조화 결과", pdf: "논문", image: "그림", code: "소스", text: "기록" }[kind] || "파일";
}

function inlineMarkdown(value) {
  return escapeHtml(value)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
}

function renderMarkdownDocument(source) {
  const lines = source.replace(/\r\n/g, "\n").split("\n");
  const output = [];
  let paragraph = [];
  let listType = null;
  let inFence = false;
  let fence = [];
  const flushParagraph = () => {
    if (paragraph.length) output.push(`<p>${inlineMarkdown(paragraph.join(" "))}</p>`);
    paragraph = [];
  };
  const closeList = () => {
    if (listType) output.push(`</${listType}>`);
    listType = null;
  };
  for (const line of lines) {
    if (line.trim().startsWith("```")) {
      flushParagraph(); closeList();
      if (inFence) { output.push(`<pre><code>${escapeHtml(fence.join("\n"))}</code></pre>`); fence = []; }
      inFence = !inFence;
      continue;
    }
    if (inFence) { fence.push(line); continue; }
    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    const bullet = line.match(/^\s*[-*]\s+(.+)$/);
    const ordered = line.match(/^\s*\d+[.)]\s+(.+)$/);
    if (heading) {
      flushParagraph(); closeList();
      const level = Math.min(4, heading[1].length + 1);
      output.push(`<h${level}>${inlineMarkdown(heading[2])}</h${level}>`);
    } else if (bullet || ordered) {
      flushParagraph();
      const nextType = bullet ? "ul" : "ol";
      if (listType !== nextType) { closeList(); output.push(`<${nextType}>`); listType = nextType; }
      output.push(`<li>${inlineMarkdown((bullet || ordered)[1])}</li>`);
    } else if (/^\s*>/.test(line)) {
      flushParagraph(); closeList();
      output.push(`<blockquote>${inlineMarkdown(line.replace(/^\s*>\s?/, ""))}</blockquote>`);
    } else if (!line.trim()) {
      flushParagraph(); closeList();
    } else {
      paragraph.push(line.trim());
    }
  }
  if (inFence && fence.length) output.push(`<pre><code>${escapeHtml(fence.join("\n"))}</code></pre>`);
  flushParagraph(); closeList();
  return output.join("");
}

function renderJsonDocument(content) {
  let data;
  try { data = JSON.parse(content); } catch (_) { return `<pre><code>${escapeHtml(content)}</code></pre>`; }
  const records = Array.isArray(data) ? data : [data];
  if (!records.length || !records.every((item) => item && typeof item === "object" && !Array.isArray(item))) {
    return `<pre><code>${escapeHtml(JSON.stringify(data, null, 2))}</code></pre>`;
  }
  const renderValue = (value) => {
    if (typeof value === "string") return renderMarkdownDocument(value);
    if (Array.isArray(value) && value.every((item) => typeof item === "string")) {
      return `<ol class="structured-list">${value.map((item) => `<li>${renderMarkdownDocument(item)}</li>`).join("")}</ol>`;
    }
    return `<pre><code>${escapeHtml(JSON.stringify(value, null, 2))}</code></pre>`;
  };
  return records.map((record, index) => {
    const title = record.Title || record.Name || record.title || `결과 ${index + 1}`;
    const entries = Object.entries(record).filter(([key]) => !["Title", "Name", "title"].includes(key));
    return `<section class="result-sheet" data-result-index="${index}"><header><span>${String(index + 1).padStart(2, "0")}</span><h3>${escapeHtml(title)}</h3></header>${entries.map(([key, value]) => {
      const rendered = renderValue(value);
      return `<section class="result-field"><h4>${escapeHtml(key.replaceAll("_", " "))}</h4><div>${rendered}</div></section>`;
    }).join("")}</section>`;
  }).join("");
}

function formatIdeaPreviewHeader(preview, focusIndex) {
  if (preview.kind !== "json" || !Number.isInteger(focusIndex)) return null;
  try {
    const data = JSON.parse(preview.content);
    const records = Array.isArray(data) ? data : [data];
    const record = records[focusIndex];
    if (!record || typeof record !== "object" || Array.isArray(record)) return null;
    const title = record.Title || record.Name || record.title;
    if (!title) return null;
    return { title: String(title), position: `${focusIndex + 1} / ${records.length}` };
  } catch (_) {
    return null;
  }
}

async function openArtifact(file, focusIndex = null) {
  const dialog = $("#artifact-viewer");
  const documentView = $("#artifact-document");
  $("#artifact-viewer-title").textContent = file.name;
  $("#reader-file-mark").textContent = file.name.split(".").pop().slice(0, 4).toUpperCase();
  $("#reader-meta").textContent = `${artifactKindLabel(file.kind)} · ${formatBytes(file.size)}`;
  $("#artifact-download").href = file.url;
  $("#reader-status").textContent = "산출물을 불러오는 중입니다…";
  $("#reader-status").hidden = false;
  documentView.hidden = true;
  documentView.innerHTML = "";
  if (!dialog.open) dialog.showModal();
  try {
    const preview = await api(file.preview_url);
    const ideaHeader = formatIdeaPreviewHeader(preview, focusIndex);
    if (ideaHeader) {
      $("#artifact-viewer-title").textContent = ideaHeader.title;
      $("#reader-meta").textContent = `아이디어 후보 ${ideaHeader.position} · ${artifactKindLabel(file.kind)} · ${formatBytes(file.size)}`;
    }
    if (preview.kind === "image") {
      documentView.innerHTML = `<figure class="artifact-figure"><img src="${escapeHtml(preview.view_url)}" alt="${escapeHtml(preview.name)}" /><figcaption>${escapeHtml(preview.name)}</figcaption></figure>`;
    } else if (preview.kind === "pdf") {
      documentView.innerHTML = `<iframe class="pdf-reader" src="${escapeHtml(preview.view_url)}#view=FitH" title="${escapeHtml(preview.name)}"></iframe>`;
    } else if (preview.kind === "markdown") {
      documentView.innerHTML = renderMarkdownDocument(preview.content);
    } else if (preview.kind === "json") {
      documentView.innerHTML = renderJsonDocument(preview.content);
    } else {
      documentView.innerHTML = `<pre><code>${escapeHtml(preview.content)}</code></pre>`;
    }
    if (preview.truncated) toast("큰 파일이라 앞부분 2MB만 표시했습니다.");
    $("#reader-status").hidden = true;
    documentView.hidden = false;
    documentView.scrollTop = 0;
    if (Number.isInteger(focusIndex)) {
      window.requestAnimationFrame(() => {
        const target = documentView.querySelector(`[data-result-index="${focusIndex}"]`);
        if (target) {
          const targetTop = documentView.scrollTop + target.getBoundingClientRect().top - documentView.getBoundingClientRect().top;
          documentView.scrollTo({ top: Math.max(0, targetTop - 20), behavior: "smooth" });
        }
      });
    }
  } catch (error) {
    $("#reader-status").textContent = error.message;
  }
}

function startElapsed(startedAt, finishedAt) {
  if (state.elapsedTimer) window.clearInterval(state.elapsedTimer);
  const update = () => {
    if (!startedAt) return ($("#elapsed-time").textContent = "00:00:00");
    const end = finishedAt ? new Date(finishedAt) : new Date();
    const seconds = Math.max(0, Math.floor((end - new Date(startedAt)) / 1000));
    const hours = String(Math.floor(seconds / 3600)).padStart(2, "0");
    const minutes = String(Math.floor((seconds % 3600) / 60)).padStart(2, "0");
    $("#elapsed-time").textContent = `${hours}:${minutes}:${String(seconds % 60).padStart(2, "0")}`;
  };
  update();
  if (!finishedAt) state.elapsedTimer = window.setInterval(update, 1000);
}

function formatTime(value) { return new Date(value).toLocaleTimeString("ko-KR", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" }); }
function formatDate(value) { return new Date(value).toLocaleString("ko-KR", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }); }
function formatBytes(bytes) { if (bytes < 1024) return `${bytes} B`; if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`; return `${(bytes / 1048576).toFixed(1)} MB`; }

async function submitIdeation(event) {
  event.preventDefault();
  const button = event.submitter;
  button.disabled = true;
  try {
    const job = await api("/api/jobs/ideation", {
      method: "POST",
      body: JSON.stringify({
        title: $("#topic-title").value.trim(),
        keywords: $("#topic-keywords").value.trim(),
        abstract: $("#topic-abstract").value.trim(),
        generations: Number($("#generation-count").value),
        reflections: Number($("#reflection-count").value),
      }),
    });
    toast("아이디어 탐색을 시작했습니다.");
    await loadJobs(false);
    await selectJob(job.id);
    $("#live-observation").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
  }
}

async function submitExperiment(event) {
  event.preventDefault();
  const button = event.submitter;
  button.disabled = true;
  try {
    const job = await api("/api/jobs/experiment", {
      method: "POST",
      body: JSON.stringify({
        idea_path: $("#idea-file").value,
        idea_index: Number($("#idea-index").value),
        writeup: $("#include-writeup").checked,
        review: $("#include-review").checked,
        citation_rounds: Number($("#citation-rounds").value),
      }),
    });
    toast("전체 연구 실행을 시작했습니다.");
    await loadJobs(false);
    await selectJob(job.id);
    $("#live-observation").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
  }
}

async function stopSelectedJob() {
  if (!state.selectedJob || !window.confirm("현재 연구 실행을 중지할까요? 생성된 파일은 보존됩니다.")) return;
  try {
    await api(`/api/jobs/${state.selectedJob}/stop`, { method: "POST" });
    toast("중지 신호를 보냈습니다.");
  } catch (error) {
    toast(error.message, true);
  }
}

async function restartSelectedJob() {
  if (!state.selectedJob) return;
  const button = $("#restart-button");
  button.disabled = true;
  try {
    const job = await api(`/api/jobs/${state.selectedJob}/restart`, { method: "POST" });
    toast("마지막 완료 체크포인트에서 연구를 재시작했습니다.");
    await loadJobs(false);
    await selectJob(job.id);
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
  }
}

async function refreshAll() {
  try {
    await Promise.all([loadHealth(), loadIdeas(), loadJobs(false)]);
    if (state.selectedJob) {
      const job = await api(`/api/jobs/${state.selectedJob}`);
      renderJob(job, true);
    }
    toast("최신 상태를 불러왔습니다.");
  } catch (error) {
    toast(error.message, true);
  }
}

function bindEvents() {
  $("#ideation-tab").addEventListener("click", () => setMode("ideation"));
  $("#experiment-tab").addEventListener("click", () => setMode("experiment"));
  $("#idea-file").addEventListener("change", updateIdeaOptions);
  [...$("#ideation-form").elements, ...$("#experiment-form").elements].forEach((field) => {
    const syncDraftAndPreview = () => {
      saveDraft();
      updateLaunchPreviews();
    };
    field.addEventListener("input", syncDraftAndPreview);
    field.addEventListener("change", syncDraftAndPreview);
  });
  $("#ideation-form").addEventListener("submit", submitIdeation);
  $("#experiment-form").addEventListener("submit", submitExperiment);
  $("#stop-button").addEventListener("click", stopSelectedJob);
  $("#restart-button").addEventListener("click", restartSelectedJob);
  $("#quick-stop-button").addEventListener("click", stopSelectedJob);
  $("#refresh-button").addEventListener("click", refreshAll);
  $("#idea-summary-button").addEventListener("click", () => $("#idea-summary").scrollIntoView({ behavior: "smooth", block: "start" }));
  $("#result-summary-button").addEventListener("click", () => $("#experiment-summary").scrollIntoView({ behavior: "smooth", block: "start" }));
  $("#artifact-close").addEventListener("click", () => $("#artifact-viewer").close());
  $("#artifact-viewer").addEventListener("click", (event) => {
    if (event.target === $("#artifact-viewer")) $("#artifact-viewer").close();
  });
  $$("[data-scroll]").forEach((button) => button.addEventListener("click", () => {
    $$(".nav-item").forEach((item) => item.classList.toggle("is-active", item === button));
    document.getElementById(button.dataset.scroll).scrollIntoView({ behavior: "smooth", block: "start" });
  }));
}

async function initialize() {
  bindEvents();
  const savedState = loadWorkbenchState();
  restoreDraft(["topic-title", "topic-abstract", "topic-keywords", "generation-count", "reflection-count", "include-writeup", "include-review", "citation-rounds"]);
  setMode(savedState.mode === "experiment" ? "experiment" : "ideation");
  updateLaunchPreviews();
  renderTopology({ kind: "ideation", stage: "queued", topology_step: "intake", status: "queued", model: "gpt-5.6-sol", reasoning_effort: "xhigh" });
  try {
    await Promise.all([loadHealth(), loadIdeas(), loadJobs()]);
  } catch (error) {
    toast(error.message, true);
  }
}

initialize();
