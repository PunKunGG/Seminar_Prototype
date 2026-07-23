let currentCamera = 1;
let currentLab = "";
let currentSessionName = "";
let currentRoomName = "";
let currentCourseName = "";
let currentRecordingStart = "";
let useBehaviorMode = true; // ✅ เปิดโหมดวิเคราะห์พฤติกรรมเป็นค่าเริ่มต้น
let liveFeedInterval = null;
let lastAlertId = 0; // ID สุดท้ายที่ได้รับเพื่อหลีกเอา alert ซ้ำ
let alertPollInterval = null; // setInterval handle สำหรับดึง alerts
let latestExportData = null; // เก็บข้อมูลล่าสุดสำหรับ export
let sourceStatusInterval = null;
let currentSourceType = null;
let autoReportShown = false;
let streamReloadToken = 0;
const API_BASE =
  window.location.protocol === "file:" ? "http://127.0.0.1:5000" : window.location.origin;

function apiUrl(path) {
  return `${API_BASE}${path}`;
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

function behaviorLabel(value) {
  return {
    attentive: "ตั้งใจเรียน",
    sleeping: "หลับ",
    looking_down: "ก้มหน้า/โทรศัพท์",
    hand_raised: "ยกมือ",
    standing: "ยืน/ลุก",
    unknown: "ไม่ชัดเจน",
  }[value] || value || "-";
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

  const periods = tracking?.periods || [];
  const overallTracks = tracking?.tracks || [];
  const rows = periods.length
    ? periods.flatMap((period) =>
        (period.tracks || []).map((track) => ({
          ...track,
          period_label: period.label,
        })),
      )
    : overallTracks.map((track) => ({
        ...track,
        period_label: "ภาพรวม",
      }));

  section.classList.toggle("hidden", rows.length === 0);
  body.innerHTML = rows
    .map((track, index) => {
      const counts = track.event_counts || {};
      const rowClass = index % 2 === 0 ? "bg-white" : "bg-gray-50";
      return `
        <tr class="${rowClass}">
          <td class="px-3 py-2 whitespace-nowrap">${escapeHtml(track.period_label)}</td>
          <td class="px-3 py-2 font-semibold text-blue-700 whitespace-nowrap">ID ${toWholePeople(track.track_id)}</td>
          <td class="px-3 py-2 text-right whitespace-nowrap">${formatDuration(track.visible_seconds)}</td>
          <td class="px-3 py-2 text-right font-semibold text-green-700">${formatDecimal(track.attention_rate)}%</td>
          <td class="px-3 py-2 text-right">${toWholePeople(counts.attentive)}</td>
          <td class="px-3 py-2 text-right">${toWholePeople(counts.sleeping)}</td>
          <td class="px-3 py-2 text-right">${toWholePeople(counts.looking_down)}</td>
          <td class="px-3 py-2 text-right">${toWholePeople(counts.hand_raised)}</td>
          <td class="px-3 py-2 text-right">${toWholePeople(counts.standing)}</td>
          <td class="px-3 py-2 text-right">${toWholePeople(counts.unknown)}</td>
        </tr>
      `;
    })
    .join("");
}

function renderEvidenceReport(tracking = null) {
  const section = document.getElementById("reportEvidenceSection");
  const gallery = document.getElementById("reportEvidenceGallery");
  const caption = document.getElementById("reportEvidenceCaption");
  if (!section || !gallery || !caption) return;

  const evidence = tracking?.evidence || [];
  const displayLimit = 60;
  const references = evidence.filter((item) => item.kind === "reference");
  const events = evidence.filter((item) => item.kind !== "reference");
  const visibleEvidence = [
    ...references.slice(0, displayLimit),
    ...events.slice(0, Math.max(0, displayLimit - references.length)),
  ];
  section.classList.toggle("hidden", visibleEvidence.length === 0);
  caption.textContent =
    evidence.length > displayLimit
      ? `แสดง ${displayLimit} จาก ${evidence.length} ภาพ`
      : `${evidence.length} ภาพ`;

  gallery.innerHTML = visibleEvidence
    .map((item) => {
      const event = item.event || {};
      const isReference = item.kind === "reference";
      const title = isReference
        ? `ID ${toWholePeople(item.track_id)} - ภาพอ้างอิง`
        : `ID ${toWholePeople(item.track_id)} - ${behaviorLabel(item.behavior)}`;
      const detail = isReference
        ? `ตรวจพบครั้งแรก ${item.captured_time || "-"}`
        : `${item.captured_time || "-"} | ${formatDuration(event.duration_seconds)} | มั่นใจ ${formatDecimal(event.avg_confidence)}%`;
      return `
        <figure class="min-w-0 border border-gray-200 rounded-lg overflow-hidden bg-white">
          <img
            src="${escapeHtml(apiUrl(item.url || ""))}"
            alt="${escapeHtml(title)}"
            class="h-40 w-full object-cover bg-gray-100"
          />
          <figcaption class="px-3 py-2">
            <p class="text-sm font-semibold text-gray-800">${escapeHtml(title)}</p>
            <p class="mt-1 text-xs text-gray-500">${escapeHtml(detail)}</p>
          </figcaption>
        </figure>
      `;
    })
    .join("");
}

function renderReportTimeline(periods = [], periodSeconds = 600) {
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
    `ช่วงละ ${Math.round((Number(periodSeconds) || 600) / 60)} นาที`,
  );
  body.innerHTML = periods
    .map((period, index) => {
      const summary = period.summary || {};
      const rowClass = index % 2 === 0 ? "bg-white" : "bg-gray-50";
      return `
        <tr class="${rowClass}">
          <td class="px-3 py-2 font-medium text-gray-700 whitespace-nowrap">${escapeHtml(period.label)}</td>
          <td class="px-3 py-2 text-right">${formatDecimal(period.avg_people)}</td>
          <td class="px-3 py-2 text-right font-semibold text-green-700">${formatDecimal(period.avg_attention_rate)}%</td>
          <td class="px-3 py-2 text-right">${toWholePeople(summary.attentive)}</td>
          <td class="px-3 py-2 text-right">${toWholePeople(summary.sleeping)}</td>
          <td class="px-3 py-2 text-right">${toWholePeople(summary.looking_down)}</td>
          <td class="px-3 py-2 text-right">${toWholePeople(summary.hand_raised)}</td>
          <td class="px-3 py-2 text-right">${toWholePeople(summary.standing)}</td>
          <td class="px-3 py-2 text-right">${toWholePeople(summary.unknown)}</td>
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
      ? `สรุปทุก ${sourceData.sample_interval_seconds || 60} วินาทีของคลิป`
      : "อัปเดตทุก 2 วินาที",
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
  const feed = document.getElementById("liveFeed");
  const detectionCount = document.getElementById("detectionCount");
  if (!feed || !currentLab) return;

  if (!isStreamActive(currentLab, currentCamera)) {
    showFeedPlaceholder();
    return;
  }

  try {
    // ดึงข้อมูลการตรวจจับ
    const dataRes = await fetch(apiUrl(`/api/data/${currentLab}/${currentCamera}`));
    const data = await dataRes.json();

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
      const behaviorRes = await fetch(apiUrl(`/api/behavior/${currentLab}/${currentCamera}`));
      const behaviorData = await behaviorRes.json();

      if (behaviorData && !behaviorData.error) {
        updateBehaviorStats(behaviorData);
        detectionCount.textContent = `ตรวจพบ ${toWholePeople(behaviorData.total_people)} คน | ตั้งใจเรียน ${behaviorData.attention_rate}%`;
      }
    } else {
      detectionCount.textContent = `ตรวจพบ ${data.num_people} คน | เชื่อมั่น ${data.avg_confidence}%`;
    }
  } catch (e) {
    console.error("Error fetching data:", e);
    detectionCount.textContent = "ข้อมูลไม่พร้อม";
  }
}

// 🧠 อัปเดตสถิติพฤติกรรม
function updateBehaviorStats(data) {
  const attentiveEl = document.getElementById("behaviorAttentive");
  const sleepingEl = document.getElementById("behaviorSleeping");
  const lookingDownEl = document.getElementById("behaviorLookingDown");
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
    "flex-1 rounded-lg bg-white px-3 py-1.5 text-sm font-semibold text-slate-900 shadow-sm transition-colors sm:flex-none";
  const inactiveClass =
    "flex-1 rounded-lg px-3 py-1.5 text-sm font-semibold text-white/85 transition-colors hover:bg-white/10 hover:text-white sm:flex-none";

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
  return `${slug || "session"}_${Date.now()}`;
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
  const now = new Date();
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000);
  input.value = local.toISOString().slice(0, 16);
}

function resetDashboardState() {
  stopSourceStatusPolling();
  latestExportData = null;
  currentSourceType = null;
  autoReportShown = false;
  activeSources.clear();
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
  renderLiveTracks([]);
}

// 🎥 เริ่มรอบวิเคราะห์
function startSession() {
  const input = document.getElementById("sessionNameInput");
  const name = input?.value.trim() || getDefaultSessionName();
  currentRoomName =
    document.getElementById("roomNameInput")?.value.trim() || "ไม่ระบุ";
  currentCourseName =
    document.getElementById("courseNameInput")?.value.trim() || "ไม่ระบุ";
  currentRecordingStart =
    document.getElementById("recordingStartInput")?.value || "";
  openAnalysisSession(makeSessionId(name), name);
}

function openAnalysisSession(sessionId, sessionName) {
  currentLab = sessionId;
  currentSessionName = sessionName;
  currentCamera = 1;

  document.getElementById("labMenu").classList.add("hidden");
  document.getElementById("labInterface").classList.remove("hidden");
  document.getElementById("currentLabName").textContent = sessionName;
  setTextIfPresent(
    "currentSessionMeta",
    `${currentCourseName} | ${currentRoomName}`,
  );

  resetDashboardState();
  updateCameraFeed();
  startLiveFeed();
  initCharts(); // 📊 สร้างกราฟ
  startChartUpdates(); // 📊 เริ่มอัปเดตกราฟ
  startAlertPolling(); // 🔔 เริ่มยิงฟังการแจ้งเตือน
}

// 🔙 กลับไปหน้าเริ่มต้น
function backToMenu() {
  const sessionId = currentLab;
  const cameraId = currentCamera;
  if (sessionId && isStreamActive(sessionId, cameraId)) {
    fetch(apiUrl(`/api/sources/${sessionId}/${cameraId}`), {
      method: "DELETE",
    }).catch(() => {
      /* the server may already be stopped */
    });
  }
  document.getElementById("labInterface").classList.add("hidden");
  document.getElementById("labMenu").classList.remove("hidden");
  currentLab = "";
  currentSessionName = "";
  currentRoomName = "";
  currentCourseName = "";
  currentRecordingStart = "";

  // หยุด intervals
  if (liveFeedInterval) {
    clearInterval(liveFeedInterval);
    liveFeedInterval = null;
  }
  stopChartUpdates();
  stopAlertPolling(); // 🔔 หยุดยิงฟังแจ้งเตือน
  resetDashboardState();
  resetRecordingStartInput();
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
  const labId = currentLab || "unknown";
  const fileName = `ClassMood_Report_${labId}_${Date.now()}`;

  // สร้าง object สรุปข้อมูลจาก latestExportData หรือ fallback
  let data;
  if (latestExportData) {
    const s = latestExportData.summary || {};
    const latest = s.latest_summary || {};
    const hasPeriods = (latestExportData.periods || []).length > 0;
    const reportBehavior = hasPeriods ? s.overall_summary || latest : latest;
    data = {
      lab_id: latestExportData.lab_id,
      session_name: currentSessionName || latestExportData.lab_id,
      export_time: latestExportData.export_time,
      avg_attention_rate: s.avg_attention_rate,
      avg_people: s.avg_people,
      max_people: s.max_people,
      total_records: s.total_records,
      latest_attention_rate: s.latest_attention_rate,
      report_attention_label: hasPeriods
        ? "อัตราความตั้งใจเฉลี่ย (%)"
        : "อัตราความตั้งใจล่าสุด (%)",
      report_attention_rate: hasPeriods
        ? s.avg_attention_rate
        : s.latest_attention_rate,
      latest_total_people: s.latest_total_people,
      behavior_scope: hasPeriods ? "ภาพรวมพฤติกรรม" : "พฤติกรรมล่าสุด",
      behavior_attentive: reportBehavior.attentive || 0,
      behavior_sleeping: reportBehavior.sleeping || 0,
      behavior_looking_down: reportBehavior.looking_down || 0,
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
      total_records: 0,
      latest_attention_rate: 0,
      report_attention_label: "อัตราความตั้งใจล่าสุด (%)",
      report_attention_rate: 0,
      latest_total_people: 0,
      behavior_attentive: 0,
      behavior_sleeping: 0,
      behavior_looking_down: 0,
      behavior_hand_raised: 0,
      behavior_standing: 0,
      behavior_unknown: 0,
      behavior_scope: "พฤติกรรมล่าสุด",
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
  const tracking = latestExportData?.tracking;
  if (!tracking) return;

  const session = tracking.session || {};
  rows.push([]);
  rows.push(["ข้อมูลคาบเรียน"]);
  rows.push(["รายวิชา", session.course_name || "ไม่ระบุ"]);
  rows.push(["ห้อง", session.room_name || "ไม่ระบุ"]);
  rows.push(["เวลาเริ่มบันทึก", session.recording_started_at || "-"]);

  const periods = tracking.periods || [];
  const reportRows = periods.length
    ? periods.flatMap((period) =>
        (period.tracks || []).map((track) => [period.label, track]),
      )
    : (tracking.tracks || []).map((track) => ["ภาพรวม", track]);
  if (!reportRows.length) return;

  rows.push([]);
  rows.push(["สรุปรายบุคคล (Anonymous ID)"]);
  rows.push([
    "ช่วงเวลา",
    "รหัสบุคคล",
    "เวลาที่ตรวจพบ (วินาที)",
    "ความตั้งใจ (%)",
    "ตั้งใจเรียน (ครั้ง)",
    "หลับ (ครั้ง)",
    "ก้มหน้า/โทรศัพท์ (ครั้ง)",
    "ยกมือ (ครั้ง)",
    "ยืน/ลุก (ครั้ง)",
    "ไม่ชัดเจน (ครั้ง)",
  ]);
  for (const [periodLabel, track] of reportRows) {
    const counts = track.event_counts || {};
    rows.push([
      periodLabel,
      `ID ${track.track_id}`,
      track.visible_seconds,
      track.attention_rate,
      toWholePeople(counts.attentive),
      toWholePeople(counts.sleeping),
      toWholePeople(counts.looking_down),
      toWholePeople(counts.hand_raised),
      toWholePeople(counts.standing),
      toWholePeople(counts.unknown),
    ]);
  }

  const evidence = tracking.evidence || [];
  if (!evidence.length) return;
  rows.push([]);
  rows.push(["ภาพหลักฐานประกอบเหตุการณ์"]);
  rows.push([
    "รหัสบุคคล",
    "ประเภทภาพ",
    "เวลา",
    "พฤติกรรม",
    "ระยะเวลา (วินาที)",
    "ความมั่นใจ (%)",
    "ชื่อไฟล์",
  ]);
  for (const item of evidence) {
    const event = item.event || {};
    rows.push([
      `ID ${item.track_id}`,
      item.kind === "reference" ? "ภาพอ้างอิง" : "ภาพเหตุการณ์",
      item.captured_time,
      behaviorLabel(item.behavior),
      item.kind === "event" ? event.duration_seconds : "",
      item.kind === "event" ? event.avg_confidence : "",
      item.filename,
    ]);
  }
}

// 🛠️ สร้างเนื้อหา CSV
function buildCSV(data) {
  const rows = [
    ["รายงานรอบวิเคราะห์ - ClassMood AI"],
    [],
    ["ข้อมูลทั่วไป"],
    ["รอบวิเคราะห์", data.session_name || data.lab_id],
    ["รหัสรอบ", data.lab_id],
    ["เวลาส่งออก", data.export_time],
    [],
    ["สถิติรวม"],
    ["จำนวนนักศึกษาเฉลี่ย (คน)", data.avg_people],
    ["ความตั้งใจเรียนเฉลี่ย (%)", data.avg_attention_rate],
    ["นักเรียนสูงสุด (คน)", data.max_people],
    ["จำนวนบันทึกทั้งหมด", data.total_records],
    [],
    [data.behavior_scope || "พฤติกรรมล่าสุด"],
    ["ตั้งใจเรียน (คน)", data.behavior_attentive],
    ["หลับ (คน)", data.behavior_sleeping],
    ["ก้มหน้า (คน)", data.behavior_looking_down],
    ["ยกมือ (คน)", data.behavior_hand_raised],
    ["ยืน/ลุก (คน)", data.behavior_standing],
    ["ไม่ชัดเจน (คน)", data.behavior_unknown],
    [
      data.report_attention_label || "อัตราความตั้งใจล่าสุด (%)",
      data.report_attention_rate ?? data.latest_attention_rate,
    ],
  ];

  if ((latestExportData?.periods || []).length > 0) {
    rows.push([]);
    rows.push(["สรุปตามช่วงเวลา"]);
    rows.push([
      "ช่วงในคลิป", "คนเฉลี่ย", "ความตั้งใจ (%)", "ตั้งใจเรียน",
      "หลับ", "ก้มหน้า", "ยกมือ", "ยืน/ลุก", "ไม่ชัดเจน",
    ]);
    for (const period of latestExportData.periods) {
      const summary = period.summary || {};
      rows.push([
        period.label,
        period.avg_people,
        period.avg_attention_rate,
        toWholePeople(summary.attentive),
        toWholePeople(summary.sleeping),
        toWholePeople(summary.looking_down),
        toWholePeople(summary.hand_raised),
        toWholePeople(summary.standing),
        toWholePeople(summary.unknown),
      ]);
    }
  }

  appendTrackingExportRows(rows);

  // เพิ่มข้อมูลย้อนหลัง
  if (
    latestExportData &&
    latestExportData.history &&
    latestExportData.history.length > 0
  ) {
    rows.push([]);
    rows.push(["ข้อมูลย้อนหลัง"]);
    rows.push([
      "เวลา", "ความตั้งใจ (%)", "จำนวนคน", "ตั้งใจเรียน",
      "หลับ", "ก้มหน้า", "ยกมือ", "ยืน/ลุก", "ไม่ชัดเจน",
    ]);
    for (const h of latestExportData.history) {
      const summary = h.summary || {};
      rows.push([
        h.time,
        h.attention_rate,
        h.total_people,
        toWholePeople(summary.attentive),
        toWholePeople(summary.sleeping),
        toWholePeople(summary.looking_down),
        toWholePeople(summary.hand_raised),
        toWholePeople(summary.standing),
        toWholePeople(summary.unknown),
      ]);
    }
  }

  return rows
    .map((r) => r.map((cell) => `"${cell ?? ""}"`).join(","))
    .join("\n");
}

// 🛠️ สร้างเนื้อหา Excel (TSV)
function buildExcel(data) {
  const rows = [
    ["รายงานรอบวิเคราะห์ - ClassMood AI"],
    [],
    ["รอบวิเคราะห์", data.session_name || data.lab_id],
    ["รหัสรอบ", data.lab_id],
    ["เวลาส่งออก", data.export_time],
    [],
    ["จำนวนนักศึกษาเฉลี่ย (คน)", data.avg_people],
    ["ความตั้งใจเรียนเฉลี่ย (%)", data.avg_attention_rate],
    ["นักเรียนสูงสุด (คน)", data.max_people],
    ["จำนวนบันทึก", data.total_records],
    [],
    [data.behavior_scope || "พฤติกรรมล่าสุด"],
    ["ตั้งใจเรียน (คน)", data.behavior_attentive],
    ["หลับ (คน)", data.behavior_sleeping],
    ["ก้มหน้า (คน)", data.behavior_looking_down],
    ["ยกมือ (คน)", data.behavior_hand_raised],
    ["ยืน/ลุก (คน)", data.behavior_standing],
    ["ไม่ชัดเจน (คน)", data.behavior_unknown],
    [
      data.report_attention_label || "อัตราความตั้งใจล่าสุด (%)",
      data.report_attention_rate ?? data.latest_attention_rate,
    ],
  ];

  if ((latestExportData?.periods || []).length > 0) {
    rows.push([]);
    rows.push(["สรุปตามช่วงเวลา"]);
    rows.push([
      "ช่วงในคลิป", "คนเฉลี่ย", "ความตั้งใจ (%)", "ตั้งใจเรียน",
      "หลับ", "ก้มหน้า", "ยกมือ", "ยืน/ลุก", "ไม่ชัดเจน",
    ]);
    for (const period of latestExportData.periods) {
      const summary = period.summary || {};
      rows.push([
        period.label,
        period.avg_people,
        period.avg_attention_rate,
        toWholePeople(summary.attentive),
        toWholePeople(summary.sleeping),
        toWholePeople(summary.looking_down),
        toWholePeople(summary.hand_raised),
        toWholePeople(summary.standing),
        toWholePeople(summary.unknown),
      ]);
    }
  }

  appendTrackingExportRows(rows);

  if (
    latestExportData &&
    latestExportData.history &&
    latestExportData.history.length > 0
  ) {
    rows.push([]);
    rows.push([
      "เวลา", "ความตั้งใจ (%)", "จำนวนคน", "ตั้งใจเรียน",
      "หลับ", "ก้มหน้า", "ยกมือ", "ยืน/ลุก", "ไม่ชัดเจน",
    ]);
    for (const h of latestExportData.history) {
      const summary = h.summary || {};
      rows.push([
        h.time,
        h.attention_rate,
        h.total_people,
        toWholePeople(summary.attentive),
        toWholePeople(summary.sleeping),
        toWholePeople(summary.looking_down),
        toWholePeople(summary.hand_raised),
        toWholePeople(summary.standing),
        toWholePeople(summary.unknown),
      ]);
    }
  }

  return rows.map((r) => r.join("\t")).join("\n");
}

function waitForReportImages(root, timeoutMs = 5000) {
  const images = Array.from(root.querySelectorAll("img"));
  if (!images.length) return Promise.resolve();
  return Promise.all(
    images.map(
      (image) =>
        new Promise((resolve) => {
          if (image.complete) {
            resolve();
            return;
          }
          const done = () => resolve();
          image.addEventListener("load", done, { once: true });
          image.addEventListener("error", done, { once: true });
          setTimeout(done, timeoutMs);
        }),
    ),
  );
}

function collectPdfKeepTogetherRanges(root) {
  const rootRect = root.getBoundingClientRect();
  if (!rootRect.height) return [];

  return Array.from(
    root.querySelectorAll(
      "[data-pdf-keep-together], #reportEvidenceGallery figure, table tr, canvas",
    ),
  )
    .map((element) => {
      const rect = element.getBoundingClientRect();
      return {
        top: Math.max(0, rect.top - rootRect.top),
        bottom: Math.min(rootRect.height, rect.bottom - rootRect.top),
      };
    })
    .filter((range) => range.bottom - range.top > 1);
}

function choosePdfSliceEnd(
  sourceStart,
  desiredEnd,
  pagePixelHeight,
  keepTogetherRanges,
) {
  const crossingRanges = keepTogetherRanges.filter((range) => {
    const height = range.bottom - range.top;
    return (
      height <= pagePixelHeight &&
      range.top > sourceStart + 1 &&
      range.top < desiredEnd &&
      range.bottom > desiredEnd
    );
  });
  if (!crossingRanges.length) return desiredEnd;

  const safeEnd = Math.min(...crossingRanges.map((range) => range.top));
  return safeEnd > sourceStart + 1 ? safeEnd : desiredEnd;
}

// 🛠️ สร้าง PDF จาก modal content
function generatePDF(labId) {
  const reportContent = document.querySelector("#reportModal .bg-white");
  if (!reportContent) {
    alert("ไม่พบเนื้อหารายงาน");
    return;
  }
  if (typeof html2canvas === "undefined" || !window.jspdf) {
    alert("ไม่สามารถสร้าง PDF ได้ กรุณาตรวจสอบการเชื่อมต่ออินเทอร์เน็ต");
    return;
  }

  const dlSection = document.getElementById("reportDownloadActions");
  const closeButton = document.getElementById("reportCloseButton");
  const timelineWrapper = document.getElementById("reportTimelineTableWrapper");
  const trackingWrapper = document.getElementById("reportTrackingTableWrapper");
  const savedStyles = {
    maxHeight: reportContent.style.maxHeight,
    overflow: reportContent.style.overflow,
    width: reportContent.style.width,
    maxWidth: reportContent.style.maxWidth,
    actionsDisplay: dlSection?.style.display || "",
    closeDisplay: closeButton?.style.display || "",
    timelineOverflow: timelineWrapper?.style.overflow || "",
    trackingOverflow: trackingWrapper?.style.overflow || "",
  };
  const restoreReportLayout = () => {
    reportContent.style.maxHeight = savedStyles.maxHeight;
    reportContent.style.overflow = savedStyles.overflow;
    reportContent.style.width = savedStyles.width;
    reportContent.style.maxWidth = savedStyles.maxWidth;
    if (dlSection) dlSection.style.display = savedStyles.actionsDisplay;
    if (closeButton) closeButton.style.display = savedStyles.closeDisplay;
    if (timelineWrapper) timelineWrapper.style.overflow = savedStyles.timelineOverflow;
    if (trackingWrapper) trackingWrapper.style.overflow = savedStyles.trackingOverflow;
  };

  reportContent.style.maxHeight = "none";
  reportContent.style.overflow = "visible";
  reportContent.style.width = "1200px";
  reportContent.style.maxWidth = "1200px";
  if (dlSection) dlSection.style.display = "none";
  if (closeButton) closeButton.style.display = "none";
  if (timelineWrapper) timelineWrapper.style.overflow = "visible";
  if (trackingWrapper) trackingWrapper.style.overflow = "visible";

  waitForReportImages(reportContent)
    .then(() => {
      const contentHeight = reportContent.getBoundingClientRect().height;
      const keepTogetherRanges = collectPdfKeepTogetherRanges(reportContent);
      return html2canvas(reportContent, { scale: 2, useCORS: true })
        .then((canvas) => ({
          canvas,
          contentHeight,
          keepTogetherRanges,
        }));
    })
    .then(({ canvas, contentHeight, keepTogetherRanges }) => {
      restoreReportLayout();

      const { jsPDF } = window.jspdf;
      const pdf = new jsPDF("p", "mm", "a4");
      const pageWidth = pdf.internal.pageSize.getWidth();
      const pageHeight = pdf.internal.pageSize.getHeight();
      const margin = 10;
      const imageWidth = pageWidth - margin * 2;
      const pageContentHeight = pageHeight - margin * 2;
      const pagePixelHeight =
        (pageContentHeight / imageWidth) * canvas.width;
      const canvasScaleY = canvas.height / Math.max(1, contentHeight);
      const scaledRanges = keepTogetherRanges.map((range) => ({
        top: range.top * canvasScaleY,
        bottom: range.bottom * canvasScaleY,
      }));

      let sourceY = 0;
      let pageIndex = 0;
      while (sourceY < canvas.height) {
        const desiredEnd = Math.min(
          canvas.height,
          sourceY + pagePixelHeight,
        );
        const safeEnd = choosePdfSliceEnd(
          sourceY,
          desiredEnd,
          pagePixelHeight,
          scaledRanges,
        );
        const sliceEnd = Math.max(
          sourceY + 1,
          Math.min(canvas.height, Math.floor(safeEnd)),
        );
        const slicePixelHeight = sliceEnd - sourceY;
        const sliceHeight =
          (slicePixelHeight * imageWidth) / canvas.width;
        const sliceCanvas = document.createElement("canvas");
        sliceCanvas.width = canvas.width;
        sliceCanvas.height = slicePixelHeight;
        const context = sliceCanvas.getContext("2d");
        context.drawImage(
          canvas,
          0,
          sourceY,
          canvas.width,
          slicePixelHeight,
          0,
          0,
          sliceCanvas.width,
          sliceCanvas.height,
        );

        if (pageIndex > 0) pdf.addPage();
        pdf.addImage(
          sliceCanvas.toDataURL("image/png"),
          "PNG",
          margin,
          margin,
          imageWidth,
          sliceHeight,
        );
        sourceY = sliceEnd;
        pageIndex += 1;
      }

      pdf.save(`ClassMood_Report_${labId}_${Date.now()}.pdf`);
    })
    .catch((error) => {
      restoreReportLayout();
      console.error("Error generating PDF:", error);
      alert("ไม่สามารถสร้าง PDF ได้");
    });
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

// 📊 เปิด modal และดึงข้อมูลจริงจาก backend
async function exportReport() {
  if (!currentLab) {
    alert("กรุณาเริ่มรอบวิเคราะห์ก่อน");
    return;
  }

  const modal = document.getElementById("reportModal");
  if (modal) modal.classList.remove("hidden");
  renderReportTimeline([]);
  renderTrackingReport(null);
  renderEvidenceReport(null);

  // ชื่อรอบ
  const labName =
    document.getElementById("currentLabName")?.textContent || "ไม่ทราบรอบ";
  const el = document.getElementById("reportLabName");
  if (el) el.textContent = labName;

  // วันที่/เวลา
  const now = new Date();
  const dateStr = now.toLocaleDateString("th-TH", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
  const timeStr = now.toLocaleTimeString("th-TH");
  const dateEl = document.getElementById("reportDate");
  const timeEl = document.getElementById("reportTime");
  if (dateEl) dateEl.textContent = `วันที่: ${dateStr}`;
  if (timeEl) timeEl.textContent = `เวลาส่งออก: ${timeStr}`;

  // ดึงข้อมูลจาก backend
  try {
    const res = await fetch(apiUrl(`/api/export/${currentLab}`));
    const data = await res.json();
    latestExportData = {
      ...data,
      session_name: currentSessionName || data.lab_id,
    };

    const s = latestExportData.summary || {};
    const latest = s.latest_summary || {};
    const periods = latestExportData.periods || [];
    const tracking = latestExportData.tracking || null;
    const session = tracking?.session || {};
    const isTimelineReport = periods.length > 0;
    const reportBehavior = isTimelineReport
      ? s.overall_summary || latest
      : latest;

    const set = (id, text) => {
      const el = document.getElementById(id);
      if (el) el.textContent = text;
    };

    set("reportRecords", `บันทึก: ${s.total_records ?? 0} รายการ`);
    set(
      "reportSessionContext",
      `วิชา: ${session.course_name || currentCourseName || "ไม่ระบุ"} | ห้อง: ${session.room_name || currentRoomName || "ไม่ระบุ"}`,
    );
    set("reportAvgPeople", `นักเรียนเฉลี่ย: ${s.avg_people ?? 0} คน`);
    set(
      "reportAvgAttention",
      `ความตั้งใจเฉลี่ย: ${s.avg_attention_rate ?? 0}%`,
    );
    set("reportMaxPeople", `นักเรียนสูงสุด: ${toWholePeople(s.max_people)} คน`);
    set(
      "reportBehaviorTitle",
      isTimelineReport ? "ภาพรวมพฤติกรรม" : "พฤติกรรมล่าสุด",
    );
    set(
      "reportAttentionLabel",
      isTimelineReport ? "อัตราความตั้งใจเฉลี่ย" : "อัตราความตั้งใจล่าสุด",
    );
    set("reportAttentive", `${toWholePeople(reportBehavior.attentive)} คน`);
    set("reportSleeping", `${toWholePeople(reportBehavior.sleeping)} คน`);
    set("reportLookingDown", `${toWholePeople(reportBehavior.looking_down)} คน`);
    set("reportHandRaised", `${toWholePeople(reportBehavior.hand_raised)} คน`);
    set("reportStanding", `${toWholePeople(reportBehavior.standing)} คน`);
    set("reportUnknown", `${toWholePeople(reportBehavior.unknown)} คน`);
    set(
      "reportLatestAttention",
      `${isTimelineReport ? s.avg_attention_rate ?? 0 : s.latest_attention_rate ?? 0}%`,
    );
    renderReportTimeline(periods, latestExportData.period_seconds);
    renderTrackingReport(tracking);
    renderEvidenceReport(tracking);
  } catch (e) {
    console.error("Error fetching export data:", e);
    latestExportData = null;
    renderReportTimeline([]);
    renderTrackingReport(null);
    renderEvidenceReport(null);
    const recEl = document.getElementById("reportRecords");
    if (recEl) recEl.textContent = "ไม่สามารถโหลดข้อมูลได้";
  }
}

// ❌ ปิด modal
function closeReportModal() {
  const modal = document.getElementById("reportModal");
  if (modal) modal.classList.add("hidden");
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
        labels: ["ตั้งใจเรียน", "หลับ", "ก้มหน้า/โทรศัพท์", "ยกมือ", "ยืน/ลุก", "ไม่ชัดเจน"],
        datasets: [
          {
            data: [0, 0, 0, 0, 0, 0],
            backgroundColor: [
              "rgba(34, 197, 94, 0.8)",
              "rgba(239, 68, 68, 0.8)",
              "rgba(249, 115, 22, 0.8)",
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
  if (!currentLab) return;

  try {
    const res = await fetch(apiUrl(`/api/stats/${currentLab}`));
    const data = await res.json();

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
  if (!currentLab) return;

  try {
    const res = await fetch(apiUrl(`/api/activities/${currentLab}`));
    const data = await res.json();

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
  updateModeToggle();

  const savedDarkMode = localStorage.getItem("darkMode");
  if (savedDarkMode === "true") {
    document.body.classList.add("dark");
    setTextIfPresent("themeIcon", "สว่าง");
    setTextIfPresent("themeText", "โหมดสว่าง");
  }

  const sessionInput = document.getElementById("sessionNameInput");
  if (sessionInput) {
    sessionInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") startSession();
    });
  }

  resetRecordingStartInput();
});

// =============================================
// 🔔  Alert polling (แจ้งเตือนแบบ real-time)
// =============================================

function startAlertPolling() {
  if (alertPollInterval) return; // กันทำซ้ำ
  alertPollInterval = setInterval(pollAlerts, 3000);
  pollAlerts(); // เรียกทันที
}

function stopAlertPolling() {
  if (alertPollInterval) {
    clearInterval(alertPollInterval);
    alertPollInterval = null;
  }
}

function startSourceStatusPolling() {
  stopSourceStatusPolling();
  if (!currentLab || currentSourceType !== "video") return;
  checkSourceStatus();
  sourceStatusInterval = setInterval(checkSourceStatus, 1000);
}

function stopSourceStatusPolling() {
  if (sourceStatusInterval) {
    clearInterval(sourceStatusInterval);
    sourceStatusInterval = null;
  }
}

async function checkSourceStatus() {
  if (!currentLab || currentSourceType !== "video") return;

  try {
    const res = await fetch(apiUrl(`/api/sources/${currentLab}/${currentCamera}/status`));
    if (!res.ok) return;
    const data = await res.json();

    if (data.source_type === "video" && data.ended) {
      await handleVideoEnded(data);
    } else if (data.error) {
      setConnectionStatus("แหล่งภาพมีปัญหา", "text-red-600");
      setSourceStatusText(`Error: ${data.error}`, "text-xs font-medium text-red-600");
      stopSourceStatusPolling();
    } else if (data.processing_mode === "sampled") {
      const progress = Number(data.progress_percent || 0).toFixed(1);
      const position = formatVideoTime(data.position_seconds);
      const duration = formatVideoTime(data.duration_seconds);
      setConnectionStatus("กำลังวิเคราะห์คลิปยาว", "text-purple-600");
      setSourceStatusText(
        `กำลังวิเคราะห์ ${progress}% | ${position} / ${duration}`,
        "text-xs font-medium text-purple-600",
      );
    }
  } catch (_) {
    /* server not running is fine */
  }
}

async function handleVideoEnded(data) {
  if (autoReportShown || !currentLab) return;
  autoReportShown = true;
  stopSourceStatusPolling();

  if (liveFeedInterval) {
    clearInterval(liveFeedInterval);
    liveFeedInterval = null;
  }
  stopChartUpdates();
  stopAlertPolling();

  const label = data.source ? data.source.split(/[\\/]/).pop() : "";
  setConnectionStatus("คลิปจบแล้ว", "text-blue-600");
  setSourceStatusText(
    label ? `■ คลิปจบแล้ว: ${label}` : "■ คลิปจบแล้ว",
    "text-xs font-medium text-blue-600",
  );
  showToast("คลิปวิดีโอจบแล้ว กำลังเตรียมรายงาน", "info");

  await updateLiveFeed();
  await updateCharts();
  setTextIfPresent("detectionCount", "คลิปจบแล้ว");
  activeSources.delete(_srcKey(currentLab, currentCamera));
  await exportReport();
  showToast("รายงานพร้อมแล้ว เลือกรูปแบบไฟล์ที่ต้องการดาวน์โหลด", "success");
}

async function pollAlerts() {
  try {
    const res = await fetch(apiUrl(`/api/alerts?since_id=${lastAlertId}`));
    if (!res.ok) return;
    const data = await res.json();
    for (const alert of data.alerts || []) {
      showToast(alert.message, alert.type);
    }
    if (data.latest_id > lastAlertId) lastAlertId = data.latest_id;
  } catch (_) {
    /* server not running is fine */
  }
}

function showToast(message, type = "info") {
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

  const toast = document.createElement("div");
  toast.className = `${bg} text-white text-sm font-medium px-4 py-3 rounded-lg shadow-lg
    pointer-events-auto opacity-0 transition-opacity duration-300`;
  toast.textContent = `${label}: ${cleanMessage}`;
  container.appendChild(toast);

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
async function setVideoSource(labId, camId, source, displayLabel = null) {
  if (!labId) {
    showToast("กรุณาเริ่มรอบวิเคราะห์ก่อน", "warning");
    return;
  }
  try {
    const res = await fetch(apiUrl(`/api/sources/${labId}/${camId}`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source,
        session_name: currentSessionName || labId,
        room_name: currentRoomName || "ไม่ระบุ",
        course_name: currentCourseName || "ไม่ระบุ",
        recording_start: currentRecordingStart || null,
      }),
    });
    const data = await readResponsePayload(res);
    if (data.ok) {
      currentSourceType =
        data.source_type || (typeof source === "number" ? "webcam" : "video");
      autoReportShown = false;
      streamReloadToken += 1;
      activeSources.add(_srcKey(labId, camId));
      updateCameraFeed();
      startLiveFeed();
      startChartUpdates();
      startAlertPolling();
      updateAnalysisCadence(data);
      const srcLabel =
        displayLabel || (typeof source === "number" ? `Webcam ${source}` : source);
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
      currentSourceType = null;
      stopSourceStatusPolling();
      updateAnalysisCadence();
      setConnectionStatus("เชื่อมต่อไม่สำเร็จ", "text-red-600");
      showToast(`เชื่อมต่อไม่สำเร็จ: ${data.error || ""}`, "alert");
    }
  } catch (e) {
    currentSourceType = null;
    stopSourceStatusPolling();
    updateAnalysisCadence();
    setConnectionStatus("เชื่อมต่อไม่สำเร็จ", "text-red-600");
    showToast(`เชื่อมต่อไม่สำเร็จ: ${e.message}`, "alert");
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
  const idx = parseInt(document.getElementById("webcamSelect")?.value ?? "0");
  setVideoSource(currentLab, currentCamera, idx);
}

function connectVideoFile() {
  if (!currentLab) {
    showToast("กรุณาเริ่มรอบวิเคราะห์ก่อน", "warning");
    return;
  }

  const input = document.getElementById("videoFileInput");
  const file = input?.files?.[0];
  if (!file) {
    showToast("กรุณาเลือกไฟล์วิดีโอก่อน", "warning");
    return;
  }

  uploadAndUseVideo(file);
}

async function uploadAndUseVideo(file) {
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

    const res = await fetch(apiUrl("/api/videos"), {
      method: "POST",
      body: formData,
    });
    const data = await readResponsePayload(res);

    if (!res.ok || !data.ok) {
      showToast(`อัปโหลดไม่สำเร็จ: ${data.error || res.statusText}`, "alert");
      return;
    }

    await setVideoSource(currentLab, currentCamera, data.source, data.filename);
    const input = document.getElementById("videoFileInput");
    if (input) input.value = "";
  } catch (e) {
    showToast(`อัปโหลดไม่สำเร็จ: ${e.message}`, "alert");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = oldLabel || "อัปโหลดคลิป";
      btn.classList.remove("opacity-60", "cursor-not-allowed");
    }
  }
}
