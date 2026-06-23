// DebugMate frontend logic.
// Talks to the FastAPI backend at /api/chat, animates the agent's
// idle -> planning -> executing -> done lifecycle, and renders each
// planning step as a traceback-style "stack frame" (the signature UI element).

const API_BASE = ""; // same origin
const SESSION_KEY = "debugmate_session_id";

const chatWindow = document.getElementById("chat-window");
const composer = document.getElementById("composer");
const input = document.getElementById("message-input");
const sendBtn = document.getElementById("send-btn");
const statusDot = document.getElementById("status-dot");
const statusText = document.getElementById("status-text");
const memoryList = document.getElementById("memory-list");

function getSessionId() {
  let id = localStorage.getItem(SESSION_KEY);
  if (!id) {
    id = "sess_" + Math.random().toString(36).slice(2, 10);
    localStorage.setItem(SESSION_KEY, id);
  }
  return id;
}

function setStatus(state) {
  const labels = {
    idle: "idle",
    planning: "planning...",
    executing: "executing...",
    done: "done",
    error: "error",
  };
  statusDot.className = "status-dot " + state;
  statusText.textContent = labels[state] || state;
}

function autoResize() {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 160) + "px";
}
input.addEventListener("input", autoResize);

input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    composer.requestSubmit();
  }
});

function appendUserMessage(text) {
  const div = document.createElement("div");
  div.className = "msg user";
  div.innerHTML = `<div class="msg-meta">you</div><div class="msg-body"></div>`;
  div.querySelector(".msg-body").textContent = text;
  chatWindow.appendChild(div);
  scrollToBottom();
}

function escapeHtml(str) {
  return str.replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

// Render a fenced ```code``` block (if present) as <pre><code>, escape the rest.
function renderRichText(text) {
  const parts = text.split(/```(\w+)?\n([\s\S]*?)```/g);
  let html = "";
  for (let i = 0; i < parts.length; i++) {
    if (i % 3 === 0) {
      html += escapeHtml(parts[i] || "").replace(/\n/g, "<br>");
    } else if (i % 3 === 2) {
      html += `<pre><code>${escapeHtml(parts[i] || "")}</code></pre>`;
    }
    // i % 3 === 1 is the language tag, skip rendering it directly
  }
  return html;
}

function appendAgentResult(result) {
  const div = document.createElement("div");
  div.className = "msg agent";

  if (!result.domain_match) {
    div.innerHTML = `
      <div class="msg-meta">DebugMate</div>
      <div class="msg-body refusal">${renderRichText(result.final_answer)}</div>
    `;
    chatWindow.appendChild(div);
    scrollToBottom();
    return;
  }

  const frames = (result.steps || []).map((step, idx) => `
    <div class="frame">
      <span class="frame-loc"><span class="step-num">Step ${idx + 1}</span> &mdash; File "debugmate_agent.py", in ${step.name.replace(/\s+/g, "_")}()</span>
      <div class="frame-body">${renderRichText(step.detail || "")}</div>
    </div>
  `).join("");

  div.innerHTML = `
    <div class="msg-meta">DebugMate</div>
    <div class="msg-body">
      <div class="trace">
        <div class="trace-header">Traceback (most recent agent run):</div>
        ${frames}
      </div>
      <div style="margin-top:10px;">${renderRichText(result.final_answer)}</div>
    </div>
  `;
  chatWindow.appendChild(div);
  scrollToBottom();
}

function scrollToBottom() {
  chatWindow.scrollTop = chatWindow.scrollHeight;
}

function renderMemory(snapshot) {
  memoryList.innerHTML = "";
  const items = [];

  if (snapshot.preferred_language) {
    items.push(`<li><span class="k">lang</span> &middot; ${escapeHtml(snapshot.preferred_language)}</li>`);
  }
  if (snapshot.most_common_bug_types && snapshot.most_common_bug_types.length) {
    items.push(`<li><span class="k">common bugs</span> &middot; ${snapshot.most_common_bug_types.map(escapeHtml).join(", ")}</li>`);
  }
  if (snapshot.recent_bugs && snapshot.recent_bugs.length) {
    const last = snapshot.recent_bugs[snapshot.recent_bugs.length - 1];
    items.push(`<li><span class="k">last fix</span> &middot; ${escapeHtml(last.bug_type)}</li>`);
  }
  if (snapshot.constraints && snapshot.constraints.length) {
    items.push(`<li><span class="k">notes</span> &middot; ${snapshot.constraints.map(escapeHtml).join("; ")}</li>`);
  }

  if (items.length === 0) {
    memoryList.innerHTML = `<li class="memory-empty">No memory yet &mdash; send your first bug report.</li>`;
  } else {
    memoryList.innerHTML = items.join("");
  }
}

async function sendMessage(text) {
  if (!text.trim()) return;
  appendUserMessage(text);
  input.value = "";
  autoResize();
  sendBtn.disabled = true;
  setStatus("planning");

  // Give the planning phase a beat to feel real before the network resolves,
  // then flip to "executing" shortly after -- purely a UX cue.
  const executingTimer = setTimeout(() => setStatus("executing"), 700);

  try {
    const res = await fetch(`${API_BASE}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: getSessionId(), message: text }),
    });
    clearTimeout(executingTimer);

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Unknown error" }));
      setStatus("error");
      appendAgentResult({
        domain_match: false,
        final_answer: `Something went wrong: ${err.detail || res.statusText}. ` +
          `If this is a fresh deploy, double check GROQ_API_KEY is set in the environment.`,
      });
      sendBtn.disabled = false;
      return;
    }

    const result = await res.json();
    appendAgentResult(result);
    if (result.memory_snapshot) renderMemory(result.memory_snapshot);
    setStatus("done");
  } catch (e) {
    clearTimeout(executingTimer);
    setStatus("error");
    appendAgentResult({
      domain_match: false,
      final_answer: "Couldn't reach the DebugMate backend. Check your connection or try again in a moment.",
    });
  } finally {
    sendBtn.disabled = false;
    setTimeout(() => setStatus("idle"), 1500);
  }
}

composer.addEventListener("submit", (e) => {
  e.preventDefault();
  sendMessage(input.value);
});

document.querySelectorAll(".example-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    sendMessage(btn.dataset.msg);
  });
});

// Load any existing memory for this session on first paint.
(async function init() {
  try {
    const res = await fetch(`${API_BASE}/api/memory/${getSessionId()}`);
    if (res.ok) renderMemory(await res.json());
  } catch (e) {
    /* non-fatal */
  }
})();
