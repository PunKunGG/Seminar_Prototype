let currentCamera = 1;
let currentLab = "";
let currentSessionName = "";
let currentRoomName = "";
let currentCourseName = "";
let currentRecordingStart = "";
let currentAnalysisInterval = 30;
let selectedSourceMode = "video";
let useBehaviorMode = true; // ✅ เปิดโหมดวิเคราะห์พฤติกรรมเป็นค่าเริ่มต้น
let liveFeedInterval = null;
let lastAlertId = 0; // ID สุดท้ายที่ได้รับเพื่อหลีกเอา alert ซ้ำ
let alertPollInterval = null; // setInterval handle สำหรับดึง alerts
let alertCursorReady = false;
let alertPollGeneration = 0;
let alertPollRequest = null;
let latestExportData = null; // เก็บข้อมูลล่าสุดสำหรับ export
let sourceStatusInterval = null;
let currentSourceType = null;
let autoReportShown = false;
let sessionCompleted = false;
let streamReloadToken = 0;
const API_BASE =
  window.location.protocol === "file:" ? "http://127.0.0.1:5000" : window.location.origin;

function apiUrl(path) {
  return `${API_BASE}${path}`;
}

function apiFetch(path, options = {}) {
  return fetch(apiUrl(path), {
    ...options,
    credentials: "include",
  });
}

function setTextIfPresent(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

function setConnectionStatus(text, colorClass = "text-gray-500") {
  const el = document.getElementById("connectionStatus");
  if (!el) return;
  el.textContent = text;
  el.className = `${colorClass} font-medium`;
}

function formatVideoTime(seconds) {
  const total = Math.max(0, Math.round(Number(seconds) || 0));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  return [hours, minutes, secs]
    .map((value) => String(value).padStart(2, "0"))
    .join(":");
}

function toWholePeople(value) {
  return Math.max(0, Math.round(Number(value) || 0));
}

function getReportBehavior(summary = {}) {
  if (latestExportData?.qualified_analysis) {
    return Object.fromEntries(Object.entries(latestExportData.qualified_analysis.summary.behavior_seconds)
      .map(([key, seconds]) => [key, Number(seconds) / 60]));
  }
  return (
    summary.report_summary ||
    summary.overall_summary ||
    summary.latest_summary ||
    {}
  );
}

function getReportBehaviorTitle(summary = {}) {
  if (latestExportData?.qualified_analysis) return "พฤติกรรมที่ผ่านเกณฑ์ (นาทีรวมทุก ID)";
  if (summary.report_summary_scope !== "peak_concurrent_people") {
    return "ภาพรวมพฤติกรรม";
  }

  const base = "พฤติกรรมช่วงที่ตรวจพบคนสูงสุด";
  if (summary.report_video_position_seconds != null) {
    return `${base} (${formatVideoTime(summary.report_video_position_seconds)})`;
  }
  if (summary.report_summary_time) {
    return `${base} (${summary.report_summary_time})`;
  }
  return base;
}

function formatDecimal(value) {
  const number = Number(value) || 0;
  return number.toFixed(1).replace(/\.0$/, "");
}

function formatDuration(seconds) {
  const total = Math.max(0, Math.round(Number(seconds) || 0));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  if (hours > 0) return `${hours} ชม. ${minutes} นาที`;
  if (minutes > 0) return `${minutes} นาที ${secs} วินาที`;
  return `${secs} วินาที`;
}

function formatAttention(value) {
  return value == null ? "-" : `${formatDecimal(value)}%`;
}

function reportTrackingData(data = latestExportData) {
  const raw = data?.tracking || {};
  return data?.qualified_analysis
    ? { ...raw, ...data.qualified_analysis, is_qualified: true, report_policy: data.report_policy }
    : raw;
}

function reportEvidenceData(data = latestExportData) {
  return data?.tracking || {};
}

function reportPeriodData(data = latestExportData) {
  if (!data?.qualified_analysis) return data?.periods || [];
  const qualified = new Map(data.qualified_analysis.periods.map(item => [item.start_seconds, item]));
  return (data.periods || []).map(period => {
    const metrics = qualified.get(period.start_seconds);
    return { ...period, is_qualified: true, avg_attention_rate: metrics?.attention_rate ?? null,
      summary: metrics?.behavior_seconds || {} };
  });
}

function representativeImages(tracking = {}) {
  const images = new Map((tracking.representative_evidence || []).map(item => [Number(item.track_id), item]));
  for (const item of tracking.evidence || []) {
    if (!images.has(Number(item.track_id)) && item.evidence_key !== "portrait") images.set(Number(item.track_id), item);
  }
  for (const item of tracking.evidence || []) {
    if (!images.has(Number(item.track_id))) images.set(Number(item.track_id), item);
  }
  return images;
}

function reportPortrait(track, image) {
  const id = toWholePeople(track.track_id);
  const placeholder = '<span class="evidence-placeholder">ไม่มีภาพ</span>';
  if (!image?.url) return `<span class="report-portrait">${placeholder}</span>`;
  return `<button type="button" class="report-portrait" data-evidence-url="${escapeHtml(apiUrl(image.url))}"
    data-evidence-title="${escapeHtml(`ID ${id} | ${image.captured_time || "-"} | ${behaviorLabel(image.behavior)}`)}"
    title="ดูภาพหลักฐาน ID ${id}" aria-label="ดูภาพหลักฐาน ID ${id}">
    ${placeholder}<img src="${escapeHtml(apiUrl(image.thumbnail_url || image.url))}" alt="ภาพ ID ${id}" width="80" height="80" />
    </button>`;
}

function behaviorLabel(value) {
  return {
    attentive: "ตั้งใจเรียน",
    sleeping: "ท่าเข้าข่ายหลับ",
    looking_down: "ก้มหน้า",
    phone_use: "ใช้โทรศัพท์",
    phone_suspected: "สงสัยใช้โทรศัพท์",
    hand_raised: "ยกมือ",
    standing: "ยืน/ลุก",
    unknown: "ไม่ชัดเจน",
  }[value] || value || "-";
}

function formatReportDateTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString("th-TH", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatRecordingPeriod(session = {}) {
  const start = session.recording_started_at;
  const end = session.recording_ended_at || session.ended_at;
  if (!start) return "-";
  const startLabel = formatReportDateTime(start);
  const endLabel = end ? formatReportDateTime(end) : "กำลังวิเคราะห์";
  const startDate = new Date(start);
  const endDate = new Date(end || Date.now());
  const duration = endDate.getTime() - startDate.getTime();
  const durationLabel = Number.isFinite(duration) && duration >= 0
    ? ` (${formatDuration(duration / 1000)})`
    : "";
  return `${startLabel} - ${endLabel}${durationLabel}`;
}

function reportMinimumSeconds(behavior) {
  const policy = latestExportData?.report_policy;
  const override = policy?.version >= 3 ? policy.minimum_behavior_seconds_by_behavior?.[behavior] : null;
  return Number(override ?? policy?.minimum_behavior_seconds ?? 30);
}

function formatBehaviorMetric(track, behavior) {
  const count = toWholePeople(track?.event_counts?.[behavior]);
  if (!count) return "-";
  const seconds = track?.behavior_seconds?.[behavior];
  const duration = track?.qualified_seconds != null
    ? `${formatDecimal((Number(seconds) || 0) / 60)} นาที` : formatDuration(seconds);
  return `<span class="block">${count} ครั้ง</span><span class="block mt-1 text-gray-500">${duration}</span>`;
}

function renderLiveTracks(tracks = []) {
  const body = document.getElementById("liveTrackRows");
  const empty = document.getElementById("liveTrackEmpty");
  if (!body || !empty) return;

  const sorted = [...tracks].sort(
    (left, right) => Number(left.track_id) - Number(right.track_id),
  );
  empty.classList.toggle("hidden", sorted.length > 0);
  body.innerHTML = sorted
    .map((track) => {
      const counts = track.event_counts || {};
      return `
        <tr class="border-t border-gray-100">
          <td class="px-3 py-2 font-semibold text-blue-700 whitespace-nowrap">ID ${toWholePeople(track.track_id)}</td>
          <td class="px-3 py-2 whitespace-nowrap">${escapeHtml(behaviorLabel(track.current_behavior))}</td>
          <td class="px-3 py-2 text-right whitespace-nowrap">${formatDuration(track.visible_seconds)}</td>
          <td class="px-3 py-2 text-right font-semibold text-green-700">${formatDecimal(track.attention_rate)}%</td>
          <td class="px-3 py-2 text-right">${toWholePeople(counts.sleeping)}</td>
          <td class="px-3 py-2 text-right">${toWholePeople(counts.looking_down)}</td>
          <td class="px-3 py-2 text-right">${toWholePeople(counts.phone_use)}</td>
          <td class="px-3 py-2 text-right">${toWholePeople(counts.phone_suspected)}</td>
          <td class="px-3 py-2 text-right">${toWholePeople(counts.hand_raised)}</td>
          <td class="px-3 py-2 text-right">${toWholePeople(counts.standing)}</td>
        </tr>
      `;
    })
    .join("");
}

function renderTrackingReport(tracking = null) {
  const section = document.getElementById("reportTrackingSection");
  const body = document.getElementById("reportTrackingRows");
  if (!section || !body) return;

  const rows = tracking?.tracks || [];
  const images = representativeImages(tracking || {});
  const keys = ["attentive", "sleeping", "looking_down", "phone_use", "phone_suspected", "hand_raised", "standing", "unknown"]
    .filter(key => rows.some(track => toWholePeople(track.event_counts?.[key]) > 0));
  const head = document.getElementById("reportTrackingHead");
  if (head) head.innerHTML = `<tr><th class="px-3 py-2 text-center">ภาพ / ID</th><th class="px-3 py-2 text-right">เวลาวิเคราะห์รวม</th><th class="px-3 py-2 text-right">ตั้งใจ (%)</th>${keys.map(key => `<th class="px-3 py-2 text-right">${escapeHtml(behaviorLabel(key))}</th>`).join("")}</tr>`;
  const table = head?.closest("table");
  if (table) table.style.minWidth = `${Math.max(520, 320 + keys.length * 100)}px`;
  setTextIfPresent("reportTrackingCaption", tracking?.is_qualified
    ? (keys.length ? "จำนวนครั้ง / เวลาที่ผ่านเกณฑ์รายพฤติกรรม" : "ไม่มีช่วงพฤติกรรมผ่านเกณฑ์รายงาน") : "จำนวนครั้ง / ระยะเวลาที่วิเคราะห์ได้ตลอดคาบ");

  section.classList.toggle("hidden", rows.length === 0);
  body.innerHTML = rows
    .map((track, index) => {
      const rowClass = index % 2 === 0 ? "bg-white" : "bg-gray-50";
      return `
        <tr class="${rowClass}">
          <td class="px-3 py-2 font-semibold text-blue-700 text-center whitespace-nowrap">${reportPortrait(track, images.get(Number(track.track_id)))}<span class="block mt-1">ID ${toWholePeople(track.track_id)}</span></td>
          <td class="px-3 py-2 text-right whitespace-nowrap">${formatDuration(track.visible_seconds)}${tracking.is_qualified ? `<span class="block mt-1 text-gray-500">ผ่านเกณฑ์ ${formatDuration(track.qualified_seconds)}</span>` : ""}</td>
          <td class="px-3 py-2 text-right font-semibold text-green-700">${formatAttention(track.attention_rate)}${tracking.is_qualified && track.attention_rate == null ? '<span class="block mt-1 font-normal text-gray-500" title="ไม่มีช่วงพฤติกรรมที่ผ่านเกณฑ์รายงาน">เวลาไม่พอ</span>' : ""}</td>
          ${keys.map(key => `<td class="px-3 py-2 text-right whitespace-nowrap">${formatBehaviorMetric(track, key)}</td>`).join("")}
        </tr>
      `;
    })
    .join("");
}

function renderAnalysisMethodology(methodology = null) {
  const section = document.getElementById("reportMethodologySection");
  const body = document.getElementById("reportMethodologyRows");
  const limitations = document.getElementById("reportMethodologyLimitations");
  if (!section || !body || !limitations) return;

  const criteria = methodology?.criteria || [];
  setTextIfPresent("reportSummaryInterval", methodology
    ? `ช่วงสรุปผลที่เลือก: ${formatDecimal(methodology.realtime_summary_interval_seconds)} วินาที (แยกจากเวลายืนยันสถานะและเกณฑ์รายงาน)` : "");
  section.classList.toggle("hidden", criteria.length === 0);
  setTextIfPresent(
    "reportAttentionFormula",
    `สูตรอัตราความตั้งใจ: ${methodology?.attention_formula || "-"}`,
  );
  setTextIfPresent(
    "reportMethodologyCaption",
    methodology
      ? `${methodology.pose_model || "Pose"} | ตรวจคน >= ${formatDecimal((methodology.person_detection_confidence || 0) * 100)}% | keypoint >= ${formatDecimal((methodology.keypoint_confidence || 0) * 100)}% | ตรวจวัตถุ >= ${formatDecimal((methodology.context_detection_confidence || 0) * 100)}% ทุก ${formatDecimal(methodology.context_detection_interval_seconds)} วินาที`
      : "อ้างอิงจากค่าที่ระบบใช้ในรอบนี้",
  );
  body.innerHTML = criteria
    .map((item, index) => `
      <tr class="${index % 2 === 0 ? "bg-white" : "bg-gray-50"}">
        <td class="px-3 py-2 font-semibold text-gray-800 whitespace-nowrap">${escapeHtml(item.behavior === "sleeping" ? behaviorLabel(item.behavior) : item.label || behaviorLabel(item.behavior))}</td>
        <td class="px-3 py-2 text-gray-700">
          <p>${escapeHtml(item.measurement || "-")}</p>
          <p class="mt-1 text-gray-500">เกณฑ์: ${escapeHtml(item.decision_rule || "-")}</p>
        </td>
        <td class="px-3 py-2 text-right whitespace-nowrap">${formatDecimal(item.confirmation_seconds)} วินาที</td>
        <td class="px-3 py-2 text-right whitespace-nowrap">${item.report_minimum_seconds != null ? `${formatDecimal(item.report_minimum_seconds)} วินาทีที่ตรวจจริง` : (latestExportData?.report_policy ? `${formatDecimal(reportMinimumSeconds(item.behavior))} วินาทีที่ตรวจจริง` : "ไม่คัดช่วง")}</td>
        <td class="px-3 py-2 text-gray-600">${escapeHtml(item.limitation || "-")}</td>
      </tr>
    `)
    .join("");
  limitations.innerHTML = (methodology?.limitations || [])
    .map((item) => `<li>${escapeHtml(item)}</li>`)
    .join("");
}



function hasExcessivePortraitPadding(pixels, width, height) {
  let left = width, top = height, right = -1, bottom = -1;
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const offset = (y * width + x) * 4;
      if (Math.abs(pixels[offset] - 245) <= 6
          && Math.abs(pixels[offset + 1] - 245) <= 6
          && Math.abs(pixels[offset + 2] - 245) <= 6) continue;
      left = Math.min(left, x); right = Math.max(right, x);
      top = Math.min(top, y); bottom = Math.max(bottom, y);
    }
  }
  // Only reject the old generated padding, never crop or infer a face from pixels.
  return left > 0 && top > 0 && right < width - 1 && bottom < height - 1
    && (right - left + 1) * (bottom - top + 1) < width * height * 0.25;
}

