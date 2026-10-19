let videoEvidenceState = null;
let videoEvidenceAnimation = null;

function evidenceSegments(event) {
  return (event?.observed_segments || []).filter(segment => Array.isArray(segment)
    && segment.length >= 3 && segment.every(Number.isFinite)
    && segment[0] >= 0 && segment[1] > segment[0] && segment[2] > 0)
    .map(([start, end]) => ({ start, end })).sort((a, b) => a.start - b.start);
}

function videoUnavailableMessage(reason) {
  return { webcam: "เว็บแคมรอบนี้ไม่ได้บันทึกวิดีโอ", unbound: "รอบนี้ไม่มีคลิปต้นฉบับที่ผูกไว้",
    cloud_only: "มีเฉพาะรายงานบนคลาวด์ ไม่มีคลิปต้นฉบับในเครื่องนี้",
    missing: "ไม่พบไฟล์คลิปบนเซิร์ฟเวอร์", changed: "ไฟล์คลิปเปลี่ยนจากต้นฉบับ",
    invalid_source: "ไฟล์อยู่นอกโฟลเดอร์ที่อนุญาต" }[reason] || "ไม่มีวิดีโอหลักฐานสำหรับรอบนี้";
}

function videoEvidenceAction(event, index) {
  const evidence = latestExportData?.video_evidence;
  if (!evidence?.available) return `<span class="text-gray-500">${escapeHtml(videoUnavailableMessage(evidence?.reason))}</span>`;
  if (!evidenceSegments(event).length) return '<span class="text-gray-500">ไม่มีข้อมูลช่วงที่ตรวจจริง</span>';
  return `<button type="button" data-video-event="${index}" aria-label="ดูหลักฐาน ID ${toWholePeople(event.track_id)} ${escapeHtml(behaviorLabel(event.behavior))}">ดูหลักฐาน</button>`;
}

function evidenceTime(seconds) {
  const milliseconds = Math.max(0, Math.round(seconds * 1000));
  const total = Math.floor(milliseconds / 1000);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor(total % 3600 / 60);
  const fraction = milliseconds % 1000 ? `.${String(milliseconds % 1000).padStart(3, "0").replace(/0+$/, "")}` : "";
  return `${hours ? `${hours}:` : ""}${String(minutes).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}${fraction}`;
}

function playbackBounds(segment, duration) {
  if (!segment || !Number.isFinite(duration) || duration <= 0
      || !Number.isFinite(segment.start) || !Number.isFinite(segment.end)
      || segment.start < 0 || segment.start >= duration) return null;
  const end = Math.min(segment.end, duration);
  return end > segment.start ? { start: segment.start, end } : null;
}

function evidencePlaybackWindow(segment, duration, mode = "observed") {
  const observed = playbackBounds(segment, duration);
  if (!observed) return null;
  return mode === "context"
    ? { start: Math.max(0, observed.start - 3), end: Math.min(duration, observed.end + 3) }
    : observed;
}

function evidenceTimeTolerance(segment) {
  return Math.min(0.05, (segment.end - segment.start) / 4);
}

function evidencePlaybackPhase(time, observed) {
  if (time < observed.start - evidenceTimeTolerance(observed)) return "บริบทก่อนช่วงตรวจ";
  if (time >= observed.end) return "บริบทหลังช่วงตรวจ";
  return "อยู่ในช่วงที่ตรวจจริง";
}

function closeVideoEvidence() {
  const dialog = document.getElementById("videoEvidenceDialog");
  if (dialog?.open) dialog.close();
}

