const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

function fixture() {
  const elements = new Map();
  const callbacks = [];
  const calls = [];
  const intervals = new Map();
  const documentEvents = new Map();
  let nextTimer = 0;
  const document = { activeElement: null, querySelectorAll: () => [], createElement: () => element("created"),
    addEventListener() {}, getElementById: id => element(id) };
  function element(id) {
    if (elements.has(id)) return elements.get(id);
    const handlers = {};
    const classes = new Set();
    const item = { id, value: "", innerHTML: "", textContent: "", style: {}, dataset: {}, disabled: false,
      isConnected: true, open: false, returnValue: "", setAttribute() {}, removeAttribute() {},
      replaceChildren() { this.innerHTML = ""; },
      classList: { add: (...names) => names.forEach(name => classes.add(name)), remove: (...names) => names.forEach(name => classes.delete(name)),
        toggle(name, value) { if (value) classes.add(name); else classes.delete(name); }, contains: name => classes.has(name) },
      addEventListener(type, callback) { (handlers[type] ||= []).push(callback); },
      emit(type, event = {}) { return Promise.all((handlers[type] || []).map(callback => callback(event))); },
      focus() { document.activeElement = item; }, showModal() { this.open = true; },
      close(value) { if (!this.open) return; this.open = false; if (value !== undefined) this.returnValue = value; this.emit("close"); },
    };
    elements.set(id, item);
    return item;
  }
  const location = { protocol: "http:", origin: "http://localhost", hash: "#analysis" };
  const context = vm.createContext({ console, document, window: { location, scrollTo() {}, addEventListener() {},
    history: { pushState(a, b, hash) { location.hash = hash; }, replaceState(a, b, hash) { location.hash = hash; } } },
    setInterval(callback, delay) { const id = ++nextTimer; intervals.set(id, { callback, delay }); return id; },
    clearInterval(id) { intervals.delete(id); }, FormData: class { append() {} } });
  for (const filename of ["shared.js", "analysis-jobs.js", "video-evidence.js", "session-history.js"]) {
    document.addEventListener = (type, callback) => {
      if (filename === "analysis-jobs.js" && type === "DOMContentLoaded") callbacks.push(callback);
      if (type.startsWith("classmood:")) {
        if (!documentEvents.has(type)) documentEvents.set(type, []);
        documentEvents.get(type).push(callback);
      }
    };
    vm.runInContext(fs.readFileSync(path.join(__dirname, "..", "dashboard", filename), "utf8"), context);
  }
  for (const callback of callbacks) callback();
  const reportLoader = vm.runInContext("exportReport", context);
  context.testCalls = calls;
  vm.runInContext(`appReady=true;analysisJobsReady=true;appView='analysis';currentLab='round';currentSessionName='Round';
    currentRoomName='Lab';currentCourseName='AI';currentRecordingStart='2026-10-19T09:00:00+07:00';
    showToast=(message,type,sessionId)=>testCalls.push({toast:message,type,sessionId});loadSessionHistory=async()=>{};
    exportReport=async(id,name)=>testCalls.push({report:id,name});initCharts=()=>{};updateCameraFeed=()=>{};
    startLiveFeed=()=>{};startChartUpdates=()=>{};startAlertPolling=()=>{};`, context);
  context.apiFetch = async (url, options = {}) => {
    calls.push({ url, ...options });
    return { ok: true, json: async () => url === "/api/sources" ? context.sources || {} : { sessions: context.sessions || [] } };
  };
  const run = code => vm.runInContext(code, context);
  const job = (type = "video") => run(`registerAnalysisJob(analysisSelection(), {source_type:'${type}',active:true})`);
  const emitDocument = type => Promise.all((documentEvents.get(type) || []).map(callback => callback()));
  return { context, element, calls, run, job, location, intervals, reportLoader, emitDocument };
}

