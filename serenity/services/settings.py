"""Validated, live settings. Database commit always precedes changing runtime values."""

import asyncio
from dataclasses import dataclass, fields
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from serenity.config import get_settings
from serenity.repositories.settings import SettingsRepository
from serenity.services.reporting import ITEM_PRICES


@dataclass(frozen=True)
class SettingSpec:
    label: str
    group: str
    kind: str = "text"
    minimum: int = 0
    maximum: int = 4000


LABELS = {
    "high_staff": "Старший состав",
    "staff": "Рассмотрение заявок",
    "application": "Вступление",
    "rank": "Ранги",
    "family": "Семья",
    "verified": "Подтверждённые участники",
    "vacation": "Отпуск",
    "support": "Поддержка",
    "submit": "Подача заявок",
    "accept": "Принятые заявки",
    "bonus": "Бонусы",
    "news": "Сборы",
    "bronya": "Запись участников",
    "birthday": "Дни рождения",
    "promotion": "Повышения",
    "report_output": "Отчёты: публикация",
    "report_interface": "Отчёты: панель",
    "contract": "Контракты",
    "attendance_log": "Журнал явок",
    "payout": "Выплаты: результаты",
    "payout_file": "Выплаты: файл",
    "welcome": "Приветствие",
    "car_catalog": "Каталог машин",
    "temp_voice_trigger": "Создание голосовой комнаты",
    "temp_voice_category": "Категория голосовых комнат",
    "temp_voice_allowed": "Доступ к голосовым комнатам",
}


def specs():
    result = {}
    for field in fields(get_settings()):
        key = field.name
        if key.endswith("_channel_id"):
            result[key] = SettingSpec(LABELS.get(key[:-11], key), "Каналы", "channel")
        elif key.endswith("_category_id"):
            result[key] = SettingSpec(LABELS.get(key[:-12], key), "Каналы", "category")
        elif key.endswith("_role_id") or key.endswith("_role_ids"):
            multiple = key.endswith("_role_ids")
            result[key] = SettingSpec(
                LABELS.get(key[:-9] if multiple else key[:-8], key),
                "Роли",
                "ranks" if key == "rank_role_ids" else "roles" if multiple else "role",
            )
    result.update(
        {
            "prices": SettingSpec("Категории и цены", "Отчёты", "prices"),
            "contract_slots": SettingSpec(
                "Мест в контракте, включая ведущего", "Контракты", "int", 1, 25
            ),
            "attendance_reward": SettingSpec("Премия за одну явку", "Выплаты", "money"),
            "payout_comment": SettingSpec("Комментарий в файле выплат", "Выплаты", maximum=100),
            "payout_time": SettingSpec("Время выплаты в воскресенье", "Выплаты", "time"),
            "timezone": SettingSpec("Часовой пояс", "Напоминания", "timezone"),
            "reminder_minutes": SettingSpec("Минут до сбора", "Напоминания", "int", 1, 1440),
            "reminder_text": SettingSpec("Текст напоминания", "Сообщения", maximum=1900),
            "welcome_title": SettingSpec("Заголовок приветствия", "Сообщения", maximum=256),
            "welcome_text": SettingSpec("Приветствие", "Сообщения"),
            "welcome_images": SettingSpec(
                "Картинки приветствия", "Изображения", "urls", maximum=20000
            ),
            "news_images": SettingSpec("Картинки сборов", "Изображения", "urls", maximum=20000),
            "payout_images": SettingSpec("Картинки выплат", "Изображения", "urls", maximum=20000),
            "report_image": SettingSpec("Картинка панели отчётов", "Изображения", "url"),
            "bonus_title": SettingSpec("Заголовок бонусной панели", "Сообщения", maximum=256),
            "bonus_text": SettingSpec("Инструкция по бонусам", "Сообщения"),
            "bonus_image": SettingSpec("Картинка бонусной панели", "Изображения", "url"),
            "application_title": SettingSpec(
                "Заголовок заявки на вступление", "Сообщения", maximum=256
            ),
            "application_text": SettingSpec("Инструкция по вступлению", "Сообщения"),
            "application_image": SettingSpec("Картинка заявки на вступление", "Изображения", "url"),
            "promotion_title": SettingSpec("Заголовок панели повышения", "Сообщения", maximum=256),
            "promotion_text": SettingSpec("Инструкция по повышению", "Сообщения"),
            "vacation_title": SettingSpec("Заголовок панели отпуска", "Сообщения", maximum=256),
            "vacation_text": SettingSpec("Инструкция по отпуску", "Сообщения"),
            "birthday_title": SettingSpec(
                "Заголовок панели дней рождения", "Сообщения", maximum=256
            ),
            "report_title": SettingSpec("Заголовок панели отчётов", "Сообщения", maximum=256),
            "report_text": SettingSpec("Инструкция по отчётам", "Сообщения"),
            "birthday_text": SettingSpec(
                "Поздравление: {user} — участник", "Сообщения", maximum=1900
            ),
            "temp_voice_default_name": SettingSpec(
                "Название комнаты: {user} — имя", "Голосовые комнаты", maximum=100
            ),
            "temp_voice_default_limit": SettingSpec(
                "Лимит комнаты: 0 — без лимита", "Голосовые комнаты", "int", 0, 99
            ),
        }
    )
    for key, label in {
        "reports": "Приём отчётов",
        "contracts": "Контракты",
        "applications": "Заявки",
        "promotion": "Повышения",
        "bonus": "Бонусы",
        "birthday": "Дни рождения",
        "Otpysk": "Отпуска",
        "bronya": "Запись участников",
        "news": "Сборы",
        "welcome": "Приветствия",
        "temp_voice": "Голосовые комнаты",
        "giveaways": "Розыгрыши",
        "cars": "Машины",
        "payouts": "Автоматические выплаты",
    }.items():
        result[f"enabled:{key}"] = SettingSpec(label, "Возможности", "bool")
    return result


