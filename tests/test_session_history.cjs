const assert = require("node:assert/strict");
const { execFileSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

function dashboardContext() {
  const input = { value: "30" };
  const elements = { analysisIntervalInput: input };
  const context = vm.createContext({
    console,
    document: { addEventListener() {}, getElementById: (id) => elements[id] ?? null },
    window: { location: { protocol: "http:", origin: "http://localhost" }, addEventListener() {} },
  });
  for (const filename of ["shared.js", "video-evidence.js", "session-history.js"]) {
    vm.runInContext(fs.readFileSync(path.join(__dirname, "..", "dashboard", filename), "utf8"), context);
  }
  return { context, input, elements };
}

function sortedIds(context, sessions, settings) {
  context.testState = { sessions, query: "", sort: "date", direction: -1, ...settings };
  return Array.from(vm.runInContext("filterAndSortSessions(testState).map(item => item.id)", context));
}

test("qualified report helpers preserve raw evidence and people but use eligible minutes", () => {
  const { context } = dashboardContext();
  context.reportFixture = {
    tracking: { session: { name: "Round" }, tracks: [{ track_id: 1, attention_rate: 50 }],
      representative_evidence: [{ track_id: 1, url: "/api/evidence/round/ref.jpg", filename: "ref.jpg" }] },
    periods: [{ start_seconds: 0, label: "09:00 - 09:05", avg_people: 11, avg_attention_rate: 70, summary: { sleeping: 3 } }],
    qualified_analysis: {
      summary: { behavior_seconds: { attentive: 60, sleeping: 30 } },
      tracks: [{ track_id: 1, attention_rate: 66.7, qualified_seconds: 90 }], events: [],
      periods: [{ start_seconds: 0, attention_rate: 66.7, behavior_seconds: { attentive: 60, sleeping: 30 } }],
    },
  };
  vm.runInContext("latestExportData = reportFixture", context);
  assert.equal(vm.runInContext("reportTrackingData().representative_evidence[0].filename", context), "ref.jpg");
  assert.equal(vm.runInContext("reportTrackingData().tracks[0].attention_rate", context), 66.7);
  assert.equal(vm.runInContext("reportPeriodData()[0].avg_people", context), 11);
  assert.equal(vm.runInContext("reportPeriodData()[0].summary.sleeping", context), 30);
  assert.equal(vm.runInContext("getReportBehavior().sleeping", context), 0.5);
  assert.equal(vm.runInContext("formatAttention(null)", context), "-");
});

test("legacy reports keep their results while portraits share the ID cell", () => {
  const { context, elements } = dashboardContext();
  elements.reportTrackingSection = { classList: { toggle() {} } };
  elements.reportTrackingRows = { innerHTML: "" };
  elements.reportTrackingCaption = {};
  context.reportFixture = { tracks: [{ track_id: 2, visible_seconds: 1, attention_rate: 80, behavior_seconds: {} }],
    representative_evidence: [{ track_id: 2, url: "/api/evidence/round/ref.jpg" }] };
  vm.runInContext("renderTrackingReport(reportFixture)", context);
  assert.match(elements.reportTrackingRows.innerHTML, /width="80" height="80"/);
  assert.match(elements.reportTrackingRows.innerHTML, /ID 2/);
  assert.match(elements.reportTrackingRows.innerHTML, /80%/);
  assert.match(elements.reportTrackingRows.innerHTML, /data-evidence-url/);
  assert.doesNotMatch(elements.reportTrackingRows.innerHTML, /ผ่านเกณฑ์/);
});

test("CSV and Excel use the same qualified results and image filename in each ID row", () => {
  const { context } = dashboardContext();
  context.reportFixture = {
    lab_id: "round", summary: { total_records: 2, avg_people: 11, max_people: 11, report_total_people: 11, avg_attention_rate: 100 },
    tracking: { session: { name: "Round" }, tracks: [], events: [],
      representative_evidence: [{ track_id: 1, filename: "ref.jpg", thumbnail_filename: "portrait.jpg", url: "/api/evidence/round/ref.jpg" }] },
    report_policy: { minimum_behavior_seconds: 30 }, periods: [], history: [{ time: "raw", attention_rate: 0 }],
    qualified_analysis: { summary: { behavior_seconds: { attentive: 60, sleeping: 0 } },
      tracks: [{ track_id: 1, visible_seconds: 65, qualified_seconds: 60, attention_rate: 100,
        behavior_seconds: { attentive: 60 }, event_counts: { attentive: 1 } }], events: [], periods: [] },
  };
  vm.runInContext("latestExportData = reportFixture; downloadBlob = value => { capturedExport = value; }", context);
  for (const format of ["csv", "excel"]) {
    vm.runInContext(`downloadReport("${format}")`, context);
    assert.match(context.capturedExport, /portrait\.jpg/);
    assert.match(context.capturedExport, /ตั้งใจเรียน \(นาทีรวม\)/);
    assert.match(context.capturedExport, /เวลาที่ผ่านเกณฑ์/);
    assert.doesNotMatch(context.capturedExport, /ข้อมูลย้อนหลัง|ภาพอ้างอิงและพฤติกรรมรายตำแหน่ง/);
  }
});

test("people and attention sort numerically with missing measurements last", () => {
  const { context } = dashboardContext();
  const sessions = [
    { id: "missing", report_total_people: null },
    { id: "ten", report_total_people: 10, avg_attention_rate: 90 },
    { id: "two", report_total_people: 2, avg_attention_rate: 10 },
    { id: "zero", report_total_people: 0, avg_attention_rate: 0 },
  ];
  assert.deepEqual(sortedIds(context, sessions, { sort: "people", direction: 1 }), ["zero", "two", "ten", "missing"]);
  assert.deepEqual(sortedIds(context, sessions, { sort: "people", direction: -1 }), ["ten", "two", "zero", "missing"]);
  assert.deepEqual(sortedIds(context, sessions, { sort: "attention", direction: 1 }), ["zero", "two", "ten", "missing"]);
});

test("ID summaries hide all-zero columns but keep portraits and individual dashes", () => {
  const { context, elements } = dashboardContext();
  elements.reportTrackingSection = { classList: { toggle() {} } };
  elements.reportTrackingRows = { innerHTML: "" };
  elements.reportTrackingCaption = {};
  elements.reportTrackingHead = { innerHTML: "", closest: () => ({ style: {} }) };
  context.tracking = { is_qualified: true, tracks: [
    { track_id: 1, qualified_seconds: 30, visible_seconds: 35, attention_rate: 100, event_counts: { attentive: 1 }, behavior_seconds: { attentive: 30 } },
    { track_id: 2, qualified_seconds: 0, visible_seconds: 20, attention_rate: null, event_counts: {} },
  ] };
  vm.runInContext("renderTrackingReport(tracking)", context);
  assert.doesNotMatch(elements.reportTrackingHead.innerHTML, /หลับ|โทรศัพท์/);
  assert.match(elements.reportTrackingHead.innerHTML, /ตั้งใจเรียน/);
  assert.match(elements.reportTrackingRows.innerHTML, /ID 2/);
  assert.match(elements.reportTrackingRows.innerHTML, />-<\/td>/);
  context.tracking.tracks[0].event_counts = {};
  vm.runInContext("renderTrackingReport(tracking)", context);
  assert.match(elements.reportTrackingCaption.textContent, /ไม่มีช่วงพฤติกรรมผ่านเกณฑ์/);
  assert.equal((elements.reportTrackingRows.innerHTML.match(/<td /g) || []).length, 6);
});

test("evidence segments preserve unsampled gaps and reject invalid offsets", () => {
  const { context } = dashboardContext();
  context.event = { observed_segments: [[600, 660, 60], [270, 330, 60], [-1, 1, 2], [3, 3, 1], [4, Infinity, 1]] };
  assert.equal(vm.runInContext("JSON.stringify(evidenceSegments(event))", context), '[{"start":270,"end":330},{"start":600,"end":660}]');
  assert.equal(vm.runInContext("evidenceSegments({}).length", context), 0);
  assert.equal(vm.runInContext("evidenceTime(3661)", context), "1:01:01");
});

test("evidence playback clamps media end without discarding playable content", () => {
  const { context } = dashboardContext();
  for (const end of [10.01, 10.25, 15]) {
    assert.equal(vm.runInContext(`JSON.stringify(playbackBounds({start: 9, end: ${end}}, 10))`, context), '{"start":9,"end":10}');
  }
  assert.equal(vm.runInContext("JSON.stringify(playbackBounds({start: 1, end: 5}, 10))", context), '{"start":1,"end":5}');
  for (const start of [-1, 10, 11]) {
    assert.equal(vm.runInContext(`playbackBounds({start: ${start}, end: 12}, 10)`, context), null);
  }
  assert.equal(vm.runInContext("playbackBounds({start: 1, end: 5}, NaN)", context), null);
  assert.equal(vm.runInContext("playbackBounds({start: 1, end: 5}, Infinity)", context), null);
});

test("raw excluded events remain inspectable independently of qualified totals", () => {
  const { context, elements } = dashboardContext();
  elements.reportBehaviorEventsSection = { classList: { toggle() {} } };
  elements.reportBehaviorEventRows = { innerHTML: "" };
  elements.reportBehaviorEventsCaption = {};
  const events = [
    { track_id: 2, event_index: 1, behavior: "sleeping", duration_seconds: 90, observed_segments: [[10,100,90]] },
    { track_id: 3, event_index: 1, behavior: "hand_raised", duration_seconds: 20, observed_segments: [[110,130,20]] },
    { track_id: 4, event_index: 1, behavior: "attentive", duration_seconds: 60, observed_segments: [[140,200,60]] },
  ];
  context.fixture = { tracking: { events }, report_policy: { version: 3, minimum_behavior_seconds: 30, minimum_behavior_seconds_by_behavior: { sleeping: 120 } },
    qualified_analysis: { summary: { attention_rate: 100 }, events: [events[2]] },
    video_evidence: { available: true, url: "/api/sessions/round/video" } };
  vm.runInContext("latestExportData=fixture; renderBehaviorEvents(reportEvidenceData())", context);
  assert.equal((elements.reportBehaviorEventRows.innerHTML.match(/data-video-event=/g) || []).length, 3);
  assert.match(elements.reportBehaviorEventRows.innerHTML, /ไม่คิดในรายงาน/);
  assert.match(elements.reportBehaviorEventRows.innerHTML, /นับในรายงาน/);
  assert.match(elements.reportBehaviorEventsCaption.textContent, /ผลตรวจดิบ/);
  assert.equal(vm.runInContext("reportTrackingData().events.length", context), 1);
  assert.equal(vm.runInContext("reportEvidenceData().events[1].track_id", context), 3);
  assert.equal(vm.runInContext("latestExportData.qualified_analysis.summary.attention_rate", context), 100);
});

test("new report minimums do not rewrite legacy policy thresholds", () => {
  const { context } = dashboardContext();
  vm.runInContext("latestExportData = { report_policy: { version: 3, minimum_behavior_seconds: 30, minimum_behavior_seconds_by_behavior: { sleeping: 120 } } }", context);
  assert.equal(vm.runInContext("reportMinimumSeconds('sleeping')", context), 120);
  assert.equal(vm.runInContext("reportMinimumSeconds('attentive')", context), 30);
  vm.runInContext("latestExportData.report_policy.version = 2", context);
  assert.equal(vm.runInContext("reportMinimumSeconds('sleeping')", context), 30);
});

test("sleeping labels stay non-definitive across reports, evidence and exports", () => {
  const { context, elements } = dashboardContext();
  for (const id of ["reportTrackingSection", "reportBehaviorEventsSection", "reportMethodologySection"]) {
    elements[id] = { classList: { toggle() {} } };
  }
  for (const id of ["reportTrackingRows", "reportTrackingCaption", "reportBehaviorEventRows", "reportBehaviorEventsCaption",
    "reportMethodologyRows", "reportMethodologyLimitations", "reportSummaryInterval"]) elements[id] = { innerHTML: "" };
  elements.reportTrackingHead = { innerHTML: "", closest: () => ({ style: {} }) };
  const rawEvent = { track_id: 1, event_index: 1, behavior: "sleeping", duration_seconds: 90, observed_segments: [[0,90,90]] };
  const track = { track_id: 1, visible_seconds: 120, qualified_seconds: 120, attention_rate: 0, event_counts: { sleeping: 1 }, behavior_seconds: { sleeping: 120 } };
  context.fixture = { lab_id: "round", summary: { total_records: 1, avg_people: 1, max_people: 1, report_total_people: 1, avg_attention_rate: 0 },
    tracking: { session: { name: "Round" }, tracks: [track], events: [rawEvent] },
    report_policy: { version: 3, minimum_behavior_seconds: 30, minimum_behavior_seconds_by_behavior: { sleeping: 120 } },
    qualified_analysis: { summary: { behavior_seconds: { sleeping: 120 } }, tracks: [track], events: [], periods: [] },
    video_evidence: { available: true, url: "/api/sessions/round/video" },
    analysis_methodology: { realtime_summary_interval_seconds: 30, criteria: [{ behavior: "sleeping", label: "หลับ", confirmation_seconds: 8, report_minimum_seconds: 120 }] } };
  vm.runInContext("latestExportData=fixture; renderTrackingReport(reportTrackingData()); renderBehaviorEvents(reportEvidenceData()); renderAnalysisMethodology(fixture.analysis_methodology)", context);
  assert.equal(vm.runInContext("behaviorLabel('sleeping')", context), "ท่าเข้าข่ายหลับ");
  assert.match(elements.reportTrackingHead.innerHTML, /ท่าเข้าข่ายหลับ/);
  assert.match(elements.reportBehaviorEventRows.innerHTML, /ท่าเข้าข่ายหลับ/);
  assert.match(elements.reportMethodologyRows.innerHTML, /ท่าเข้าข่ายหลับ/);
  for (const format of ["csv", "excel"]) {
    vm.runInContext(`downloadBlob=value=>{capturedExport=value;}; downloadReport('${format}')`, context);
    assert.match(context.capturedExport, /ท่าเข้าข่ายหลับ \(ครั้ง\)/);
    assert.doesNotMatch(context.capturedExport, /(?:>|\")หลับ(?:<|\"| \()/);
  }
  assert.equal(vm.runInContext("latestExportData.qualified_analysis.tracks[0].event_counts.sleeping", context), 1);
});

test("cloud-only footage explains storage availability instead of missing binding", () => {
  const { context } = dashboardContext();
  assert.match(vm.runInContext("videoUnavailableMessage('cloud_only')", context), /คลาวด์/);
  assert.notEqual(vm.runInContext("videoUnavailableMessage('cloud_only')", context), vm.runInContext("videoUnavailableMessage('unbound')", context));
});

test("video actions explain unavailable sources instead of guessing a clip", () => {
  const { context } = dashboardContext();
  vm.runInContext("latestExportData = { video_evidence: { available: false, reason: 'changed' } }", context);
  assert.match(vm.runInContext("videoEvidenceAction({}, 0)", context), /ไฟล์คลิปเปลี่ยน/);
  assert.doesNotMatch(vm.runInContext("videoEvidenceAction({}, 0)", context), /<button/);
  vm.runInContext("latestExportData.video_evidence = { available: true, url: '/api/sessions/round/video' }", context);
  assert.match(vm.runInContext("videoEvidenceAction({ track_id: 1, observed_segments: [[1,2,1]] }, 0)", context), /data-video-event="0"/);
});

test("search includes names, subjects, rooms and Thai display dates", () => {
  const { context } = dashboardContext();
  const sessions = [
    { id: "ai", name: "Morning", course_name: "AI", room_name: "Lab 9226", recording_started_at: "2026-09-20T10:34:00+07:00" },
    { id: "game", name: "Afternoon", course_name: "GameDev", room_name: "Lab 9227" },
  ];
  for (const query of ["morning", "9226", "ai", "20/9/2569"]) {
    assert.deepEqual(sortedIds(context, sessions, { query }), ["ai"]);
  }
  assert.deepEqual(sortedIds(context, sessions, { query: "no match" }), []);
});

test("date sorting is chronological and name sorting handles numbered lessons", () => {
  const { context } = dashboardContext();
  const sessions = [
    { id: "old", name: "Lesson 10", recording_started_at: "2026-09-01T09:00:00+07:00" },
    { id: "new", name: "Lesson 2", recording_started_at: "2026-10-01T11:00:00+07:00" },
    { id: "missing", name: "Lesson 20", recording_started_at: "invalid" },
  ];
  assert.deepEqual(sortedIds(context, sessions, {}), ["new", "old", "missing"]);
  assert.deepEqual(sortedIds(context, sessions, { sort: "name", direction: 1 }), ["new", "old", "missing"]);
  assert.deepEqual(sortedIds(context, sessions, { sort: "time", direction: 1 }), ["old", "new", "missing"]);
});

test("manually typed summary intervals remain within 15-300 seconds", () => {
  const { context, input } = dashboardContext();
  for (const [raw, expected] of [["1", 15], ["14.5", 15], ["999", 300], ["", 30], ["bad", 30], ["30", 30]]) {
    input.value = raw;
    assert.equal(vm.runInContext("normalizeAnalysisIntervalInput()", context), expected);
    assert.equal(input.value, String(expected));
  }
});

test("live and normal-video chart captions use the round summary interval", () => {
  const { context, elements } = dashboardContext();
  elements.attentionChartCadence = {};
  elements.attentionChartTitle = {};
  for (const interval of [15, 30, 60]) {
    vm.runInContext(`currentAnalysisInterval = ${interval}`, context);
    for (const sourceType of ["webcam", "video"]) {
      context.sourceData = { source_type: sourceType, processing_mode: "realtime" };
      vm.runInContext("updateAnalysisCadence(sourceData)", context);
      assert.equal(elements.attentionChartCadence.textContent, `สรุปผลทุก ${interval} วินาที`);
      assert.equal(elements.attentionChartTitle.textContent, "กราฟความตั้งใจเรียน (Real-time)");
    }
    vm.runInContext("updateAnalysisCadence()", context);
    assert.equal(elements.attentionChartCadence.textContent, `สรุปผลทุก ${interval} วินาที`);
  }
});

test("sampled-video captions use the server interval with the round interval as fallback", () => {
  const { context, elements } = dashboardContext();
  elements.attentionChartCadence = {};
  elements.attentionChartTitle = {};
  for (const interval of [15, 30, 60]) {
    context.sourceData = { processing_mode: "sampled", sample_interval_seconds: interval };
    vm.runInContext("currentAnalysisInterval = 30; updateAnalysisCadence(sourceData)", context);
    assert.equal(elements.attentionChartCadence.textContent, `สรุปทุก ${interval} วินาทีของคลิป`);
    assert.equal(elements.attentionChartTitle.textContent, "กราฟความตั้งใจเรียน (Timeline)");
    vm.runInContext(`currentAnalysisInterval = ${interval}; updateAnalysisCadence({ processing_mode: 'sampled' })`, context);
    assert.equal(elements.attentionChartCadence.textContent, `สรุปทุก ${interval} วินาทีของคลิป`);
  }
});

test("detection-mode buttons keep selected color and accessible pressed state", () => {
  const { context, elements } = dashboardContext();
  for (const id of ["behaviorModeBehaviorBtn", "behaviorModeCountBtn"]) {
    elements[id] = { attributes: {}, setAttribute(name, value) { this.attributes[name] = value; } };
  }
  for (const behavior of [true, false]) {
    vm.runInContext(`useBehaviorMode = ${behavior}; updateModeToggle()`, context);
    const active = elements[behavior ? "behaviorModeBehaviorBtn" : "behaviorModeCountBtn"];
    const inactive = elements[behavior ? "behaviorModeCountBtn" : "behaviorModeBehaviorBtn"];
    assert.match(active.className, /bg-blue-600/);
    assert.match(active.className, /text-white/);
    assert.equal(active.attributes["aria-pressed"], "true");
    assert.match(inactive.className, /bg-white/);
    assert.match(inactive.className, /text-gray-700/);
    assert.equal(inactive.attributes["aria-pressed"], "false");
    assert.match(active.className, /flex-1/);
    assert.match(inactive.className, /flex-1/);
  }
});

test("screen polling stays at two seconds independently of the summary interval", () => {
  const { context, elements } = dashboardContext();
  const delays = [];
  elements.liveFeed = {};
  context.setInterval = (_, delay) => { delays.push(delay); return delays.length; };
  context.clearInterval = () => {};
  vm.runInContext("currentAnalysisInterval = 60; updateLiveFeed = () => {}; updateCharts = () => {}; startLiveFeed(); startChartUpdates()", context);
  assert.deepEqual(delays, [2000, 2000]);
});

test("report timestamps show the same instant in each browser timezone", () => {
  const sharedPath = path.join(__dirname, "..", "dashboard", "shared.js");
  const script = `
    const fs = require('node:fs');
    const vm = require('node:vm');
    const context = vm.createContext({
      document: { addEventListener() {} },
      window: { location: { protocol: 'http:', origin: 'http://localhost' } },
    });
    vm.runInContext(fs.readFileSync(${JSON.stringify(sharedPath)}, 'utf8'), context);
    console.log(vm.runInContext('formatReportDateTime("2026-10-07T03:00:00+00:00")', context));
  `;
  for (const [timezone, expectedTime] of [
    ["UTC", "03:00:00"],
    ["Asia/Bangkok", "10:00:00"],
    ["America/New_York", "23:00:00"],
  ]) {
    const result = execFileSync(process.execPath, ["-e", script], {
      env: { ...process.env, TZ: timezone }, encoding: "utf8",
    }).trim();
    assert.ok(result.includes(expectedTime), `${timezone}: ${result}`);
  }
});