test("starting a round keeps every unread terminal notice and only prunes acknowledged jobs", () => {
  const f = fixture();
  for (const status of ["completed", "stopped", "interrupted", "failed"]) {
    f.run(`registerAnalysisJob({sessionId:'${status}',camId:1,name:'${status}'},{source_type:'video'}).status='${status}'`);
  }
  f.run("registerAnalysisJob({sessionId:'read',camId:1,name:'Read'},{source_type:'video'}).status='completed';acknowledgeAnalysisReport('read','completed')");
  f.element("sessionNameInput").value = "Next round";
  f.element("analysisIntervalInput").value = "30";
  f.run("makeSessionId=()=> 'new-round';openAnalysisSession=(id)=>{currentLab=id;showAppView('analysis')};startSession();showAppView('history')");
  assert.equal(f.run("currentLab"), "new-round");
  assert.equal(f.run("analysisJobs.has('read/1')"), false);
  for (const status of ["completed", "stopped", "interrupted", "failed"]) {
    assert.equal(f.run(`analysisJobs.has('${status}/1')`), true);
    assert.match(f.element("analysisJobsList").innerHTML, new RegExp(`data-report-job="${status}/1"`));
  }
});

test("same-account ready events refresh data without closing a draft or reloading a report", async () => {
  const f = fixture();
  f.context.routeCalls = 0;
  f.context.historyCalls = 0;
  f.run("appReady=false;appView='history';window.location.hash='#history';const originalRoute=applyAppRoute;applyAppRoute=()=>{routeCalls++;return originalRoute()};loadSessionHistory=async()=>{historyCalls++}");
  await f.emitDocument("classmood:ready");
  assert.equal(f.context.routeCalls, 1);
  const initialHistoryCalls = f.context.historyCalls;
  await f.run("showNewSessionForm()");
  f.element("sessionNameInput").value = "Unfinished lesson";
  f.element("courseNameInput").value = "AI";
  const opener = f.context.document.activeElement;
  await f.emitDocument("classmood:ready");
  assert.equal(f.element("newSessionDialog").open, true);
  assert.equal(f.element("sessionNameInput").value, "Unfinished lesson");
  assert.equal(f.element("courseNameInput").value, "AI");
  assert.equal(f.context.document.activeElement, opener);
  f.run("appView='report';window.location.hash='#report/round';latestExportData={lab_id:'round'}");
  await f.emitDocument("classmood:ready");
  assert.equal(f.run("latestExportData.lab_id"), "round");
  assert.equal(f.context.routeCalls, 1);
  assert.equal(f.context.historyCalls, initialHistoryCalls + 2);
  await f.emitDocument("classmood:locked");
  await f.emitDocument("classmood:ready");
  assert.equal(f.context.routeCalls, 2);
});

test("an old initial ready event cannot apply its route after an account lock", async () => {
  const f = fixture();
  let finish;
  f.context.routeCalls = 0;
  f.context.loadSessionHistory = () => new Promise(resolve => { finish = resolve; });
  f.run("appReady=false;applyAppRoute=()=>{routeCalls++}");
  const oldReady = f.emitDocument("classmood:ready");
  await f.emitDocument("classmood:locked");
  f.context.loadSessionHistory = async () => {};
  await f.emitDocument("classmood:ready");
  finish(); await oldReady;
  assert.equal(f.context.routeCalls, 1);
});

test("errored workers keep explicit cleanup in history and analysis and block new sources", async () => {
  for (const type of ["video", "webcam"]) {
    const f = fixture(); const job = f.job(type);
    f.context.sources = {"round/1": {active:false,ended:false,error:"Decode failed",source_type:type}};
    await f.run("refreshAnalysisJobs()");
    f.run("showAppView('history');acknowledgeAnalysisReport('round','completed')");
    assert.equal(job.status, "error");
    assert.equal(f.run("analysisJobBlocksCreation()"), true);
    assert.equal(f.run("activeSources.has('round/1')"), true);
    assert.notEqual(job.reportViewed, true);
    assert.match(f.element("analysisJobsList").innerHTML, /data-stop-job="round\/1"/);
    assert.doesNotMatch(f.element("analysisJobsList").innerHTML, /data-report-job="round\/1"/);
    assert.equal(f.element(type === "video" ? "stopVideoBtn" : "stopWebcamBtn").classList.contains("hidden"), false);
    await f.run("setVideoSource('fresh',1,'clip.mp4')");
    assert.ok(!f.calls.some(call => call.method === "POST"));
  }
});

test("reconnecting discovers inactive errored sources that still need DELETE", async () => {
  const f = fixture();
  f.context.sources = {"broken/1": {active:false,ended:false,error:"Cannot open",source_type:"video"}};
  f.run("appView='history'");
  await f.run("refreshAnalysisJobs()");
  assert.equal(f.run("analysisJobs.get('broken/1').status"), "error");
  assert.equal(f.run("analysisJobBlocksCreation()"), true);
  assert.match(f.element("analysisJobsList").innerHTML, /data-stop-job="broken\/1"/);
});

