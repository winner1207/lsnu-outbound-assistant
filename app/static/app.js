const $ = (id) => document.getElementById(id);
const LANGS = ["zh", "en", "ja", "fr", "es"];
const state = { sessionId: "", terms: [] };

function setStatus(text) {
  $("status").textContent = text;
}

function setSteps(active) {
  const order = ["identify", "load", "lock", "deliver"];
  const idx = order.indexOf(active);
  document.querySelectorAll(".steps li").forEach((li) => {
    const step = li.dataset.step;
    li.classList.toggle("on", step === active);
    li.classList.toggle("done", order.indexOf(step) < idx);
  });
}

function highlight(text, words) {
  const src = String(text || "");
  const ranges = [];
  const uniq = [...new Set(words || [])].filter(Boolean).sort((a, b) => b.length - a.length);
  for (const word of uniq) {
    let from = 0;
    while (from <= src.length) {
      const idx = src.indexOf(word, from);
      if (idx < 0) break;
      const end = idx + word.length;
      const overlap = ranges.some((r) => !(end <= r[0] || idx >= r[1]));
      if (!overlap) ranges.push([idx, end, word]);
      from = idx + 1;
    }
  }
  ranges.sort((a, b) => a[0] - b[0]);
  let html = "";
  let cursor = 0;
  const esc = (s) => s.replace(/[&<>]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[ch]));
  for (const [start, end, word] of ranges) {
    html += esc(src.slice(cursor, start));
    html += `<mark>${esc(word)}</mark>`;
    cursor = end;
  }
  html += esc(src.slice(cursor));
  return html;
}

function renderResult(data) {
  state.sessionId = data.session_id;
  state.terms = data.term_table || [];
  const bits = [`识别为「${data.label_zh}」`];
  if (data.in_photo) bits.push(data.in_photo);
  if (data.reason) bits.push(data.reason);
  $("ident").textContent = bits.join(" · ");
  if (data.ocr_text) {
    $("ocr").hidden = false;
    $("ocr").textContent = `图中文字：${data.ocr_text}${data.ocr_note ? "（" + data.ocr_note + "）" : ""}`;
  } else {
    $("ocr").hidden = true;
  }
  const select = $("scene");
  select.innerHTML = "";
  (data.scenes || []).forEach((scene) => {
    const opt = document.createElement("option");
    opt.value = scene.id;
    opt.textContent = scene.label_zh;
    if (scene.id === data.scene) opt.selected = true;
    select.appendChild(opt);
  });
  select.disabled = false;
  $("terms").innerHTML = state.terms.map((t) => `<span>${t.zh} / ${t.en}</span>`).join("");
  LANGS.forEach((lang) => {
    const hits = (data.locked_terms && data.locked_terms[lang]) || [];
    $(lang).innerHTML = highlight((data.intro && data.intro[lang]) || "", hits);
  });
  $("q").disabled = false;
  $("ask").querySelector("button").disabled = false;
  $("chat").innerHTML = `<div class="msg bot">${highlight((data.intro && data.intro.zh) || "", (data.locked_terms && data.locked_terms.zh) || [])}</div>`;
}

$("file").addEventListener("change", () => {
  const file = $("file").files[0];
  if (!file) return;
  $("preview").src = URL.createObjectURL(file);
  $("preview").hidden = false;
  $("hint").textContent = file.name;
});

$("analyze").addEventListener("click", async () => {
  const file = $("file").files[0];
  if (!file) {
    setStatus("请先选择图片");
    return;
  }
  const body = new FormData();
  body.append("file", file);
  $("analyze").disabled = true;
  setSteps("identify");
  setStatus("正在识字并讲解…");
  try {
    const res = await fetch("/api/analyze", { method: "POST", body });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "识别失败");
    setSteps("deliver");
    renderResult(data);
    setStatus("完成");
  } catch (err) {
    setStatus(err.message || String(err));
  } finally {
    $("analyze").disabled = false;
  }
});

$("scene").addEventListener("change", async (ev) => {
  if (!state.sessionId) return;
  setStatus("按手选场景重新生成…");
  try {
    const res = await fetch("/api/scene", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: state.sessionId, scene: ev.target.value }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "切换失败");
    renderResult(data);
    setStatus("已按手选场景更新");
  } catch (err) {
    setStatus(err.message || String(err));
  }
});

$("ask").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const text = $("q").value.trim();
  if (!text || !state.sessionId) return;
  $("chat").insertAdjacentHTML("beforeend", `<div class="msg user">${highlight(text, [])}</div>`);
  $("q").value = "";
  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: state.sessionId, message: text }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "对话失败");
    $("chat").insertAdjacentHTML("beforeend", `<div class="msg bot">${highlight(data.reply, data.locked_terms)}</div>`);
    $("chat").scrollTop = $("chat").scrollHeight;
  } catch (err) {
    setStatus(err.message || String(err));
  }
});
