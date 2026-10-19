const analysisJobs = new Map();
let analysisJobsEpoch = 0;
let analysisJobsReady = false;
let analysisJobsUnavailable = false;
let analysisJobsTimer = null;
let analysisJobsRequest = null;
let sourceOperation = null;
let analysisStopRequest = null;
let analysisViewVersion = 0;

function analysisJobBlocksCreation() {
  return !analysisJobsReady || analysisJobsUnavailable || Boolean(sourceOperation)
    || [...analysisJobs.values()].some(job => job.status === "running" || job.stopping);
}

function analysisSelection(sessionId = currentLab, camId = currentCamera) {
  return { sessionId, camId, name: currentSessionName || sessionId, roomName: currentRoomName,
    courseName: currentCourseName, recordingStart: currentRecordingStart, interval: currentAnalysisInterval };
}

function beginSourceOperation(kind, selection) {
  if (!appReady || analysisJobBlocksCreation()) throw new Error("มีงานกำลังทำอยู่ หรือยังตรวจสถานะงานไม่สำเร็จ");
  const operation = { ...selection, kind, epoch: analysisJobsEpoch };
  sourceOperation = operation;
  renderAnalysisJobs();
  return operation;
}

function sourceOperationIsCurrent(operation) {
  return appReady && operation === sourceOperation && operation.epoch === analysisJobsEpoch;
}

function endSourceOperation(operation) {
  if (operation === sourceOperation) { sourceOperation = null; renderAnalysisJobs(); }
}

function registerAnalysisJob(selection, state) {
  const key = _srcKey(selection.sessionId, selection.camId);
  const existing = analysisJobs.get(key);
  const job = existing || { key, state, status: "running", notified: false };
  Object.assign(job, selection, { sourceType: state.source_type });
  analysisJobs.set(key, job);
  if (job.status === "running") activeSources.add(key);
  renderAnalysisJobs();
  return job;
}

function analysisJobStatusText(job) {
  if (analysisJobsUnavailable) return "ตรวจสถานะไม่ได้ กำลังลองเชื่อมต่ออีกครั้ง";
  if (job.stopping) return "กำลังหยุดและบันทึก...";
  if (job.status === "completed") return "วิเคราะห์เสร็จแล้ว";
  if (job.status === "stopped") return "หยุดก่อนจบคลิป เก็บผลเท่าที่ตรวจได้";
  if (job.status === "interrupted") return "ไม่พบงานที่กำลังทำบนเซิร์ฟเวอร์ ดูผลที่บันทึกไว้ได้";
  if (job.status === "error") return "การวิเคราะห์มีปัญหา ดูผลที่บันทึกไว้ได้";
  const progress = job.state.progress_percent;
  return Number.isFinite(progress) ? `กำลังวิเคราะห์ ${formatDecimal(progress)}%`
    : job.sourceType === "webcam" ? "เว็บแคมกำลังเปิดอยู่" : "กำลังวิเคราะห์วิดีโอ";
}

function jobActionReference(button) {
  for (const name of ["resumeJob", "stopJob", "reportJob"]) if (button?.dataset?.[name]) return { name, key: button.dataset[name] };
  return null;
}

function findJobAction(reference) {
  if (!reference) return null;
  return [...document.querySelectorAll("#analysisJobsList button")].find(button => button.dataset[reference.name] === reference.key);
}

function analysisSourceName(job) {
  if (job.sourceType === "webcam") {
    const index = job.state?.source;
    return index == null ? job.sourceLabel || "เว็บแคม" : `Webcam ${index}`;
  }
  const source = job.sourceLabel || job.state?.source;
  return typeof source === "string" ? source.split(/[\\/]/).pop() : "";
}

