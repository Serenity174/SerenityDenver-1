
CREATE TABLE IF NOT EXISTS public.give (
    id           INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    guild_id     BIGINT       NOT NULL,
    channel_id   BIGINT       NOT NULL,
    "name"       VARCHAR      NOT NULL,
    user_ids     VARCHAR      NULL,
    end_date     TIMESTAMPTZ  NOT NULL,
    finished     BOOLEAN      NOT NULL DEFAULT FALSE,
    messege_id   VARCHAR      NOT NULL,
    host_id      VARCHAR      NOT NULL,
    winner_count INT          NOT NULL
);


ALTER TABLE public.give
    ADD COLUMN IF NOT EXISTS guild_id     BIGINT;
ALTER TABLE public.give
    ADD COLUMN IF NOT EXISTS channel_id   BIGINT;
ALTER TABLE public.give
    ADD COLUMN IF NOT EXISTS "name"       VARCHAR;
ALTER TABLE public.give
    ADD COLUMN IF NOT EXISTS user_ids     VARCHAR;
ALTER TABLE public.give
    ADD COLUMN IF NOT EXISTS end_date     TIMESTAMPTZ;
ALTER TABLE public.give
    ADD COLUMN IF NOT EXISTS finished     BOOLEAN;
ALTER TABLE public.give
    ADD COLUMN IF NOT EXISTS messege_id   VARCHAR;
ALTER TABLE public.give
    ADD COLUMN IF NOT EXISTS host_id      VARCHAR;
ALTER TABLE public.give
    ADD COLUMN IF NOT EXISTS winner_count INT;


CREATE TABLE IF NOT EXISTS public.guild_settings (
    guild_id  BIGINT PRIMARY KEY,
    color_hex VARCHAR(6) NOT NULL DEFAULT '5865F2',
    emoji     VARCHAR(64) NOT NULL DEFAULT '🎉'
);


ALTER TABLE public.guild_settings
    ADD COLUMN IF NOT EXISTS color_hex VARCHAR(6) NOT NULL DEFAULT '5865F2';
ALTER TABLE public.guild_settings
    ADD COLUMN IF NOT EXISTS emoji     VARCHAR(64) NOT NULL DEFAULT '🎉';


CREATE TABLE IF NOT EXISTS public.reports (
    id         INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    nickname   VARCHAR     NOT NULL,
    static_id  BIGINT      NOT NULL,
    category   VARCHAR     NOT NULL,
    quantity   INT         NOT NULL,
    total      NUMERIC(12,2) NOT NULL,
    proof      TEXT        NOT NULL,
    user_id    BIGINT      NOT NULL,
    username   VARCHAR     NOT NULL
);


        CREATE TABLE IF NOT EXISTS public.contract_users (
            discord_id BIGINT PRIMARY KEY,
            rank INT NOT NULL,
            weekly_attendance INT NOT NULL DEFAULT 0,
            total_attendance INT NOT NULL DEFAULT 0,
            last_attended_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE TABLE IF NOT EXISTS public.contracts (
            id BIGSERIAL PRIMARY KEY,
            message_id BIGINT UNIQUE,
            channel_id BIGINT NOT NULL,
            host_id BIGINT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            closed BOOLEAN NOT NULL DEFAULT FALSE,
            attendance_marked BOOLEAN NOT NULL DEFAULT FALSE
        );

        CREATE TABLE IF NOT EXISTS public.contract_signups (
            contract_id BIGINT REFERENCES public.contracts(id) ON DELETE CASCADE,
            user_id BIGINT REFERENCES public.contract_users(discord_id) ON DELETE CASCADE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (contract_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS public.attendance_events (
            id BIGSERIAL PRIMARY KEY,
            contract_id BIGINT REFERENCES public.contracts(id) ON DELETE CASCADE,
            user_id BIGINT REFERENCES public.contract_users(discord_id) ON DELETE CASCADE,
            marked_by BIGINT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE TABLE IF NOT EXISTS public.contract_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        

                    CREATE TABLE IF NOT EXISTS public.cars (
                        id BIGSERIAL PRIMARY KEY,
                        guild_id BIGINT NOT NULL,
                        category TEXT NOT NULL CHECK(category IN ('family', 'cargo')),
                        title TEXT NOT NULL,
                        max_speed_kmh INT NOT NULL,
                        accel_0_100 DOUBLE PRECISION NOT NULL,
                        trunk_kg INT NOT NULL,
                        payload_tons_text TEXT,
                        url TEXT NOT NULL,
                        image_url TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        UNIQUE(guild_id, category, title)
                    );

                    CREATE TABLE IF NOT EXISTS public.car_catalog_settings (
                        guild_id BIGINT PRIMARY KEY,
                        channel_id BIGINT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS public.car_catalog_messages (
                        guild_id BIGINT NOT NULL,
                        category TEXT NOT NULL CHECK(category IN ('family', 'cargo')),
                        page_index INT NOT NULL,
                        channel_id BIGINT NOT NULL,
                        message_id BIGINT NOT NULL,
                        PRIMARY KEY(guild_id, category, page_index)
                    );
                    

        CREATE TABLE IF NOT EXISTS public.attendance_weekly_snapshots (
            week_start DATE NOT NULL,
            user_id BIGINT NOT NULL,
            count INT NOT NULL DEFAULT 0,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (week_start, user_id)
        );
        CREATE TABLE IF NOT EXISTS public.attendance_stats_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        

        CREATE TABLE IF NOT EXISTS public.payout_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        