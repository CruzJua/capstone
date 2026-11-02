"use strict";
const $ = (selector) => document.querySelector(selector);
const ui = {
  tenant: $("#tenant"), question: $("#question"), send: $("#send"),
  messages: $("#messages"), sources: $("#sources"), count: $("#source-count"),
  meta: $("#retrieval-meta"), context: $("#context-text"), raw: $("#raw-context"),
  topK: $("#top-k"), warnings: $("#warnings"), refresh: $("#refresh"), newChat: $("#new-chat"),
};
const welcomeTemplate = $("#welcome").cloneNode(true);
let history = [];
let busy = false;
let config = null;
let latestEvidence = null;

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
function setBusy(value) {
  busy = value;
  const available = Boolean(config && config.tenants.length);
  ui.send.disabled = value || !available;
  ui.question.disabled = !available;
  ui.tenant.disabled = value || !available;
  ui.topK.disabled = value;
  ui.newChat.disabled = value;
  ui.refresh.disabled = value;
}
function showWarnings(messages) {
  ui.warnings.replaceChildren(...messages.map((message) => element("p", "", message)));
  ui.warnings.hidden = messages.length === 0;
}
async function loadConfig() {
  ui.refresh.disabled = true;
  try {
    const response = await fetch("/api/config?refresh=1");
    if (!response.ok) throw new Error("Could not connect to the demo backend.");
    config = await response.json();
    const selected = ui.tenant.value;
    ui.tenant.replaceChildren(...config.tenants.map((tenant) => {
      const option = document.createElement("option");
      option.value = tenant.id;
      option.textContent = tenant.name;
      return option;
    }));
    if (config.tenants.some((tenant) => tenant.id === selected)) ui.tenant.value = selected;
    $("#model-name").textContent = config.model;
    $("#connection-status").textContent = config.ollama_ready && config.rag_ready
      ? "Model & knowledge base connected" : "Connection needs attention";
    showWarnings(config.warnings);
  } catch (error) {
    showWarnings([error.message]);
    $("#connection-status").textContent = "Backend unavailable";
  } finally {
    setBusy(false);
  }
}
function scrollConversation() { ui.messages.scrollTop = ui.messages.scrollHeight; }
function message(role, text = "") {
  $("#welcome")?.remove();
  const container = element("article", `message ${role}`);
  const label = element("div", "message-label", role === "user" ? "YOU" : "GROUNDWORK / SUPPORT AGENT");
  const body = element("div", "message-body", text);
  container.append(label, body);
  ui.messages.append(container);
  scrollConversation();
  return { container, body };
}
function emptyEvidence(text) {
  ui.sources.replaceChildren(element("div", "evidence-empty", text));
  ui.count.textContent = "0";
  ui.raw.hidden = true;
  ui.meta.textContent = "Tenant-filtered vector search · MongoDB Atlas";
}
function normalizedSource(source) {
  return String(source).split(" - ")[0].split(/[\\/]/).pop().replace(/\.(md|json|txt|csv|pdf)$/i, "");
}
function renderEvidence(evidence, citedSources = []) {
  latestEvidence = evidence;
  const sources = evidence.sources || [];
  const cited = new Set(citedSources.map(normalizedSource));
  ui.count.textContent = String(sources.length);
  ui.meta.textContent = `${evidence.tenant.replaceAll("_", " ")} · ${Math.round(evidence.retrieval_ms)} ms · fetched passages`;
  ui.sources.replaceChildren();
  if (!sources.length) {
    ui.sources.append(element("div", "evidence-empty", "No relevant passages were returned. The agent should escalate if it cannot answer from the provided context."));
  }
  sources.forEach((source, index) => {
    const isCited = cited.has(normalizedSource(source.doc_id));
    const card = element("article", `source-card${isCited ? " cited" : ""}`);
    const top = element("div", "source-card-top");
    top.append(element("h3", "source-title", source.doc_id), element("span", "source-rank", `#${index + 1}`));
    card.append(top);
    if (source.section) card.append(element("div", "source-section", source.section));
    card.append(element("p", "source-text", source.text));
    const score = element("div", "source-score");
    score.append(element("span", "", `Similarity: ${typeof source.score === "number" ? source.score.toFixed(4) : "unavailable"}${source.chunk_index != null ? ` · Chunk ${source.chunk_index}` : ""}`));
    if (isCited) score.append(element("span", "source-cited", "CITED IN ANSWER"));
    card.append(score);
    ui.sources.append(card);
  });
  ui.context.textContent = evidence.context || "(no relevant documents found)";
  ui.raw.hidden = false;
}
function resetConversation() {
  if (busy) return;
  history = [];
  latestEvidence = null;
  ui.messages.replaceChildren(welcomeTemplate.cloneNode(true));
  emptyEvidence("Ask a question to see the passages retrieved from this business’s documents.");
  ui.question.value = "";
  ui.question.focus();
}
async function sendQuestion(event) {
  event.preventDefault();
  const query = ui.question.value.trim();
  if (busy || !query || !ui.tenant.value) return;
  const requestHistory = history.slice(-12);
  const tenant = ui.tenant.value;
  message("user", query);
  ui.question.value = "";
  setBusy(true);
  emptyEvidence("Searching this business’s knowledge base…");
  latestEvidence = null;
  const pending = element("div", "thinking");
  pending.setAttribute("role", "status");
  const statusText = element("span", "", "Finding relevant passages…");
  pending.append(element("span", "dot"), statusText);
  ui.messages.append(pending);
  scrollConversation();
  let evidence = null;
  let answered = false;
  let failed = false;
  const handleEvent = (item) => {
    if (item.type === "status") statusText.textContent = item.message;
    if (item.type === "retrieved") {
      evidence = item;
      renderEvidence(item);
    }
    if (item.type === "error") throw new Error(item.message);
    if (item.type === "answer") {
      answered = true;
      pending.remove();
      const result = message("assistant", item.response.answer);
      const meta = element("div", "message-meta");
      const isEscalation = item.response.action === "escalate";
      meta.append(element("span", `badge${isEscalation ? " escalate" : ""}`, isEscalation ? "HUMAN FOLLOW-UP NEEDED" : "ANSWER"));
      meta.append(element("span", "", `Model confidence ${Math.round(item.response.confidence * 100)}%`));
      meta.append(element("span", "", `${(item.timing.total_ms / 1000).toFixed(1)}s · ${Number(item.timing.tokens_per_second || 0).toFixed(1)} tokens/s`));
      if (evidence) {
        const evidenceForTurn = evidence;
        const cites = item.response.cited_sources;
        const button = element("button", "source-link", `View ${evidence.sources.length} fetched passages ↗`);
        button.type = "button";
        button.addEventListener("click", () => renderEvidence(evidenceForTurn, cites));
        meta.append(button);
        renderEvidence(evidence, cites);
      }
      if (item.response.cited_sources.length) {
        meta.append(element("span", "", `Cites: ${item.response.cited_sources.join(", ")}`));
      }
      if (isEscalation) meta.append(element("span", "", "Demo only: no ticket has been sent."));
      result.container.append(meta);
      history.push({role: "user", content: query}, {role: "assistant", content: item.response.answer.slice(0, 8000)});
      history = history.slice(-12);
      scrollConversation();
    }
  };
  try {
    const response = await fetch("/api/chat", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({tenant, query, history: requestHistory, top_k: Number(ui.topK.value)}),
    });
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.error || "The backend could not process your question.");
    }
    if (!response.body) throw new Error("Your browser did not receive a response stream.");
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    try {
      while (true) {
        const {value, done} = await reader.read();
        buffer += done ? decoder.decode() : decoder.decode(value, {stream: true});
        const lines = buffer.split("\n");
        buffer = lines.pop();
        for (const line of lines) if (line.trim()) handleEvent(JSON.parse(line));
        if (done) break;
      }
      if (buffer.trim()) handleEvent(JSON.parse(buffer));
    } finally {
      reader.releaseLock();
    }
    if (!answered) throw new Error("The connection closed before an answer arrived. Please retry.");
  } catch (error) {
    failed = true;
    pending.remove();
    const result = message("assistant", error.message || "Something went wrong. Please retry.");
    result.container.classList.add("error");
    // Keep the user's question available for an easy retry.
    if (!ui.question.value.trim()) ui.question.value = query;
  } finally {
    pending.remove();
    setBusy(false);
    ui.question.focus();
    if (!evidence && failed) emptyEvidence("Retrieval did not finish. Check the connection message in the chat and try again.");
  }
}
$("#chat-form").addEventListener("submit", sendQuestion);
ui.question.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    if (!busy) $("#chat-form").requestSubmit();
  }
});
ui.messages.addEventListener("click", (event) => {
  const suggestion = event.target.closest("[data-question]");
  if (suggestion && !busy) {
    ui.question.value = suggestion.dataset.question;
    ui.question.focus();
  }
});
ui.tenant.addEventListener("change", resetConversation);
ui.newChat.addEventListener("click", resetConversation);
ui.refresh.addEventListener("click", loadConfig);
loadConfig();
