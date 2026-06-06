const state = {
  sessionId: "",
  running: false,
};

const els = {
  form: document.querySelector("#chatForm"),
  input: document.querySelector("#queryInput"),
  sendButton: document.querySelector("#sendButton"),
  newSessionButton: document.querySelector("#newSessionButton"),
  messages: document.querySelector("#messages"),
  emptyState: document.querySelector("#emptyState"),
  sessionList: document.querySelector("#sessionList"),
  sessionStatus: document.querySelector("#sessionStatus"),
  runStatus: document.querySelector("#runStatus"),
};

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatMultiline(value) {
  return escapeHtml(value).replace(/\n/g, "<br>");
}

function scrollToBottom() {
  els.messages.scrollTop = els.messages.scrollHeight;
}

function setRunning(running) {
  state.running = running;
  els.sendButton.disabled = running;
  els.input.disabled = running;
  els.runStatus.textContent = running ? "运行中" : "就绪";
  els.runStatus.classList.toggle("running", running);
}

function updateSessionStatus() {
  els.sessionStatus.textContent = state.sessionId ? state.sessionId : "未连接会话";
}

function ensureMessagesVisible() {
  if (els.emptyState) {
    els.emptyState.remove();
    els.emptyState = null;
  }
}

function appendUserMessage(text) {
  ensureMessagesVisible();
  const item = document.createElement("article");
  item.className = "message user";
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;
  item.appendChild(bubble);
  els.messages.appendChild(item);
  scrollToBottom();
}

function appendAssistantShell({ history = false } = {}) {
  ensureMessagesVisible();
  const item = document.createElement("article");
  item.className = "message assistant";

  const bubble = document.createElement("div");
  bubble.className = "bubble";

  const meta = document.createElement("div");
  meta.className = "message-meta";
  meta.textContent = history ? "历史回答" : "Agent 过程";

  const timeline = document.createElement("div");
  timeline.className = "timeline";

  const answer = document.createElement("div");
  answer.className = "answer pending";
  answer.textContent = history ? "" : "正在分析...";

  bubble.append(meta, timeline, answer);
  item.appendChild(bubble);
  els.messages.appendChild(item);
  scrollToBottom();
  return { item, bubble, meta, timeline, answer };
}

function agentName(value) {
  const names = {
    session_manager: "Session",
    coordinator_agent: "Coordinator",
    data_analysis_agent: "SQL",
    visualization_agent: "Visualization",
    nlp_agent: "NLP",
    decision_agent: "Decision",
  };
  return names[value] || String(value || "Agent");
}

function addTrace(shell, trace) {
  const item = document.createElement("div");
  item.className = "trace-item";

  const dot = document.createElement("span");
  dot.className = "trace-dot";

  const body = document.createElement("div");
  const title = document.createElement("strong");
  title.textContent = `${agentName(trace.agent)} · ${trace.step || trace.kind || "event"}`;
  body.appendChild(title);

  const summary = trace.summary || trace.title || "";
  if (summary) {
    const p = document.createElement("p");
    p.textContent = summary;
    body.appendChild(p);
  }

  const sqls = (trace.metadata && trace.metadata.sqls) || [];
  sqls.slice(0, 2).forEach((sql) => {
    const pre = document.createElement("pre");
    pre.textContent = sql;
    body.appendChild(pre);
  });

  item.append(dot, body);
  shell.timeline.appendChild(item);
  scrollToBottom();
}

function showError(shell, message) {
  shell.answer.classList.remove("pending");
  shell.answer.classList.add("error");
  shell.answer.textContent = message || "请求失败。";
  scrollToBottom();
}

function handleWebEvent(event, shell, userQuery) {
  if (event.session_id) {
    state.sessionId = event.session_id;
    updateSessionStatus();
  }

  if (event.type === "turn.started") {
    const resolved = event.data && event.data.resolved_task;
    if (resolved && resolved !== userQuery) {
      shell.meta.textContent = `Agent 过程 · ${resolved}`;
    }
    return;
  }

  if (event.type === "trace.event") {
    addTrace(shell, event.data.trace || {});
    return;
  }

  if (event.type === "answer.final") {
    shell.answer.classList.remove("pending");
    shell.answer.innerHTML = formatMultiline(event.data.final_answer || "（无回答）");
    scrollToBottom();
    return;
  }

  if (event.type === "turn.completed") {
    shell.meta.textContent = `已保存 · Turn ${event.turn_id || ""}`.trim();
    return;
  }

  if (event.type === "turn.error") {
    const data = event.data || {};
    showError(shell, `${data.error_type || "Error"}: ${data.message || "未知错误"}`);
  }
}

