/**
 * PyTorch Memory Profiler – Frontend Application
 * ================================================
 * Communicates with the Python REST API at http://127.0.0.1:<port>/api/
 * using plain fetch() calls (no framework required).
 */

/* ============================================================
   Tiny REST client
   ============================================================ */
const API = {
  async get(path) {
    const res = await fetch(path);
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(`HTTP ${res.status}: ${text}`);
    }
    return res.json();
  },

  async post(path, body) {
    const res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(`HTTP ${res.status}: ${text}`);
    }
    return res.json();
  },

  async upload(path, formData) {
    const res = await fetch(path, { method: "POST", body: formData });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(`HTTP ${res.status}: ${text}`);
    }
    return res.json();
  },
};

/* ============================================================
   Application state
   ============================================================ */
const state = {
  views: [],
  currentView: null,
  search: "",
  page: 0,
  perPage: 200,
  total: 0,
  columns: [],
  rows: [],
  /** absolute index in the filtered result set */
  selectedAbsIndex: null,
  /** index within the currently rendered page */
  selectedPageIndex: null,
  sshHost: "",
  frameUser: "",
  _searchTimer: null,
  /** SSH host metadata keyed by alias */
  _sshHosts: {},
};

/* ============================================================
   DOM references
   ============================================================ */
const el = {
  openPickleBtn:  document.getElementById("openPickleBtn"),
  pickleFileInput: document.getElementById("pickleFileInput"),
  viewSelect:     document.getElementById("viewSelect"),
  searchInput:    document.getElementById("searchInput"),
  clearSearchBtn: document.getElementById("clearSearchBtn"),
  countLabel:     document.getElementById("countLabel"),
  sshHostSelect:  document.getElementById("sshHostSelect"),
  frameUserInput: document.getElementById("frameUserInput"),
  tableHead:      document.getElementById("tableHead"),
  tableBody:      document.getElementById("tableBody"),
  pageInfo:       document.getElementById("pageInfo"),
  prevPageBtn:    document.getElementById("prevPageBtn"),
  nextPageBtn:    document.getElementById("nextPageBtn"),
  detailsContent: document.getElementById("detailsContent"),
  statusBar:      document.getElementById("statusBar"),
};

/* ============================================================
   Utility helpers
   ============================================================ */

function setStatus(msg, isError = false) {
  el.statusBar.textContent = msg;
  el.statusBar.className = isError ? "error" : "";
}

function formatValue(val) {
  if (val === null || val === undefined) return "";
  if (typeof val === "object") {
    try { return JSON.stringify(val); } catch { return String(val); }
  }
  return String(val);
}

function truncate(s, max) {
  return s.length > max ? s.slice(0, max) + "…" : s;
}

/* ============================================================
   SSH hosts
   ============================================================ */

async function loadSSHHosts() {
  try {
    const data = await API.get("/api/ssh/hosts");
    const hosts = data.hosts || {};
    state._sshHosts = hosts;

    // Preserve existing value if still valid
    const existing = el.sshHostSelect.value;

    el.sshHostSelect.innerHTML = '<option value="">— no filter —</option>';
    const aliases = Object.keys(hosts).filter(k => k !== "*").sort();
    for (const alias of aliases) {
      const opt = document.createElement("option");
      opt.value = alias;
      opt.textContent = alias;
      el.sshHostSelect.appendChild(opt);
    }

    // Auto-select first real host on initial load
    if (!existing && aliases.length > 0) {
      el.sshHostSelect.value = aliases[0];
      state.sshHost = aliases[0];
      const user = (hosts[aliases[0]] || {}).user || "";
      if (user) {
        el.frameUserInput.value = user;
        state.frameUser = user;
      }
    } else {
      el.sshHostSelect.value = existing;
      state.sshHost = existing;
    }
  } catch (_) {
    // SSH config is optional – silently ignore
  }
}

/* ============================================================
   Pickle loading
   ============================================================ */

async function loadPickleByPath(path) {
  setStatus(`Loading ${path}…`);
  try {
    const data = await API.post("/api/pickle", { path });
    await onPickleLoaded(data, path);
  } catch (e) {
    setStatus(`Error loading pickle: ${e.message}`, true);
  }
}

async function uploadPickle(file) {
  setStatus(`Uploading ${file.name}…`);
  const form = new FormData();
  form.append("file", file);
  try {
    const data = await API.upload("/api/pickle/upload", form);
    await onPickleLoaded(data, file.name);
  } catch (e) {
    setStatus(`Error uploading pickle: ${e.message}`, true);
  }
}