function useOriginalForPaddedPortrait(image, originalUrl) {
  if (image.src === originalUrl || !image.naturalWidth || image.naturalWidth !== image.naturalHeight) return false;
  try {
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = 80;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    if (!context) return false;
    context.drawImage(image, 0, 0, 80, 80);
    if (hasExcessivePortraitPadding(context.getImageData(0, 0, 80, 80).data, 80, 80)) {
      image.src = originalUrl;
      return true;
    }
  } catch {
    // A cross-origin image without canvas access remains viewable as saved.
  }
  return false;
}

function setupEvidenceViewer() {
  const dialog = document.getElementById("evidenceDialog");
  if (!dialog) return;
  let opener = null;
  document.getElementById("evidenceCloseButton").addEventListener("click", () => dialog.close());
  dialog.addEventListener("close", () => {
    document.getElementById("evidenceFullImage").removeAttribute("src");
    if (opener?.isConnected) opener.focus();
    opener = null;
  });
  document.getElementById("reportTrackingRows").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-evidence-url]");
    if (!button || button.disabled) return;
    opener = button;
    const image = document.getElementById("evidenceFullImage");
    image.src = button.dataset.evidenceUrl;
    image.alt = button.dataset.evidenceTitle;
    setTextIfPresent("evidenceDialogTitle", button.dataset.evidenceTitle);
    dialog.showModal();
  });
  document.getElementById("reportTrackingRows").addEventListener("load", (event) => {
    if (event.target.tagName !== "IMG") return;
    const button = event.target.closest("button[data-evidence-url]");
    if (button) useOriginalForPaddedPortrait(event.target, button.dataset.evidenceUrl);
  }, true);
  document.getElementById("reportTrackingRows").addEventListener("error", (event) => {
    if (event.target.tagName !== "IMG") return;
    const button = event.target.closest("button");
    if (button && event.target.src !== button.dataset.evidenceUrl) {
      event.target.src = button.dataset.evidenceUrl;
      return;
    }
    event.target.hidden = true;
    if (button) { button.disabled = true; button.setAttribute("aria-label", "ไม่มีภาพหลักฐาน"); }
  }, true);
}

const BEHAVIOR_EVENT_PAGE_SIZE = 25;
let behaviorEventView = { includeExcluded: false, trackId: "", behavior: "", page: 1 };

function resetBehaviorEventView() {
  behaviorEventView = { includeExcluded: false, trackId: "", behavior: "", page: 1 };
}

function behaviorEventKey(event) {
  return `${Number(event.track_id)}:${Number(event.event_index)}`;
}

function behaviorEventPage(tracking = {}, qualified = null, view = behaviorEventView) {
  const accepted = new Set((qualified?.events || []).map(behaviorEventKey));
  const filtered = (tracking?.events || []).map((event, rawIndex) => ({
    event, rawIndex, accepted: !qualified || accepted.has(behaviorEventKey(event)),
  })).filter(item => (!qualified || view.includeExcluded || item.accepted)
    && (!view.trackId || String(item.event.track_id) === view.trackId)
    && (!view.behavior || item.event.behavior === view.behavior));
  const pages = Math.max(1, Math.ceil(filtered.length / BEHAVIOR_EVENT_PAGE_SIZE));
  const page = Math.max(1, Math.min(pages, Math.floor(Number(view.page) || 1)));
  return { items: filtered.slice((page - 1) * BEHAVIOR_EVENT_PAGE_SIZE, page * BEHAVIOR_EVENT_PAGE_SIZE),
    total: filtered.length, page, pages };
}

function formatEventDuration(event) {
  const seconds = Number(event.observed_duration_seconds ?? event.duration_seconds);
  return seconds > 0 && seconds < 1 ? "น้อยกว่า 1 วินาที" : formatDuration(seconds);
}

function setupBehaviorEventControls() {
  for (const [id, key] of [["reportEventsIncludeExcluded", "includeExcluded"],
    ["reportEventsTrack", "trackId"], ["reportEventsBehavior", "behavior"]]) {
    document.getElementById(id)?.addEventListener("change", event => {
      behaviorEventView[key] = key === "includeExcluded" ? event.target.checked : event.target.value;
      behaviorEventView.page = 1;
      renderBehaviorEvents(reportEvidenceData());
    });
  }
  for (const [id, step] of [["reportEventsPrevious", -1], ["reportEventsNext", 1]]) {
    document.getElementById(id)?.addEventListener("click", () => {
      behaviorEventView.page += step;
      renderBehaviorEvents(reportEvidenceData());
    });
  }
}

