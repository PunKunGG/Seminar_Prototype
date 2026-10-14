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
  const total = Math.floor(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor(total % 3600 / 60);
  return `${hours ? `${hours}:` : ""}${String(minutes).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

function playbackBounds(segment, duration) {
  if (!segment || !Number.isFinite(duration) || duration <= 0
      || !Number.isFinite(segment.start) || !Number.isFinite(segment.end)
      || segment.start < 0 || segment.start >= duration) return null;
  const end = Math.min(segment.end, duration);
  return end > segment.start ? { start: segment.start, end } : null;
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
  const setStatus = message => setTextIfPresent("videoEvidenceStatus", message);
  const stopAnimation = () => {
    if (videoEvidenceAnimation != null) cancelAnimationFrame(videoEvidenceAnimation);
    videoEvidenceAnimation = null;
  };
  const bounds = () => playbackBounds(videoEvidenceState?.segments[Number(select.value)], player.duration);
  const validBounds = () => Boolean(bounds());
  const enforceBounds = () => {
    const segment = bounds();
    if (!segment || !dialog.open || !validBounds()) return;
    if (player.currentTime >= segment.end) {
      player.pause();
      if (player.currentTime !== segment.end) player.currentTime = segment.end;
      setStatus("จบช่วงที่ตรวจจริงแล้ว");
    } else if (player.currentTime < segment.start) {
      player.currentTime = segment.start;
    }
  };
  const watchFrames = () => {
    enforceBounds();
    if (!player.paused && dialog.open) videoEvidenceAnimation = requestAnimationFrame(watchFrames);
  };
  const chooseSegment = () => {
    player.pause();
    if (!validBounds()) {
      replay.disabled = true;
      setStatus(player.readyState ? "ช่วงเวลาหลักฐานไม่ตรงกับความยาวคลิป" : "กำลังโหลดคลิป...");
      return;
    }
    player.currentTime = bounds().start;
    replay.disabled = false;
    const clamped = bounds().end < videoEvidenceState.segments[Number(select.value)].end;
    setStatus(`ตรวจจริง ${evidenceTime(bounds().start)} - ${evidenceTime(bounds().end)} ในคลิปต้นฉบับ${clamped ? " (จำกัดจุดจบตามความยาวคลิป)" : ""}`);
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
    replay.disabled = true;
    if (opener?.isConnected) opener.focus();
  });
  select.addEventListener("change", chooseSegment);
  player.addEventListener("loadedmetadata", chooseSegment);
  player.addEventListener("seeking", enforceBounds);
  player.addEventListener("timeupdate", enforceBounds);
  player.addEventListener("play", () => {
    if (!validBounds()) { player.pause(); return; }
    if (player.currentTime >= bounds().end) player.currentTime = bounds().start;
    stopAnimation();
    watchFrames();
  });
  player.addEventListener("pause", stopAnimation);
  replay.addEventListener("click", () => {
    if (!validBounds()) return;
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
  portrait.addEventListener("error", () => { portrait.hidden = true; });
  document.getElementById("reportBehaviorEventRows").addEventListener("click", event => {
    const opener = event.target.closest("button[data-video-event]");
    if (!opener) return;
    const tracking = reportEvidenceData();
    const behaviorEvent = tracking.events?.[Number(opener.dataset.videoEvent)];
    const segments = evidenceSegments(behaviorEvent);
    const url = latestExportData?.video_evidence?.url;
    if (!segments.length || !latestExportData.video_evidence.available || !/^\/api\/sessions\/[^/]+\/video$/.test(url)) return;
    videoEvidenceState = { segments, opener, url };
    select.innerHTML = segments.map((segment, index) => `<option value="${index}">${index + 1}. ${evidenceTime(segment.start)} - ${evidenceTime(segment.end)}</option>`).join("");
    select.value = "0";
    const image = representativeImages(tracking).get(Number(behaviorEvent.track_id));
    portrait.hidden = !image?.url;
    if (image?.url) portrait.src = apiUrl(image.thumbnail_url || image.url);
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