function renderCurrentSourceControls() {
  const job = analysisJobs.get(_srcKey(currentLab, currentCamera));
  const pending = sourceOperation?.sessionId === currentLab && sourceOperation.camId === currentCamera;
  const locked = Boolean(job || pending);
  for (const id of ["recordingStartInput", "videoFileInput", "uploadVideoBtn", "webcamSelect", "startWebcamBtn"]) {
    const element = document.getElementById(id);
    if (element) element.disabled = locked;
  }
  const boundVideo = job?.sourceType === "video";
  document.getElementById("videoSourceSettings")?.classList.toggle("hidden", boundVideo);
  document.getElementById("activeVideoDetails")?.classList.toggle("hidden", !boundVideo);
  setTextIfPresent("activeVideoName", boundVideo ? analysisSourceName(job) || "ไม่ระบุชื่อคลิป" : "");
  const start = boundVideo ? recordingStartLocalValue(job.recordingStart) : "";
  if (boundVideo) {
    const input = document.getElementById("recordingStartInput");
    if (input) input.value = start;
  }
  const startLabel = start
    ? new Date(job.recordingStart).toLocaleString("th-TH", { dateStyle: "medium", timeStyle: "short" }) : "ไม่ระบุ";
  setTextIfPresent("activeVideoRecordingStart", boundVideo ? startLabel : "");
  if (job?.sourceType === "webcam" && job.state?.source != null) {
    const input = document.getElementById("webcamSelect");
    if (input) input.value = String(job.state.source);
  }
}

function renderAnalysisJobs() {
  const section = document.getElementById("analysisJobsBanner");
  const list = document.getElementById("analysisJobsList");
  if (!section || !list) return;
  const visibleJobs = [...analysisJobs.values()].filter(job => job.status === "running" || job.stopping || !job.reportViewed);
  section.classList.toggle("hidden", !appReady || appView !== "history"
    || (!visibleJobs.length && !sourceOperation && !analysisJobsUnavailable));
  let html = visibleJobs.map(job => `
    <div class="analysis-job-row">
      <div class="min-w-0"><p class="font-semibold break-words">${escapeHtml(job.name)}</p>
        <p class="text-sm text-gray-600" role="status">${escapeHtml(analysisJobStatusText(job))}</p></div>
      <div class="analysis-job-actions">${job.status === "running"
        ? `<button type="button" data-resume-job="${escapeHtml(job.key)}" class="job-primary">กลับไปหน้าวิเคราะห์</button>
           <button type="button" data-stop-job="${escapeHtml(job.key)}" class="job-stop" ${job.stopping ? "disabled" : ""}>หยุด${job.sourceType === "webcam" ? "และบันทึก" : "วิเคราะห์"}</button>`
        : `<button type="button" data-report-job="${escapeHtml(job.key)}" class="job-primary">ดูรายงาน</button>`}</div>
    </div>`).join("");
  if (sourceOperation) html += `<div class="analysis-job-row"><div class="min-w-0"><p class="font-semibold break-words">${escapeHtml(sourceOperation.name)}</p><p class="text-sm text-gray-600">${sourceOperation.kind === "upload" ? "กำลังอัปโหลดคลิป..." : "กำลังเริ่มแหล่งภาพ..."}</p></div></div>`;
  if (analysisJobsUnavailable && !visibleJobs.length) html = '<p class="text-sm text-red-700">ตรวจสถานะงานไม่ได้ กำลังลองเชื่อมต่ออีกครั้ง</p>';
  if (list.innerHTML !== html) {
    const focus = jobActionReference(document.activeElement);
    list.innerHTML = html;
    findJobAction(focus)?.focus();
  }
  const create = document.getElementById("showNewSessionBtn");
  if (create) create.disabled = analysisJobBlocksCreation();
  const stopVideo = document.getElementById("stopVideoBtn");
  const current = analysisJobs.get(_srcKey(currentLab, currentCamera));
  if (stopVideo) stopVideo.classList.toggle("hidden", current?.sourceType !== "video" || current.status !== "running");
  if (current?.sourceType === "webcam") document.getElementById("stopWebcamBtn")?.classList.toggle("hidden", current.status !== "running");
  renderCurrentSourceControls();
}

function acknowledgeAnalysisReport(sessionId, reportStatus) {
  if (!["completed", "cancelled"].includes(reportStatus)) return;
  for (const job of analysisJobs.values()) {
    if (job.sessionId === sessionId && job.status !== "running" && !job.stopping) job.reportViewed = true;
  }
  renderAnalysisJobs();
}

function suspendAnalysisView() {
  analysisViewVersion += 1;
  if (liveFeedInterval) { clearInterval(liveFeedInterval); liveFeedInterval = null; }
  stopChartUpdates();
  stopAlertPolling();
  showFeedPlaceholder();
}

