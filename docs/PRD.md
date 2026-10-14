# ClassMood AI Product Requirements

This document records the existing prototype and the report/evidence changes approved on 2026-10-14. It does not authorize additional product scope.

## Users and Purpose

Teachers create analysis rounds for a course and room, analyze an uploaded video or a server-connected webcam, and review anonymous behavior estimates, reports, and evidence. Reviewers can compare estimated behavior with source footage. These estimates do not establish learning, comprehension, identity, or actual sleep.

## Current Scope

- Login uses Supabase Auth. Completed reports and images can be archived privately in Supabase. SQLite retains local round and tracking data.
- Detection uses person pose and phone/screen object context. No face recognition, eyelid analysis, or audio analysis is used.
- IDs apply inside one round and are anchored to positions. They do not establish the same person's identity after a seat swap. A fixed camera is required.
- Users choose a 15-300 second summary interval; the default is 30 seconds. This is separate from per-behavior state confirmation and report qualification.
- Report periods are five minutes. Evidence and raw observations remain available independently of report qualification.

## Approved Report Changes

- Label ID summaries as per-person summaries, retaining the position-based identity limitation.
- New report policy: sleeping requires 120 seconds of observed behavior; other behaviors require 30 seconds. Exclude shorter runs before calculating counts, durations, rates, or splitting periods. Do not reinterpret excluded time as attentive.
- Preserve legacy policies and historical results. The live sleeping posture still has an eight-second state-confirmation threshold and is described as a suspected sleeping posture.
- Hide all-zero behavior columns in web/PDF ID summaries; use a dash for individual zero cells. Preserve complete numeric data in JSON, CSV, and Excel.
- Local video rounds can play original full-frame evidence with an ID reference image. Playback is bounded to actual observed segments, not unsampled gaps.
- Missing, changed, unbound, cloud-only, webcam, or unsupported video sources have explicit unavailable states. Do not guess old source bindings.
- Do not archive source videos, transcode footage, add models, or record webcams in this increment.

## Demo Preparation

Provide a recording guide and ground-truth table template. Real clips will be supplied later by the project owner. Synthetic tests do not substitute for real validation footage. Never commit runtime clips or infer ground truth from the AI's own predictions.
