let appReady = false;
let appView = "history";
let reportReturnHash = "#history";
let reportSessionId = "";
let reportRequestVersion = 0;
let historyRequestVersion = 0;
const sessionHistoryState = {
  sessions: [], query: "", sort: "date", direction: -1, page: 1, pageSize: 10,
};

function showNewSessionForm() {
  const dialog = document.getElementById("newSessionDialog");
  if (!dialog.open) dialog.showModal();
  document.getElementById("sessionNameInput")?.focus();
}

function closeNewSessionForm() {
  document.getElementById("newSessionDialog")?.close();
}

function showSessionHistory() {
  closeNewSessionForm();
  showAppView("history");
}

function showAppView(view) {
  const changed = appView !== view;
  if (view !== "report") {
    reportRequestVersion += 1;
    latestExportData = null;
  }
  appView = view;
  for (const [name, id] of [["history", "labMenu"], ["analysis", "labInterface"], ["report", "reportPage"]]) {
    document.getElementById(id)?.classList.toggle("hidden", name !== view);
  }
  window.scrollTo(0, 0);
  if (changed) {
    const heading = { history: "historyTitle", analysis: "currentLabName", report: "reportPageTitle" }[view];
    document.getElementById(heading)?.focus({ preventScroll: true });
  }
}

function navigateApp(hash, { replace = false } = {}) {
  if (window.location.hash !== hash) {
    window.history[replace ? "replaceState" : "pushState"](null, "", hash);
  }
  return applyAppRoute();
}

async function applyAppRoute() {
  if (!appReady) return;
  const hash = window.location.hash;
  if (hash.startsWith("#report/")) {
    let id;
    try { id = decodeURIComponent(hash.slice(8)); } catch { id = ""; }
    if (id) {
      if (appView !== "report") {
        reportReturnHash = appView === "analysis" && currentLab ? "#analysis" : "#history";
      }
      const item = sessionHistoryState.sessions.find((session) => session.id === id);
      return exportReport(id, item?.name || (id === currentLab ? currentSessionName : ""), false);
    }
  }
  if (hash === "#analysis" && currentLab) {
    showAppView("analysis");
    return;
  }
  if (currentLab) {
    await backToMenu(false);
    return;
  }
  window.history.replaceState(null, "", "#history");
  showSessionHistory();
}

function backFromReport() {
  return navigateApp(reportReturnHash, { replace: true });
}

function retryReport() {
  return exportReport(reportSessionId, "", false);
}

function historyDate(item) {
  const date = new Date(item.recording_started_at || item.created_at);
  return Number.isFinite(date.getTime()) ? date : null;
}

function historyNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function historySortValue(item, key) {
  const date = historyDate(item);
  if (key === "date") return date?.getTime() ?? null;
  if (key === "time") return date ? date.getHours() * 60 + date.getMinutes() : null;
  if (key === "people") return historyNumber(item.report_total_people);
  if (key === "attention") return historyNumber(item.avg_attention_rate);
  return item.name || item.id;
}

function filterAndSortSessions(state) {
  const query = state.query.trim().toLocaleLowerCase("th-TH");
  return state.sessions.filter((item) => {
    const date = historyDate(item);
    const haystack = [item.name, item.id, item.course_name, item.room_name,
      date?.toLocaleDateString("th-TH"), date?.toLocaleDateString("en-GB"),
      item.recording_started_at, item.source_type === "video" ? "วิดีโอ" : "เว็บแคม"];
    return haystack.join(" ").toLocaleLowerCase("th-TH").includes(query);
  }).sort((left, right) => {
    const a = historySortValue(left, state.sort);
    const b = historySortValue(right, state.sort);
    // Missing measurements stay at the end in either sort direction.
    if (a === null && b !== null) return 1;
    if (b === null && a !== null) return -1;
    const compared = typeof a === "string" ? a.localeCompare(b, "th", { numeric: true }) : (a ?? 0) - (b ?? 0);
    return compared * state.direction || String(left.id).localeCompare(String(right.id));
  });
}