function activateAnalysisView() {
  if (!appReady || appView !== "analysis" || !currentLab) return;
  const job = analysisJobs.get(_srcKey(currentLab, currentCamera));
  if (!job || job.status !== "running") return;
  updateCameraFeed();
  startLiveFeed();
  startChartUpdates();
  startAlertPolling();
}

function analysisViewIsCurrent(sessionId, version) {
  return appReady && appView === "analysis" && currentLab === sessionId && version === analysisViewVersion;
}

async function resumeAnalysisJob(key) {
  const job = analysisJobs.get(key);
  if (!job || job.status !== "running") return;
  const current = analysisJobs.get(_srcKey(currentLab, currentCamera));
  if (current?.key !== key && current?.sourceType === "webcam" && current.status === "running"
    && !await requestAnalysisStop(current)) return;
  if (!appReady || !analysisJobs.has(key) || job.status !== "running") return;
  suspendAnalysisView();
  currentLab = job.sessionId;
  currentCamera = job.camId;
  currentSessionName = job.name;
  currentRoomName = job.roomName || "ไม่ระบุ";
  currentCourseName = job.courseName || "ไม่ระบุ";
  currentAnalysisInterval = job.interval || 30;
  currentRecordingStart = job.recordingStart || "";
  resetDashboardState();
  for (const running of analysisJobs.values()) if (running.status === "running") activeSources.add(running.key);
  currentSourceType = job.sourceType;
  renderSourceMode(job.sourceType);
  document.getElementById("stopWebcamBtn")?.classList.toggle("hidden", job.sourceType !== "webcam");
  document.getElementById("startWebcamBtn")?.classList.toggle("hidden", job.sourceType === "webcam");
  setTextIfPresent("currentLabName", job.name);
  setTextIfPresent("currentSessionMeta", `${currentCourseName} | ${currentRoomName}`);
  updateAnalysisCadence(job.state);
  setConnectionStatus(analysisJobStatusText(job), "text-blue-600");
  setSourceStatusText(analysisJobStatusText(job), "text-xs font-medium text-blue-600");
  initCharts();
  renderAnalysisJobs();
  await navigateApp("#analysis");
}

async function refreshAnalysisJobs() {
  if (!appReady) return;
  if (analysisJobsRequest) return analysisJobsRequest;
  const epoch = analysisJobsEpoch;
  const knownKeys = new Set(analysisJobs.keys());
  const request = (async () => {
    try {
      const response = await apiFetch("/api/sources");
      if (!response.ok) throw new Error("Unable to read running sources");
      const sources = await response.json();
      if (!appReady || epoch !== analysisJobsEpoch) return;
      analysisJobsReady = true;
      analysisJobsUnavailable = false;
      let discovered = false;
      for (const [key, state] of Object.entries(sources)) {
        const match = /^(.*)\/(\d+)$/.exec(key);
        if (!match || !state.active || analysisJobs.has(key)) continue;
        const metadata = sessionHistoryState.sessions.find(item => item.id === match[1]);
        registerAnalysisJob({ sessionId: match[1], camId: Number(match[2]), name: metadata?.name || match[1],
          roomName: metadata?.room_name, courseName: metadata?.course_name,
          interval: metadata?.analysis_interval_seconds, recordingStart: metadata?.recording_started_at,
          sourceLabel: metadata?.source_label }, state);
        discovered = true;
      }
      if (discovered) {
        await loadSessionHistory();
        if (!appReady || epoch !== analysisJobsEpoch) return;
      }
      for (const job of analysisJobs.values()) {
        const metadata = sessionHistoryState.sessions.find(item => item.id === job.sessionId);
        if (metadata) Object.assign(job, { name: metadata.name || job.name, roomName: metadata.room_name,
          courseName: metadata.course_name, interval: metadata.analysis_interval_seconds,
          recordingStart: metadata.recording_started_at || job.recordingStart,
          sourceLabel: metadata.source_label || job.sourceLabel });
        if (job.status !== "running" || job.stopping) continue;
        const state = sources[job.key];
        if (!state) {
          if (knownKeys.has(job.key)) { job.status = "interrupted"; activeSources.delete(job.key); }
          continue;
        }
        job.state = state;
        if (state.error) { job.status = "error"; activeSources.delete(job.key); }
        else if (state.ended) {
          job.status = "completed";
          activeSources.delete(job.key);
          if (analysisStopRequest?.key === job.key && !analysisStopRequest.busy) document.getElementById("analysisStopDialog")?.close("finished");
          if (!job.notified) {
            job.notified = true;
            if (currentLab === job.sessionId && currentCamera === job.camId) sessionCompleted = true;
            if (appView === "analysis" && currentLab === job.sessionId && currentCamera === job.camId) {
              suspendAnalysisView();
              await exportReport(job.sessionId, job.name);
              if (epoch !== analysisJobsEpoch) return;
            } else showToast(`วิเคราะห์ ${job.name} เสร็จแล้ว`, "success");
            loadSessionHistory();
          }
        }
      }
      const current = analysisJobs.get(_srcKey(currentLab, currentCamera));
      if (appView === "analysis" && current) {
        if (current.status !== "running") suspendAnalysisView();
        setConnectionStatus(analysisJobStatusText(current), current.status === "error" ? "text-red-600" : "text-blue-600");
        setSourceStatusText(analysisJobStatusText(current), "text-xs font-medium text-blue-600");
      }
      renderAnalysisJobs();
    } catch (_) {
      if (appReady && epoch === analysisJobsEpoch) { analysisJobsUnavailable = true; renderAnalysisJobs(); }
    }
  })();
  analysisJobsRequest = request;
  try { await request; } finally { if (analysisJobsRequest === request) analysisJobsRequest = null; }
}

