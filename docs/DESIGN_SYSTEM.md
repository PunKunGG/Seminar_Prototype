# ClassMood AI Design System

## Existing Conventions

Use the dashboard's existing typography, blue selected controls, white/gray operational surfaces, green report actions, and established spacing. Preserve native buttons, forms, tables, focus rings, and responsive overflow. Do not introduce marketing layouts or a new component library.

## Reports

Keep ID portraits at 80 by 80 pixels with fixed placeholders and existing image dialogs. ID summaries retain portraits, observed time, qualified time, and attention even if no behavior passes the policy. Hide behavior columns only if all displayed IDs have zero counts; individual zero cells use a dash. Exported spreadsheets retain full columns and numeric zeros.

Preserve the thumbnail's aspect ratio with actual fitted image dimensions inside the 80px frame, not only `object-fit`, so the PDF rasterizer also avoids stretching. The image dialog reserves space for its title and close control, then contains the full original image within the remaining viewport height, including on mobile. Do not crop or stretch the expanded image. When an older thumbnail is dominated by the uniform generated padding (over 75% of its area, with padding on all four edges), show its preserved original instead. Do not recrop or overwrite historical evidence files.

Separate selected summary interval, state-confirmation time, and report-qualification minimum in methodology. A position-based ID must not be described as a verified identity. A sleeping pose must not be presented as confirmed eyelid closure.

Use the non-definitive Thai sleeping-posture label consistently in live results, reports, evidence dialogs, methodology, and exports, including when displaying older archived labels. Retain the `sleeping` data key and historical numeric results unchanged.

## Video Evidence Dialog

Use the existing native `<dialog>` conventions: labelled title, accessible close icon, Escape support, focus restoration, and existing reduced-motion handling. Present an un-cropped full-frame player, an ID reference portrait, behavior label, and an observed-segment selector. Use a labelled replay command. Stop and unload media on close or leaving the report; do not autoplay on opening.

Align the replay button and segment selector at their bottom edge, both 42px high on desktop. Mobile controls stack with a full-width replay button.

The observed-range label always shows the saved segment, even when browser media duration limits playback; only the separate playback range and its warning reflect that limit.

Default playback to the selected observed segment. Provide a keyboard-accessible segmented radio control for observed-only or three-second context playback. Show observed and playback ranges separately, label before/after context while playing, and state that context adds no report time. Clamp both modes to finite media duration. Changing mode or segment pauses and seeks to its playback start; opening always resets to observed-only without autoplay. Show gaps as gaps, not continuous detection. Stack controls on mobile and prevent horizontal page overflow. Evidence playback controls are not part of PDF/CSV/Excel output.

The evidence table defaults to server-qualified events. A labelled checkbox includes excluded raw events; ID and behavior selectors filter either view. Paginate 25 rows with a result count, disabled boundary arrows, and an accessible page indicator. Reset to page one when filtering and restore defaults when opening a report. Keep controls visible for empty results. Positive subsecond observed time reads as less than one second, not zero. Label counted and excluded events explicitly; inspecting an excluded event must not promote it into report totals. Legacy reports without qualification use their original event list. When the browser reports a shorter duration, play the available portion and state that its end is clamped.

## Analysis Jobs and Navigation

Use a restrained full-width job-status band only on the rounds/history screen, with separate rows for discovered jobs, return-to-analysis and explicit stop actions. Hide it immediately in analysis and report views, whose existing controls remain available. This is display-only: job polling and completion tracking continue across all views. Completed/partial/interrupted jobs retain their history-screen report action without navigating away from another report. Show only progress supplied by the server. The current webcam's running state remains visible in its analysis controls.

Remove a completed/partial job notice after its final report loads successfully, while retaining the history-table report link. A failed report load keeps the notice available. Starting another round must not dismiss unread terminal notices. An errored source keeps its stop-and-save action in history and analysis until cleanup is verified; do not replace it with only a report action. Live behavior popups belong only to the current running analysis and disappear when leaving it. Bound the visible toast stack to three items, suppress identical visible duplicates, and retain the existing automatic dismissal time.

Webcam departure and explicit video stop use a labelled native dialog. Focus Stay initially; Escape/Stay cancel without DELETE and restore the opener. Disable repeat confirmation and dismissal during saving. Keep failures in the dialog and do not navigate until terminal saving is verified. New-round creation is visibly disabled while jobs or source operations are active, or discovery is unavailable.

After a failed stop/save verification, retain a pending-verification status and a retry action in the history band and analysis controls. Escape/Stay dismisses only the dialog, not the pending lock. Leaving that analysis asks again, for video as well as webcam, until terminal saving is verified; ordinary running-video navigation is unchanged.

For a bound video, show the clip name and recording start as read-only labelled details in place of the upload form. Restore these details on return or refresh, using the browser's local time for the saved timestamp. Stack details on mobile and allow long filenames to wrap. Source setup remains editable only for an unbound round; restoring the selected mode must not show the warning reserved for an actual source change.