function renderSessionHistory() {
  const state = sessionHistoryState;
  const rows = filterAndSortSessions(state);
  const pages = Math.max(1, Math.ceil(rows.length / state.pageSize));
  state.page = Math.min(pages, Math.max(1, state.page));
  const offset = (state.page - 1) * state.pageSize;
  const body = document.getElementById("sessionHistory");
  body.replaceChildren();
  for (const item of rows.slice(offset, offset + state.pageSize)) {
    const row = document.createElement("tr");
    row.dataset.sessionId = item.id;
    const date = historyDate(item);
    const people = historyNumber(item.report_total_people);
    const attention = historyNumber(item.avg_attention_rate);
    row.innerHTML = `
      <td class="max-w-xs"><a class="font-semibold text-blue-700 hover:underline break-words" href="#report/${encodeURIComponent(item.id)}">${escapeHtml(item.name || item.id)}</a>
        <p class="mt-1 text-xs text-gray-500 break-words">${escapeHtml(item.course_name || "ไม่ระบุวิชา")} | ${escapeHtml(item.room_name || "ไม่ระบุห้อง")}</p></td>
      <td class="whitespace-nowrap">${date ? date.toLocaleDateString("th-TH") : "-"}</td>
      <td class="whitespace-nowrap">${date ? date.toLocaleTimeString("th-TH", { hour: "2-digit", minute: "2-digit" }) : "-"}</td>
      <td class="text-center tabular-nums">${people === null ? "-" : toWholePeople(people)}</td>
      <td class="text-right tabular-nums font-medium">${attention === null ? "-" : `${formatDecimal(attention)}%`}</td>
      <td class="whitespace-nowrap"><span>${item.source_type === "video" ? "วิดีโอ" : "เว็บแคม"}</span><p class="mt-1 text-xs text-gray-500">${item.storage === "supabase" ? "คลาวด์" : "ในเครื่อง"}</p></td>
      <td><a href="#report/${encodeURIComponent(item.id)}" class="text-blue-700 hover:underline whitespace-nowrap" aria-label="ดูรายงาน ${escapeHtml(item.name || item.id)}">ดูรายงาน &#8594;</a></td>`;
    row.addEventListener("click", (event) => {
      if (!event.target.closest("a, button") && !window.getSelection()?.toString()) {
        navigateApp(`#report/${encodeURIComponent(item.id)}`);
      }
    });
    body.append(row);
  }
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="7" class="text-center text-gray-500">${state.sessions.length ? "ไม่พบรอบวิเคราะห์ที่ตรงกับคำค้น" : "ยังไม่มีรอบวิเคราะห์ที่บันทึกไว้"}</td></tr>`;
  }
  setTextIfPresent("historyResultCount", rows.length ? `${offset + 1}-${Math.min(offset + state.pageSize, rows.length)} จาก ${rows.length} รอบ` : "0 รอบ");
  setTextIfPresent("historyPageNumber", `${state.page} / ${pages}`);
  document.getElementById("historyPreviousBtn").disabled = state.page <= 1;
  document.getElementById("historyNextBtn").disabled = state.page >= pages;
  for (const heading of document.querySelectorAll("[data-history-sort]")) {
    const selected = heading.dataset.historySort === state.sort;
    heading.setAttribute("aria-sort", selected ? (state.direction === 1 ? "ascending" : "descending") : "none");
    heading.querySelector("span").textContent = selected ? (state.direction === 1 ? "\u2191" : "\u2193") : "";
  }
}

async function loadSessionHistory() {
  const request = ++historyRequestVersion;
  const refresh = document.getElementById("historyRefreshBtn");
  refresh.disabled = true;
  setTextIfPresent("historyStatus", "กำลังโหลดประวัติ...");
  try {
    const response = await apiFetch("/api/sessions");
    if (!response.ok) throw new Error("ไม่สามารถโหลดประวัติได้ กรุณาลองรีเฟรชอีกครั้ง");
    const payload = await response.json();
    if (request !== historyRequestVersion) return;
    sessionHistoryState.sessions = payload.sessions || [];
    renderSessionHistory();
    setTextIfPresent("historyStatus", payload.archive_error ? "เชื่อมข้อมูลบนคลาวด์ไม่ได้ กำลังแสดงรอบที่เก็บในเครื่อง" : "");
  } catch (error) {
    if (request === historyRequestVersion) {
      renderSessionHistory();
      setTextIfPresent("historyStatus", error.message);
    }
  } finally {
    if (request === historyRequestVersion) refresh.disabled = false;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("newSessionForm").addEventListener("submit", (event) => {
    event.preventDefault();
    startSession();
  });
  document.getElementById("historySearch").addEventListener("input", (event) => {
    sessionHistoryState.query = event.target.value;
    sessionHistoryState.page = 1;
    renderSessionHistory();
  });
  document.getElementById("historyPageSize").addEventListener("change", (event) => {
    sessionHistoryState.pageSize = Number(event.target.value);
    sessionHistoryState.page = 1;
    renderSessionHistory();
  });
  for (const [id, delta] of [["historyPreviousBtn", -1], ["historyNextBtn", 1]]) {
    document.getElementById(id).addEventListener("click", () => {
      sessionHistoryState.page += delta;
      renderSessionHistory();
    });
  }
  for (const heading of document.querySelectorAll("[data-history-sort]")) {
    heading.querySelector("button").addEventListener("click", () => {
      const state = sessionHistoryState;
      state.direction = state.sort === heading.dataset.historySort ? -state.direction : 1;
      state.sort = heading.dataset.historySort;
      state.page = 1;
      renderSessionHistory();
    });
  }
  renderSessionHistory();
});

document.addEventListener("classmood:ready", () => {
  appReady = true;
  loadSessionHistory();
  applyAppRoute();
});
document.addEventListener("classmood:locked", () => {
  appReady = false;
  historyRequestVersion += 1;
  reportRequestVersion += 1;
  latestExportData = null;
  sessionHistoryState.sessions = [];
  closeNewSessionForm();
  renderSessionHistory();
});
window.addEventListener("hashchange", applyAppRoute);