function startAnalysisJobPolling() {
  if (!analysisJobsTimer) analysisJobsTimer = setInterval(refreshAnalysisJobs, 1000);
}

function clearAnalysisJobs() {
  analysisJobsEpoch += 1;
  if (analysisJobsTimer) clearInterval(analysisJobsTimer);
  analysisJobsTimer = null;
  analysisJobsRequest = null;
  analysisJobs.clear();
  sourceOperation = null;
  analysisJobsReady = false;
  analysisJobsUnavailable = false;
  suspendAnalysisView();
  activeSources.clear();
  currentLab = "";
  currentSessionName = "";
  currentRoomName = "";
  currentCourseName = "";
  currentRecordingStart = "";
  currentSourceType = null;
  lastAlertId = 0;
  resetDashboardState();
  setTextIfPresent("currentLabName", "");
  setTextIfPresent("currentSessionMeta", "");
  document.getElementById("toastContainer")?.replaceChildren();
  const upload = document.getElementById("uploadVideoBtn");
  if (upload) { upload.disabled = false; upload.textContent = "อัปโหลดคลิป"; upload.classList.remove("opacity-60", "cursor-not-allowed"); }
  if (attentionChart) { attentionChart.destroy(); attentionChart = null; }
  if (behaviorPieChart) { behaviorPieChart.destroy(); behaviorPieChart = null; }
  document.getElementById("analysisStopDialog")?.close();
  renderAnalysisJobs();
}

async function stopAnalysisJob(job) {
  const epoch = analysisJobsEpoch;
  job.stopping = true;
  renderAnalysisJobs();
  try {
    const response = await apiFetch(`/api/sources/${encodeURIComponent(job.sessionId)}/${job.camId}`, { method: "DELETE" });
    if (!response.ok) throw new Error("หยุดและบันทึกรอบวิเคราะห์ไม่สำเร็จ");
    if (!appReady || epoch !== analysisJobsEpoch) return false;
    const savedResponse = await apiFetch("/api/sessions");
    if (!savedResponse.ok) throw new Error("หยุดแหล่งภาพแล้ว แต่ยังยืนยันการบันทึกไม่ได้ กรุณาลองอีกครั้ง");
    const saved = (await savedResponse.json()).sessions?.find(item => item.id === job.sessionId);
    if (!saved || !["completed", "cancelled"].includes(saved.status)) throw new Error("ยังยืนยันการบันทึกรอบไม่ได้ กรุณาลองอีกครั้ง");
    if (!appReady || epoch !== analysisJobsEpoch) return false;
    job.status = saved.status === "completed" ? "completed" : "stopped";
    activeSources.delete(job.key);
    if (currentLab === job.sessionId && currentCamera === job.camId) {
      sessionCompleted = true;
      suspendAnalysisView();
    }
    loadSessionHistory();
    return true;
  } finally { if (epoch === analysisJobsEpoch) { job.stopping = false; renderAnalysisJobs(); } }
}

