/**
 * LLM Council Frontend (Alt UI)
 * Same backend endpoints, different layout/UX.
 */

// --------------------
// Config
// --------------------
const API_BASE = window.location.origin;
const ENDPOINTS = {
  health: `${API_BASE}/api/health`,
  status: `${API_BASE}/api/status`,
  queryStream: `${API_BASE}/api/council/query/stream`,
};

// --------------------
// State
// --------------------
const state = {
  theme: localStorage.getItem("theme") || "dark",
  nodes: [],
  isProcessing: false,
  lastSession: null,
  activeOpinionIndex: 0,
};

// --------------------
// DOM
// --------------------
const el = {
  themeToggle: document.getElementById("themeToggle"),
  healthBtn: document.getElementById("healthBtn"),
  healthDot: document.getElementById("healthDot"),
  healthModal: document.getElementById("healthModal"),
  modalOverlay: document.getElementById("modalOverlay"),
  modalClose: document.getElementById("modalClose"),
  healthContent: document.getElementById("healthContent"),

  queryInput: document.getElementById("queryInput"),
  submitBtn: document.getElementById("submitBtn"),
  submitLabel: document.getElementById("submitLabel"),
  submitSpinner: document.getElementById("submitSpinner"),

  modelBadges: document.getElementById("modelBadges"),
  sessionMeta: document.getElementById("sessionMeta"),

  s1Status: document.getElementById("s1Status"),
  s2Status: document.getElementById("s2Status"),
  s3Status: document.getElementById("s3Status"),
  doneStatus: document.getElementById("doneStatus"),
  timeline: document.getElementById("timeline"),

  opinionTabs: document.getElementById("opinionTabs"),
  opinionsContent: document.getElementById("opinionsContent"),

  rankingsGrid: document.getElementById("rankingsGrid"),
  reviewsDetails: document.getElementById("reviewsDetails"),
  reviewsContent: document.getElementById("reviewsContent"),

  chairmanContent: document.getElementById("chairmanContent"),

  inspectBtn: document.getElementById("inspectBtn"),
  drawer: document.getElementById("drawer"),
  drawerClose: document.getElementById("drawerClose"),
  inspectJson: document.getElementById("inspectJson"),
};

// --------------------
// Theme
// --------------------
function applyTheme() {
  document.documentElement.setAttribute("data-theme", state.theme);
}
function toggleTheme() {
  state.theme = state.theme === "dark" ? "light" : "dark";
  localStorage.setItem("theme", state.theme);
  applyTheme();
}

// --------------------
// API
// --------------------
async function apiGet(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`GET ${url} failed: ${r.status}`);
  return r.json();
}

async function streamCouncil(query, onUpdate) {
  const r = await fetch(ENDPOINTS.queryStream, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query }),
  });

  if (!r.ok || !r.body) throw new Error(`Stream failed: ${r.status}`);

  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buf += decoder.decode(value, { stream: true });

    const chunks = buf.split("\n\n");
    buf = chunks.pop() || "";

    for (const chunk of chunks) {
      const line = chunk.trim();
      if (!line.startsWith("data:")) continue;

      const payload = line.slice(5).trim();
      if (!payload) continue;

      const data = JSON.parse(payload);
      onUpdate(data);
    }
  }
}

