const el = (id) => document.getElementById(id);

const state = {
  route: "pattern",
  sql: "",
  rows: [],
  columns: [],
  summary: "",
  plan: "",
  presets: {},
};

function setHealth(status, model, db) {
  const hp = el("healthPill");
  if (status === "ok") {
    hp.textContent = `متصل — ${db} | ${model}`;
    hp.className = "px-3 py-1 rounded-full text-sm bg-green-100 text-green-800";
  } else {
    hp.textContent = "غير متصل";
    hp.className = "px-3 py-1 rounded-full text-sm bg-red-100 text-red-800";
  }
}

async function fetchJSON(url, opts = {}) {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    let detail = "";
    try { const j = await res.json(); detail = j.detail || JSON.stringify(j); } catch {}
    throw new Error(detail || `${res.status} ${res.statusText}`);
  }
  return res.json();
}

function toggleLoader(show) {
  el("loader").classList.toggle("hidden", !show);
}

function renderPresets() {
  const container = el("presetsList");
  container.innerHTML = "";
  const entries = Object.entries(state.presets);
  if (entries.length === 0) {
    container.innerHTML = `<div class="text-sm text-gray-500">لا توجد استعلامات.</div>`;
    return;
  }
  for (const [name] of entries) {
    const btn = document.createElement("button");
    btn.className = "text-right w-full px-3 py-2 rounded-lg border hover:bg-gray-50 text-sm";
    btn.textContent = name;
    btn.onclick = () => runPreset(name);
    container.appendChild(btn);
  }
}

function renderTable(columns, rows) {
  const head = el("tblHead");
  const body = el("tblBody");
  head.innerHTML = "";
  body.innerHTML = "";

  if (!columns || columns.length === 0) {
    head.innerHTML = `<tr><th class="px-3 py-2 text-left">لا أعمدة</th></tr>`;
    return;
  }

  let htr = document.createElement("tr");
  for (const c of columns) {
    const th = document.createElement("th");
    th.className = "px-3 py-2 text-left font-semibold";
    th.textContent = c;
    htr.appendChild(th);
  }
  head.appendChild(htr);

  if (!rows || rows.length === 0) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = columns.length;
    td.className = "px-3 py-4 text-gray-500";
    td.textContent = "لا توجد بيانات لعرضها.";
    tr.appendChild(td);
    body.appendChild(tr);
    return;
  }

  for (const r of rows) {
    const tr = document.createElement("tr");
    for (const c of columns) {
      const td = document.createElement("td");
      td.className = "px-3 py-2";
      let v = r[c];
      if (v === null || v === undefined) v = "";
      td.textContent = String(v);
      tr.appendChild(td);
    }
    body.appendChild(tr);
  }
}

function setSQL(sql) {
  state.sql = sql || "";
  el("sqlOut").textContent = state.sql;
}

function setSummary(text) {
  state.summary = text || "";
  el("summary").textContent = text || "";
}
function setMetrics(resp) {
  const m = el("metrics");
  const model = resp.model || "—";
  const pt = resp.llm_prompt_tokens ?? 0;
  const et = resp.llm_eval_tokens ?? 0;
  const tt = resp.llm_total_tokens ?? (pt + et);
  const llmMs = resp.llm_duration_ms ?? 0;
  const totalMs = resp.total_ms ?? 0;
  m.textContent =
    `النموذج: ${model} | الرموز (Prompt/Eval/Total): ${pt}/${et}/${tt} | ` +
    `زمن LLM: ${llmMs}ms | الزمن الكلي: ${totalMs}ms`;
}

function setPlan(text) {
  state.plan = text || "";
  const pc = el("planCard");
  if (text) {
    pc.textContent = text;
    pc.classList.remove("hidden");
  } else {
    pc.classList.add("hidden");
    pc.textContent = "";
  }
}

