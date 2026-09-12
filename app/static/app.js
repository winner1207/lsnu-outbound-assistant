const $ = (id) => document.getElementById(id);
const LANGS = ["zh", "en", "ja", "fr", "es", "ko", "th"];
const state = { sessionId: "", terms: [] };


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
    setStatus(err.message || String(err));
    thinkAdd("identify", err.message || String(err));
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
