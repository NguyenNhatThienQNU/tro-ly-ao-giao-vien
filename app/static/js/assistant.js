/* Giao diện trò chuyện với trợ lý AI */
(function () {
  "use strict";
  const body = document.getElementById("chatBody");
  const form = document.getElementById("chatForm");
  const input = document.getElementById("chatInput");
  const sendBtn = document.getElementById("chatSend");
  const fileInput = document.getElementById("chatFile");
  const csrf = window.APP.csrf;

  const escapeHtml = (s) =>
    s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

  // Markdown tối giản và an toàn: thoát HTML trước, rồi mới định dạng
  function md(text) {
    const lines = escapeHtml(text || "").split("\n");
    let html = "";
    let inList = false;
    for (const raw of lines) {
      const line = raw
        .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
        .replace(/`([^`]+)`/g, "<code>$1</code>")
        .replace(/(https?:\/\/[^\s<]+)/g, '<a href="$1" target="_blank" rel="noopener">$1</a>')
        .replace(/(^|[\s(:])(\/(?:assignments|bank|grading|students|classes|dashboard)[\w\-/?=&;#.]*)/g, '$1<a href="$2">$2</a>');
      const item = line.match(/^\s*[-*•]\s+(.*)$/);
      if (item) {
        if (!inList) { html += "<ul>"; inList = true; }
        html += `<li>${item[1]}</li>`;
        continue;
      }
      if (inList) { html += "</ul>"; inList = false; }
      if (line.trim()) html += `<p>${line}</p>`;
    }
    if (inList) html += "</ul>";
    return html;
  }

  function addMessage(role, text, actions) {
    const wrap = document.createElement("div");
    wrap.className = `msg msg-${role}`;
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    if (role === "assistant") {
      bubble.classList.add("md");
      bubble.innerHTML = md(text);
    } else {
      bubble.textContent = text;
    }
    wrap.appendChild(bubble);
    if (actions && actions.length) {
      const box = document.createElement("div");
      box.className = "actions";
      actions.forEach((a) => {
        const link = document.createElement("a");
        link.className = "btn btn-sm btn-outline-primary";
        link.href = a.url;
        link.innerHTML = `${escapeHtml(a.label)} <i class="bi bi-arrow-right"></i>`;
        box.appendChild(link);
      });
      wrap.appendChild(box);
    }
    body.appendChild(wrap);
    body.scrollTop = body.scrollHeight;
    return wrap;
  }

  body.querySelectorAll('.msg[data-md="1"] .bubble').forEach((b) => {
    b.classList.add("md");
    b.innerHTML = md(b.textContent);
  });
  body.scrollTop = body.scrollHeight;

  async function send(text) {
    addMessage("user", text);
    const typing = addMessage("assistant", "");
    typing.querySelector(".bubble").innerHTML = '<span class="typing"><span></span><span></span><span></span></span>';
    sendBtn.disabled = true;
    try {
      const res = await fetch("/api/assistant/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
        body: JSON.stringify({ message: text }),
      });
      const data = await res.json().catch(() => ({}));
      typing.remove();
      if (!res.ok) {
        addMessage("assistant", "⚠️ " + (data.detail || "Có lỗi xảy ra, thầy/cô thử lại nhé."));
        return;
      }
      addMessage("assistant", data.reply, data.actions);
    } catch (err) {
      typing.remove();
      addMessage("assistant", "⚠️ Không kết nối được máy chủ.");
    } finally {
      sendBtn.disabled = false;
      input.focus();
    }
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const text = input.value.trim();
    if (!text || sendBtn.disabled) return;
    input.value = "";
    send(text);
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });
  document.querySelectorAll(".suggestion").forEach((btn) =>
    btn.addEventListener("click", () => {
      input.value = btn.textContent.trim();
      input.focus();
    })
  );

  fileInput.addEventListener("change", async () => {
    const file = fileInput.files[0];
    if (!file) return;
    const data = new FormData();
    data.append("file", file);
    try {
      const res = await fetch("/api/assistant/upload", { method: "POST", headers: { "X-CSRF-Token": csrf }, body: data });
      const json = await res.json();
      if (json.ok) {
        const prefix = input.value.trim() ? input.value.trim() + "\n\n" : "Đây là bảng điểm, hãy lưu lại cho lớp:\n";
        input.value = `${prefix}[Tệp ${json.filename}]\n${json.text}`;
        input.focus();
      } else {
        window.alert(json.error || "Không đọc được tệp.");
      }
    } finally {
      fileInput.value = "";
    }
  });

  document.getElementById("clearChat").addEventListener("click", async () => {
    if (!window.confirm("Xóa toàn bộ lịch sử trò chuyện với trợ lý?")) return;
    await fetch("/api/assistant/clear", { method: "POST", headers: { "X-CSRF-Token": csrf } });
    window.location.reload();
  });
})();