// --------------------
// Render helpers
// --------------------
function escapeHtml(text) {
  if (!text) return "";
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function setProcessing(on) {
  state.isProcessing = on;
  el.submitBtn.disabled = on;
  el.submitSpinner.style.display = on ? "inline-block" : "none";
  el.submitLabel.textContent = on ? "Running…" : "Run Council";
}

function setTimeline(stage) {
  // stage enum: pending / first_opinions / review_ranking / chairman_synthesis / completed / error
  const steps = el.timeline.querySelectorAll(".step");

  // reset
  steps.forEach(s => s.classList.remove("active", "done"));

  const mark = (selector, mode) => {
    const node = el.timeline.querySelector(`.step[data-step="${selector}"]`);
    if (!node) return;
    node.classList.add(mode);
  };

  if (stage === "pending") {
    mark("pending", "active");
  } else if (stage === "first_opinions") {
    mark("pending", "done");
    mark("first_opinions", "active");
  } else if (stage === "review_ranking") {
    mark("pending", "done");
    mark("first_opinions", "done");
    mark("review_ranking", "active");
  } else if (stage === "chairman_synthesis") {
    mark("pending", "done");
    mark("first_opinions", "done");
    mark("review_ranking", "done");
    mark("completed", "active");
  } else if (stage === "completed") {
    mark("pending", "done");
    mark("first_opinions", "done");
    mark("review_ranking", "done");
    mark("completed", "done");
  }
}

function renderModelBadgesFromStatus(status) {
  const nodes = [...(status.council_members || []), status.chairman].filter(Boolean);
  state.nodes = nodes;

  el.modelBadges.innerHTML = nodes
    .filter(n => !n.is_chairman)
    .map(n => {
      const off = n.status !== "online";
      return `
        <span class="pill ${off ? "off" : ""}">
          <span class="p-dot"></span>${escapeHtml(n.model)}
        </span>
      `;
    })
    .join("");

  // system dot
  const allOnline = status.system_status === "operational";
  el.healthDot.style.background = allOnline ? "var(--good)" : "var(--warn)";
  el.healthDot.style.boxShadow = allOnline
    ? "0 0 0 3px rgba(71,209,140,.15)"
    : "0 0 0 3px rgba(247,184,75,.15)";
}

function renderHealthModal(data) {
  if (!data || !Array.isArray(data.nodes)) {
    el.healthContent.innerHTML = `<div class="empty">Unable to fetch health</div>`;
    return;
  }

  el.healthContent.innerHTML = data.nodes
    .map(n => {
      const s = n.status;
      const tagClass = s === "online" ? "on" : s === "busy" ? "busy" : "off";
      return `
        <div class="node">
          <div class="lefty">
            <div class="name">
              ${escapeHtml(n.name)}
              ${n.is_chairman ? `<span class="tag chair">chairman</span>` : ``}
              <span class="tag ${tagClass}">${escapeHtml(s)}</span>
            </div>
            <div class="sub">${escapeHtml(n.model)}</div>
            <div class="sub">${escapeHtml(n.host)}:${n.port}</div>
          </div>
          <div class="righty">${n.latency_ms ? `${n.latency_ms.toFixed(0)}ms` : `—`}</div>
        </div>
      `;
    })
    .join("");
}

function renderOpinions(opinions) {
  if (!opinions || opinions.length === 0) {
    el.opinionTabs.innerHTML = "";
    el.opinionsContent.innerHTML = `<div class="empty">No opinions yet.</div>`;
    return;
  }

  // tabs
  el.opinionTabs.innerHTML = opinions
    .map((op, i) => {
      const active = i === state.activeOpinionIndex ? "active" : "";
      const sec = (op.latency_ms / 1000).toFixed(1);
      return `
        <button class="tab ${active}" data-i="${i}">
          ${escapeHtml(op.llm_name)}
          <small>${escapeHtml(op.model)} • ${sec}s</small>
        </button>
      `;
    })
    .join("");

  // content
  const op = opinions[state.activeOpinionIndex] || opinions[0];
  el.opinionsContent.innerHTML = `
    <div class="pre">${escapeHtml(op.response)}</div>
    <hr class="sep" />
    <div class="meta">
      <span>Model: ${escapeHtml(op.model)}</span>
      <span>Latency: ${(op.latency_ms / 1000).toFixed(2)}s</span>
      ${op.token_count ? `<span>Tokens: ${op.token_count}</span>` : ``}
    </div>
  `;

  // handlers
  el.opinionTabs.querySelectorAll(".tab").forEach(btn => {
    btn.addEventListener("click", () => {
      state.activeOpinionIndex = Number(btn.dataset.i || 0);
      renderOpinions(opinions);
    });
  });
}

function renderRankings(rankings) {
  if (!rankings || Object.keys(rankings).length === 0) {
    el.rankingsGrid.innerHTML = `<div class="empty">No rankings yet.</div>`;
    return;
  }

  const entries = Object.entries(rankings).sort((a, b) => b[1] - a[1]);
  const max = Math.max(...entries.map(([, v]) => v));

  el.rankingsGrid.innerHTML = entries
    .map(([name, score]) => {
      const pct = max ? (score / max) * 100 : 0;
      return `
        <div class="rank-card">
          <div class="rank-top">
            <div class="rank-name">${escapeHtml(name)}</div>
            <div class="rank-score">${score.toFixed(1)}/10</div>
          </div>
          <div class="bar"><div class="fill" style="width:${pct.toFixed(0)}%"></div></div>
        </div>
      `;
    })
    .join("");
}

function renderReviews(reviews) {
  if (!reviews || reviews.length === 0) {
    el.reviewsContent.innerHTML = `<div class="empty">No reviews yet.</div>`;
    return;
  }

  // group by reviewer
  const grouped = {};
  for (const r of reviews) {
    grouped[r.reviewer_name] ||= [];
    grouped[r.reviewer_name].push(r);
  }

  el.reviewsContent.innerHTML = Object.entries(grouped)
    .map(([reviewer, list]) => {
      const items = list
        .map(r => {
          return `
            <div class="review">
              <h4>${escapeHtml(r.reviewed_name)} — ${r.score}/10</h4>
              <p class="mono">Accuracy: ${r.accuracy_score}/10 • Insight: ${r.insight_score}/10</p>
              <p>${escapeHtml(r.reasoning)}</p>
            </div>
          `;
        })
        .join("");

      return `
        <div style="margin-bottom:14px;">
          <div class="mono" style="color:var(--muted); margin-bottom:8px;">Reviewer: ${escapeHtml(reviewer)}</div>
          ${items}
        </div>
      `;
    })
    .join("");

  // auto-open details once there is content
  el.reviewsDetails.open = true;
}

function renderChairman(synthesis) {
  if (!synthesis) {
    el.chairmanContent.innerHTML = `<div class="empty">No synthesis yet.</div>`;
    return;
  }

  el.chairmanContent.innerHTML = `
    <div class="pre">${escapeHtml(synthesis.final_response)}</div>
    ${synthesis.reasoning_summary ? `
      <hr class="sep" />
      <div class="mono" style="color:var(--muted); margin-bottom:6px;">Reasoning</div>
      <div class="pre">${escapeHtml(synthesis.reasoning_summary)}</div>
    ` : ``}
    <hr class="sep" />
    <div class="meta">
      <span>Model: ${escapeHtml(synthesis.model)}</span>
      <span>Latency: ${(synthesis.latency_ms / 1000).toFixed(2)}s</span>
    </div>
  `;
}

function renderSessionMeta(session) {
  if (!session) {
    el.sessionMeta.innerHTML = "";
    return;
  }

  const total = session.total_latency_ms ? `${(session.total_latency_ms / 1000).toFixed(1)}s` : "—";
  const opinions = session.first_opinions?.length ?? 0;
  const reviews = session.review_results?.reviews?.length ?? 0;

  el.sessionMeta.innerHTML = `
    <span>Session: <span class="mono">${escapeHtml(session.session_id || "—")}</span></span>
    <span>Opinions: <span class="mono">${opinions}</span></span>
    <span>Reviews: <span class="mono">${reviews}</span></span>
    <span>Total: <span class="mono">${total}</span></span>
  `;
}

// --------------------
// Orchestration (UI updates from SSE)
// --------------------
function handleSessionUpdate(session) {
  state.lastSession = session;

  // Inspect drawer content
  el.inspectJson.textContent = JSON.stringify(session, null, 2);

  if (session.error) {
    // stream error payload
    el.s1Status.textContent = "Error";
    el.s2Status.textContent = "—";
    el.s3Status.textContent = "—";
    el.doneStatus.textContent = session.error;
    setProcessing(false);
    return;
  }

  const stage = session.stage;

  // statuses
  if (stage === "pending") {
    el.s1Status.textContent = "Running…";
    el.s2Status.textContent = "Waiting";
    el.s3Status.textContent = "Waiting";
    el.doneStatus.textContent = "—";
    setTimeline("pending");
  } else if (stage === "first_opinions") {
    el.s1Status.textContent = `${session.first_opinions?.length || 0} opinion(s)`;
    el.s2Status.textContent = "Running…";
    el.s3Status.textContent = "Waiting";
    el.doneStatus.textContent = "—";
    setTimeline("first_opinions");
    renderOpinions(session.first_opinions);
  } else if (stage === "review_ranking") {
    el.s1Status.textContent = `${session.first_opinions?.length || 0} opinion(s)`;
    el.s2Status.textContent = `${session.review_results?.reviews?.length || 0} review(s)`;
    el.s3Status.textContent = "Running…";
    el.doneStatus.textContent = "—";
    setTimeline("review_ranking");
    renderRankings(session.review_results?.rankings);
    renderReviews(session.review_results?.reviews);
  } else if (stage === "completed") {
    el.s1Status.textContent = `${session.first_opinions?.length || 0} opinion(s)`;
    el.s2Status.textContent = `${session.review_results?.reviews?.length || 0} review(s)`;
    el.s3Status.textContent = "Done";
    el.doneStatus.textContent = "Finished";
    setTimeline("completed");
    renderChairman(session.chairman_synthesis);
    renderSessionMeta(session);
    setProcessing(false);
  } else if (stage === "error") {
    el.doneStatus.textContent = session.error_message || "Unknown error";
    setProcessing(false);
  }

  // Keep meta updated
  renderSessionMeta(session);
}

// --------------------
// Events
// --------------------
async function onSubmit() {
  const q = el.queryInput.value.trim();
  if (!q || state.isProcessing) return;

  // reset UI blocks
  state.activeOpinionIndex = 0;
  el.opinionTabs.innerHTML = "";
  el.opinionsContent.innerHTML = `<div class="empty">Waiting…</div>`;
  el.rankingsGrid.innerHTML = `<div class="empty">Waiting…</div>`;
  el.reviewsContent.innerHTML = `<div class="empty">Waiting…</div>`;
  el.reviewsDetails.open = false;
  el.chairmanContent.innerHTML = `<div class="empty">Waiting…</div>`;
  el.sessionMeta.innerHTML = "";
  el.inspectJson.textContent = "{}";

  el.s1Status.textContent = "Starting…";
  el.s2Status.textContent = "Waiting";
  el.s3Status.textContent = "Waiting";
  el.doneStatus.textContent = "—";
  setTimeline("pending");

  setProcessing(true);

  try {
    await streamCouncil(q, handleSessionUpdate);
  } catch (err) {
    el.doneStatus.textContent = `Error: ${err.message || err}`;
    setProcessing(false);
  }
}

async function openHealth() {
  el.healthModal.classList.add("show");
  el.healthContent.innerHTML = `<div class="empty">Loading…</div>`;
  try {
    const data = await apiGet(ENDPOINTS.health);
    renderHealthModal(data);
  } catch (e) {
    el.healthContent.innerHTML = `<div class="empty">Failed: ${escapeHtml(e.message)}</div>`;
  }
}
function closeHealth() {
  el.healthModal.classList.remove("show");
}

function openDrawer() {
  el.drawer.classList.add("show");
}
function closeDrawer() {
  el.drawer.classList.remove("show");
}

// --------------------
// Init
// --------------------
async function init() {
  applyTheme();

  el.themeToggle.addEventListener("click", toggleTheme);
  el.healthBtn.addEventListener("click", openHealth);
  el.modalClose.addEventListener("click", closeHealth);
  el.modalOverlay.addEventListener("click", closeHealth);

  el.inspectBtn.addEventListener("click", openDrawer);
  el.drawerClose.addEventListener("click", closeDrawer);

  el.submitBtn.addEventListener("click", onSubmit);
  el.queryInput.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") onSubmit();
  });

  // initial status
  try {
    const status = await apiGet(`${API_BASE}/api/status`);
    renderModelBadgesFromStatus(status);
  } catch {
    el.modelBadges.innerHTML = `<span class="pill off"><span class="p-dot"></span>offline</span>`;
    el.healthDot.style.background = "var(--bad)";
    el.healthDot.style.boxShadow = "0 0 0 3px rgba(255,107,107,.15)";
  }
}

document.addEventListener("DOMContentLoaded", init);