test("foreground error cleanup saves once before opening its final report", async () => {
  const f = fixture(); const job = f.job(); job.status = "error";
  f.context.sessions = [{id:"round",status:"cancelled"}];
  const stopping = f.run("stopCurrentAnalysis()");
  assert.equal(f.element("analysisStopDialog").open, true);
  await Promise.all([f.element("analysisStopConfirm").emit("click"), f.element("analysisStopConfirm").emit("click")]);
  await stopping;
  assert.equal(f.calls.filter(call => call.method === "DELETE").length, 1);
  assert.equal(job.status, "stopped");
  assert.equal(f.run("analysisJobBlocksCreation()"), false);
  assert.equal(f.run("activeSources.has('round/1')"), false);
  assert.equal(f.calls.filter(call => call.report === "round").length, 1);
});

test("failed error cleanup stays actionable until saving is verified, even after the source disappears", async () => {
  const f = fixture(); const job = f.job(); job.status = "error";
  f.context.sessions = [{id:"round",status:"active"}];
  let deleteOk = false;
  f.context.apiFetch = async (url, options = {}) => {
    f.calls.push({url,...options});
    return {ok:options.method !== "DELETE" || deleteOk,json:async()=>url === "/api/sources" ? {} : {sessions:f.context.sessions}};
  };
  const stopping = f.run("stopCurrentAnalysis()");
  await f.element("analysisStopConfirm").emit("click");
  assert.match(f.element("analysisStopError").textContent, /ไม่สำเร็จ/);
  deleteOk = true;
  await f.element("analysisStopConfirm").emit("click");
  assert.match(f.element("analysisStopError").textContent, /ยืนยันการบันทึก/);
  await f.run("refreshAnalysisJobs()");
  assert.equal(job.status, "error");
  assert.equal(f.run("analysisJobBlocksCreation()"), true);
  assert.equal(f.element("analysisStopDialog").open, true);
  f.context.sessions = [{id:"round",status:"cancelled"}];
  await f.element("analysisStopConfirm").emit("click");
  await stopping;
  assert.equal(job.status, "stopped");
  assert.equal(f.run("analysisJobBlocksCreation()"), false);
});

test("leaving an errored webcam still supports Stay without stopping the source", async () => {
  const f = fixture(); const job = f.job("webcam"); job.status = "error";
  const opener = f.element("back"); opener.focus();
  const navigating = f.run("backToMenu()");
  assert.equal(f.element("analysisStopDialog").open, true);
  f.element("analysisStopDialog").close("stay");
  await navigating;
  assert.equal(f.location.hash, "#analysis");
  assert.equal(f.context.document.activeElement, opener);
  assert.ok(!f.calls.some(call => call.method === "DELETE"));
});

test("video navigation leaves capture running and preserves the round", async () => {
  const f = fixture();
  f.job();
  await f.run("backToMenu()");
  assert.equal(f.location.hash, "#history");
  assert.equal(f.run("currentLab"), "round");
  assert.equal(f.run("analysisJobs.get('round/1').status"), "running");
  assert.ok(!f.calls.some(call => call.method === "DELETE"));
});

test("restore discovers real sources, supports multiple jobs and resumes without POST", async () => {
  const f = fixture();
  f.context.sources = { "one/1": { active: true, source_type: "video" }, "two/2": { active: true, source_type: "video" } };
  f.run("sessionHistoryState.sessions=[{id:'one',name:'One'},{id:'two',name:'Two',course_name:'Game',analysis_interval_seconds:60}]");
  await f.run("refreshAnalysisJobs()");
  assert.equal(f.run("analysisJobs.size"), 2);
  await f.run("resumeAnalysisJob('two/2')");
  assert.equal(f.run("currentLab"), "two");
  assert.equal(f.run("currentCamera"), 2);
  assert.equal(f.run("currentAnalysisInterval"), 60);
  assert.equal(f.run("currentSessionName"), "Two");
  assert.ok(!f.calls.some(call => call.method));
});

test("database active rows alone do not restore or restart an interrupted worker", async () => {
  const f = fixture();
  f.run("sessionHistoryState.sessions=[{id:'old',status:'active'}]");
  await f.run("refreshAnalysisJobs()");
  assert.equal(f.run("analysisJobs.size"), 0);
  f.job();
  await f.run("refreshAnalysisJobs()");
  assert.equal(f.run("analysisJobs.get('round/1').status"), "interrupted");
  assert.equal(f.run("analysisJobBlocksCreation()"), false);
  assert.ok(!f.calls.some(call => call.report));
});

