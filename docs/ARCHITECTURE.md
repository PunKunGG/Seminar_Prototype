# ClassMood AI Architecture

## Existing Boundaries

- `backend/server.py` is a Flask application serving the dashboard and authenticated APIs. OpenCV reads local files or server-connected webcams. YOLO pose/object inference and session tracking run on the server.
- `dashboard/` uses HTML, CSS, and JavaScript without a frontend framework. Native dialogs present small evidence tools; reports are separate views. Browser-side exporters produce PDF, CSV, and Excel.
- SQLite stores rounds, tracks, behavior events, observed-segment JSON, time buckets, and image metadata. A local evidence store owns JPEG files. Runtime data and uploaded videos are ignored by Git.
- Pose-derived portraits exclude masked `(0, 0)` and out-of-frame keypoints, even when confidence is above threshold. Insufficient head/shoulder geometry retains the original person image; this does not add facial detection or alter behavior classification.
- Supabase Auth verifies login. The server archive adapter stores completed report JSON, normalized records, and private images. Server credentials never reach the browser.

## Report Policies

Persist the policy with each round. Legacy rounds remain unchanged. Policy v2 qualifies all behaviors at 30 observed seconds. Policy v3 adds a sleeping override of 120 seconds while retaining 30 seconds for other behaviors. Both policies retain persistent position tracking and observed-segment recording.

Qualification precedes five-minute allocation; attentive and hand-raised qualified time form the attention numerator. History listing uses a single owner-scoped SQL aggregate, not per-round full reports. Python qualification and the SQLite aggregate must use the same per-behavior thresholds.

## Analysis Job Lifecycle

`dashboard/analysis-jobs.js` owns the browser's job registry independently of the displayed route. It discovers owner-scoped live sources through existing `/api/sources` and joins the existing session metadata; SQLite `active` status alone never restores a worker. One non-overlapping one-second poll continues across views. Background views detach streams and stop chart/live-feed polling without DELETE. Reconnection attaches to the running source without POST or tracker reset. A missing live source is interrupted, not silently restarted; a failed status request preserves the job and blocks new creation.

Uploads and source starts retain a snapshot of their original round and an authentication-generation token. Route changes cannot retarget a late response. Account lock or a changed application user clears jobs, view data, timers and notices before revealing the new account, without stopping server video work. Completion navigation is limited to the corresponding foreground analysis. Explicit stop uses the existing DELETE API and verifies terminal saved metadata before allowing navigation. Webcam navigation is guarded by a native confirmation dialog, including hash/Back navigation. This adds no server worker service, persistence schema, endpoint, cloud queue, or durable restart recovery.

Restoration renders the source mode separately from the guarded user command for changing sources. Job metadata supplies the recording start and source label, with the live source as a filename fallback; display only the basename, not a server filesystem path. A bound video's source details replace the upload form, and source inputs are disabled during uploads/starts or once bound. Never repopulate a file input or re-upload footage to reconnect.

Successful final-report rendering acknowledges terminal job notices in the browser registry without deleting the job or report. A live report snapshot cannot consume a later completion notice. Alert polling uses the existing owner-scoped `/api/alerts?since_id=...` API: establish a latest-ID baseline on each foreground watch, then display only newer alerts matching that round's `lab_id`. Serialize requests and reject responses from an old view, source or authentication generation. Stop polling and remove round-scoped popups on leaving analysis; do not replay the offscreen backlog on return. This adds no alert endpoint or persistence schema.

## Local Video Evidence

Persist the source reference and file identity in SQLite only when a new video round starts. Keep these fields out of public metadata, normalized Supabase records, and report JSON. Validate real paths against configured video roots unless `CLASSMOOD_ALLOW_ANY_VIDEO_PATH` explicitly permits unrestricted local paths. Always check the persisted source binding, file identity, and ownership each time footage is requested, regardless of that setting.

Source admission resolves both the input path and configured roots before checking containment, then passes that canonical path to capture and binding. A symlink escaping an allowed root is rejected before analysis starts unless unrestricted paths are explicitly enabled. In-root aliases and symlinked roots use the same real-path validation as evidence playback.

`GET /api/sessions/<session_id>/video` serves the owner's original file with HTTP Range support and private/no-store headers. Auth-disabled operation retains local access restrictions. It must never accept a client-provided filesystem path.

Report responses include additive `video_evidence` availability information and a session-scoped URL when available. Recompute this information for local and archived reports at request time. Cloud-only reports remain readable but cannot obtain unbound local footage.

When the local round row is absent, use the archived source context for the unavailable reason: `webcam` for webcam footage that was not recorded, otherwise `cloud_only` for an archived report whose original footage is not present locally. Reserve `unbound` for local rounds without a persisted source binding; do not infer past binding history from an absent local row.

The evidence table and player retain raw events independently of qualified report totals. Default table membership comes from `qualified_analysis.events`, keyed by track ID and event index; excluded raw events remain opt-in. Filters and client-side pagination preserve raw event indexes so media actions cannot select the wrong event. They never alter report JSON or exports.

The browser uses numeric offsets from `observed_segments`. It plays one selected observed segment, or an explicit context window extending up to three seconds on each side, clamped to finite media duration. The selected observed bounds remain unchanged and context is labelled separately, including before/during/after playback status. It stops at the selected playback end, never automatically crosses to another observed segment, and does not rerun inference. Segments starting outside the media cannot play. No video is embedded in exports or uploaded to Supabase. Unsupported codecs are surfaced without automatic transcoding.

Playback boundary enforcement waits for pending seeks to settle and tolerates media-clock rounding (at most 50ms, reduced for short segments). This prevents repeated seeks at fractional segment starts without rounding or changing stored report offsets. Metadata/duration updates refresh bounds without rewinding an already positioned player; explicit mode/segment changes still pause and seek to the selected start.

## Compatibility

Use additive SQLite migration only, no Supabase schema change or new dependency. Store v3 report thresholds in the existing policy/report JSON. Existing endpoints remain compatible. Authorization and owner isolation apply independently to each media request.
