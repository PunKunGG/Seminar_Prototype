begin;

grant select, insert, update on
    public.rooms,
    public.courses,
    public.class_sessions,
    public.analysis_jobs,
    public.session_tracks,
    public.behavior_events,
    public.track_time_buckets,
    public.evidence_images
to service_role;

grant usage, select on sequence
    public.rooms_id_seq,
    public.courses_id_seq
to service_role;

commit;