test("network failures do not cancel jobs or permit a new round", async () => {
  const f = fixture();
  f.job();
  f.context.apiFetch = async () => { throw Error("offline"); };
  await f.run("refreshAnalysisJobs()");
  assert.equal(f.run("analysisJobs.get('round/1').status"), "running");
  assert.equal(f.run("analysisJobBlocksCreation()"), true);
  assert.match(f.run("analysisJobStatusText(analysisJobs.get('round/1'))"), /ตรวจสถานะไม่ได้/);
});

test("completion only opens a report for its own foreground analysis", async () => {
  for (const view of ["analysis", "history", "report"]) {
    const f = fixture();
    f.job();
    f.context.sources = { "round/1": { active: false, ended: true, source_type: "video" } };
    f.run(`appView='${view}';latestExportData={report:'other'};`);
    await f.run("refreshAnalysisJobs()");
    await f.run("refreshAnalysisJobs()");
    assert.equal(f.calls.filter(call => call.report).length, view === "analysis" ? 1 : 0);
    assert.equal(f.run("latestExportData.report"), "other");
    assert.equal(f.run("analysisJobs.get('round/1').status"), "completed");
  }
});

test("webcam Back asks before DELETE and Escape stays on analysis", async () => {
  const f = fixture();
  f.job("webcam");
  const opener = f.element("back"); opener.focus();
  const navigation = f.run("backToMenu()");
  assert.equal(f.element("analysisStopDialog").open, true);
  f.element("analysisStopDialog").close();
  await navigation;
  assert.equal(f.location.hash, "#analysis");
  assert.equal(f.context.document.activeElement, opener);
  assert.ok(!f.calls.some(call => call.method === "DELETE"));
});

test("webcam confirmation stops once, verifies saving and follows requested navigation", async () => {
  const f = fixture();
  f.job("webcam");
  f.context.sessions = [{ id: "round", status: "completed" }];
  const navigation = f.run("navigateApp('#history')");
  const first = f.element("analysisStopConfirm").emit("click");
  const second = f.element("analysisStopConfirm").emit("click");
  await first; await second; await navigation;
  assert.equal(f.calls.filter(call => call.method === "DELETE").length, 1);
  assert.equal(f.location.hash, "#history");
  assert.equal(f.run("analysisJobs.get('round/1').status"), "completed");
  assert.ok(!f.calls.some(call => call.report));
});

test("stop failures leave the dialog and webcam view intact", async () => {
  const f = fixture();
  f.job("webcam");
  f.context.apiFetch = async () => ({ ok: false });
  const navigation = f.run("navigateApp('#history')");
  await f.element("analysisStopConfirm").emit("click");
  assert.equal(f.element("analysisStopDialog").open, true);
  assert.match(f.element("analysisStopError").textContent, /ไม่สำเร็จ/);
  assert.equal(f.location.hash, "#analysis");
  f.element("analysisStopDialog").close("stay");
  await navigation;
});

test("cancel on a reused dialog cannot reuse a previous stopped return value", async () => {
  const f = fixture(); f.job("webcam");
  f.element("analysisStopDialog").returnValue = "stopped";
  const pending = f.run("requestAnalysisStop(analysisJobs.get('round/1'))");
  f.element("analysisStopDialog").close();
  assert.equal(await pending, false);
});

test("upload completion uses its original round metadata after navigation", async () => {
  const f = fixture();
  let finishUpload;
  f.context.apiFetch = async (url, options = {}) => {
    f.calls.push({ url, ...options });
    if (url === "/api/videos") return new Promise(resolve => { finishUpload = resolve; });
    return { ok: true, headers: { get: () => "application/json" }, json: async () => url === "/api/sources" ? {} : { ok: true, source_type: "video" } };
  };
  const upload = f.run("uploadAndUseVideo({})");
  assert.equal(f.run("analysisJobBlocksCreation()"), true);
  f.run("appView='history';currentLab='different';currentCourseName='Changed';currentAnalysisInterval=60");
  finishUpload({ ok: true, headers: { get: () => "application/json" }, json: async () => ({ ok: true, source: "clip.mp4", filename: "clip.mp4" }) });
  await upload;
  const post = f.calls.find(call => call.url === "/api/sources/round/1");
  assert.equal(JSON.parse(post.body).course_name, "AI");
  assert.equal(JSON.parse(post.body).analysis_interval_seconds, 30);
  assert.equal(f.run("analysisJobs.has('round/1')"), true);
  assert.equal(f.run("currentLab"), "different");
});