function parseSseBlock(block) {
  const dataLines = [];
  block.split("\n").forEach((line) => {
    if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trimStart());
    }
  });
  if (!dataLines.length) {
    return null;
  }
  return JSON.parse(dataLines.join("\n"));
}

async function readSseStream(response, onEvent) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    buffer = buffer.replace(/\r\n/g, "\n");

    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      const block = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      if (block.trim()) {
        onEvent(parseSseBlock(block));
      }
      boundary = buffer.indexOf("\n\n");
    }
  }
}

async function sendTurn(query) {
  appendUserMessage(query);
  const shell = appendAssistantShell();
  setRunning(true);

  try {
    const response = await fetch("/api/turn", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query,
        session_id: state.sessionId || null,
        new_session: !state.sessionId,
      }),
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.message || response.statusText);
    }

    await readSseStream(response, (event) => {
      if (event) {
        handleWebEvent(event, shell, query);
      }
    });
    await loadSessions();
  } catch (error) {
    showError(shell, error.message);
  } finally {
    setRunning(false);
    els.input.focus();
  }
}

function renderSessionList(sessions) {
  els.sessionList.textContent = "";
  if (!sessions.length) {
    const empty = document.createElement("div");
    empty.className = "session-meta";
    empty.textContent = "暂无 session";
    els.sessionList.appendChild(empty);
    return;
  }

  sessions.forEach((session) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "session-item";
    button.classList.toggle("active", session.session_id === state.sessionId);

    const title = document.createElement("div");
    title.className = "session-title";
    title.textContent = session.title || session.session_id;

    const meta = document.createElement("div");
    meta.className = "session-meta";
    meta.textContent = `${session.turn_count || 0} 轮 · ${session.updated_at || ""}`;

    button.append(title, meta);
    button.addEventListener("click", () => loadSession(session.session_id));
    els.sessionList.appendChild(button);
  });
}

async function loadSessions() {
  const response = await fetch("/api/sessions");
  const data = await response.json();
  renderSessionList(data.sessions || []);
}

function renderLoadedSession(session) {
  state.sessionId = session.session_id || "";
  updateSessionStatus();
  els.messages.textContent = "";
  els.emptyState = null;

  (session.turns || []).forEach((turn) => {
    appendUserMessage(turn.user_query || "");
    const shell = appendAssistantShell({ history: true });
    (turn.trace_events || []).slice(0, 4).forEach((trace) => addTrace(shell, trace));
    shell.answer.classList.remove("pending");
    shell.answer.innerHTML = formatMultiline(turn.final_answer || "（无回答）");
    shell.meta.textContent = `历史回答 · Turn ${turn.turn_id || ""}`.trim();
  });
  scrollToBottom();
}

async function loadSession(sessionId) {
  if (!sessionId || state.running) {
    return;
  }
  const response = await fetch(`/api/session?id=${encodeURIComponent(sessionId)}`);
  if (!response.ok) {
    return;
  }
  const data = await response.json();
  renderLoadedSession(data.session || {});
  await loadSessions();
}

function resetSession() {
  if (state.running) {
    return;
  }
  state.sessionId = "";
  updateSessionStatus();
  els.messages.textContent = "";
  const empty = document.createElement("div");
  empty.id = "emptyState";
  empty.className = "empty-state";
  empty.innerHTML = `
    <strong>开始一个 session</strong>
    <div class="prompt-row">
      <button type="button" class="prompt-chip">2017年哪个州的销售额最高？</button>
      <button type="button" class="prompt-chip">casa_conforto 类产品口碑如何？</button>
      <button type="button" class="prompt-chip">给我一个入行该品类的决策建议</button>
    </div>
  `;
  els.messages.appendChild(empty);
  els.emptyState = empty;
  bindPromptChips();
  loadSessions();
  els.input.focus();
}

function bindPromptChips() {
  document.querySelectorAll(".prompt-chip").forEach((button) => {
    button.addEventListener("click", () => {
      els.input.value = button.textContent.trim();
      autosizeInput();
      els.input.focus();
    });
  });
}

function autosizeInput() {
  els.input.style.height = "auto";
  els.input.style.height = `${Math.min(els.input.scrollHeight, 180)}px`;
}

els.form.addEventListener("submit", (event) => {
  event.preventDefault();
  if (state.running) {
    return;
  }
  const query = els.input.value.trim();
  if (!query) {
    return;
  }
  els.input.value = "";
  autosizeInput();
  sendTurn(query);
});

els.input.addEventListener("input", autosizeInput);
els.newSessionButton.addEventListener("click", resetSession);
bindPromptChips();
updateSessionStatus();
loadSessions();
