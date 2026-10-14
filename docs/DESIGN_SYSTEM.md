# ClassMood AI Design System

## Existing Conventions

Use the dashboard's existing typography, blue selected controls, white/gray operational surfaces, green report actions, and established spacing. Preserve native buttons, forms, tables, focus rings, and responsive overflow. Do not introduce marketing layouts or a new component library.

## Reports

Keep ID portraits at 80 by 80 pixels with fixed placeholders and existing image dialogs. ID summaries retain portraits, observed time, qualified time, and attention even if no behavior passes the policy. Hide behavior columns only if all displayed IDs have zero counts; individual zero cells use a dash. Exported spreadsheets retain full columns and numeric zeros.

Separate selected summary interval, state-confirmation time, and report-qualification minimum in methodology. A position-based ID must not be described as a verified identity. A sleeping pose must not be presented as confirmed eyelid closure.

Use the non-definitive Thai sleeping-posture label consistently in live results, reports, evidence dialogs, methodology, and exports, including when displaying older archived labels. Retain the `sleeping` data key and historical numeric results unchanged.

## Video Evidence Dialog

Use the existing native `<dialog>` conventions: labelled title, accessible close icon, Escape support, focus restoration, and existing reduced-motion handling. Present an un-cropped full-frame player, an ID reference portrait, behavior label, and an observed-segment selector. Use a labelled replay command. Stop and unload media on close or leaving the report; do not autoplay on opening.

Bound playback to the selected observed segment. Show gaps as gaps, not continuous detection. Show loading/error/unavailable messages without replacing valid report data. Stack controls on mobile; constrain the player and portrait to prevent horizontal page overflow. Evidence playback controls are not part of PDF/CSV/Excel output.

The evidence table includes raw events that do not qualify for report metrics. Label counted and excluded events explicitly; inspecting an excluded event must not promote it into the report totals. When the browser reports a shorter duration than the observed segment end, play its available portion and state that its end is clamped to the media duration.