def validate(spec, value):
    if spec.kind == "bool":
        if type(value) is not bool:
            raise ValueError("Выберите включение или отключение.")
        return value
    if spec.kind in ("role", "channel", "category", "int"):
        try:
            number = int(value)
        except (TypeError, ValueError):
            raise ValueError("Введите целое число.") from None
        lower, upper = (
            (spec.minimum, spec.maximum)
            if spec.kind == "int"
            else (0 if spec.kind == "category" else 1, 2**64 - 1)
        )
        if not lower <= number <= upper:
            raise ValueError(f"Значение должно быть от {lower} до {upper}.")
        return number
    if spec.kind in ("roles", "ranks"):
        values = list(value)
        if not values or len(values) > 25 or len(set(values)) != len(values):
            raise ValueError("Выберите от 1 до 25 разных ролей.")
        if spec.kind == "ranks" and len(values) < 2:
            raise ValueError("Выберите хотя бы два ранга.")
        if any(type(item) is not int or not 0 < item < 2**64 for item in values):
            raise ValueError("Некорректная роль.")
        return values
    if spec.kind == "prices":
        if not isinstance(value, dict) or not 1 <= len(value) <= 100:
            raise ValueError("Оставьте от 1 до 100 категорий.")
        return {
            validate(SettingSpec("", "", maximum=80), key): money(price)
            for key, price in value.items()
        }
    if spec.kind == "money":
        return money(value)
    text = str(value).strip()
    if not text or len(text) > spec.maximum:
        raise ValueError(f"Введите от 1 до {spec.maximum} символов.")
    if spec.kind in ("url", "urls"):
        urls = text.splitlines() if spec.kind == "urls" else [text]
        if len(urls) > 150:
            raise ValueError("Не более 150 изображений.")
        for url in urls:
            parsed = urlsplit(url.strip())
            if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
                raise ValueError("Укажите HTTPS-ссылку на изображение.")
        return "\n".join(url.strip() for url in urls)
    if spec.kind == "time":
        try:
            hour, minute = map(int, text.split(":"))
            if not (0 <= hour < 24 and 0 <= minute < 60):
                raise ValueError
        except ValueError:
            raise ValueError("Время должно быть в формате ЧЧ:ММ, например 23:30.") from None
        return f"{hour:02}:{minute:02}"
    if spec.kind == "timezone":
        try:
            ZoneInfo(text)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(
                "Неизвестный пояс. Например: Europe/Moscow или Asia/Yekaterinburg."
            ) from None
    return text


def money(value):
    try:
        amount = Decimal(str(value).replace(",", "."))
        if (
            not amount.is_finite()
            or not 0 <= amount <= 1_000_000_000
            or amount.as_tuple().exponent < -4
        ):
            raise ValueError
    except (InvalidOperation, ValueError):
        raise ValueError(
            "Сумма: от 0 до 1 000 000 000, не более четырёх знаков после запятой."
        ) from None
    return str(amount)


class LiveSettings:
    def __init__(self, pool, settings, defaults):
        self.repo = SettingsRepository(pool)
        self.settings = settings
        self.specs = specs()
        self.defaults = defaults
        self.values = {}
        self.lock = asyncio.Lock()

    async def load(self):
        values = await self.repo.seed(self.settings.guild_id, self.defaults)
        for key, value in values.items():
            if key in self.specs:
                self.apply(key, validate(self.specs[key], value))

    def apply(self, key, value):
        self.values[key] = value
        if key in self.settings.__dataclass_fields__:
            # Keep the shared settings identity: modules and bot reference the same object.
            current = getattr(self.settings, key)
            object.__setattr__(
                self.settings, key, tuple(value) if isinstance(current, tuple) else value
            )

    async def save(self, key, value, actor_id, expected):
        value = validate(self.specs[key], value)
        if key == "payout_comment" and any(character in value for character in (";", "\n", "\r")):
            raise ValueError("Комментарий к выплате должен быть одной строкой без точки с запятой.")
        async with self.lock:
            await self.repo.save(self.settings.guild_id, key, value, actor_id, expected)
            self.apply(key, value)


_live = None


def set_live(service):
    global _live
    _live = service


def option(key, default=None):
    return _live.values.get(key, default) if _live else default


def enabled(feature):
    return option(f"enabled:{feature}", True)


def feature_for(module):
    if not module.startswith("serenity.cogs."):
        return None
    feature = module.rsplit(".", 1)[-1]
    return (
        "reports"
        if feature == "report_db"
        else None
        if feature in ("admin", "jobs", "payouts")
        else feature
    )


async def feature_check(interaction, module):
    feature = feature_for(module)
    if feature == "Otpysk" and (interaction.data or {}).get("custom_id") == "vacation_return":
        return True
    if feature and not enabled(feature):
        from serenity.ui.base import reply

        await reply(interaction, "Эта возможность отключена администратором.")
        return False
    return True


def prices():
    return option("prices", ITEM_PRICES)


def images(key, defaults):
    value = option(key)
    return value.splitlines() if value else defaults


def timezone():
    return ZoneInfo(option("timezone", "Europe/Moscow"))
