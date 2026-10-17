-- Replace obsolete custom emojis in saved descriptions without resetting user edits.
WITH changed AS (
    SELECT guild_id, key, value AS old_value,
           regexp_replace(
               regexp_replace(
                   regexp_replace(value::text, '<a?:(justice|serenity):[0-9]+>', '<:Justice:1560611219105120257>', 'gi'),
                   '<a?:loading:[0-9]+>', '<a:loading:1498065004677566524>', 'gi'),
               '<a?:(cloud|purpleclouds):[0-9]+>', '<a:purpleclouds:1498065043521278014>', 'gi')::jsonb AS new_value
    FROM public.admin_settings
), audited AS (
    INSERT INTO public.settings_history(guild_id,key,old_value,new_value,actor_id)
    SELECT guild_id,key,old_value,new_value,0 FROM changed WHERE old_value IS DISTINCT FROM new_value
)
UPDATE public.admin_settings s SET value=c.new_value, updated_at=now()
FROM changed c WHERE s.guild_id=c.guild_id AND s.key=c.key
AND c.old_value IS DISTINCT FROM c.new_value;

UPDATE public.admin_settings SET value=to_jsonb('<:Justice:1560611219105120257> '::text || 'Добро пожаловать в Justice!'), updated_at=now()
WHERE key='welcome_title' AND value=to_jsonb('👋 Добро пожаловать в Justice!'::text);

INSERT INTO public.admin_settings(guild_id,key,value)
SELECT DISTINCT guild_id,'bonus_review_channel_id','1495255518502060183'::jsonb
FROM public.admin_settings
ON CONFLICT(guild_id,key) DO UPDATE SET value=excluded.value,updated_at=now();
