CREATE TABLE IF NOT EXISTS public.bot_state (
    guild_id BIGINT NOT NULL, namespace TEXT NOT NULL, key TEXT NOT NULL,
    value JSONB NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (guild_id, namespace, key)
);
CREATE TABLE IF NOT EXISTS public.birthdays (
    guild_id BIGINT NOT NULL, user_id BIGINT NOT NULL,
    day INT NOT NULL CHECK(day BETWEEN 1 AND 31),
    month INT NOT NULL CHECK(month BETWEEN 1 AND 12),
    wish TEXT NOT NULL DEFAULT '', updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (guild_id, user_id)
);
CREATE TABLE IF NOT EXISTS public.requests (
    id BIGSERIAL PRIMARY KEY, guild_id BIGINT NOT NULL, user_id BIGINT NOT NULL,
    kind TEXT NOT NULL, interaction_id BIGINT UNIQUE, channel_id BIGINT,
    message_id BIGINT UNIQUE, payload JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','accepted','rejected','returned')),
    handled_by BIGINT, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS requests_one_pending
    ON public.requests(guild_id,user_id,kind) WHERE status='pending';
CREATE TABLE IF NOT EXISTS public.jobs (
    id BIGSERIAL PRIMARY KEY, kind TEXT NOT NULL, dedupe_key TEXT NOT NULL,
    payload JSONB NOT NULL, due_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL, lease_until TIMESTAMPTZ,
    attempts INT NOT NULL DEFAULT 0, completed_at TIMESTAMPTZ,
    last_error TEXT, UNIQUE(kind,dedupe_key)
);
CREATE INDEX IF NOT EXISTS jobs_due ON public.jobs(due_at) WHERE completed_at IS NULL;
CREATE TABLE IF NOT EXISTS public.invite_events (
    id BIGSERIAL PRIMARY KEY, guild_id BIGINT NOT NULL, user_id BIGINT NOT NULL,
    inviter_id BIGINT, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS public.payout_runs (
    guild_id BIGINT NOT NULL, week_start DATE NOT NULL,
    payload JSONB NOT NULL, embed_message_id BIGINT, file_message_id BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), completed_at TIMESTAMPTZ,
    PRIMARY KEY(guild_id, week_start)
);
ALTER TABLE public.reports ADD COLUMN IF NOT EXISTS interaction_id BIGINT;
CREATE UNIQUE INDEX IF NOT EXISTS reports_interaction_id ON public.reports(interaction_id);
CREATE INDEX IF NOT EXISTS reports_created_user ON public.reports(created_at, user_id);
CREATE INDEX IF NOT EXISTS attendance_created_user ON public.attendance_events(created_at, user_id);
ALTER TABLE public.give ADD COLUMN IF NOT EXISTS winner_ids BIGINT[];