async function onPickleLoaded(data, source) {
  state.views = data.views || [];
  state.currentView = null;
  state.page = 0;
  state.selectedAbsIndex = null;
  state.selectedPageIndex = null;

  // Rebuild view selector
  el.viewSelect.innerHTML = "";
  for (const v of state.views) {
    const opt = document.createElement("option");
    opt.value = v;
    opt.textContent = v;
    el.viewSelect.appendChild(opt);
  }

  if (state.views.length === 0) {
    el.viewSelect.innerHTML = '<option value="">— no table-like data found —</option>';
    el.viewSelect.disabled = true;
    el.searchInput.disabled = true;
    el.clearSearchBtn.disabled = true;
    setStatus(`Loaded ${source} – no table-like data found`, true);
    return;
  }

  el.viewSelect.disabled = false;
  el.searchInput.disabled = false;
  el.clearSearchBtn.disabled = false;

  // Prefer device_traces[0], otherwise first view
  const preferred = state.views.find(v => v === "device_traces[0]") || state.views[0];
  el.viewSelect.value = preferred;
  state.currentView = preferred;
  state.search = "";
  el.searchInput.value = "";

  await loadView();
  setStatus(`Loaded: ${source}`);
}

/* ============================================================
   View loading
   ============================================================ */

async function loadView() {
  if (!state.currentView) return;

  const params = new URLSearchParams({
    name: state.currentView,
    search: state.search,
    page: state.page,
    per_page: state.perPage,
  });

  try {
    const data = await API.get(`/api/view?${params}`);
    state.total   = data.total   || 0;
    state.columns = data.columns || [];
    state.rows    = data.rows    || [];

    renderTable();
    updateCountLabel();
    updatePagination();

    if (state.rows.length > 0) {
      // Try to keep the previous selection; otherwise select first row
      const keepIndex = (state.selectedAbsIndex !== null &&
        state.selectedAbsIndex >= state.page * state.perPage &&
        state.selectedAbsIndex < state.page * state.perPage + state.rows.length)
        ? state.selectedAbsIndex - state.page * state.perPage
        : 0;
      selectRow(keepIndex);
    } else {
      state.selectedAbsIndex = null;
      state.selectedPageIndex = null;
      el.detailsContent.textContent = "No rows match the current filter.";
    }
  } catch (e) {
    setStatus(`Error loading view: ${e.message}`, true);
  }
}

/* ============================================================
   Table rendering
   ============================================================ */

function renderTable() {
  // ---- Header ----
  const headerRow = document.createElement("tr");
  const thNum = document.createElement("th");
  thNum.textContent = "#";
  headerRow.appendChild(thNum);

  for (const col of state.columns) {
    const th = document.createElement("th");
    th.textContent = col;
    th.title = col;
    headerRow.appendChild(th);
  }

  el.tableHead.innerHTML = "";
  el.tableHead.appendChild(headerRow);

  // ---- Body ----
  const fragment = document.createDocumentFragment();
  const pageStart = state.page * state.perPage;

  state.rows.forEach((row, pageIdx) => {
    const tr = document.createElement("tr");
    tr.dataset.pageIndex = pageIdx;
    tr.dataset.absIndex  = pageStart + pageIdx;

    if (pageStart + pageIdx === state.selectedAbsIndex) {
      tr.classList.add("selected");
    }

    tr.addEventListener("click", () => selectRow(pageIdx));

    // Row number cell
    const tdNum = document.createElement("td");
    tdNum.className = "row-num";
    tdNum.textContent = pageStart + pageIdx;
    tr.appendChild(tdNum);

    // Data cells
    for (const col of state.columns) {
      const td = document.createElement("td");
      const val = row[col];
      const text = formatValue(val);
      td.title = text;
      td.textContent = truncate(text, 80);
      if (typeof val === "number") td.classList.add("num");
      tr.appendChild(td);
    }

    fragment.appendChild(tr);
  });

  el.tableBody.innerHTML = "";
  el.tableBody.appendChild(fragment);
}

function updateCountLabel() {
  const total = state.total;
  if (total === 0) {
    el.countLabel.textContent = "0 rows";
    return;
  }
  const start = state.page * state.perPage + 1;
  const end   = Math.min(start + state.rows.length - 1, total);
  if (total <= state.perPage && state.page === 0) {
    el.countLabel.textContent = `${total} rows`;
  } else {
    el.countLabel.textContent = `${start}–${end} of ${total}`;
  }
}

function updatePagination() {
  const totalPages = Math.max(1, Math.ceil(state.total / state.perPage));
  el.pageInfo.textContent = `Page ${state.page + 1} / ${totalPages}`;
  el.prevPageBtn.disabled = state.page === 0;
  el.nextPageBtn.disabled = state.page >= totalPages - 1;
}

/* ============================================================
   Row selection & detail loading
   ============================================================ */

