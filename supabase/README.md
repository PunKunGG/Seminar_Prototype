# Supabase setup

The cloud database schema is stored in `migrations/` so it can be reviewed
and recreated without relying on the Supabase dashboard history.

## Initial schema

`migrations/202608030001_initial_schema.sql` creates:

- rooms, courses, and class sessions
- asynchronous analysis jobs
- anonymous person tracks and behavior events
- time-bucket summaries and evidence metadata
- private `class-videos` and `class-evidence` Storage buckets
- Row Level Security policies scoped to the authenticated owner

The migration has been applied to the ClassMood AI Supabase project.

Public user signups are disabled in `Authentication > Sign In / Providers`.
Teacher accounts must be created or invited by a project administrator.

`migrations/202608030002_harden_rls_auto_enable.sql` removes direct execution
access to Supabase's automatic-RLS trigger function from API users. The event
trigger continues to enable RLS for new tables, but clients cannot invoke its
`SECURITY DEFINER` function themselves.

## Applying to another project

Run the migration once with the Supabase SQL Editor, or use the Supabase CLI
after linking the local repository to the target project. Do not rerun an
already-applied initial migration; create a new migration for later changes.

## Secrets

Never commit any of these values:

- database password
- service-role key
- direct database connection string
- access or refresh tokens

The project URL and publishable/anonymous key may be used by the browser once
authentication is integrated. The service-role key must only be available to
the Python worker or another trusted backend process.
