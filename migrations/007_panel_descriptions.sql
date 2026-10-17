-- Update descriptions already stored in the admin settings.
WITH replacements(key, value) AS (
VALUES
    ('application_text', '"Перед подачей заявки внимательно и подробно ответьте на все вопросы.\nЗаявки, заполненные с ошибками или не соответствующие правилам семьи, будут отклонены.\n\nПосле отправки заявки дождитесь её рассмотрения — Бот свяжется с вами в личных сообщениях, уведомит о результате и при положительном решении направит в приёмную."'::jsonb),
    ('promotion_text', '"**Отчёт на Повышение**\n\nПеред подачей отчёта, внимательно проверьте:\n\n1. Все ссылки должны быть рабочими и актуальными.\n2. Все условия для повышения должны быть выполнены полностью.\n\n**Несоблюдение этих пунктов может привести к отклонению отчёта.**"'::jsonb),
    ('vacation_text', '"**📋 Оформление отпуска**\n\nОформите отпуск, если планируете отсутствовать более 3 дней. После выбора даты вам будет выдана соответствующая роль. По возвращении нажмите ''Вернулся/лась'', чтобы снять роль. Пожалуйста, не пользуйтесь без необходимости."'::jsonb)
), changed AS (
    SELECT s.guild_id, s.key, s.value AS old_value, r.value AS new_value
    FROM public.admin_settings s JOIN replacements r USING (key)
    WHERE s.value IS DISTINCT FROM r.value
), audited AS (
    INSERT INTO public.settings_history(guild_id,key,old_value,new_value,actor_id)
    SELECT guild_id,key,old_value,new_value,0 FROM changed
)
UPDATE public.admin_settings s SET value=c.new_value, updated_at=now()
FROM changed c WHERE s.guild_id=c.guild_id AND s.key=c.key;