function renderBehaviorEvents(tracking = null) {
  const section = document.getElementById("reportBehaviorEventsSection");
  const body = document.getElementById("reportBehaviorEventRows");
  const caption = document.getElementById("reportBehaviorEventsCaption");
  if (!section || !body || !caption) return;

  const events = tracking?.events || [];
  const qualified = latestExportData?.qualified_analysis;
  const result = behaviorEventPage(tracking, qualified);
  behaviorEventView.page = result.page;
  section.classList.toggle("hidden", !tracking);
  const include = document.getElementById("reportEventsIncludeExcluded");
  if (include) { include.checked = behaviorEventView.includeExcluded; include.disabled = !qualified; }
  const trackSelect = document.getElementById("reportEventsTrack");
  if (trackSelect) {
    const ids = [...new Set(events.map(event => Number(event.track_id)))].sort((a, b) => a - b);
    trackSelect.innerHTML = '<option value="">ทุก ID</option>' + ids.map(id => `<option value="${id}">ID ${id}</option>`).join("");
    trackSelect.value = behaviorEventView.trackId;
  }
  const behaviorSelect = document.getElementById("reportEventsBehavior");
  if (behaviorSelect) {
    const keys = [...new Set(events.map(event => event.behavior))];
    behaviorSelect.innerHTML = '<option value="">ทุกพฤติกรรม</option>' + keys.map(key => `<option value="${escapeHtml(key)}">${escapeHtml(behaviorLabel(key))}</option>`).join("");
    behaviorSelect.value = behaviorEventView.behavior;
  }
  const first = result.total ? (result.page - 1) * BEHAVIOR_EVENT_PAGE_SIZE + 1 : 0;
  caption.textContent = `แสดง ${first}–${first ? first + result.items.length - 1 : 0} จาก ${result.total} ช่วง | ${qualified ? (behaviorEventView.includeExcluded ? "ผลตรวจดิบ รวมช่วงที่ไม่คิดในรายงาน" : "เฉพาะช่วงที่นับในรายงาน") : "ผลตามเกณฑ์เดิม"}`;
  setTextIfPresent("reportEventsPage", `หน้า ${result.page} / ${result.pages}`);
  const previous = document.getElementById("reportEventsPrevious");
  const next = document.getElementById("reportEventsNext");
  if (previous) previous.disabled = result.page <= 1;
  if (next) next.disabled = result.page >= result.pages;
  body.innerHTML = result.items
    .map(({ event, rawIndex, accepted }, index) => `
      <tr class="${index % 2 === 0 ? "bg-white" : "bg-gray-50"}">
        <td class="px-3 py-2 font-semibold text-blue-700 whitespace-nowrap">ID ${toWholePeople(event.track_id)}</td>
        <td class="px-3 py-2 whitespace-nowrap">${escapeHtml(event.start_time || "-")}</td>
        <td class="px-3 py-2 whitespace-nowrap">${escapeHtml(event.end_time || "-")}</td>
        <td class="px-3 py-2 whitespace-nowrap">${escapeHtml(behaviorLabel(event.behavior))}</td>
        <td class="px-3 py-2 text-right whitespace-nowrap">${formatEventDuration(event)}</td>
        <td class="px-3 py-2 text-right whitespace-nowrap">${formatDecimal(event.avg_confidence)}%</td>
        <td class="px-3 py-2 text-xs ${!accepted ? "text-gray-500" : "text-green-700"}">${qualified ? (accepted ? "นับในรายงาน" : `ไม่คิดในรายงาน (ขั้นต่ำ ${formatDecimal(reportMinimumSeconds(event.behavior))} วินาทีที่ตรวจจริง)`) : "ผลตามเกณฑ์เดิม"}</td>
        <td class="px-3 py-2 evidence-action">${videoEvidenceAction(event, rawIndex)}</td>
      </tr>
    `)
    .join("") || `<tr><td colspan="8" class="px-3 py-6 text-center text-gray-500">${qualified && !behaviorEventView.includeExcluded
      ? "ไม่มีช่วงพฤติกรรมผ่านเกณฑ์ตามตัวกรองนี้ เปิดรวมช่วงที่ไม่ผ่านเกณฑ์เพื่อดูผลตรวจดิบ"
      : "ไม่มีช่วงพฤติกรรมตามตัวกรองนี้"}</td></tr>`;
}

function renderReportTimeline(periods = [], periodSeconds = 300) {
  const section = document.getElementById("reportTimelineSection");
  const body = document.getElementById("reportTimelineBody");
  if (!section || !body) return;

  if (!periods.length) {
    section.classList.add("hidden");
    body.innerHTML = "";
    return;
  }

  section.classList.remove("hidden");
  setTextIfPresent(
    "reportTimelineCaption",
    `ช่วงละ ${Math.round((Number(periodSeconds) || 300) / 60)} นาที`,
  );
  body.innerHTML = periods
    .map((period, index) => {
      const summary = period.summary || {};
      const rowClass = index % 2 === 0 ? "bg-white" : "bg-gray-50";
      return `
        <tr class="${rowClass}">
          <td class="px-3 py-2 font-medium text-gray-700 whitespace-nowrap">${escapeHtml(period.label)}</td>
          <td class="px-3 py-2 text-right">${formatDecimal(period.avg_people)}</td>
          <td class="px-3 py-2 text-right font-semibold text-green-700">${formatAttention(period.avg_attention_rate)}</td>
          ${["attentive", "sleeping", "looking_down", "phone_use", "phone_suspected", "hand_raised", "standing", "unknown"].map(key => `<td class="px-3 py-2 text-right">${period.is_qualified ? formatDecimal((summary[key] || 0) / 60) : toWholePeople(summary[key])}</td>`).join("")}
        </tr>
      `;
    })
    .join("");
}

function updateAnalysisCadence(sourceData = null) {
  const sampled = sourceData?.processing_mode === "sampled";
  setTextIfPresent(
    "attentionChartTitle",
    sampled ? "กราฟความตั้งใจเรียน (Timeline)" : "กราฟความตั้งใจเรียน (Real-time)",
  );
  setTextIfPresent(
    "attentionChartCadence",
    sampled
      ? `สรุปทุก ${sourceData.sample_interval_seconds || currentAnalysisInterval} วินาทีของคลิป`
      : `สรุปผลทุก ${currentAnalysisInterval} วินาที`,
  );
}

