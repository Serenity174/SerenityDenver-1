-- Apply the requested Justice branding and artwork to settings already stored in PostgreSQL.
-- Runs once; later changes made through the admin menu remain editable.
WITH replacements(key, value) AS (
VALUES
    ('welcome_title', '"👋 Добро пожаловать в Justice!"'::jsonb),
    ('welcome_text', '"Для подачи заявки в нашу семью переходите в канал <#1495255487061426286>.\nДля получения роли **Family Friends/Best Friend** обращайтесь к старшему составу семьи предварительно изменив ник по форме.\n`Пример: Friend Milo | Имя Static`\n\nВ канале <#1495255508368490506> Вы сможете получить приятный бонус за введённый промокод `/promo E-73118`.\nВ разделе Guides собраны разного рода памятки, гайды и ссылки на полезные ресурсы.\n**Ждём именно твою заявку!**"'::jsonb),
    ('welcome_images', '"https://i.imgur.com/g5tNLY5.png\nhttps://i.imgur.com/pxIJf8W.png\nhttps://i.imgur.com/SsVtjXc.png\nhttps://i.imgur.com/J6Pd5ui.png\nhttps://i.imgur.com/5bXFrmr.png\nhttps://i.imgur.com/Giv1rhA.png\nhttps://i.imgur.com/2IEzQ8a.png\nhttps://i.imgur.com/4XLAYiu.png\nhttps://i.imgur.com/aJNnYUf.png\nhttps://i.imgur.com/zhesQKA.png\nhttps://i.imgur.com/nV1NP8W.png\nhttps://i.imgur.com/flLjtEL.png\nhttps://i.imgur.com/DqWjGkM.png\nhttps://i.imgur.com/od2Xpug.png\nhttps://i.imgur.com/n060Rxl.png\nhttps://i.imgur.com/Dyzd6Pf.png\nhttps://i.imgur.com/SZD7qiu.png\nhttps://i.imgur.com/ZvRXpHl.png\nhttps://i.imgur.com/hA3gAE8.png\nhttps://i.imgur.com/vsMl5CC.png\nhttps://i.imgur.com/6JmIt5a.png\nhttps://i.imgur.com/2zBwZvG.png\nhttps://i.imgur.com/5DssVBV.png"'::jsonb),
    ('news_images', '"https://i.imgur.com/pXkrhvF.png\nhttps://i.imgur.com/iyemRDR.png\nhttps://i.imgur.com/cvtVraa.png\nhttps://i.imgur.com/hAmsK59.png\nhttps://i.imgur.com/gnKKAv8.png\nhttps://i.imgur.com/AibZSaY.png\nhttps://i.imgur.com/bqGVF2q.png\nhttps://i.imgur.com/g8LTjn8.png\nhttps://i.imgur.com/OUUKW9J.png\nhttps://i.imgur.com/YveFtxx.png\nhttps://i.imgur.com/qwMPQGZ.png\nhttps://i.imgur.com/69tq1gV.png\nhttps://i.imgur.com/tu2IQt0.png\nhttps://i.imgur.com/G0XQKEr.png\nhttps://i.imgur.com/GJJnhgw.png"'::jsonb),
    ('payout_images', '"https://i.imgur.com/JfcwP2J.png\nhttps://i.imgur.com/SulY8pj.png\nhttps://i.imgur.com/e67sspv.png\nhttps://i.imgur.com/tsl6Bw7.png\nhttps://i.imgur.com/dOxEMXk.png\nhttps://i.imgur.com/TTINh1B.png\nhttps://i.imgur.com/7VMNDku.png\nhttps://i.imgur.com/DCXYbLb.png\nhttps://i.imgur.com/pYweYQU.png\nhttps://i.imgur.com/eMoM4UD.png\nhttps://i.imgur.com/f6PuqVV.png"'::jsonb),
    ('report_image', '"https://i.imgur.com/UxkSA3E.png"'::jsonb),
    ('application_image', '"https://i.imgur.com/vxDAmbs.png"'::jsonb),
    ('application_title', '"Заявка на вступление в семью Justice"'::jsonb),
    ('bonus_text', '"```1. Введите команду /promo E-73118 в игровой чат.\n2. Сделайте полный скриншот с подтверждением ввода команды.\n3. Отправьте скриншот в качестве доказательства активации.\n4. Ожидайте уведомление о начислении бонуса.```\n<@&1495255277744951296> — выдаётся всем, кто использует промокод и поддерживает нашу семью на сервере Denver.\nТакже данная роль присваивается всем, кто оказал помощь семье. Это может быть финансовая помощь в развитии семьи, организация и участие в мероприятиях, предоставление ресурсов или любая иная значимая помощь, направленная на укрепление и развитие нашей семьи. Список не является исчерпывающим."'::jsonb),
    ('support_role_id', '1495255277744951296'::jsonb)
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

DELETE FROM public.admin_settings WHERE key='bonus_image';