test("late upload after account lock cannot start an old user's source", async () => {
  const f = fixture();
  let finishUpload;
  f.context.apiFetch = (url, options) => { f.calls.push({ url, ...options }); return new Promise(resolve => { finishUpload = resolve; }); };
  const upload = f.run("uploadAndUseVideo({})");
  f.run("appReady=false;clearAnalysisJobs();appReady=true;analysisJobsReady=true");
  finishUpload({ ok: true, headers: { get: () => "application/json" }, json: async () => ({ ok: true, source: "old.mp4" }) });
  await upload;
  assert.equal(f.calls.length, 1);
  assert.equal(f.run("analysisJobs.size"), 0);
  assert.equal(f.run("currentLab"), "");
});

test("poll responses predating a newly registered job cannot mark it interrupted", async () => {
  const f = fixture();
  let finish;
  f.context.apiFetch = () => new Promise(resolve => { finish = resolve; });
  const poll = f.run("refreshAnalysisJobs()");
  f.job();
  finish({ ok: true, json: async () => ({}) });
  await poll;
  assert.equal(f.run("analysisJobs.get('round/1').status"), "running");
});

test("late discovery after account lock cannot expose old job names", async () => {
  const f = fixture();
  let finish;
  f.context.apiFetch = () => new Promise(resolve => { finish = resolve; });
  const poll = f.run("refreshAnalysisJobs()");
  f.run("appReady=false;clearAnalysisJobs();appReady=true");
  finish({ ok: true, json: async () => ({ "private/1": { active: true, source_type: "video" } }) });
  await poll;
  assert.equal(f.run("analysisJobs.size"), 0);
  assert.equal(f.element("analysisJobsList").innerHTML, "");
});

test("late start acknowledgement cannot reopen a job already completed by polling", () => {
  const f = fixture();
  const job = f.job();
  job.status = "completed"; job.notified = true; job.stopping = true;
  f.run("activeSources.clear();registerAnalysisJob(analysisSelection(),{source_type:'video'})");
  assert.equal(f.run("analysisJobs.get('round/1').status"), "completed");
  assert.equal(f.run("analysisJobs.get('round/1').notified"), true);
  assert.equal(f.run("activeSources.size"), 0);
  assert.equal(f.run("analysisJobs.get('round/1')"), job);
  assert.equal(job.stopping, true);
});

test("stopping cannot navigate until terminal saved status is verified", async () => {
  const f = fixture(); f.job("webcam");
  f.context.sessions = [{id:"round",status:"active"}];
  const pending = f.run("navigateApp('#history')");
  await f.element("analysisStopConfirm").emit("click");
  assert.match(f.element("analysisStopError").textContent, /ยืนยันการบันทึก/);
  assert.equal(f.element("analysisStopDialog").open, true);
  assert.equal(f.location.hash, "#analysis");
  f.element("analysisStopDialog").close("stay");
  await pending;
});

test("job polling stays independent from view polling and starts only once", () => {
  const f = fixture();
  f.run("startAnalysisJobPolling();startAnalysisJobPolling();suspendAnalysisView()");
  assert.equal(f.intervals.size, 1);
  assert.equal([...f.intervals.values()][0].delay, 1000);
  f.run("appReady=false;clearAnalysisJobs()");
  assert.equal(f.intervals.size, 0);
});

test("pending webcam startup blocks navigation without stopping or changing the round", async () => {
  const f = fixture();
  f.run("beginSourceOperation('starting',{...analysisSelection(),sourceType:'webcam'})");
  await f.run("navigateApp('#history')");
  assert.equal(f.location.hash, "#analysis");
  assert.equal(f.run("currentLab"), "round");
  assert.ok(!f.calls.some(call => call.method === "DELETE"));
});

test("live responses and errors from a hidden or previous account view cannot alter the screen", async () => {
  for (const fail of [false, true]) {
    const f = fixture();
    f.job();
    let finish;
    f.context.apiFetch = () => new Promise((resolve, reject) => { finish = fail ? reject : resolve; });
    const update = f.run("updateLiveFeed()");
    f.run("appReady=false;clearAnalysisJobs();appReady=true");
    f.element("detectionCount").textContent = "new account";
    finish(fail ? Error("old network error") : {json: async () => ({num_people: 7})});
    await update;
    assert.equal(f.element("detectionCount").textContent, "new account");
  }
});

