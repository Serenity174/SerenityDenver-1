from dataclasses import fields

from justice.services.settings import specs
from justice.ui.panel_texts import APPLICATION_TEXT, PROMOTION_TEXT, VACATION_TEXT


def defaults(settings):
    from justice.cogs.news import IMAGE_URLS, REMINDER_TEXT
    from justice.cogs.payouts import IMAGE_POOL
    from justice.cogs.welcome import Welcome
    from justice.services.reporting import ITEM_PRICES

    catalog = specs()
    values = {
        field.name: getattr(settings, field.name)
        for field in fields(settings)
        if field.name in catalog
    }
    values = {
        key: list(value) if isinstance(value, tuple) else value for key, value in values.items()
    }
    values.update(
        {
            "prices": {key: str(value) for key, value in ITEM_PRICES.items()},
            "contract_slots": 5,
            "attendance_reward": "40000",
            "payout_comment": "Недельная премия",
            "payout_time": "23:30",
            "timezone": "Europe/Moscow",
            "reminder_minutes": 10,
            "reminder_text": REMINDER_TEXT,
            "welcome_title": "👋 Добро пожаловать в Justice!",
            "welcome_text": (
                f"Для подачи заявки переходите в канал <#{settings.submit_channel_id}>.\n"
                "Для получения роли Family Friends/Best Friend обратитесь к старшему составу.\n"
                f"Бонусы за промокод — в канале <#{settings.bonus_channel_id}>.\n"
                "Ждём твою заявку!"
            ),
            "welcome_images": "\n".join(Welcome(None).images),
            "news_images": "\n".join(IMAGE_URLS),
            "payout_images": "\n".join(IMAGE_POOL),
            "report_image": "https://i.imgur.com/UxkSA3E.png",
            "bonus_title": "Как получить бонусы за промокод?",
            "bonus_text": "Введите /promo E-73118 в игре. Сделайте скриншот подтверждения и отправьте его кнопкой ниже. Ожидайте рассмотрения заявки.",
            "birthday_text": "Сегодня {user} празднует день рождения! Желаем счастья, здоровья и радости!",
            "application_title": "Заявка на вступление в семью Justice",
            "application_text": APPLICATION_TEXT,
            "application_image": "https://i.imgur.com/vxDAmbs.png",
            "promotion_title": "Подача отчёта на повышение",
            "promotion_text": PROMOTION_TEXT,
            "vacation_title": "Оформление отпуска",
            "vacation_text": VACATION_TEXT,
            "birthday_title": "Укажите дату рождения! 🎂",
            "report_title": "Отчёт по складу",
            "report_text": "Выберите категорию и приложите доказательство.",
        }
    )
    values["welcome_text"] = (
        f"Для подачи заявки в нашу семью переходите в канал <#{settings.submit_channel_id}>.\nДля получения роли **Family Friends/Best Friend** обращайтесь к старшему составу семьи предварительно изменив ник по форме.\n`Пример: Friend Milo | Имя Static`\n\nВ канале <#{settings.bonus_channel_id}> Вы сможете получить приятный бонус за введённый промокод `/promo E-73118`.\nВ разделе Guides собраны разного рода памятки, гайды и ссылки на полезные ресурсы.\n**Ждём именно твою заявку!**"
    )
    support_role_id = settings.support_role_id
    values["bonus_text"] = (
        f"```1. Введите команду /promo E-73118 в игровой чат.\n2. Сделайте полный скриншот с подтверждением ввода команды.\n3. Отправьте скриншот в качестве доказательства активации.\n4. Ожидайте уведомление о начислении бонуса.```\n<@&{support_role_id}> — выдаётся всем, кто использует промокод и поддерживает нашу семью на сервере Orlando.\nТакже данная роль присваивается всем, кто оказал помощь семье. Это может быть финансовая помощь в развитии семьи, организация и участие в мероприятиях, предоставление ресурсов или любая иная значимая помощь, направленная на укрепление и развитие нашей семьи. Список не является исчерпывающим."
    )
    values["reminder_text"] = values["reminder_text"].replace("10 минут", "{minutes} минут")
    values.update({key: True for key in catalog if key.startswith("enabled:")})
    return values