function setupVideoEvidenceViewer() {
  const dialog = document.getElementById("videoEvidenceDialog");
  if (!dialog) return;
  const player = document.getElementById("videoEvidencePlayer");
  const select = document.getElementById("videoEvidenceSegment");
  const replay = document.getElementById("videoEvidenceReplay");
  const portrait = document.getElementById("videoEvidencePortrait");
  const setStatus = message => {
    if (document.getElementById("videoEvidenceStatus").textContent !== message) setTextIfPresent("videoEvidenceStatus", message);
  };
  const stopAnimation = () => {
    if (videoEvidenceAnimation != null) cancelAnimationFrame(videoEvidenceAnimation);
    videoEvidenceAnimation = null;
  };
  const selectedSegment = () => videoEvidenceState?.segments[Number(select.value)];
  const observedBounds = () => playbackBounds(selectedSegment(), player.duration);
  const bounds = () => evidencePlaybackWindow(selectedSegment(), player.duration, videoEvidenceState?.mode);
  const validBounds = () => Boolean(bounds());
  const enforceBounds = () => {
    const segment = bounds();
    if (!segment || !dialog.open || player.error || player.seeking) return;
    // Media clocks round fractional offsets; correcting every tiny difference can loop seeks.
    const tolerance = evidenceTimeTolerance(segment);
    if (player.currentTime >= segment.end
      || (videoEvidenceState.reachedEnd && player.currentTime >= segment.end - tolerance)) {
      videoEvidenceState.reachedEnd = true;
      player.pause();
      if (player.currentTime > segment.end + tolerance) player.currentTime = segment.end;
      setStatus(videoEvidenceState.mode === "context" ? "จบช่วงเล่นพร้อมบริบทแล้ว" : "จบช่วงที่ตรวจจริงแล้ว");
    } else {
      videoEvidenceState.reachedEnd = false;
      if (player.currentTime < segment.start - tolerance) player.currentTime = segment.start;
      setStatus(evidencePlaybackPhase(player.currentTime, observedBounds()));
    }
  };
  const watchFrames = () => {
    enforceBounds();
    if (!player.paused && dialog.open) videoEvidenceAnimation = requestAnimationFrame(watchFrames);
  };
  const updateRanges = () => {
    const observed = selectedSegment();
    const clamped = observedBounds().end < observed.end;
    setTextIfPresent("videoEvidenceRanges", `ช่วงตรวจจริง ${evidenceTime(observed.start)} - ${evidenceTime(observed.end)} | ช่วงเล่น ${evidenceTime(bounds().start)} - ${evidenceTime(bounds().end)} ในคลิปต้นฉบับ${clamped ? " (จำกัดจุดจบตามความยาวคลิป)" : ""}`);
  };
  const chooseSegment = () => {
    if (!videoEvidenceState || !dialog.open) return;
    player.pause();
    videoEvidenceState.positioned = false;
    videoEvidenceState.reachedEnd = false;
    document.getElementById("videoEvidenceContextNote").classList.toggle("hidden", videoEvidenceState.mode !== "context");
    replay.disabled = !validBounds();
    if (replay.disabled) {
      setTextIfPresent("videoEvidenceRanges", "");
      setStatus(player.readyState ? "ช่วงเวลาหลักฐานไม่ตรงกับความยาวคลิป" : "กำลังโหลดคลิป...");
      return;
    }
    videoEvidenceState.positioned = true;
    player.currentTime = bounds().start;
    updateRanges();
    const observed = observedBounds();
    setStatus(evidencePlaybackPhase(bounds().start, observed));
  };
  const syncMediaBounds = () => {
    if (!videoEvidenceState || !dialog.open) return;
    if (!videoEvidenceState.positioned) { chooseSegment(); return; }
    replay.disabled = !validBounds();
    if (replay.disabled) {
      player.pause();
      setTextIfPresent("videoEvidenceRanges", "");
      setStatus("ช่วงเวลาหลักฐานไม่ตรงกับความยาวคลิป");
      return;
    }
    updateRanges();
    enforceBounds();
  };
  document.getElementById("videoEvidenceClose").addEventListener("click", closeVideoEvidence);
  dialog.addEventListener("close", () => {
    const opener = videoEvidenceState?.opener;
    videoEvidenceState = null;
    stopAnimation();
    player.pause();
    player.removeAttribute("src");
    player.load();
    portrait.removeAttribute("src");
    delete portrait.dataset.originalUrl;
    replay.disabled = true;
    if (opener?.isConnected) opener.focus();
  });
  select.addEventListener("change", chooseSegment);
  for (const radio of document.querySelectorAll('input[name="videoEvidenceMode"]')) {
    radio.addEventListener("change", () => {
      if (!radio.checked || !videoEvidenceState) return;
      videoEvidenceState.mode = radio.value;
      chooseSegment();
    });
  }
  player.addEventListener("loadedmetadata", syncMediaBounds);
  player.addEventListener("durationchange", syncMediaBounds);
  player.addEventListener("seeking", enforceBounds);
  player.addEventListener("seeked", enforceBounds);
  player.addEventListener("timeupdate", enforceBounds);
  player.addEventListener("play", () => {
    if (!validBounds()) { player.pause(); return; }
    if (videoEvidenceState.reachedEnd || player.currentTime >= bounds().end) {
      videoEvidenceState.reachedEnd = false;
      player.currentTime = bounds().start;
    }
    stopAnimation();
    watchFrames();
  });
  player.addEventListener("pause", stopAnimation);
  replay.addEventListener("click", () => {
    if (!validBounds()) return;
    videoEvidenceState.reachedEnd = false;
    player.currentTime = bounds().start;
    player.play().catch(() => setStatus("กดเล่นในตัวเล่นวิดีโออีกครั้ง"));
  });
  player.addEventListener("error", async () => {
    const state = videoEvidenceState;
    if (!state) return;
    replay.disabled = true;
    setStatus("เล่นคลิปไม่ได้ เบราว์เซอร์อาจไม่รองรับ codec (แนะนำ MP4/H.264)");
    try {
      const response = await apiFetch(state.url, { headers: { Range: "bytes=0-0" } });
      if (!response.ok) {
        const data = await response.json();
        if (videoEvidenceState === state) setStatus(videoUnavailableMessage(data.reason));
      } else await response.body?.cancel();
    } catch { /* The report remains readable when its source is unavailable. */ }
  });
  portrait.addEventListener("load", () => {
    if (portrait.dataset.originalUrl) useOriginalForPaddedPortrait(portrait, portrait.dataset.originalUrl);
  });
  portrait.addEventListener("error", () => {
    if (portrait.dataset.originalUrl && portrait.src !== portrait.dataset.originalUrl) {
      portrait.src = portrait.dataset.originalUrl;
    } else portrait.hidden = true;
  });
  document.getElementById("reportBehaviorEventRows").addEventListener("click", event => {
    const opener = event.target.closest("button[data-video-event]");
    if (!opener) return;
    const tracking = reportEvidenceData();
    const behaviorEvent = tracking.events?.[Number(opener.dataset.videoEvent)];
    const segments = evidenceSegments(behaviorEvent);
    const url = latestExportData?.video_evidence?.url;
    if (!segments.length || !latestExportData.video_evidence.available || !/^\/api\/sessions\/[^/]+\/video$/.test(url)) return;
    videoEvidenceState = { segments, opener, url, mode: "observed" };
    for (const radio of document.querySelectorAll('input[name="videoEvidenceMode"]')) radio.checked = radio.value === "observed";
    document.getElementById("videoEvidenceContextNote").classList.add("hidden");
    setTextIfPresent("videoEvidenceRanges", "");
    select.innerHTML = segments.map((segment, index) => `<option value="${index}">${index + 1}. ${evidenceTime(segment.start)} - ${evidenceTime(segment.end)}</option>`).join("");
    select.value = "0";
    const image = representativeImages(tracking).get(Number(behaviorEvent.track_id));
    portrait.hidden = !image?.url;
    if (image?.url) {
      portrait.dataset.originalUrl = apiUrl(image.url);
      portrait.src = apiUrl(image.thumbnail_url || image.url);
    }
    portrait.alt = `ภาพอ้างอิง ID ${behaviorEvent.track_id}`;
    setTextIfPresent("videoEvidencePerson", `ID ${behaviorEvent.track_id}`);
    setTextIfPresent("videoEvidenceTitle", `ID ${behaviorEvent.track_id} | ${behaviorLabel(behaviorEvent.behavior)}`);
    replay.disabled = true;
    setStatus("กำลังโหลดคลิป...");
    dialog.showModal();
    player.src = apiUrl(url);
    player.load();
  });
}

document.addEventListener("DOMContentLoaded", setupVideoEvidenceViewer);
