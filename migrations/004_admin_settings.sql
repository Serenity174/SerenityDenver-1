CREATE TABLE IF NOT EXISTS public.admin_settings (
    guild_id BIGINT NOT NULL, key TEXT NOT NULL, value JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(guild_id, key)
);
CREATE TABLE IF NOT EXISTS public.settings_history (
    id BIGSERIAL PRIMARY KEY, guild_id BIGINT NOT NULL, key TEXT NOT NULL,
    old_value JSONB NOT NULL, new_value JSONB NOT NULL, actor_id BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS settings_history_guild ON public.settings_history(guild_id, id DESC);