test("job banners are visible only in history while polling and analysis controls remain active", () => {
  const f = fixture(); f.job(); f.run("startAnalysisJobPolling()");
  for (const view of ["history", "analysis", "report", "history"]) {
    f.run(`showAppView('${view}')`);
    assert.equal(f.element("analysisJobsBanner").classList.contains("hidden"), view !== "history");
    assert.equal(f.run("analysisJobs.get('round/1').status"), "running");
  }
  assert.equal(f.intervals.size, 1);
  assert.equal(f.element("stopVideoBtn").classList.contains("hidden"), false);
  assert.ok(!f.calls.some(call => call.method === "DELETE"));
});

test("resume restores source presentation and recording time without a source-change warning", async () => {
  const f = fixture();
  const job = f.job(); job.state.source = "C:\\private\\videos\\lecture.mp4";
  f.run("selectedSourceMode='webcam';appView='history'");
  await f.run("resumeAnalysisJob('round/1')");
  assert.equal(f.run("selectedSourceMode"), "video");
  assert.equal(f.element("activeVideoName").textContent, "lecture.mp4");
  assert.notEqual(f.element("recordingStartInput").value, "");
  assert.equal(f.element("recordingStartInput").disabled, true);
  assert.equal(f.element("activeVideoDetails").classList.contains("hidden"), false);
  assert.equal(f.element("videoSourceSettings").classList.contains("hidden"), true);
  assert.ok(!f.calls.some(call => call.toast?.includes("หยุดรอบปัจจุบัน")));
  assert.ok(!f.calls.some(call => call.method));
});

test("rediscovery restores clip metadata after refresh without a file input selection", async () => {
  const f = fixture();
  f.context.sources = {"restored/1": {active:true, source_type:"video", source:"D:\\server\\renamed.mp4"}};
  f.run("currentLab='';appView='history';sessionHistoryState.sessions=[{id:'restored',name:'Restored',source_label:'lesson.mp4',recording_started_at:'2026-10-19T10:34:00+07:00'}]");
  await f.run("refreshAnalysisJobs()");
  await f.run("resumeAnalysisJob('restored/1')");
  assert.equal(f.element("activeVideoName").textContent, "lesson.mp4");
  assert.equal(f.run("currentRecordingStart"), "2026-10-19T10:34:00+07:00");
  assert.match(f.element("recordingStartInput").value, /^2026-10-19T\d{2}:\d{2}$/);
  assert.notEqual(f.element("activeVideoRecordingStart").textContent, "ไม่ระบุ");
  assert.equal(f.element("videoFileInput").value, "");
  assert.ok(!f.calls.some(call => call.toast?.includes("หยุดรอบปัจจุบัน")));
});

test("source-mode presentation is silent but a real change during a running job remains guarded", () => {
  const f = fixture(); f.job();
  f.run("currentSourceType='video';selectedSourceMode='video';setSourceMode('video')");
  assert.ok(!f.calls.some(call => call.toast));
  f.run("setSourceMode('webcam')");
  assert.equal(f.run("selectedSourceMode"), "video");
  assert.match(f.calls.find(call => call.toast).toast, /หยุดรอบปัจจุบัน/);
});

test("source fields are unlocked and old source details cleared for a new round", async () => {
  const f = fixture(); f.job();
  await f.run("resumeAnalysisJob('round/1')");
  f.run("analysisJobs.clear();currentLab='fresh';currentRecordingStart='';sessionCompleted=false;resetDashboardState();renderAnalysisJobs()");
  assert.equal(f.element("videoSourceSettings").classList.contains("hidden"), false);
  assert.equal(f.element("activeVideoDetails").classList.contains("hidden"), true);
  assert.equal(f.element("activeVideoName").textContent, "");
  assert.equal(f.element("recordingStartInput").value, "");
  assert.equal(f.element("recordingStartInput").disabled, false);
  assert.equal(f.element("uploadVideoBtn").disabled, false);
});

