-- Preserve prior migration checksums; update server names in saved settings once.
WITH changed AS (
    SELECT guild_id, key, value AS old_value,
           regexp_replace(value::text, 'Denver|Seattle', 'Orlando', 'gi')::jsonb AS new_value
    FROM public.admin_settings
    WHERE value::text ~* 'Denver|Seattle'
), audited AS (
    INSERT INTO public.settings_history(guild_id,key,old_value,new_value,actor_id)
    SELECT guild_id,key,old_value,new_value,0 FROM changed
)
UPDATE public.admin_settings s SET value=c.new_value, updated_at=now()
FROM changed c WHERE s.guild_id=c.guild_id AND s.key=c.key;