function selectRow(pageIdx) {
  const oldSel = el.tableBody.querySelector("tr.selected");
  if (oldSel) oldSel.classList.remove("selected");

  const tr = el.tableBody.querySelector(`tr[data-page-index="${pageIdx}"]`);
  if (!tr) return;

  tr.classList.add("selected");
  state.selectedPageIndex = pageIdx;
  state.selectedAbsIndex  = parseInt(tr.dataset.absIndex, 10);

  loadRowDetails(state.selectedAbsIndex);
}

async function loadRowDetails(absIndex) {
  if (!state.currentView) return;

  const params = new URLSearchParams({
    view:     state.currentView,
    index:    absIndex,
    search:   state.search,
    username: state.frameUser,
    ssh_host: state.sshHost,
  });

  try {
    const data = await API.get(`/api/row?${params}`);
    renderDetails(data);
  } catch (e) {
    el.detailsContent.textContent = `Error fetching row details:\n${e.message}`;
  }
}

function renderDetails(data) {
  const { row, user_frames, source_lines } = data;
  const username = state.frameUser;
  const sshHost  = state.sshHost;
  const lines    = [];

  // ── User code frames ──
  if (user_frames && user_frames.length > 0) {
    const header = sshHost
      ? `=== User Code Frames  [${sshHost} / ${username}] ===`
      : `=== User Code Frames  [${username}] ===`;
    lines.push(header);

    user_frames.forEach((fr, i) => {
      const fn   = fr.filename || "?";
      const ln   = fr.line     || 0;
      const name = fr.name     || "";
      lines.push(`  [${i + 1}] ${fn}:${ln}  —  ${name}`);
      const src = source_lines && source_lines[`${fn}:${ln}`];
      if (src != null) {
        lines.push(`       |  ${src}`);
      }
    });

    lines.push("");
  } else if (username && row.frames) {
    lines.push(`=== User Code Frames  (no match for '${username}') ===`);
    lines.push("");
  }

  // ── Full row data ──
  lines.push("=== Full Row Data ===");
  try {
    lines.push(JSON.stringify(row, null, 2));
  } catch (_) {
    lines.push(String(row));
  }

  el.detailsContent.textContent = lines.join("\n");
}

/* ============================================================
   Event handlers
   ============================================================ */

// Open pickle via file input
el.openPickleBtn.addEventListener("click", () => el.pickleFileInput.click());

el.pickleFileInput.addEventListener("change", (e) => {
  const file = e.target.files && e.target.files[0];
  if (file) uploadPickle(file);
  // Reset so the same file can be re-selected
  e.target.value = "";
});

// View selector
el.viewSelect.addEventListener("change", async () => {
  state.currentView = el.viewSelect.value;
  state.page        = 0;
  state.selectedAbsIndex = null;
  await loadView();
});

// Search (debounced 400 ms)
el.searchInput.addEventListener("input", () => {
  clearTimeout(state._searchTimer);
  state._searchTimer = setTimeout(async () => {
    state.search = el.searchInput.value;
    state.page   = 0;
    state.selectedAbsIndex = null;
    await loadView();
  }, 400);
});

el.clearSearchBtn.addEventListener("click", async () => {
  el.searchInput.value = "";
  state.search = "";
  state.page   = 0;
  state.selectedAbsIndex = null;
  await loadView();
});

// Pagination
el.prevPageBtn.addEventListener("click", async () => {
  if (state.page > 0) { state.page--; await loadView(); }
});

el.nextPageBtn.addEventListener("click", async () => {
  const totalPages = Math.ceil(state.total / state.perPage);
  if (state.page < totalPages - 1) { state.page++; await loadView(); }
});

// SSH host selection
el.sshHostSelect.addEventListener("change", async () => {
  state.sshHost = el.sshHostSelect.value;
  // Auto-fill frame user from the host's User field
  const cfg = state._sshHosts[state.sshHost] || {};
  if (cfg.user) {
    el.frameUserInput.value = cfg.user;
    state.frameUser = cfg.user;
  }
  if (state.selectedAbsIndex !== null) await loadRowDetails(state.selectedAbsIndex);
});

// Frame user filter
el.frameUserInput.addEventListener("input", async () => {
  state.frameUser = el.frameUserInput.value;
  if (state.selectedAbsIndex !== null) await loadRowDetails(state.selectedAbsIndex);
});

/* ============================================================
   Startup
   ============================================================ */

async function init() {
  await loadSSHHosts();

  // Auto-load pickle if its path was passed via URL query string ?pickle=...
  const params = new URLSearchParams(window.location.search);
  // URLSearchParams.get() already decodes percent-encoding; no extra call needed
  const picklePath = params.get("pickle");
  if (picklePath) {
    await loadPickleByPath(picklePath);
  }
}

init().catch(e => setStatus(`Startup error: ${e.message}`, true));
