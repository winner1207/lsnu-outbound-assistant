const $ = (id) => document.getElementById(id);
const LANGS = ["zh", "en", "ja", "fr", "es", "ko", "th"];
const state = { sessionId: "", terms: [], catalog: { terms: [], scenes: [], packs: [] }, editingId: "" };

function escapeHtml(s) {
  return String(s || "").replace(/[&<>"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch]));
}


function thinkClear() {
  $("think-log").innerHTML = "";
  $("think-box").open = true;
}

function thinkAdd(step, message) {
  const li = document.createElement("li");
  const tag = { identify: "看图", search: "检索", story: "撰写", deliver: "完成" }[step] || step;
  li.innerHTML = `<em>${tag}</em>${message || ""}`;
  $("think-log").appendChild(li);
  $("think-log").scrollTop = $("think-log").scrollHeight;
}

async function readSSE(res, onEvent) {
  if (!res.body) throw new Error("浏览器不支持流式输出");
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const chunks = buf.split("\n\n");
    buf = chunks.pop();
    for (const block of chunks) {
      const line = block.split("\n").find((x) => x.startsWith("data: "));
      if (!line) continue;
      onEvent(JSON.parse(line.slice(6)));
    }
  }
}

function setStatus(text) {
  $("status").textContent = text;
}

function friendlyError(err) {
  const raw = String((err && err.message) || err || "");
  if (/network error|failed to fetch|load failed|networkerror/i.test(raw)) {
    return "连接中断：七语讲解生成时间过长。请再试一次。";
  }
  return raw;
}

function setSteps(active) {
  const order = ["identify", "search", "story", "deliver"];
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
  const esc = escapeHtml;
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
  const bits = [data.region ? `识别为「${data.label_zh}」（${data.region}）` : `识别为「${data.label_zh}」`];
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
  thinkClear();
  setSteps("identify");
  setStatus("Agent 开始思考…");
  thinkAdd("identify", "已提交图片，正在调用视觉模型");
  try {
    const res = await fetch("/api/analyze/stream", { method: "POST", body });
    if (!res.ok) throw new Error("识别请求失败");
    await readSSE(res, (ev) => {
      if (ev.step) setSteps(ev.step);
      if (ev.message) {
        setStatus(ev.message);
        thinkAdd(ev.step || "identify", ev.message);
      }
      if (ev.type === "identify" && ev.features && ev.features.length) {
        thinkAdd("identify", "特征：" + ev.features.join("、"));
      }
      if (ev.type === "identify" && ev.candidates && ev.candidates.length) {
        const names = ev.candidates.map((c) => `${c.name || ""} ${c.confidence != null ? c.confidence : ""}`.trim());
        thinkAdd("identify", "候选：" + names.join("；"));
      }
      if (ev.type === "search" && ev.grounding) {
        thinkAdd("search", ev.grounding.slice(0, 220));
      }
      if (ev.type === "done" && ev.result) {
        renderResult(ev.result);
        setStatus("完成");
      }
      if (ev.type === "error") {
        thinkAdd(ev.step || "identify", ev.message || "识别失败");
        throw new Error(ev.message || "识别失败");
      }
    });
  } catch (err) {
    const msg = friendlyError(err);
    setStatus(msg);
    thinkAdd("identify", msg);
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


function apiError(data, fallback) {
  const detail = data && data.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail[0] && detail[0].msg) return detail[0].msg;
  return fallback;
}

function fillSelect(node, items, extra) {
  node.innerHTML = "";
  (extra || []).forEach((item) => {
    const opt = document.createElement("option");
    opt.value = item.id;
    opt.textContent = item.label_zh;
    node.appendChild(opt);
  });
  (items || []).forEach((item) => {
    const opt = document.createElement("option");
    opt.value = item.id;
    opt.textContent = item.label_zh;
    node.appendChild(opt);
  });
}

function renderTermList() {
  const q = ($("term-q").value || "").trim().toLowerCase();
  const rows = (state.catalog.terms || []).filter((t) => {
    if (!q) return true;
    return [t.zh, t.en, t.ja, t.id].some((x) => String(x || "").toLowerCase().includes(q));
  });
  if (!rows.length) {
    $("term-list").innerHTML = `<p class="muted">${q ? "没有匹配的词条" : "词库是空的"}</p>`;
    return;
  }
  $("term-list").innerHTML = `<table><thead><tr><th>中文</th><th>English</th><th>日本語</th><th>词包</th><th>审定</th></tr></thead><tbody>${rows.map((t) => {
    const pack = (state.catalog.packs || []).find((p) => p.id === t.pack);
    return `<tr data-id="${escapeHtml(t.id)}" class="${t.id === state.editingId ? "on" : ""}"><td>${escapeHtml(t.zh)}</td><td>${escapeHtml(t.en)}</td><td>${escapeHtml(t.ja)}</td><td>${escapeHtml((pack && pack.label_zh) || t.pack || "")}</td><td>${escapeHtml(t.reviewer || "")}</td></tr>`;
  }).join("")}</tbody></table>`;
}

function showTermForm(term) {
  state.editingId = (term && term.id) || "";
  $("term-form").hidden = false;
  $("term-id").value = state.editingId;
  $("term-zh").value = (term && term.zh) || "";
  LANGS.slice(1).forEach((lang) => {
    $("term-" + lang).value = (term && term[lang]) || "";
  });
  $("term-pack").value = (term && term.pack) || "tourism";
  $("term-scene").value = (term && term.scene) || "";
  $("term-region").value = (term && term.region) || "";
  $("term-aliases").value = ((term && term.aliases_zh) || []).join("，");
  $("term-source").value = (term && term.source) || "";
  $("term-reviewer").value = (term && term.reviewer) || "待审定";
  $("term-del").hidden = !state.editingId;
  $("term-status").textContent = state.editingId ? "正在编辑「" + (term.zh || "") + "」" : "新增词条";
  renderTermList();
  $("term-zh").focus();
}

function collectTerm() {
  return {
    zh: $("term-zh").value.trim(),
    en: $("term-en").value.trim(),
    ja: $("term-ja").value.trim(),
    fr: $("term-fr").value.trim(),
    es: $("term-es").value.trim(),
    ko: $("term-ko").value.trim(),
    th: $("term-th").value.trim(),
    pack: $("term-pack").value,
    scene: $("term-scene").value,
    region: $("term-region").value.trim(),
    aliases_zh: $("term-aliases").value.split(/[,，、]/).map((x) => x.trim()).filter(Boolean),
    source: $("term-source").value.trim(),
    reviewer: $("term-reviewer").value.trim() || "待审定",
  };
}

async function loadCatalog() {
  const res = await fetch("/api/terms");
  const data = await res.json();
  if (!res.ok) throw new Error(apiError(data, "读取词库失败"));
  state.catalog = data;
  fillSelect($("term-pack"), data.packs || []);
  fillSelect($("term-scene"), data.scenes || [], [{ id: "", label_zh: "不指定" }]);
  renderTermList();
}

$("term-q").addEventListener("input", renderTermList);
$("term-new").addEventListener("click", () => showTermForm(null));
$("term-list").addEventListener("click", (ev) => {
  const row = ev.target.closest("tr[data-id]");
  if (!row) return;
  const term = (state.catalog.terms || []).find((t) => t.id === row.dataset.id);
  if (term) showTermForm(term);
});
$("term-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const body = collectTerm();
  if (!body.zh) {
    $("term-status").textContent = "请填写中文专名";
    return;
  }
  const editing = $("term-id").value;
  $("term-status").textContent = "保存中…";
  try {
    const res = await fetch(editing ? "/api/terms/" + encodeURIComponent(editing) : "/api/terms", {
      method: editing ? "PUT" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(apiError(data, "保存失败"));
    await loadCatalog();
    showTermForm(data);
    $("term-status").textContent = "已保存";
  } catch (err) {
    $("term-status").textContent = err.message || String(err);
  }
});
$("term-del").addEventListener("click", async () => {
  const id = $("term-id").value;
  const zh = $("term-zh").value.trim();
  if (!id) return;
  if (!window.confirm("确定删除「" + (zh || id) + "」？")) return;
  $("term-status").textContent = "删除中…";
  try {
    const res = await fetch("/api/terms/" + encodeURIComponent(id), { method: "DELETE" });
    const data = await res.json();
    if (!res.ok) throw new Error(apiError(data, "删除失败"));
    await loadCatalog();
    $("term-form").hidden = true;
    state.editingId = "";
    $("term-status").textContent = "已删除";
    renderTermList();
  } catch (err) {
    $("term-status").textContent = err.message || String(err);
  }
});
loadCatalog().catch((err) => {
  $("term-list").innerHTML = `<p class="muted">${escapeHtml(err.message || String(err))}</p>`;
});

$("translate").addEventListener("click", async () => {
  const query = $("query").value.trim();
  if (!query) {
    setStatus("请输入专名，例如：乐山大佛下山虎");
    return;
  }
  $("translate").disabled = true;
  setSteps("identify");
  setStatus("正在生成七语讲解…");
  try {
    const res = await fetch("/api/text", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "讲解失败");
    setSteps("deliver");
    renderResult(data);
    setStatus("完成");
  } catch (err) {
    setStatus(err.message || String(err));
  } finally {
    $("translate").disabled = false;
  }
});