test("restoring a webcam renders its mode and index without hiding its stop action", async () => {
  const f = fixture(); const job = f.job("webcam");
  job.state.source = 2; job.sourceLabel = "Webcam 2";
  await f.run("resumeAnalysisJob('round/1')");
  assert.equal(f.run("selectedSourceMode"), "webcam");
  assert.equal(f.element("webcamSelect").value, "2");
  assert.equal(f.element("webcamSelect").disabled, true);
  assert.equal(f.element("stopWebcamBtn").classList.contains("hidden"), false);
  assert.equal(f.element("activeVideoDetails").classList.contains("hidden"), true);
  assert.equal(f.run("analysisSourceName(analysisJobs.get('round/1'))"), "Webcam 2");
  assert.ok(!f.calls.some(call => call.toast));
});

test("a pending source operation locks its own inputs and releases them on failure", () => {
  const f = fixture();
  f.run("beginSourceOperation('upload',{...analysisSelection(),sourceType:'video'})");
  assert.equal(f.element("recordingStartInput").disabled, true);
  assert.equal(f.element("videoFileInput").disabled, true);
  f.run("setSourceMode('webcam')");
  assert.equal(f.run("selectedSourceMode"), "video");
  f.run("endSourceOperation(sourceOperation)");
  assert.equal(f.element("recordingStartInput").disabled, false);
  assert.equal(f.element("videoFileInput").disabled, false);
});

test("live alerts prime at the latest cursor and only show new alerts for the current round", async () => {
  const f = fixture(); f.job();
  let payload = {latest_id: 10, alerts: [{id: 9, lab_id: "old", message: "Old round"},
    {id: 10, lab_id: "round", message: "Existing alert"}]};
  f.context.apiFetch = async () => ({ok:true,json:async()=>payload});
  await f.run("pollAlerts()");
  assert.ok(!f.calls.some(call=>call.toast));
  payload = {latest_id:13, alerts:[{id:11,lab_id:"old",message:"Other round"},
    {id:12,lab_id:"round",message:"Current alert",type:"warning"}, {id:13,message:"No round"}]};
  await f.run("pollAlerts()"); await f.run("pollAlerts()");
  assert.deepEqual(f.calls.filter(call=>call.toast).map(call=>({...call})), [{toast:"Current alert",type:"warning",sessionId:"round"}]);
  assert.equal(f.run("lastAlertId"), 13);
});

test("draft rounds do not request behavior alerts", async () => {
  const f = fixture(); await f.run("pollAlerts()");
  assert.equal(f.calls.length, 0);
});

test("overlapping alert polls share one request and stale responses cannot leak across views", async () => {
  const f = fixture(); f.job(); let finish; let requests = 0;
  f.context.apiFetch = () => { requests += 1; return new Promise(resolve=>{finish=resolve;}); };
  const first = f.run("pollAlerts()"); const second = f.run("pollAlerts()");
  assert.equal(requests, 1);
  f.run("suspendAnalysisView();currentLab='other'");
  finish({ok:true,json:async()=>({latest_id:5,alerts:[{id:5,lab_id:'round',message:'Stale'}]})});
  await first; await second;
  assert.ok(!f.calls.some(call=>call.toast));
  assert.equal(f.run("lastAlertId"), 0);
});

test("acknowledging a final report hides only its completed notice and retains the job state", () => {
  const f = fixture(); const job = f.job(); job.status = "completed";
  f.run("registerAnalysisJob({sessionId:'other',camId:1,name:'Other'},{source_type:'video'}).status='completed';showAppView('history')");
  f.run("acknowledgeAnalysisReport('round','completed')");
  assert.equal(f.element("analysisJobsList").innerHTML.includes('data-report-job="round/1"'), false);
  assert.equal(f.element("analysisJobsList").innerHTML.includes('data-report-job="other/1"'), true);
  assert.equal(f.run("analysisJobs.get('round/1').status"), "completed");
  assert.equal(f.run("analysisJobs.size"), 2);
});

test("running or non-final report snapshots cannot consume a later completion notice", () => {
  const f = fixture(); const job = f.job();
  f.run("acknowledgeAnalysisReport('round','completed')");
  assert.notEqual(job.reportViewed, true);
  job.status = "completed";
  f.run("acknowledgeAnalysisReport('round','active')");
  assert.notEqual(job.reportViewed, true);
});