function downloadCsv() {
  if (!state.columns.length || !state.rows.length) return;
  const csvHeader = state.columns.map(escapeCsv).join(",") + "\n";
  const csvRows = state.rows.map(row =>
    state.columns.map(c => escapeCsv(row[c])).join(",")
  ).join("\n");
  const blob = new Blob([csvHeader + csvRows], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "result.csv";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
function escapeCsv(val) {
  if (val === null || val === undefined) return "";
  const str = String(val);
  if (/[",\n]/.test(str)) return `"${str.replace(/"/g, '""')}"`;
  return str;
}

async function health() {
  try {
    const j = await fetchJSON("/api/health");
    setHealth("ok", j.model, j.db);
  } catch {
    setHealth("fail");
  }
}

async function loadPresets() {
  try {
    const j = await fetchJSON("/api/presets");
    state.presets = j.presets || {};
    renderPresets();
  } catch (e) {
    console.warn("Presets error:", e.message);
  }
}

function currentRoute() {
  const radios = document.querySelectorAll('input[name="route"]');
  for (const r of radios) if (r.checked) return r.value;
  return "pattern";
}

async function runQuery() {
  const isSqlMode = el("chkSqlMode").checked;
  toggleLoader(true);
  setPlan("");
  try {
    let resp;
    if (isSqlMode) {
      const sql = el("txtSql").value.trim();
      resp = await fetchJSON("/api/run-sql", {
        method: "POST",
        body: JSON.stringify({ sql }),
      });
    } else {
      const question = el("txtQuestion").value.trim();
      const route = currentRoute();
      const url = route === "pattern" ? "/api/pattern"
                : route === "langchain" ? "/api/langchain"
                : "/api/agents";
      resp = await fetchJSON(url, {
        method: "POST",
        body: JSON.stringify({ question }),
      });
    }

    setSQL(resp.sql || "");
    setSummary(resp.summary_ar || "");
    setMetrics(resp);
    state.columns = resp.columns || [];
    state.rows = resp.rows || [];
    renderTable(state.columns, state.rows);

    if (resp.route === "agents" && resp.plan) {
      setPlan(resp.plan);
    }
  } catch (e) {
    setSQL("");
    setSummary("");
    state.columns = [];
    state.rows = [];
    renderTable([], []);
    alert("حدث خطأ: " + e.message);
  } finally {
    toggleLoader(false);
  }
}

async function runPreset(name) {
  toggleLoader(true);
  setPlan("");
  try {
    const resp = await fetchJSON(`/api/presets/run?name=${encodeURIComponent(name)}`, {
      method: "POST",
    });
    setSQL(resp.sql || "");
    setSummary(resp.summary_ar || "");
    state.columns = resp.columns || [];
    state.rows = resp.rows || [];
    renderTable(state.columns, state.rows);
    // switch UI to SQL mode and show SQL
    el("chkSqlMode").checked = true;
    syncMode();
    el("txtSql").value = resp.sql || "";
  } catch (e) {
    alert("تعذر تنفيذ الاستعلام الجاهز: " + e.message);
  } finally {
    toggleLoader(false);
  }
}

function syncMode() {
  const manual = el("chkSqlMode").checked;
  el("nlpBox").classList.toggle("hidden", manual);
  el("sqlBox").classList.toggle("hidden", !manual);
  el("runHint").textContent = manual ? "سيتم تنفيذ الاستعلام كما هو."
                                     : "سيتم توليد SQL من السؤال.";
}
async function warmup() {
  try { await fetchJSON("/api/llm/warmup"); } catch (e) { console.warn("warmup:", e.message); }
}

function attachEvents() {
  // route radios
  document.querySelectorAll('input[name="route"]').forEach(r => {
    r.addEventListener("change", () => (state.route = currentRoute()));
  });

  el("btnRun").onclick = runQuery;
  el("btnClear").onclick = () => {
    el("txtQuestion").value = "";
    el("txtSql").value = "";
    setSQL(""); setSummary(""); setPlan("");
    state.columns = []; state.rows = [];
    renderTable([], []);
  };
  el("btnCopySql").onclick = async () => {
    if (!state.sql) return;
    await navigator.clipboard.writeText(state.sql);
    const btn = el("btnCopySql");
    const old = btn.textContent;
    btn.textContent = "تم النسخ ✓";
    setTimeout(() => (btn.textContent = old), 1200);
  };
  el("btnDownloadCsv").onclick = downloadCsv;
  el("btnRefreshPresets").onclick = loadPresets;
  el("chkSqlMode").onchange = syncMode;
}

(async function init() {
  attachEvents();
  syncMode();
  await health();
  await loadPresets();
})();
