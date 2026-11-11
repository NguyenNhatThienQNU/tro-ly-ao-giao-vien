/* Tương tác chung cho các trang của giáo viên */
(function () {
  "use strict";
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
  window.APP = { csrf };
  const fmt = (x) => (Math.round(x * 100) / 100).toString().replace(".", ",");

  // Hỏi xác nhận trước khi gửi form nguy hiểm; hiện trạng thái "đang xử lý" cho form chạy lâu
  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (form.dataset.confirm && !window.confirm(form.dataset.confirm)) {
      event.preventDefault();
      return;
    }
    if (form.dataset.loading) {
      const buttons = form.querySelectorAll("button");
      const last = buttons[buttons.length - 1];
      setTimeout(() => {
        buttons.forEach((b) => (b.disabled = true));
        if (last) last.innerHTML = `<span class="spinner-border spinner-border-sm me-1"></span>${form.dataset.loading}`;
      }, 0);
    }
  });

  // Bấm cả dòng bảng để mở chi tiết
  document.querySelectorAll(".clickable-row").forEach((row) => {
    row.addEventListener("click", (event) => {
      if (event.target.closest("a, button, form, input, select")) return;
      window.location.href = row.dataset.href;
    });
  });

  // Chọn / bỏ chọn tất cả
  document.querySelectorAll("[data-check-all]").forEach((btn) =>
    btn.addEventListener("click", () =>
      document.querySelectorAll(`input[name="${btn.dataset.checkAll}"]`).forEach((c) => (c.checked = true))
    )
  );
  document.querySelectorAll("[data-uncheck-all]").forEach((btn) =>
    btn.addEventListener("click", () =>
      document.querySelectorAll(`input[name="${btn.dataset.uncheckAll}"]`).forEach((c) => (c.checked = false))
    )
  );

  // Soạn rubric: thêm/xóa tiêu chí, tính tổng điểm
  const rubricRows = document.getElementById("rubricRows");
  if (rubricRows) {
    const sumEl = document.getElementById("rubricSum");
    const maxEl = document.getElementById("rubricMax");
    const maxInput = document.getElementById("maxScore");
    const update = () => {
      let sum = 0;
      rubricRows.querySelectorAll(".rubric-points").forEach((i) => (sum += parseFloat(i.value || 0)));
      const max = parseFloat(maxInput.value || 0);
      sumEl.textContent = fmt(sum);
      maxEl.textContent = fmt(max);
      sumEl.classList.toggle("text-danger", Math.abs(sum - max) > 0.001);
    };
    document.getElementById("rubricAdd").addEventListener("click", () => {
      const row = rubricRows.querySelector(".rubric-row").cloneNode(true);
      row.querySelectorAll("input").forEach((i) => (i.value = ""));
      rubricRows.appendChild(row);
      row.querySelector("input").focus();
    });
    rubricRows.addEventListener("click", (event) => {
      const btn = event.target.closest(".rubric-remove");
      if (!btn) return;
      const rows = rubricRows.querySelectorAll(".rubric-row");
      if (rows.length > 1) btn.closest(".rubric-row").remove();
      else btn.closest(".rubric-row").querySelectorAll("input").forEach((i) => (i.value = ""));
      update();
    });
    rubricRows.addEventListener("input", update);
    maxInput.addEventListener("input", update);
    update();
  }

  // Trang chấm bài: tự cộng tổng điểm khi sửa
  const scoreInputs = document.querySelectorAll(".score-input");
  if (scoreInputs.length) {
    const totalEl = document.getElementById("totalScore");
    const tenEl = document.getElementById("totalTen");
    const update = () => {
      let total = 0;
      let max = 0;
      scoreInputs.forEach((i) => {
        const value = Math.min(parseFloat(i.value || 0), parseFloat(i.dataset.max));
        total += isNaN(value) ? 0 : value;
        max += parseFloat(i.dataset.max);
      });
      if (totalEl) totalEl.textContent = fmt(total);
      if (tenEl) tenEl.textContent = fmt(max ? (total / max) * 10 : 0);
    };
    scoreInputs.forEach((i) => i.addEventListener("input", update));
    update();
  }
})();
