let currentCamera = 1;
let currentLab = "";
let currentSessionName = "";
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
        detectionCount.textContent = `ตรวจพบ ${behaviorData.total_people} คน | ตั้งใจเรียน ${behaviorData.attention_rate}%`;
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

  if (data.summary) {
    if (attentiveEl)
      attentiveEl.textContent = `${data.summary.attentive || 0} คน`;
    if (sleepingEl) sleepingEl.textContent = `${data.summary.sleeping || 0} คน`;
    if (lookingDownEl)
      lookingDownEl.textContent = `${data.summary.looking_down || 0} คน`;
    if (handRaisedEl)
      handRaisedEl.textContent = `${data.summary.hand_raised || 0} คน`;
    if (standingEl) standingEl.textContent = `${data.summary.standing || 0} คน`;
    if (unknownEl) unknownEl.textContent = `${data.summary.unknown || 0} คน`;
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

function resetDashboardState() {
  stopSourceStatusPolling();
  latestExportData = null;
  currentSourceType = null;
  autoReportShown = false;
  activeSources.clear();
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
}

// 🎥 เริ่มรอบวิเคราะห์
function startSession() {
  const input = document.getElementById("sessionNameInput");
  const name = input?.value.trim() || getDefaultSessionName();
  openAnalysisSession(makeSessionId(name), name);
}

function openAnalysisSession(sessionId, sessionName) {
  currentLab = sessionId;
  currentSessionName = sessionName;
  currentCamera = 1;

  document.getElementById("labMenu").classList.add("hidden");
  document.getElementById("labInterface").classList.remove("hidden");
  document.getElementById("currentLabName").textContent = sessionName;

  resetDashboardState();
  updateCameraFeed();
  startLiveFeed();
  initCharts(); // 📊 สร้างกราฟ
  startChartUpdates(); // 📊 เริ่มอัปเดตกราฟ
  startAlertPolling(); // 🔔 เริ่มยิงฟังการแจ้งเตือน
}

// 🔙 กลับไปหน้าเริ่มต้น
function backToMenu() {
  document.getElementById("labInterface").classList.add("hidden");
  document.getElementById("labMenu").classList.remove("hidden");
  currentLab = "";
  currentSessionName = "";

  // หยุด intervals
  if (liveFeedInterval) {
    clearInterval(liveFeedInterval);
    liveFeedInterval = null;
  }
  stopChartUpdates();
  stopAlertPolling(); // 🔔 หยุดยิงฟังแจ้งเตือน
  resetDashboardState();
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
    data = {
      lab_id: latestExportData.lab_id,
      session_name: currentSessionName || latestExportData.lab_id,
      export_time: latestExportData.export_time,
      avg_attention_rate: s.avg_attention_rate,
      avg_people: s.avg_people,
      max_people: s.max_people,
      total_records: s.total_records,
      latest_attention_rate: s.latest_attention_rate,
      latest_total_people: s.latest_total_people,
      behavior_attentive: latest.attentive || 0,
      behavior_sleeping: latest.sleeping || 0,
      behavior_looking_down: latest.looking_down || 0,
      behavior_hand_raised: latest.hand_raised || 0,
      behavior_standing: latest.standing || 0,
      behavior_unknown: latest.unknown || 0,
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
      latest_total_people: 0,
      behavior_attentive: 0,
      behavior_sleeping: 0,
      behavior_looking_down: 0,
      behavior_hand_raised: 0,
      behavior_standing: 0,
      behavior_unknown: 0,
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
    ["พฤติกรรมล่าสุด"],
    ["ตั้งใจเรียน (คน)", data.behavior_attentive],
    ["หลับ (คน)", data.behavior_sleeping],
    ["ก้มหน้า (คน)", data.behavior_looking_down],
    ["ยกมือ (คน)", data.behavior_hand_raised],
    ["ยืน/ลุก (คน)", data.behavior_standing],
    ["ไม่ชัดเจน (คน)", data.behavior_unknown],
    ["อัตราความตั้งใจล่าสุด (%)", data.latest_attention_rate],
  ];

  // เพิ่มข้อมูลย้อนหลัง
  if (
    latestExportData &&
    latestExportData.history &&
    latestExportData.history.length > 0
  ) {
    rows.push([]);
    rows.push(["ข้อมูลย้อนหลัง"]);
    rows.push(["เวลา", "ความตั้งใจ (%)", "จำนวนคน"]);
    for (const h of latestExportData.history) {
      rows.push([h.time, h.attention_rate, h.total_people]);
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
    ["ตั้งใจเรียน (คน)", data.behavior_attentive],
    ["หลับ (คน)", data.behavior_sleeping],
    ["ก้มหน้า (คน)", data.behavior_looking_down],
    ["ยกมือ (คน)", data.behavior_hand_raised],
    ["ยืน/ลุก (คน)", data.behavior_standing],
    ["ไม่ชัดเจน (คน)", data.behavior_unknown],
    ["อัตราความตั้งใจล่าสุด (%)", data.latest_attention_rate],
  ];

  if (
    latestExportData &&
    latestExportData.history &&
    latestExportData.history.length > 0
  ) {
    rows.push([]);
    rows.push(["เวลา", "ความตั้งใจ (%)", "จำนวนคน"]);
    for (const h of latestExportData.history) {
      rows.push([h.time, h.attention_rate, h.total_people]);
    }
  }

  return rows.map((r) => r.join("\t")).join("\n");
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

  // ซ่อนส่วนปุ่มดาวน์โหลดขณะ capture เพื่อไม่ให้ติดใน PDF
  const dlSection = reportContent.querySelector(".space-y-3");
  if (dlSection) dlSection.style.visibility = "hidden";

  html2canvas(reportContent, { scale: 2, useCORS: true }).then((canvas) => {
    if (dlSection) dlSection.style.visibility = "";

    const { jsPDF } = window.jspdf;
    const pdf = new jsPDF("p", "mm", "a4");
    const pageWidth = pdf.internal.pageSize.getWidth();
    const pageHeight = pdf.internal.pageSize.getHeight();
    const margin = 10;
    const imgWidth = pageWidth - margin * 2;
    const imgHeight = (canvas.height * imgWidth) / canvas.width;
    const imgData = canvas.toDataURL("image/png");

    // แบ่งหน้าอัตโนมัติถ้าเนื้อหายาว
    const pageContentHeight = pageHeight - margin * 2;
    let yRemaining = imgHeight;
    let sourceY = 0;

    while (yRemaining > 0) {
      const sliceH = Math.min(yRemaining, pageContentHeight);
      const sliceCanvas = document.createElement("canvas");
      sliceCanvas.width = canvas.width;
      sliceCanvas.height = (sliceH / imgWidth) * canvas.width;
      const ctx = sliceCanvas.getContext("2d");
      ctx.drawImage(
        canvas,
        0,
        sourceY * (canvas.height / imgHeight),
        canvas.width,
        sliceCanvas.height,
        0,
        0,
        sliceCanvas.width,
        sliceCanvas.height,
      );
      pdf.addImage(
        sliceCanvas.toDataURL("image/png"),
        "PNG",
        margin,
        margin,
        imgWidth,
        sliceH,
      );
      yRemaining -= pageContentHeight;
      sourceY += pageContentHeight;
      if (yRemaining > 0) pdf.addPage();
    }

    pdf.save(`ClassMood_Report_${labId}_${Date.now()}.pdf`);
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

    const set = (id, text) => {
      const el = document.getElementById(id);
      if (el) el.textContent = text;
    };

    set("reportRecords", `บันทึก: ${s.total_records ?? 0} รายการ`);
    set("reportAvgPeople", `นักเรียนเฉลี่ย: ${s.avg_people ?? 0} คน`);
    set(
      "reportAvgAttention",
      `ความตั้งใจเฉลี่ย: ${s.avg_attention_rate ?? 0}%`,
    );
    set("reportMaxPeople", `นักเรียนสูงสุด: ${s.max_people ?? 0} คน`);
    set("reportAttentive", `${latest.attentive ?? 0} คน`);
    set("reportSleeping", `${latest.sleeping ?? 0} คน`);
    set("reportLookingDown", `${latest.looking_down ?? 0} คน`);
    set("reportHandRaised", `${latest.hand_raised ?? 0} คน`);
    set("reportStanding", `${latest.standing ?? 0} คน`);
    set("reportUnknown", `${latest.unknown ?? 0} คน`);
    set("reportLatestAttention", `${s.latest_attention_rate ?? 0}%`);
  } catch (e) {
    console.error("Error fetching export data:", e);
    latestExportData = null;
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
        summary.attentive || 0,
        summary.sleeping || 0,
        summary.looking_down || 0,
        summary.hand_raised || 0,
        summary.standing || 0,
        summary.unknown || 0,
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
      setSourceStatusText(`● Error: ${data.error}`, "text-xs font-medium text-red-600");
      stopSourceStatusPolling();
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
      const srcLabel =
        displayLabel || (typeof source === "number" ? `Webcam ${source}` : source);
      setConnectionStatus("เชื่อมต่อแล้ว", "text-green-600");
      showToast(`เชื่อมต่อสำเร็จ: ${srcLabel}`, "success");
      _updateSourceStatus(labId, camId, srcLabel);
      startSourceStatusPolling();
    } else {
      currentSourceType = null;
      stopSourceStatusPolling();
      setConnectionStatus("เชื่อมต่อไม่สำเร็จ", "text-red-600");
      showToast(`เชื่อมต่อไม่สำเร็จ: ${data.error || ""}`, "alert");
    }
  } catch (e) {
    currentSourceType = null;
    stopSourceStatusPolling();
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
