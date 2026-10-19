const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

function fixture(start = 19.733333333333334, end = 61.36666666666667, extraSegments = []) {
  const elements = new Map();
  const frames = new Map();
  const document = {getElementById: id => element(id),
    querySelectorAll: () => [element("observedMode"), element("contextMode")], addEventListener() {}};
  function element(id) {
    if (elements.has(id)) return elements.get(id);
    const listeners = {};
    const item = {id, textContent: "", value: "0", dataset: {}, open: false, isConnected: true,
      addEventListener(type, listener) { (listeners[type] ||= []).push(listener); },
      emit(type, event = {}) { for (const listener of listeners[type] || []) listener(event); },
      classList: {toggle() {}, add() {}, remove() {}},
      showModal() { this.open = true; }, close() { this.open = false; this.emit("close"); },
      focus() { document.activeElement = this; }, removeAttribute(name) { delete this[name]; },
    };
    elements.set(id, item);
    return item;
  }
  const player = element("videoEvidencePlayer");
  element("observedMode").value = "observed";
  element("contextMode").value = "context";
  let time = 0;
  let nextFrame = 0;
  Object.assign(player, {duration: 180, readyState: 1, paused: true, seeking: false, seekCount: 0,
    load() {}, pause() { this.paused = true; this.emit("pause"); },
    play() { this.paused = false; this.emit("play"); return Promise.resolve(); },
    settleSeek() { this.seeking = false; this.emit("seeked"); },
    advance(seconds) { time += seconds; this.emit("timeupdate"); },
  });
  Object.defineProperty(player, "currentTime", {
    get: () => time,
    set(value) { time = Math.floor(value * 1e6) / 1e6; this.seekCount += 1; this.seeking = true; },
  });
  const context = vm.createContext({console, document,
    requestAnimationFrame(callback) { const id = ++nextFrame; frames.set(id, callback); return id; },
    cancelAnimationFrame(id) { frames.delete(id); },
    setTextIfPresent(id, text) { element(id).textContent = text; },
    representativeImages: () => new Map(), behaviorLabel: key => key, apiUrl: url => url,
    reportEvidenceData: () => ({events: [{track_id: 4, behavior: "attentive",
      observed_segments: [[start, end, end - start], ...extraSegments]}]}),
    latestExportData: {video_evidence: {available: true, url: "/api/sessions/fixture/video"}},
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, "..", "dashboard", "video-evidence.js"), "utf8"), context);
  vm.runInContext("setupVideoEvidenceViewer()", context);
  const opener = element("opener"); opener.dataset.videoEvent = "0";
  element("reportBehaviorEventRows").emit("click", {target: {closest: () => opener}});
  player.emit("loadedmetadata");
  player.settleSeek();
  return {context, player, element, frames, start, end};
}

test("video reference images share padded-thumbnail and missing-thumbnail fallbacks", () => {
  const f = fixture();
  const portrait = f.element("videoEvidencePortrait");
  const image = { url: "/original.jpg", thumbnail_url: "/portrait.jpg" };
  f.context.representativeImages = () => new Map([[4, image]]);
  let checks = 0;
  f.context.useOriginalForPaddedPortrait = (target, url) => { checks++; target.src = url; };
  const open = () => f.element("reportBehaviorEventRows").emit("click", {
    target: { closest: () => f.element("opener") },
  });
  open();
  assert.equal(portrait.src, "/portrait.jpg");
  portrait.emit("load");
  assert.equal(checks, 1);
  assert.equal(portrait.src, "/original.jpg");
  f.element("videoEvidenceDialog").close();
  assert.equal(portrait.dataset.originalUrl, undefined);
  open();
  portrait.emit("error");
  assert.equal(portrait.hidden, false);
  assert.equal(portrait.src, "/original.jpg");
  portrait.emit("error");
  assert.equal(portrait.hidden, true);
});

test("fractional segment starts do not cause repeated seeks or a false context label", async () => {
  const f = fixture();
  const initialSeeks = f.player.seekCount;
  await f.player.play();
  for (let i = 0; i < 20; i += 1) { f.player.emit("timeupdate"); f.player.settleSeek(); }
  assert.equal(f.player.seekCount, initialSeeks);
  assert.equal(f.element("videoEvidenceStatus").textContent, "อยู่ในช่วงที่ตรวจจริง");
  f.player.advance(0.5);
  assert.ok(f.player.currentTime > f.start + 0.4);
  assert.equal(f.player.paused, false);
});

