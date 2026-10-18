-- Reviewers keep their permissions; successful applicants receive only family/member roles.
WITH changed AS (
    SELECT guild_id, key, value AS old_value,
           '[1495255224158519409,1495255217825124442]'::jsonb AS new_value
    FROM public.admin_settings
    WHERE key='application_role_ids'
      AND value IS DISTINCT FROM '[1495255224158519409,1495255217825124442]'::jsonb
), audited AS (
    INSERT INTO public.settings_history(guild_id,key,old_value,new_value,actor_id)
    SELECT guild_id,key,old_value,new_value,0 FROM changed
)
UPDATE public.admin_settings s SET value=c.new_value,updated_at=now()
FROM changed c WHERE s.guild_id=c.guild_id AND s.key=c.key;