function cleanUiMessage(value) {
  const cleaned = String(value ?? "")
    .replace(/[\u200d\ufe0f]/gi, "")
    .replace(/\p{Extended_Pictographic}/gu, "")
    .replace(/\s{2,}/g, " ")
    .trim();
  if (currentLab && currentSessionName) {
    return cleaned.split(currentLab).join(currentSessionName);
  }
  return cleaned;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

async function readResponsePayload(res) {
  const contentType = res.headers.get("content-type") || "";
  if (contentType.includes("application/json")) return res.json();
  const text = await res.text();
  return { error: text || res.statusText };
}

// 🎥 ติดตามว่าแหล่งภาพหลักของแต่ละรอบกำลัง stream อยู่หรือไม่ (key: "sessionId/sourceId")
const activeSources = new Set();
function _srcKey(labId, camId) {
  return `${labId}/${camId}`;
}
function isStreamActive(labId, camId) {
  return activeSources.has(_srcKey(labId, camId));
}

function showFeedPlaceholder() {
  const feed = document.getElementById("liveFeed");
  const placeholder = document.getElementById("feedPlaceholder");
  const detectionCount = document.getElementById("detectionCount");

  if (feed) {
    feed.removeAttribute("src");
    feed.classList.add("hidden");
  }
  if (placeholder) placeholder.classList.remove("hidden");
  if (detectionCount) detectionCount.textContent = "รอแหล่งภาพ";
}

function showActiveFeed(src) {
  const feed = document.getElementById("liveFeed");
  const placeholder = document.getElementById("feedPlaceholder");

  if (placeholder) placeholder.classList.add("hidden");
  if (feed) {
    feed.classList.remove("hidden");
    feed.removeAttribute("src");
    feed.src = src;
  }
}

function streamUrlFor(labId, camId) {
  const mode = useBehaviorMode ? "behavior" : "count";
  return apiUrl(
    `/api/annotated-stream/${labId}/${camId}?mode=${mode}&v=${streamReloadToken}`,
  );
}

// 🎥 เริ่มโหลดภาพ + ดึงข้อมูลจาก Flask ทุก 2 วินาที
function startLiveFeed() {
  // หยุด interval เก่าก่อน (ป้องกันซ้ำซ้อน)
  if (liveFeedInterval) {
    clearInterval(liveFeedInterval);
  }

  const feed = document.getElementById("liveFeed");
  if (!feed) return;

  // เรียกทันทีครั้งแรก
  updateLiveFeed();

  // แล้วเรียกทุก 2 วินาที
  liveFeedInterval = setInterval(updateLiveFeed, 2000);
}

// 🔄 ฟังก์ชันอัปเดต feed และข้อมูล
async function updateLiveFeed() {
  const sessionId = currentLab;
  const version = analysisViewVersion;
  const feed = document.getElementById("liveFeed");
  const detectionCount = document.getElementById("detectionCount");
  if (!feed || !analysisViewIsCurrent(sessionId, version)) return;

  if (!isStreamActive(currentLab, currentCamera)) {
    showFeedPlaceholder();
    return;
  }

  try {
    // ดึงข้อมูลการตรวจจับ
    const dataRes = await apiFetch(`/api/data/${currentLab}/${currentCamera}`);
    const data = await dataRes.json();
    if (!analysisViewIsCurrent(sessionId, version)) return;

    if (!data || data.error) {
      detectionCount.textContent = "ไม่พบข้อมูลตรวจจับ";
      return;
    }

    // อัปเดตสถิติฝั่งขวา (จำนวนคน)
    const peopleEl = document.getElementById("detectedPeopleCount");
    const pcUsedEl = document.getElementById("pcUsedCount");
    const pcFreeEl = document.getElementById("pcFreeCount");
    const usageEl = document.getElementById("pcUsageRate");

    const total = 30;
    const used = Math.min(total, data.num_people);
    const free = total - used;
    const usage = Math.round((used / total) * 100);

    if (peopleEl) peopleEl.textContent = used;
    if (pcUsedEl) pcUsedEl.textContent = used;
    if (pcFreeEl) pcFreeEl.textContent = free;
    if (usageEl) usageEl.textContent = `${usage}%`;

    // ถ้าเปิดโหมดวิเคราะห์พฤติกรรม
    if (useBehaviorMode) {
      const behaviorRes = await apiFetch(`/api/behavior/${currentLab}/${currentCamera}`);
      const behaviorData = await behaviorRes.json();
      if (!analysisViewIsCurrent(sessionId, version)) return;

      if (behaviorData && !behaviorData.error) {
        updateBehaviorStats(behaviorData);
        detectionCount.textContent = `ตรวจพบ ${toWholePeople(behaviorData.total_people)} คน | ตั้งใจเรียน ${behaviorData.attention_rate}%`;
      }
    } else {
      detectionCount.textContent = `ตรวจพบ ${data.num_people} คน | เชื่อมั่น ${data.avg_confidence}%`;
    }
  } catch (e) {
    if (!analysisViewIsCurrent(sessionId, version)) return;
    console.error("Error fetching data:", e);
    detectionCount.textContent = "ข้อมูลไม่พร้อม";
  }
}

// 🧠 อัปเดตสถิติพฤติกรรม
function updateBehaviorStats(data) {
  const attentiveEl = document.getElementById("behaviorAttentive");
  const sleepingEl = document.getElementById("behaviorSleeping");
  const lookingDownEl = document.getElementById("behaviorLookingDown");
  const phoneUseEl = document.getElementById("behaviorPhoneUse");
  const phoneSuspectedEl = document.getElementById("behaviorPhoneSuspected");
  const handRaisedEl = document.getElementById("behaviorHandRaised");
  const standingEl = document.getElementById("behaviorStanding");
  const unknownEl = document.getElementById("behaviorUnknown");
  const attentionRateEl = document.getElementById("attentionRate");
  const attentionBarEl = document.getElementById("attentionBar");
  renderLiveTracks(data.tracks || []);

  if (data.summary) {
    if (attentiveEl)
      attentiveEl.textContent = `${toWholePeople(data.summary.attentive)} คน`;
    if (sleepingEl)
      sleepingEl.textContent = `${toWholePeople(data.summary.sleeping)} คน`;
    if (lookingDownEl)
      lookingDownEl.textContent = `${toWholePeople(data.summary.looking_down)} คน`;
    if (phoneUseEl)
      phoneUseEl.textContent = `${toWholePeople(data.summary.phone_use)} คน`;
    if (phoneSuspectedEl)
      phoneSuspectedEl.textContent = `${toWholePeople(data.summary.phone_suspected)} คน`;
    if (handRaisedEl)
      handRaisedEl.textContent = `${toWholePeople(data.summary.hand_raised)} คน`;
    if (standingEl)
      standingEl.textContent = `${toWholePeople(data.summary.standing)} คน`;
    if (unknownEl)
      unknownEl.textContent = `${toWholePeople(data.summary.unknown)} คน`;
  }

  if (attentionRateEl) {
    attentionRateEl.textContent = `${data.attention_rate || 0}%`;

    // เปลี่ยนสีตามระดับความตั้งใจ
    if (data.attention_rate >= 70) {
      attentionRateEl.className = "text-xl font-bold text-green-600";
    } else if (data.attention_rate >= 40) {
      attentionRateEl.className = "text-xl font-bold text-yellow-600";
    } else {
      attentionRateEl.className = "text-xl font-bold text-red-600";
    }
  }

  if (attentionBarEl) {
    attentionBarEl.style.width = `${data.attention_rate || 0}%`;

    // เปลี่ยนสี bar ตามระดับ
    if (data.attention_rate >= 70) {
      attentionBarEl.className =
        "bg-green-500 h-3 rounded-full transition-all duration-500";
    } else if (data.attention_rate >= 40) {
      attentionBarEl.className =
        "bg-yellow-500 h-3 rounded-full transition-all duration-500";
    } else {
      attentionBarEl.className =
        "bg-red-500 h-3 rounded-full transition-all duration-500";
    }
  }
}

function updateModeToggle() {
  const behaviorBtn = document.getElementById("behaviorModeBehaviorBtn");
  const countBtn = document.getElementById("behaviorModeCountBtn");
  const activeClass =
    "flex-1 rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white transition-colors sm:flex-none";
  const inactiveClass =
    "flex-1 rounded-md bg-white px-4 py-2 text-sm font-semibold text-gray-700 transition-colors hover:bg-gray-100 sm:flex-none";

  if (behaviorBtn) {
    behaviorBtn.className = useBehaviorMode ? activeClass : inactiveClass;
    behaviorBtn.setAttribute("aria-pressed", String(useBehaviorMode));
  }
  if (countBtn) {
    countBtn.className = useBehaviorMode ? inactiveClass : activeClass;
    countBtn.setAttribute("aria-pressed", String(!useBehaviorMode));
  }
}

function setBehaviorMode(enabled) {
  useBehaviorMode = Boolean(enabled);
  updateModeToggle();
  if (currentLab && isStreamActive(currentLab, currentCamera)) {
    streamReloadToken += 1;
    updateCameraFeed();
  }
  updateLiveFeed(); // อัปเดตทันที
}

// 🎯 Toggle โหมดวิเคราะห์พฤติกรรม
function toggleBehaviorMode() {
  setBehaviorMode(!useBehaviorMode);
}

// ✨ แอนิเมชันเปลี่ยนค่าตัวเลขให้ดู smooth
function animateNumber(el, newValue) {
  if (!el) return;
  const oldValue = parseInt(el.textContent) || 0;
  const diff = newValue - oldValue;
  const step = diff / 10;
  let current = oldValue;
  const interval = setInterval(() => {
    current += step;
    el.textContent = Math.round(current);
    if (
      (step > 0 && current >= newValue) ||
      (step < 0 && current <= newValue)
    ) {
      el.textContent = newValue;
      clearInterval(interval);
    }
  }, 30);
}

// 🎥 อัปเดต feed ปัจจุบัน
function updateCameraFeed() {
  const feed = document.getElementById("liveFeed");
  const feedLabLabel = document.getElementById("feedLabLabel");

  if (feedLabLabel) {
    feedLabLabel.textContent =
      document.getElementById("currentLabName")?.textContent || "รอบวิเคราะห์";
  }

  if (!feed || !currentLab) return;

  if (isStreamActive(currentLab, currentCamera)) {
    showActiveFeed(streamUrlFor(currentLab, currentCamera));
  } else {
    showFeedPlaceholder();
  }
}

function makeSessionId(name) {
  const slug = (name || "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^\w]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .toLowerCase();
  const unique = window.crypto?.randomUUID?.() || `${Date.now()}_${Math.random().toString(36).slice(2)}`;
  return `${(slug || "session").slice(0, 50)}_${unique}`;
}

function getDefaultSessionName() {
  return `รอบวิเคราะห์ ${new Date().toLocaleTimeString("th-TH", {
    hour: "2-digit",
    minute: "2-digit",
  })}`;
}

function resetRecordingStartInput() {
  const input = document.getElementById("recordingStartInput");
  if (!input) return;
  input.value = "";
}

function recordingStartWithOffset(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  const pad = (number) => String(number).padStart(2, "0");
  const offset = -date.getTimezoneOffset();
  const sign = offset >= 0 ? "+" : "-";
  const magnitude = Math.abs(offset);
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
    + `T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
    + `${sign}${pad(Math.floor(magnitude / 60))}:${pad(magnitude % 60)}`;
}

function recordingStartLocalValue(value) {
  const date = new Date(value);
  if (!value || Number.isNaN(date.getTime())) return "";
  const pad = number => String(number).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
    + `T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function normalizeAnalysisIntervalInput() {
  const input = document.getElementById("analysisIntervalInput");
  if (!input) return 30;
  const raw = input.value.trim();
  const parsed = raw ? Number(raw) : NaN;
  const interval = Number.isFinite(parsed)
    ? Math.min(300, Math.max(15, Math.round(parsed)))
    : 30;
  input.value = String(interval);
  return interval;
}

function setSourceMode(mode) {
  const nextMode = mode === "webcam" ? "webcam" : "video";
  const pending = sourceOperation?.sessionId === currentLab && sourceOperation.camId === currentCamera;
  if (nextMode !== selectedSourceMode && (activeSources.has(_srcKey(currentLab, currentCamera)) || pending)) {
    showToast("หยุดรอบปัจจุบันก่อนเปลี่ยนแหล่งภาพ", "warning");
    return;
  }
  renderSourceMode(nextMode);
}

function renderSourceMode(mode) {
  selectedSourceMode = mode === "webcam" ? "webcam" : "video";
  document.getElementById("webcamSourcePanel")?.classList.toggle(
    "hidden", selectedSourceMode !== "webcam",
  );
  document.getElementById("videoSourcePanel")?.classList.toggle(
    "hidden", selectedSourceMode !== "video",
  );
  for (const [type, id] of [
    ["video", "sourceModeVideoBtn"],
    ["webcam", "sourceModeWebcamBtn"],
  ]) {
    const button = document.getElementById(id);
    if (!button) continue;
    const active = type === selectedSourceMode;
    button.className = active
      ? "flex-1 px-4 py-2 rounded-md text-sm font-medium bg-blue-600 text-white sm:flex-none"
      : "flex-1 px-4 py-2 rounded-md text-sm font-medium bg-white text-gray-700 hover:bg-gray-100 sm:flex-none";
    button.setAttribute("aria-pressed", String(active));
  }
}

function resetDashboardState() {
  stopSourceStatusPolling();
  latestExportData = null;
  resetBehaviorEventView();
  currentSourceType = null;
  autoReportShown = false;
  sessionCompleted = false;
  activeSources.clear();
  document.getElementById("stopWebcamBtn")?.classList.add("hidden");
  document.getElementById("startWebcamBtn")?.classList.remove("hidden");
  updateAnalysisCadence();
  _updateSourceStatus(null, null, null);
  showFeedPlaceholder();

  setTextIfPresent("detectedPeopleCount", "0");
  setTextIfPresent("pcUsedCount", "0");
  setTextIfPresent("pcFreeCount", "30");
  setTextIfPresent("pcUsageRate", "0%");
  setTextIfPresent("behaviorAttentive", "0 คน");
  setTextIfPresent("behaviorSleeping", "0 คน");
  setTextIfPresent("behaviorLookingDown", "0 คน");
  setTextIfPresent("behaviorHandRaised", "0 คน");
  setTextIfPresent("behaviorStanding", "0 คน");
  setTextIfPresent("behaviorUnknown", "0 คน");
  setTextIfPresent("attentionRate", "0%");
  setTextIfPresent("lastUpdate", "ตอนนี้");
  setConnectionStatus("รอแหล่งภาพ");

  const attentionBar = document.getElementById("attentionBar");
  if (attentionBar) {
    attentionBar.style.width = "0%";
    attentionBar.className = "bg-green-500 h-3 rounded-full transition-all duration-500";
  }

  const activityList = document.getElementById("activityList");
  if (activityList) {
    activityList.innerHTML = `
      <div class="flex items-center space-x-3 text-sm">
        <div class="w-2 h-2 bg-gray-400 rounded-full"></div>
        <span class="text-gray-600">--:--</span>
        <span>รอข้อมูล...</span>
      </div>
    `;
  }

  const input = document.getElementById("videoFileInput");
  if (input) input.value = "";
  resetRecordingStartInput();
  renderCurrentSourceControls();
  renderLiveTracks([]);
}

// 🎥 เริ่มรอบวิเคราะห์
function startSession() {
  if (analysisJobBlocksCreation()) { showToast("มีงานกำลังทำอยู่ หรือยังตรวจสถานะงานไม่สำเร็จ", "warning"); return; }
  const input = document.getElementById("sessionNameInput");
  const name = input?.value.trim() || getDefaultSessionName();
  currentRoomName =
    document.getElementById("roomNameInput")?.value.trim() || "ไม่ระบุ";
  currentCourseName =
    document.getElementById("courseNameInput")?.value.trim() || "ไม่ระบุ";
  const interval = normalizeAnalysisIntervalInput();
  if (!Number.isInteger(interval) || interval < 15 || interval > 300) {
    showToast("ช่วงสรุปผลต้องอยู่ระหว่าง 15-300 วินาที", "warning");
    return;
  }
  for (const [key, job] of analysisJobs) {
    if (job.reportViewed && !analysisJobNeedsStop(job) && !job.stopping) analysisJobs.delete(key);
  }
  renderAnalysisJobs();
  currentAnalysisInterval = interval;
  currentRecordingStart = "";
  closeNewSessionForm();
  openAnalysisSession(makeSessionId(name), name);
}

function openAnalysisSession(sessionId, sessionName) {
  currentLab = sessionId;
  currentSessionName = sessionName;
  currentCamera = 1;

  navigateApp("#analysis");
  document.getElementById("currentLabName").textContent = sessionName;
  setTextIfPresent(
    "currentSessionMeta",
    `${currentCourseName} | ${currentRoomName}`,
  );

  resetDashboardState();
  setSourceMode("video");
  updateCameraFeed();
  startLiveFeed();
  initCharts(); // 📊 สร้างกราฟ
  startChartUpdates(); // 📊 เริ่มอัปเดตกราฟ
  startAlertPolling(); // 🔔 เริ่มยิงฟังการแจ้งเตือน
}

// 🔙 กลับไปหน้าเริ่มต้น
async function backToMenu(updateRoute = true) {
  return navigateApp("#history", { replace: !updateRoute });
}

// 🌙 โหมดมืด / สว่าง
function toggleDarkMode() {
  const body = document.body;
  const isDark = body.classList.contains("dark");
  if (isDark) {
    body.classList.remove("dark");
    setTextIfPresent("themeIcon", "มืด");
    setTextIfPresent("themeText", "โหมดมืด");
    localStorage.setItem("darkMode", "false");
  } else {
    body.classList.add("dark");
    setTextIfPresent("themeIcon", "สว่าง");
    setTextIfPresent("themeText", "โหมดสว่าง");
    localStorage.setItem("darkMode", "true");
  }
}

// 📦 ดาวน์โหลดรายงานในรูปแบบที่เลือก
function downloadReport(format) {
  if (!latestExportData) {
    showToast("กรุณารอให้โหลดรายงานสำเร็จก่อน", "warning");
    return;
  }
  const labId = latestExportData?.lab_id || currentLab || "unknown";
  const fileName = `ClassMood_Report_${labId}_${Date.now()}`;

  // สร้าง object สรุปข้อมูลจาก latestExportData หรือ fallback
  let data;
  if (latestExportData) {
    const s = latestExportData.summary || {};
    const reportBehavior = getReportBehavior(s);
    data = {
      lab_id: latestExportData.lab_id,
      session_name: latestExportData.session_name || latestExportData.lab_id,
      export_time: latestExportData.export_time,
      avg_attention_rate: s.avg_attention_rate,
      avg_people: s.avg_people,
      max_people: s.max_people,
      report_total_people: s.report_total_people ?? s.max_people,
      total_records: s.total_records,
      latest_attention_rate: s.latest_attention_rate,
      report_attention_label: "อัตราความตั้งใจเฉลี่ย (%)",
      report_attention_rate:
        s.report_attention_rate ?? s.avg_attention_rate,
      latest_total_people: s.latest_total_people,
      behavior_scope: getReportBehaviorTitle(s),
      behavior_unit: latestExportData.qualified_analysis ? "นาทีรวม" : "คน",
      behavior_attentive: reportBehavior.attentive || 0,
      behavior_sleeping: reportBehavior.sleeping || 0,
      behavior_looking_down: reportBehavior.looking_down || 0,
      behavior_phone_use: reportBehavior.phone_use || 0,
      behavior_phone_suspected: reportBehavior.phone_suspected || 0,
      behavior_hand_raised: reportBehavior.hand_raised || 0,
      behavior_standing: reportBehavior.standing || 0,
      behavior_unknown: reportBehavior.unknown || 0,
    };
  } else {
    data = {
      lab_id: labId,
      session_name: currentSessionName || labId,
      export_time: new Date().toLocaleString("th-TH"),
      avg_attention_rate: 0,
      avg_people: 0,
      max_people: 0,
      report_total_people: 0,
      total_records: 0,
      latest_attention_rate: 0,
      report_attention_label: "อัตราความตั้งใจเฉลี่ย (%)",
      report_attention_rate: 0,
      latest_total_people: 0,
      behavior_attentive: 0,
      behavior_sleeping: 0,
      behavior_looking_down: 0,
      behavior_phone_use: 0,
      behavior_phone_suspected: 0,
      behavior_hand_raised: 0,
      behavior_standing: 0,
      behavior_unknown: 0,
      behavior_scope: "พฤติกรรมช่วงที่ตรวจพบคนสูงสุด",
    };
  }

  switch (format) {
    case "json":
      downloadBlob(
        JSON.stringify(latestExportData || data, null, 2),
        "application/json",
        `${fileName}.json`,
      );
      break;

    case "csv":
      downloadBlob(
        buildCSV(data),
        "text/csv;charset=utf-8;",
        `${fileName}.csv`,
      );
      break;

    case "excel":
      downloadBlob(
        buildExcel(data),
        "application/vnd.ms-excel",
        `${fileName}.xls`,
      );
      break;

    case "pdf":
      generatePDF(labId);
      break;

    default:
      alert("ไม่รู้จักรูปแบบไฟล์ที่เลือก");
  }
}

function appendTrackingExportRows(rows) {
  const tracking = reportTrackingData();
  if (!tracking.session) return;
  const session = tracking.session;
  rows.push([], ["ข้อมูลคาบเรียน"], ["รายวิชา", session.course_name || "ไม่ระบุ"],
    ["ห้อง", session.room_name || "ไม่ระบุ"],
    ["เวลาเริ่มบันทึก", session.recording_started_at || "-"],
    ["เวลาสิ้นสุด", session.recording_ended_at || session.ended_at || "-"]);
  const keys = ["attentive", "sleeping", "looking_down", "phone_use", "phone_suspected", "hand_raised", "standing", "unknown"];
  const images = representativeImages(tracking);
  rows.push([], ["สรุปตามบุคคล (ID)"], [
    "ID ภายในรอบ", "ภาพ", "เวลาตรวจพบรวม (วินาที)",
    ...(tracking.is_qualified ? ["เวลาที่ผ่านเกณฑ์ (วินาที)"] : []),
    "ความตั้งใจ (%)",
    ...keys.flatMap(key => [`${behaviorLabel(key)} (ครั้ง)`, `${behaviorLabel(key)} (วินาที)`]),
  ]);
  for (const track of tracking.tracks || []) {
    const image = images.get(Number(track.track_id));
    rows.push([`ID ${track.track_id}`, image?.thumbnail_filename || image?.filename || "-",
      track.visible_seconds,
      ...(tracking.is_qualified ? [track.qualified_seconds] : []),
      track.attention_rate ?? "-",
      ...keys.flatMap(key => [toWholePeople(track.event_counts?.[key]), Number(track.behavior_seconds?.[key]) || 0]),
    ]);
  }
  if (tracking.events?.length) {
    rows.push([], ["ช่วงพฤติกรรมรายบุคคล"],
      ["ID ภายในรอบ", "เวลาเริ่ม", "เวลาสิ้นสุด", "พฤติกรรม", "ระยะเวลา (วินาที)", "ความมั่นใจ (%)"]);
    for (const event of tracking.events) {
      rows.push([`ID ${event.track_id}`, event.start_time, event.end_time,
        behaviorLabel(event.behavior), event.duration_seconds, event.avg_confidence]);
    }
  }
  const methodology = latestExportData?.analysis_methodology;
  if (methodology?.criteria?.length) {
    rows.push([], ["เกณฑ์การวัดพฤติกรรมและข้อจำกัด"], ["สูตรอัตราความตั้งใจ", methodology.attention_formula],
      ["ช่วงสรุปที่เลือก (วินาที)", methodology.realtime_summary_interval_seconds],
      ["พฤติกรรม", "สิ่งที่วัด", "เกณฑ์ตัดสิน", "ยืนยันก่อนเปลี่ยนสถานะ (วินาที)", "ขั้นต่ำในรายงาน (วินาทีที่ตรวจจริง)", "ข้อจำกัด"]);
    for (const item of methodology.criteria) {
      rows.push([item.behavior === "sleeping" ? behaviorLabel(item.behavior) : item.label || behaviorLabel(item.behavior), item.measurement,
        item.decision_rule, item.confirmation_seconds,
        item.report_minimum_seconds ?? (latestExportData.report_policy ? reportMinimumSeconds(item.behavior) : "ไม่คัดช่วง"), item.limitation]);
    }
    for (const limitation of methodology.limitations || []) rows.push(["ข้อจำกัดรวม", limitation]);
  }
}

function buildExportRows(data) {
  const unit = data.behavior_unit || "คน";
  const rows = [
    ["รายงานรอบวิเคราะห์ - ClassMood AI"], [],
    ["ข้อมูลทั่วไป"],
    ["รอบวิเคราะห์", data.session_name || data.lab_id],
    ["รหัสรอบ", data.lab_id], ["เวลาส่งออก", data.export_time], [],
    ["สถิติรวม"],
    ["จำนวนนักศึกษาเฉลี่ย (คน)", data.avg_people],
    ["ความตั้งใจเรียนเฉลี่ย (%)", data.avg_attention_rate ?? "-"],
    ["จำนวนคนสูงสุดพร้อมกัน (คน)", data.report_total_people ?? data.max_people],
    ["จำนวนบันทึกทั้งหมด", data.total_records], [],
    [data.behavior_scope || "ภาพรวมพฤติกรรม"],
    ...[
      ["ตั้งใจเรียน", "attentive"], [behaviorLabel("sleeping"), "sleeping"],
      ["ก้มหน้า", "looking_down"], ["ใช้โทรศัพท์", "phone_use"],
      ["สงสัยใช้โทรศัพท์", "phone_suspected"], ["ยกมือ", "hand_raised"],
      ["ยืน/ลุก", "standing"], ["ไม่ชัดเจน", "unknown"],
    ].map(([label, key]) => [`${label} (${unit})`, data[`behavior_${key}`]]),
    [data.report_attention_label || "อัตราความตั้งใจเฉลี่ย (%)", data.report_attention_rate ?? "-"],
  ];
  if (latestExportData?.report_policy) {
    rows.push(["เกณฑ์ขั้นต่ำ (วินาที)", latestExportData.report_policy.minimum_behavior_seconds]);
    rows.push([`เกณฑ์${behaviorLabel("sleeping")} (วินาทีที่ตรวจจริง)`, reportMinimumSeconds("sleeping")]);
    rows.push(["ระยะเวลา", "รวมเวลาตรวจจริงของทุก ID ไม่รวมช่วงที่ไม่ได้ตรวจ"]);
  }
  const periods = reportPeriodData();
  if (periods.length) {
    rows.push([], ["สรุปตามช่วงเวลา"], [
      "ช่วงเวลา", "คนเฉลี่ย", "ความตั้งใจ (%)",
      ...["ตั้งใจเรียน", behaviorLabel("sleeping"), "ก้มหน้า", "โทรศัพท์", "สงสัยโทรศัพท์", "ยกมือ", "ยืน/ลุก", "ไม่ชัดเจน"]
        .map(label => `${label} (${unit})`),
    ]);
    for (const period of periods) {
      rows.push([period.label, period.avg_people, period.avg_attention_rate ?? "-",
        ...["attentive", "sleeping", "looking_down", "phone_use", "phone_suspected", "hand_raised", "standing", "unknown"]
          .map(key => period.is_qualified ? (Number(period.summary[key]) || 0) / 60 : toWholePeople(period.summary[key])),
      ]);
    }
  }
  appendTrackingExportRows(rows);
  if (!latestExportData?.qualified_analysis && latestExportData?.history?.length) {
    rows.push([], ["ข้อมูลย้อนหลัง"], ["เวลา", "ความตั้งใจ (%)", "จำนวนคน",
      "ตั้งใจเรียน", behaviorLabel("sleeping"), "ก้มหน้า", "โทรศัพท์", "สงสัยโทรศัพท์", "ยกมือ", "ยืน/ลุก", "ไม่ชัดเจน"]);
    for (const item of latestExportData.history) {
      rows.push([item.time, item.attention_rate, item.total_people,
        ...["attentive", "sleeping", "looking_down", "phone_use", "phone_suspected", "hand_raised", "standing", "unknown"]
          .map(key => toWholePeople(item.summary?.[key])),
      ]);
    }
  }
  return rows;
}

function buildCSV(data) {
  return buildExportRows(data)
    .map(row => row.map(cell => `"${String(cell ?? "").replaceAll('"', '""')}"`).join(","))
    .join("\n");
}

function buildExcel(data) {
  return buildExportRows(data)
    .map(row => row.map(cell => String(cell ?? "").replace(/[\t\r\n]/g, " ")).join("\t"))
    .join("\n");
}

// 🛠️ สร้าง Blob และ trigger download
function downloadBlob(content, mimeType, filename) {
  const blob = new Blob(["\uFEFF" + content], { type: mimeType }); // BOM สำหรับ UTF-8 ภาษาไทย
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(link.href);
}

// 🔄 รีเฟรชข้อมูล (ภาพ + ตัวเลข)
function refreshData() {
  if (!currentLab) {
    alert("กรุณาเริ่มรอบวิเคราะห์ก่อนรีเฟรช");
    return;
  }
  updateCameraFeed(); // โหลดภาพใหม่
  startLiveFeed(); // โหลดข้อมูลใหม่
  document.getElementById("lastUpdate").textContent =
    new Date().toLocaleTimeString();
}

// Load a report into its dedicated page; only the newest request may render.
async function exportReport(sessionId = currentLab, sessionName = currentSessionName, updateRoute = true) {
  if (!sessionId) {
    alert("กรุณาเริ่มรอบวิเคราะห์ก่อน");
    return;
  }

  if (updateRoute) return navigateApp(`#report/${encodeURIComponent(sessionId)}`);
  reportSessionId = sessionId;
  const request = ++reportRequestVersion;
  latestExportData = null;
  resetBehaviorEventView();
  setTextIfPresent("reportPageTitle", sessionName || "รายงานรอบวิเคราะห์");
  showAppView("report");
  setTextIfPresent("reportBackLabel", reportReturnHash === "#analysis" ? "กลับไปหน้าวิเคราะห์" : "กลับไปประวัติ");
  setTextIfPresent("reportPageStatus", "กำลังโหลดรายงาน...");
  document.getElementById("reportPage").setAttribute("aria-busy", "true");
  document.getElementById("reportContent").classList.add("hidden");
  document.getElementById("reportPartialNotice")?.classList.add("hidden");
  document.getElementById("reportDownloadActions").classList.add("hidden");
  document.getElementById("reportRetryButton").classList.add("hidden");
  document.getElementById("reportMethodologySection").open = false;
  renderReportTimeline([]);
  renderTrackingReport(null);
  renderBehaviorEvents(null);
  renderAnalysisMethodology(null);

  // ดึงข้อมูลจาก backend
  try {
    const res = await apiFetch(`/api/export/${encodeURIComponent(sessionId)}`);
    if (!res.ok) throw new Error("ไม่สามารถโหลดรายงานได้");
    const data = await res.json();
    if (request !== reportRequestVersion) return;
    latestExportData = {
      ...data,
      session_name: data.session_name || data.tracking?.session?.name || sessionName || data.lab_id,
    };

    const s = latestExportData.summary || {};
    const periods = reportPeriodData(latestExportData);
    const tracking = reportTrackingData(latestExportData);
    const session = tracking?.session || {};
    document.getElementById("reportPartialNotice")?.classList.toggle("hidden", session.status !== "cancelled");
    const reportBehavior = getReportBehavior(s);

    const set = (id, text) => {
      const el = document.getElementById(id);
      if (el) el.textContent = text;
    };

    set("reportPageTitle", latestExportData.session_name);
    set("reportLabName", latestExportData.session_name);
    set("reportDate", `วันที่คาบเรียน: ${session.recording_started_at ? new Date(session.recording_started_at).toLocaleDateString("th-TH", { year: "numeric", month: "long", day: "numeric" }) : "-"}`);
    set("reportTime", `เวลาจัดทำรายงาน: ${formatReportDateTime(data.export_time)}`);
    set("reportRecords", `บันทึก: ${s.total_records ?? 0} รายการ`);
    set(
      "reportSessionContext",
      `วิชา: ${session.course_name || "ไม่ระบุ"} | ห้อง: ${session.room_name || "ไม่ระบุ"}`,
    );
    set(
      "reportRecordingPeriod",
      `ช่วงเวลาคาบ: ${formatRecordingPeriod(session)}`,
    );
    const methodology = latestExportData.analysis_methodology || {};
    const sampling = methodology.long_video_sampling || {};
    set(
      "reportAnalysisMode",
      `รูปแบบการวิเคราะห์: สรุปผล real-time ทุก ${formatDecimal(methodology.realtime_summary_interval_seconds)} วินาที | คลิปยาววิเคราะห์ช่วงละ ${formatDecimal(sampling.window_seconds)} วินาที`,
    );
    set("reportAvgPeople", `นักเรียนเฉลี่ย: ${s.avg_people ?? 0} คน`);
    set(
      "reportAvgAttention",
      `ความตั้งใจเฉลี่ย: ${formatAttention(s.avg_attention_rate)}`,
    );
    set(
      "reportMaxPeople",
      `จำนวนคนสูงสุดพร้อมกัน: ${toWholePeople(s.report_total_people ?? s.max_people)} คน`,
    );
    set(
      "reportBehaviorTitle",
      getReportBehaviorTitle(s),
    );
    set(
      "reportAttentionLabel",
      "อัตราความตั้งใจเฉลี่ย",
    );
    const qualified = Boolean(latestExportData.qualified_analysis);
    for (const [id, key] of [["reportAttentive", "attentive"], ["reportSleeping", "sleeping"],
      ["reportLookingDown", "looking_down"], ["reportPhoneUse", "phone_use"],
      ["reportPhoneSuspected", "phone_suspected"], ["reportHandRaised", "hand_raised"],
      ["reportStanding", "standing"], ["reportUnknown", "unknown"]]) {
      set(id, qualified ? `${formatDecimal(reportBehavior[key])} นาที` : `${toWholePeople(reportBehavior[key])} คน`);
    }
    document.querySelectorAll("#reportTimelineTableWrapper th[data-behavior-label]").forEach(header => {
      header.textContent = `${header.dataset.behaviorLabel}${qualified ? " (นาที)" : ""}`;
    });
    set("reportPolicyCaption", qualified
      ? `เกณฑ์รายงาน: ${behaviorLabel("sleeping")} ${formatDecimal(reportMinimumSeconds("sleeping"))} วินาทีที่ตรวจจริง พฤติกรรมอื่น ${formatDecimal(latestExportData.report_policy?.minimum_behavior_seconds ?? 30)} วินาที | ไม่นับช่องว่างระหว่างช่วงตรวจ | ID อิงตำแหน่งภายในรอบ ไม่ยืนยันตัวบุคคล`
      : "รายงานเดิม: ใช้เกณฑ์ของรอบที่บันทึกไว้");
    set(
      "reportLatestAttention",
      formatAttention(s.report_attention_rate ?? (qualified ? null : s.avg_attention_rate)),
    );
    renderReportTimeline(periods, latestExportData.period_seconds);
    renderTrackingReport(tracking);
    renderBehaviorEvents(reportEvidenceData());
    renderAnalysisMethodology(methodology);
    document.getElementById("reportContent").classList.remove("hidden");
    document.getElementById("reportDownloadActions").classList.remove("hidden");
    set("reportPageStatus", session.status === "cancelled" ? "รอบนี้หยุดก่อนวิเคราะห์ครบคลิป แสดงผลเท่าที่ตรวจได้"
      : s.total_records ? "" : "รอบนี้ยังไม่มีข้อมูลการวิเคราะห์ที่บันทึกไว้");
    acknowledgeAnalysisReport(sessionId, session.status);
  } catch (e) {
    if (request !== reportRequestVersion) return;
    console.error("Error fetching export data:", e);
    latestExportData = null;
    renderReportTimeline([]);
    renderTrackingReport(null);
    renderBehaviorEvents(null);
    renderAnalysisMethodology(null);
    setTextIfPresent("reportPageStatus", "ไม่สามารถโหลดรายงานได้ กรุณาลองอีกครั้ง");
    document.getElementById("reportRetryButton").classList.remove("hidden");
  } finally {
    if (request === reportRequestVersion) document.getElementById("reportPage").setAttribute("aria-busy", "false");
  }
}

// ===== 📊 CHART FUNCTIONS =====
let attentionChart = null;
let behaviorPieChart = null;
let chartUpdateInterval = null;

// 📊 สร้างกราฟเริ่มต้น
function initCharts() {
  // ทำลายกราฟเก่าถ้ามี
  if (attentionChart) {
    attentionChart.destroy();
    attentionChart = null;
  }
  if (behaviorPieChart) {
    behaviorPieChart.destroy();
    behaviorPieChart = null;
  }

  // กราฟเส้น - ความตั้งใจเรียน
  const lineCtx = document.getElementById("attentionChart");
  if (lineCtx) {
    attentionChart = new Chart(lineCtx, {
      type: "line",
      data: {
        labels: [],
        datasets: [
          {
            label: "ความตั้งใจเรียน (%)",
            data: [],
            borderColor: "rgb(34, 197, 94)",
            backgroundColor: "rgba(34, 197, 94, 0.1)",
            fill: true,
            tension: 0.4,
          },
          {
            label: "จำนวนนักศึกษา",
            data: [],
            borderColor: "rgb(59, 130, 246)",
            backgroundColor: "rgba(59, 130, 246, 0.1)",
            fill: false,
            tension: 0.4,
            yAxisID: "y1",
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: {
          mode: "index",
          intersect: false,
        },
        scales: {
          y: {
            type: "linear",
            display: true,
            position: "left",
            min: 0,
            max: 100,
            title: {
              display: true,
              text: "ความตั้งใจ (%)",
            },
          },
          y1: {
            type: "linear",
            display: true,
            position: "right",
            min: 0,
            max: 50,
            title: {
              display: true,
              text: "จำนวนคน",
            },
            grid: {
              drawOnChartArea: false,
            },
          },
        },
        plugins: {
          legend: {
            position: "bottom",
            labels: {
              usePointStyle: true,
              boxWidth: 8,
            },
          },
        },
      },
    });
  }

  // กราฟวงกลม - สัดส่วนพฤติกรรม
  const pieCtx = document.getElementById("behaviorPieChart");
  if (pieCtx) {
    behaviorPieChart = new Chart(pieCtx, {
      type: "doughnut",
      data: {
        labels: ["ตั้งใจเรียน", "ท่าเข้าข่ายหลับ", "ก้มหน้า", "ใช้โทรศัพท์", "สงสัยใช้โทรศัพท์", "ยกมือ", "ยืน/ลุก", "ไม่ชัดเจน"],
        datasets: [
          {
            data: [0, 0, 0, 0, 0, 0, 0, 0],
            backgroundColor: [
              "rgba(34, 197, 94, 0.8)",
              "rgba(239, 68, 68, 0.8)",
              "rgba(249, 115, 22, 0.8)",
              "rgba(217, 119, 6, 0.85)",
              "rgba(234, 179, 8, 0.8)",
              "rgba(14, 165, 233, 0.8)",
              "rgba(168, 85, 247, 0.8)",
              "rgba(107, 114, 128, 0.75)",
            ],
            borderWidth: 2,
            borderColor: "#fff",
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            position: "bottom",
            labels: {
              usePointStyle: true,
              boxWidth: 8,
              font: {
                size: 11,
              },
            },
          },
        },
      },
    });
  }
}

// 📊 อัปเดตข้อมูลกราฟ
async function updateCharts() {
  const sessionId = currentLab;
  const version = analysisViewVersion;
  if (!analysisViewIsCurrent(sessionId, version)) return;

  try {
    const res = await apiFetch(`/api/stats/${currentLab}`);
    const data = await res.json();
    if (!analysisViewIsCurrent(sessionId, version)) return;

    if (attentionChart && data.labels) {
      attentionChart.data.labels = data.labels;
      attentionChart.data.datasets[0].data = data.attention_rates;
      attentionChart.data.datasets[1].data = data.people_counts;
      attentionChart.update("none");
    }

    if (behaviorPieChart && data.latest_summary) {
      const summary = data.latest_summary;
      behaviorPieChart.data.datasets[0].data = [
        toWholePeople(summary.attentive),
        toWholePeople(summary.sleeping),
        toWholePeople(summary.looking_down),
        toWholePeople(summary.phone_use),
        toWholePeople(summary.phone_suspected),
        toWholePeople(summary.hand_raised),
        toWholePeople(summary.standing),
        toWholePeople(summary.unknown),
      ];
      behaviorPieChart.update("none");
    }

    // อัปเดต Activity Log
    await updateActivityLog();
  } catch (e) {
    console.error("Error updating charts:", e);
  }
}

// 📝 อัปเดต Activity Log
async function updateActivityLog() {
  const sessionId = currentLab;
  const version = analysisViewVersion;
  if (!analysisViewIsCurrent(sessionId, version)) return;

  try {
    const res = await apiFetch(`/api/activities/${currentLab}`);
    const data = await res.json();
    if (!analysisViewIsCurrent(sessionId, version)) return;

    const activityList = document.getElementById("activityList");
    if (!activityList || !data.activities) return;

    if (data.activities.length === 0) {
      activityList.innerHTML = `
        <div class="flex items-center space-x-3 text-sm">
          <div class="w-2 h-2 bg-gray-400 rounded-full"></div>
          <span class="text-gray-600">--:--</span>
          <span>ยังไม่มีกิจกรรม</span>
        </div>
      `;
      return;
    }

    activityList.innerHTML = data.activities
      .slice(0, 10)
      .map((activity) => {
        let dotColor = "bg-blue-500";
        if (activity.type === "warning") dotColor = "bg-yellow-500";
        if (activity.type === "alert") dotColor = "bg-red-500";
        if (activity.type === "success") dotColor = "bg-green-500";

        return `
        <div class="flex items-center space-x-3 text-sm">
          <div class="w-2 h-2 ${dotColor} rounded-full"></div>
          <span class="text-gray-600">${escapeHtml(activity.time)}</span>
          <span>${escapeHtml(cleanUiMessage(activity.message))}</span>
        </div>
      `;
      })
      .join("");
  } catch (e) {
    console.error("Error updating activity log:", e);
  }
}

// 📊 เริ่มอัปเดตกราฟทุก 2 วินาที
function startChartUpdates() {
  if (chartUpdateInterval) {
    clearInterval(chartUpdateInterval);
  }
  updateCharts(); // เรียกทันที
  chartUpdateInterval = setInterval(updateCharts, 2000);
}

// 📊 หยุดอัปเดตกราฟ
function stopChartUpdates() {
  if (chartUpdateInterval) {
    clearInterval(chartUpdateInterval);
    chartUpdateInterval = null;
  }
}

document.addEventListener("DOMContentLoaded", function () {
  setupEvidenceViewer();
  setupBehaviorEventControls();
  updateModeToggle();

  const savedDarkMode = localStorage.getItem("darkMode");
  if (savedDarkMode === "true") {
    document.body.classList.add("dark");
    setTextIfPresent("themeIcon", "สว่าง");
    setTextIfPresent("themeText", "โหมดสว่าง");
  }

  const intervalInput = document.getElementById("analysisIntervalInput");
  intervalInput?.addEventListener("change", normalizeAnalysisIntervalInput);
  intervalInput?.addEventListener("blur", normalizeAnalysisIntervalInput);

  resetRecordingStartInput();
  setSourceMode("video");
});

// =============================================
// 🔔  Alert polling (แจ้งเตือนแบบ real-time)
// =============================================

function startAlertPolling() {
  if (alertPollInterval) return; // กันทำซ้ำ
  if (!appReady || appView !== "analysis" || !isStreamActive(currentLab, currentCamera)) return;
  alertPollGeneration += 1;
  alertPollRequest = null;
  alertCursorReady = false;
  lastAlertId = 0;
  alertPollInterval = setInterval(pollAlerts, 3000);
  pollAlerts(); // เรียกทันที
}

function stopAlertPolling() {
  if (alertPollInterval) {
    clearInterval(alertPollInterval);
    alertPollInterval = null;
  }
  alertPollGeneration += 1;
  alertPollRequest = null;
  alertCursorReady = false;
  lastAlertId = 0;
  document.querySelectorAll("#toastContainer [data-analysis-session]").forEach(toast => toast.remove());
}

function startSourceStatusPolling() {
  stopSourceStatusPolling();
  startAnalysisJobPolling();
}

function stopSourceStatusPolling() {
  if (sourceStatusInterval) {
    clearInterval(sourceStatusInterval);
    sourceStatusInterval = null;
  }
}

async function checkSourceStatus() {
  return refreshAnalysisJobs();
}

async function handleVideoEnded(data) {
  return refreshAnalysisJobs();
}

async function pollAlerts() {
  const epoch = analysisJobsEpoch;
  const generation = alertPollGeneration;
  const version = analysisViewVersion;
  const sessionId = currentLab;
  const cameraId = currentCamera;
  if (!appReady || appView !== "analysis" || !isStreamActive(sessionId, cameraId)) return;
  if (alertPollRequest) return alertPollRequest;
  const request = (async () => {
    try {
      const res = await apiFetch(`/api/alerts?since_id=${lastAlertId}`);
      if (!res.ok) return;
      const data = await res.json();
      if (epoch !== analysisJobsEpoch || generation !== alertPollGeneration || currentCamera !== cameraId
        || !analysisViewIsCurrent(sessionId, version) || !isStreamActive(sessionId, cameraId)) return;
      const latest = Number(data.latest_id);
      if (!Number.isSafeInteger(latest) || latest < 0) return;
      // Establish a live cursor without replaying the owner's historical alert backlog.
      if (!alertCursorReady || latest < lastAlertId) {
        lastAlertId = latest;
        alertCursorReady = true;
        return;
      }
      for (const alert of data.alerts || []) {
        if (alert.lab_id === sessionId && alert.id > lastAlertId) showToast(alert.message, alert.type, sessionId);
      }
      lastAlertId = latest;
    } catch (_) {
      /* Keep the cursor unchanged when the status request fails. */
    }
  })();
  alertPollRequest = request;
  try { await request; } finally { if (alertPollRequest === request) alertPollRequest = null; }
}

function showToast(message, type = "info", sessionId = null) {
  const container = document.getElementById("toastContainer");
  if (!container) return;

  const colors = {
    warning: "bg-yellow-500",
    alert: "bg-red-600",
    success: "bg-green-600",
    info: "bg-blue-500",
  };
  const labels = {
    warning: "คำเตือน",
    alert: "แจ้งเตือน",
    success: "สำเร็จ",
    info: "ข้อมูล",
  };
  const bg = colors[type] || "bg-gray-700";
  const label = labels[type] || "ข้อความ";
  const cleanMessage = cleanUiMessage(message);
  const key = JSON.stringify([type, cleanMessage, sessionId]);
  if ([...container.children].some(toast => toast.dataset.toastKey === key)) return;

  const toast = document.createElement("div");
  toast.dataset.toastKey = key;
  if (sessionId) toast.dataset.analysisSession = sessionId;
  toast.className = `${bg} text-white text-sm font-medium px-4 py-3 rounded-lg shadow-lg
    pointer-events-auto opacity-0 transition-opacity duration-300`;
  toast.textContent = `${label}: ${cleanMessage}`;
  container.appendChild(toast);
  while (container.childElementCount > 3) container.firstElementChild.remove();

  // Fade in
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      toast.classList.replace("opacity-0", "opacity-100");
    });
  });

  // Auto-dismiss after 6s
  setTimeout(() => {
    toast.classList.replace("opacity-100", "opacity-0");
    setTimeout(() => toast.remove(), 350);
  }, 6000);
}

// =============================================
// 🎥 Video Source Management
// =============================================

/**
 * ตั้ง live source สำหรับแหล่งภาพหลักของรอบวิเคราะห์
 * @param {string} labId - session id สำหรับ backend
 * @param {number} camId - backend source id ปัจจุบันใช้ 1 เป็นแหล่งหลัก
 * @param {number|string} source - webcam index (0,1,...) หรือ path ไฟล์ .mp4
 * @param {string|null} displayLabel - label ที่แสดงใน UI
 */
async function setVideoSource(labId, camId, source, displayLabel = null, operation = null) {
  if (!labId) {
    showToast("กรุณาเริ่มรอบวิเคราะห์ก่อน", "warning");
    return;
  }
  const ownOperation = !operation;
  try {
    operation ||= beginSourceOperation("starting", { ...analysisSelection(labId, camId), sourceType: typeof source === "number" ? "webcam" : "video" });
    await refreshAnalysisJobs();
    if (!sourceOperationIsCurrent(operation)) return;
    if (analysisJobsUnavailable || [...analysisJobs.values()].some(analysisJobNeedsStop)) throw new Error("มีงานกำลังทำอยู่ หรือยังตรวจสถานะงานไม่สำเร็จ");
    const res = await apiFetch(`/api/sources/${labId}/${camId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source,
        session_name: operation.name,
        room_name: operation.roomName || "ไม่ระบุ",
        course_name: operation.courseName || "ไม่ระบุ",
        recording_start: operation.recordingStart || null,
        analysis_interval_seconds: operation.interval,
      }),
    });
    const data = await readResponsePayload(res);
    if (!sourceOperationIsCurrent(operation)) return;
    if (res.ok && data.ok) {
      const job = registerAnalysisJob({ ...operation, sourceLabel: displayLabel || data.source }, data);
      if (job.status !== "running") return;
      if (currentLab !== labId || currentCamera !== camId || appView !== "analysis") return;
      currentSourceType =
        data.source_type || (typeof source === "number" ? "webcam" : "video");
      document.getElementById("stopWebcamBtn")?.classList.toggle(
        "hidden", currentSourceType !== "webcam",
      );
      document.getElementById("startWebcamBtn")?.classList.toggle(
        "hidden", currentSourceType === "webcam",
      );
      autoReportShown = false;
      streamReloadToken += 1;
      updateCameraFeed();
      startLiveFeed();
      startChartUpdates();
      startAlertPolling();
      updateAnalysisCadence(data);
      const srcLabel = analysisSourceName(job);
      setConnectionStatus("เชื่อมต่อแล้ว", "text-green-600");
      if (data.processing_mode === "sampled") {
        showToast(
          `เริ่มวิเคราะห์คลิปยาว: ตรวจช่วง ${data.sample_window_seconds || 10} วินาที ทุก ${data.sample_interval_seconds || 60} วินาที`,
          "success",
        );
      } else {
        showToast(`เชื่อมต่อสำเร็จ: ${srcLabel}`, "success");
      }
      _updateSourceStatus(labId, camId, srcLabel);
      startSourceStatusPolling();
    } else {
      throw new Error(data.error || "เชื่อมต่อไม่สำเร็จ");
    }
  } catch (e) {
    if (!operation || sourceOperationIsCurrent(operation)) showToast(`เชื่อมต่อไม่สำเร็จ: ${e.message}`, "alert");
  } finally {
    if (ownOperation && operation) endSourceOperation(operation);
  }
}

function _updateSourceStatus(labId, camId, srcLabel) {
  const text = srcLabel
    ? `● Live: ${srcLabel}`
    : "○ รอเลือกเว็บแคมหรือคลิป";
  const className = srcLabel
    ? "text-xs font-medium text-green-600"
    : "text-xs text-gray-500";
  setSourceStatusText(text, className);
}

function setSourceStatusText(text, className = "text-xs text-gray-500") {
  const el = document.getElementById("sourceStatus");
  if (!el) return;
  el.textContent = text;
  el.className = className;
}

// ฟังก์ชันสำหรับปุ่มใน UI
function connectWebcam() {
  if (sessionCompleted) {
    showToast("รอบนี้จบแล้ว กรุณาสร้างรอบใหม่", "warning");
    return;
  }
  const idx = parseInt(document.getElementById("webcamSelect")?.value ?? "0");
  setVideoSource(currentLab, currentCamera, idx);
}

async function stopWebcam() {
  return stopCurrentAnalysis();
}

function connectVideoFile() {
  if (!currentLab) {
    showToast("กรุณาเริ่มรอบวิเคราะห์ก่อน", "warning");
    return;
  }

  const startValue = document.getElementById("recordingStartInput")?.value;
  const recordingStart = startValue ? recordingStartWithOffset(startValue) : null;
  if (!recordingStart) {
    showToast("กรุณาระบุวันที่และเวลาเริ่มบันทึกคลิป", "warning");
    return;
  }
  if (sessionCompleted) {
    showToast("รอบนี้จบแล้ว กรุณาสร้างรอบใหม่", "warning");
    return;
  }
  currentRecordingStart = recordingStart;

  const input = document.getElementById("videoFileInput");
  const file = input?.files?.[0];
  if (!file) {
    showToast("กรุณาเลือกไฟล์วิดีโอก่อน", "warning");
    return;
  }

  uploadAndUseVideo(file);
}

async function uploadAndUseVideo(file) {
  let operation;
  try { operation = beginSourceOperation("upload", { ...analysisSelection(), sourceType: "video" }); }
  catch (error) { showToast(error.message, "warning"); return; }
  const btn = document.getElementById("uploadVideoBtn");
  const oldLabel = btn?.textContent.trim() || "อัปโหลดคลิป";
  if (btn) {
    btn.disabled = true;
    btn.textContent = "กำลังอัปโหลด...";
    btn.classList.add("opacity-60", "cursor-not-allowed");
  }

  try {
    const formData = new FormData();
    formData.append("video", file);

    const res = await apiFetch("/api/videos", {
      method: "POST",
      body: formData,
    });
    const data = await readResponsePayload(res);
    if (!sourceOperationIsCurrent(operation)) return;

    if (!res.ok || !data.ok) {
      showToast(`อัปโหลดไม่สำเร็จ: ${data.error || res.statusText}`, "alert");
      return;
    }

    await setVideoSource(operation.sessionId, operation.camId, data.source, data.filename, operation);
    const input = document.getElementById("videoFileInput");
    if (input && sourceOperationIsCurrent(operation)) input.value = "";
  } catch (e) {
    if (sourceOperationIsCurrent(operation)) showToast(`อัปโหลดไม่สำเร็จ: ${e.message}`, "alert");
  } finally {
    if (btn && sourceOperationIsCurrent(operation)) {
      btn.disabled = false;
      btn.textContent = oldLabel || "อัปโหลดคลิป";
      btn.classList.remove("opacity-60", "cursor-not-allowed");
    }
    endSourceOperation(operation);
  }
}