test("report success acknowledges its final notice but failures retain it", async () => {
  for (const success of [true, false]) {
    const f = fixture(); const job = f.job(); job.status = "completed";
    const errors = [];
    f.context.console = {...console,error:(...args)=>errors.push(args)};
    f.run("renderReportTimeline=()=>{};renderTrackingReport=()=>{};renderBehaviorEvents=()=>{};renderAnalysisMethodology=()=>{}");
    f.context.apiFetch = async () => ({ok:success,json:async()=>({lab_id:'round',summary:{total_records:1},tracking:{session:{status:'completed'}}})});
    await f.reportLoader("round", "Round", false);
    assert.equal(job.reportViewed === true, success);
    assert.equal(errors.length, success ? 0 : 1);
    f.run("showAppView('history')");
    assert.equal(f.element("analysisJobsBanner").classList.contains("hidden"), success);
  }
});

test("a failed alert baseline retries without replaying old alerts on recovery", async () => {
  const f = fixture(); f.job(); let payload = {latest_id:5, alerts:[{id:5,lab_id:'round',message:'Old'}]}; let ok = false;
  f.context.apiFetch = async () => ({ok,json:async()=>payload});
  await f.run("pollAlerts()");
  assert.equal(f.run("lastAlertId"), 0);
  ok = true; await f.run("pollAlerts()");
  assert.ok(!f.calls.some(call=>call.toast));
  payload = {latest_id:6,alerts:[{id:6,lab_id:'round',message:'New'}]};
  await f.run("pollAlerts()");
  assert.deepEqual(f.calls.filter(call=>call.toast).map(call=>call.toast), ['New']);
});

test("returning to analysis establishes a new baseline instead of replaying offscreen alerts", async () => {
  const f = fixture(); f.job(); let payload = {latest_id:10,alerts:[]};
  f.context.apiFetch = async () => ({ok:true,json:async()=>payload});
  await f.run("pollAlerts()");
  f.run("stopAlertPolling()");
  payload = {latest_id:12,alerts:[{id:12,lab_id:'round',message:'While away'}]};
  await f.run("pollAlerts()");
  assert.ok(!f.calls.some(call=>call.toast));
  payload = {latest_id:13,alerts:[{id:13,lab_id:'round',message:'After return'}]};
  await f.run("pollAlerts()");
  assert.deepEqual(f.calls.filter(call=>call.toast).map(call=>call.toast), ['After return']);
});

test("leaving before the report finishes loading does not acknowledge completion", async () => {
  const f = fixture(); const job = f.job(); job.status = "completed"; let finish;
  f.run("renderReportTimeline=()=>{};renderTrackingReport=()=>{};renderBehaviorEvents=()=>{};renderAnalysisMethodology=()=>{}");
  f.context.apiFetch = () => new Promise(resolve=>{finish=resolve;});
  const loading = f.reportLoader("round", "Round", false);
  f.run("showAppView('history')");
  finish({ok:true,json:async()=>({lab_id:'round',tracking:{session:{status:'completed'}}})});
  await loading;
  assert.notEqual(job.reportViewed, true);
  assert.equal(f.element("analysisJobsBanner").classList.contains("hidden"), false);
});

test("late alerts from the previous account cannot overwrite a new account's cursor", async () => {
  const f = fixture(); f.job(); const responses = [];
  f.context.apiFetch = () => new Promise(resolve=>responses.push(resolve));
  const oldPoll = f.run("pollAlerts()");
  f.run("appReady=false;clearAnalysisJobs();appReady=true;currentLab='other';registerAnalysisJob(analysisSelection(),{source_type:'video'})");
  const newPoll = f.run("pollAlerts()");
  assert.equal(responses.length, 2);
  responses[1]({ok:true,json:async()=>({latest_id:20,alerts:[]})}); await newPoll;
  responses[0]({ok:true,json:async()=>({latest_id:10,alerts:[{id:10,lab_id:'round',message:'Private old alert'}]})}); await oldPoll;
  assert.equal(f.run("lastAlertId"), 20);
  assert.ok(!f.calls.some(call=>call.toast));
});

test("a connection warning remains visible when all completed notices are acknowledged", async () => {
  const f = fixture(); const job = f.job(); job.status = 'completed';
  f.run("acknowledgeAnalysisReport('round','completed');showAppView('history')");
  f.context.apiFetch = async () => { throw Error('offline'); };
  await f.run("refreshAnalysisJobs()");
  assert.equal(f.element("analysisJobsBanner").classList.contains("hidden"), false);
  assert.match(f.element("analysisJobsList").innerHTML, /ตรวจสถานะงานไม่ได้/);
  assert.equal(f.run("analysisJobBlocksCreation()"), true);
});
