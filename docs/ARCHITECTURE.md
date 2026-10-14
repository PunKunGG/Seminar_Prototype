# ClassMood AI Architecture

## Existing Boundaries

- `backend/server.py` is a Flask application serving the dashboard and authenticated APIs. OpenCV reads local files or server-connected webcams. YOLO pose/object inference and session tracking run on the server.
- `dashboard/` uses HTML, CSS, and JavaScript without a frontend framework. Native dialogs present small evidence tools; reports are separate views. Browser-side exporters produce PDF, CSV, and Excel.
- SQLite stores rounds, tracks, behavior events, observed-segment JSON, time buckets, and image metadata. A local evidence store owns JPEG files. Runtime data and uploaded videos are ignored by Git.
- Supabase Auth verifies login. The server archive adapter stores completed report JSON, normalized records, and private images. Server credentials never reach the browser.

## Report Policies

Persist the policy with each round. Legacy rounds remain unchanged. Policy v2 qualifies all behaviors at 30 observed seconds. Policy v3 adds a sleeping override of 120 seconds while retaining 30 seconds for other behaviors. Both policies retain persistent position tracking and observed-segment recording.

Qualification precedes five-minute allocation; attentive and hand-raised qualified time form the attention numerator. History listing uses a single owner-scoped SQL aggregate, not per-round full reports. Python qualification and the SQLite aggregate must use the same per-behavior thresholds.

## Local Video Evidence

Persist the source reference and file identity in SQLite only when a new video round starts. Keep these fields out of public metadata, normalized Supabase records, and report JSON. Validate real paths against configured video roots and check file identity each time footage is requested.

`GET /api/sessions/<session_id>/video` serves the owner's original file with HTTP Range support and private/no-store headers. Auth-disabled operation retains local access restrictions. It must never accept a client-provided filesystem path.

Report responses include additive `video_evidence` availability information and a session-scoped URL when available. Recompute this information for local and archived reports at request time. Cloud-only reports remain readable but cannot obtain unbound local footage.

The browser uses numeric source offsets from `observed_segments`. It plays one observed segment at a time, stops at its end, and does not rerun inference. No video is embedded in exports or uploaded to Supabase. Unsupported codecs are surfaced without automatic transcoding.

## Compatibility

Use additive SQLite migration only, no Supabase schema change or new dependency. Store v3 report thresholds in the existing policy/report JSON. Existing endpoints remain compatible. Authorization and owner isolation apply independently to each media request.
