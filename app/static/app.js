(function () {
  const root = document.querySelector("[data-chat-root]");
  if (!root) return;

  const form = root.querySelector("[data-chat-form]");
  const feed = root.querySelector("[data-message-feed]");
  const citationsPanel = root.querySelector("[data-citation-list]");
  const apiUrl = root.dataset.apiUrl;
  let conversationId = window.sessionStorage.getItem("conversationId") || null;

  function escapeHtml(text) {
    return text
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function appendMessage(role, content, extra = "") {
    const article = document.createElement("article");
    article.className = `message message-${role}`;
    article.innerHTML = `
      <div class="message-role">${role === "user" ? "用户" : "助手"}</div>
      <div class="message-body">${content}</div>
      ${extra}
    `;
    feed.appendChild(article);
    feed.scrollTop = feed.scrollHeight;
  }

  function renderAssistant(response) {
    const html = `
      <div class="answer-sections">
        <section>
          <h3>直接回答</h3>
          <div>${escapeHtml(response.answer).replaceAll("\n", "<br />")}</div>
        </section>
        <section>
          <h3>资料依据</h3>
          <div>${escapeHtml(response.grounded_answer).replaceAll("\n", "<br />")}</div>
        </section>
        <section>
          <h3>补充说明（模型推断）</h3>
          <div>${escapeHtml(response.inference_note || "无")}</div>
        </section>
      </div>
    `;
    appendMessage("assistant", html);
  }

  function renderCitations(citations) {
    if (!citations.length) {
      citationsPanel.innerHTML = `<p class="empty-state">当前没有命中的引用片段。</p>`;
      return;
    }
    citationsPanel.innerHTML = citations
      .map(
        (item, index) => `
          <article class="citation-item">
            <h3>${index + 1}. ${escapeHtml(item.file_name)}</h3>
            <p><strong>${escapeHtml(item.page_or_slide)}</strong> · ${escapeHtml(item.section_path)}</p>
            <p>${escapeHtml(item.snippet)}</p>
            <span class="badge">${escapeHtml(item.trust_level)} / ${Number(item.score).toFixed(2)}</span>
          </article>
        `
      )
      .join("");
  }

  async function handleSubmit(event) {
    event.preventDefault();
    const textarea = form.querySelector("textarea[name='question']");
    const question = textarea.value.trim();
    if (!question) return;

    appendMessage("user", escapeHtml(question).replaceAll("\n", "<br />"));
    textarea.value = "";
    const pending = document.createElement("article");
    pending.className = "message message-assistant";
    pending.innerHTML = `<div class="message-role">助手</div><div class="message-body">正在检索资料并生成回答…</div>`;
    feed.appendChild(pending);
    feed.scrollTop = feed.scrollHeight;

    try {
      const response = await fetch(apiUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question,
          conversation_id: conversationId,
        }),
      });
      const payload = await response.json();
      pending.remove();
      if (!response.ok) {
        appendMessage("assistant", `请求失败：${escapeHtml(payload.detail || "unknown error")}`);
        return;
      }
      conversationId = payload.conversation_id;
      window.sessionStorage.setItem("conversationId", conversationId);
      renderAssistant(payload);
      renderCitations(payload.citations || []);
    } catch (error) {
      pending.remove();
      appendMessage("assistant", `请求失败：${escapeHtml(String(error))}`);
    }
  }

  form.addEventListener("submit", handleSubmit);
})();