test("seeking is allowed to settle before boundary correction", () => {
  const f = fixture();
  f.player.currentTime = 2;
  const seeks = f.player.seekCount;
  f.player.emit("seeking");
  f.player.emit("timeupdate");
  assert.equal(f.player.seekCount, seeks);
  f.player.settleSeek();
  assert.equal(f.player.seekCount, seeks + 1);
  f.player.settleSeek();
  assert.equal(f.player.seekCount, seeks + 1);
});

test("duration updates do not rewind or pause an already positioned player", async () => {
  const f = fixture();
  await f.player.play(); f.player.advance(2);
  const time = f.player.currentTime;
  const seeks = f.player.seekCount;
  f.player.duration = 180.01;
  f.player.emit("durationchange");
  assert.equal(f.player.seekCount, seeks);
  assert.equal(f.player.currentTime, time);
  assert.equal(f.player.paused, false);
});

test("end clamping settles without an exact-time seek loop and replay still works", async () => {
  const f = fixture();
  await f.player.play(); f.player.advance(f.end - f.start + 1);
  assert.equal(f.player.paused, true);
  f.player.settleSeek();
  const seeks = f.player.seekCount;
  for (let i = 0; i < 10; i += 1) { f.player.emit("timeupdate"); f.player.settleSeek(); }
  assert.equal(f.player.seekCount, seeks);
  f.element("videoEvidenceReplay").emit("click");
  f.player.settleSeek();
  assert.equal(f.player.paused, false);
  assert.ok(Math.abs(f.player.currentTime - f.start) < 1e-6);
});

test("context changes pause and seek once while separate observed segments remain separate", async () => {
  const f = fixture(19.733333333333334, 21.733333333333334, [[40, 42, 2]]);
  await f.player.play(); f.player.advance(0.5);
  f.element("contextMode").checked = true;
  f.element("contextMode").emit("change");
  f.player.settleSeek();
  assert.equal(f.player.paused, true);
  assert.ok(Math.abs(f.player.currentTime - (f.start - 3)) < 1e-6);
  assert.equal(f.element("videoEvidenceStatus").textContent, "บริบทก่อนช่วงตรวจ");
  f.element("videoEvidenceReplay").emit("click"); f.player.settleSeek();
  f.player.advance(9);
  assert.equal(f.player.paused, true);
  assert.equal(f.element("videoEvidenceSegment").value, "0");
  f.element("videoEvidenceSegment").value = "1";
  f.element("videoEvidenceSegment").emit("change"); f.player.settleSeek();
  assert.equal(f.player.currentTime, 37);
  assert.equal(f.player.paused, true);
  f.element("videoEvidenceDialog").close();
  assert.equal(f.player.paused, true);
  assert.equal(f.player.src, undefined);
  assert.equal(f.frames.size, 0);
});

test("timing tolerance stays below the size of a very short segment", async () => {
  const f = fixture(19.733333333333334, 19.734333333333333);
  await f.player.play();
  const seeks = f.player.seekCount;
  f.player.advance(0.0005);
  assert.equal(f.player.paused, false);
  assert.equal(f.player.seekCount, seeks);
  f.player.advance(0.002);
  assert.equal(f.player.paused, true);
  assert.equal(f.element("videoEvidenceStatus").textContent, "จบช่วงที่ตรวจจริงแล้ว");
});

test("native play just before the end does not restart the selected segment early", async () => {
  const f = fixture();
  f.player.currentTime = f.end - 0.01; f.player.settleSeek();
  const seeks = f.player.seekCount;
  await f.player.play();
  assert.equal(f.player.seekCount, seeks);
  assert.ok(f.player.currentTime > f.end - 0.02);
  f.player.advance(0.02);
  assert.equal(f.player.paused, true);
});

test("a duration change that invalidates the segment disables playback safely", async () => {
  const f = fixture(); await f.player.play();
  f.player.duration = 5; f.player.emit("durationchange");
  assert.equal(f.player.paused, true);
  assert.equal(f.element("videoEvidenceReplay").disabled, true);
  assert.equal(f.element("videoEvidenceRanges").textContent, "");
});