function requestAnalysisStop(job) {
  if (analysisStopRequest) return analysisStopRequest.key === job.key ? analysisStopRequest.promise : Promise.resolve(false);
  const dialog = document.getElementById("analysisStopDialog");
  const opener = document.activeElement;
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  analysisStopRequest = { key: job.key, job, promise, resolve, opener, openerAction: jobActionReference(opener), epoch: analysisJobsEpoch, busy: false };
  setTextIfPresent("analysisStopTitle", job.sourceType === "webcam" ? "หยุดเว็บแคมก่อนออกหรือไม่" : "หยุดวิเคราะห์ก่อนจบคลิปหรือไม่");
  setTextIfPresent("analysisStopDescription", job.sourceType === "webcam"
    ? "หยุดกล้องและบันทึกผลรอบนี้ก่อนออกจากหน้าวิเคราะห์"
    : "ระบบจะเก็บผลเท่าที่ตรวจได้ และระบุว่ารอบนี้หยุดก่อนวิเคราะห์ครบคลิป");
  setTextIfPresent("analysisStopError", "");
  dialog.returnValue = "";
  document.getElementById("analysisStopConfirm").disabled = false;
  document.getElementById("analysisStopStay").disabled = false;
  dialog.showModal();
  document.getElementById("analysisStopStay").focus();
  return promise;
}

async function confirmAnalysisNavigation(hash) {
  if (appView !== "analysis" || hash === "#analysis") return true;
  if (sourceOperation?.sourceType === "webcam") { showToast("กำลังเริ่มเว็บแคม กรุณารอสักครู่", "warning"); return false; }
  const webcam = analysisJobs.get(_srcKey(currentLab, currentCamera));
  return webcam?.sourceType === "webcam" && webcam.status === "running" ? requestAnalysisStop(webcam) : true;
}

async function stopCurrentAnalysis() {
  const job = analysisJobs.get(_srcKey(currentLab, currentCamera));
  if (job?.status !== "running") return;
  if (await requestAnalysisStop(job) && appReady && appView === "analysis" && currentLab === job.sessionId) await exportReport(job.sessionId, job.name);
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("analysisJobsList")?.addEventListener("click", event => {
    const button = event.target.closest("button");
    if (!button) return;
    if (button.dataset.resumeJob) resumeAnalysisJob(button.dataset.resumeJob);
    if (button.dataset.reportJob) { const job = analysisJobs.get(button.dataset.reportJob); if (job) exportReport(job.sessionId, job.name); }
    if (button.dataset.stopJob) { const job = analysisJobs.get(button.dataset.stopJob); if (job) requestAnalysisStop(job); }
  });
  const dialog = document.getElementById("analysisStopDialog");
  dialog?.addEventListener("cancel", event => { if (analysisStopRequest?.busy) event.preventDefault(); });
  dialog?.addEventListener("close", () => {
    const request = analysisStopRequest;
    analysisStopRequest = null;
    request?.resolve(dialog.returnValue === "stopped" && request.epoch === analysisJobsEpoch);
    if (appReady) {
      const opener = request?.opener?.isConnected ? request.opener : findJobAction(request?.openerAction);
      opener?.focus();
    }
  });
  document.getElementById("analysisStopStay")?.addEventListener("click", () => dialog.close("stay"));
  document.getElementById("analysisStopConfirm")?.addEventListener("click", async () => {
    const request = analysisStopRequest;
    if (!request || request.busy) return;
    request.busy = true;
    document.getElementById("analysisStopConfirm").disabled = true;
    document.getElementById("analysisStopStay").disabled = true;
    try {
      if (await stopAnalysisJob(request.job)) dialog.close("stopped");
    } catch (error) {
      if (analysisStopRequest === request) setTextIfPresent("analysisStopError", error.message);
    } finally {
      if (analysisStopRequest === request) {
        request.busy = false;
        document.getElementById("analysisStopConfirm").disabled = false;
        document.getElementById("analysisStopStay").disabled = false;
      }
    }
  });
});

window.addEventListener("beforeunload", event => {
  if (sourceOperation) { event.preventDefault(); event.returnValue = ""; }
});
