"""Typed application settings. Environment variables override the project .env."""

import os
from dataclasses import MISSING, dataclass, field, fields
from functools import lru_cache
from pathlib import Path
from typing import Mapping, get_type_hints
from urllib.parse import urlsplit

from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ConfigurationError(ValueError):
    """Invalid configuration; messages never include supplied values or secrets."""


@dataclass(frozen=True, slots=True)
class Settings:
    guild_id: int
    high_staff_role_id: int
    staff_role_ids: tuple[int, ...]
    application_role_ids: tuple[int, ...]
    rank_role_ids: tuple[int, ...] = field(metadata={"min_items": 2})
    family_role_id: int
    verified_role_id: int
    vacation_role_id: int
    support_role_id: int

    application_channel_id: int
    submit_channel_id: int
    accept_channel_id: int
    bonus_channel_id: int
    news_channel_id: int
    bronya_channel_id: int
    birthday_channel_id: int
    vacation_channel_id: int
    promotion_channel_id: int
    report_output_channel_id: int
    report_interface_channel_id: int
    contract_channel_id: int
    attendance_log_channel_id: int
    payout_channel_id: int
    payout_file_channel_id: int
    welcome_channel_id: int
    car_catalog_channel_id: int

    temp_voice_trigger_channel_id: int
    temp_voice_category_id: int = field(metadata={"min": 0})
    temp_voice_allowed_role_id: int
    temp_voice_guild_id: int = field(metadata={"min": 0})

    token: str = field(default="", repr=False, metadata={"allow_empty": True})
    database_url: str = field(default="", repr=False, metadata={"allow_empty": True})
    bot_command_prefix: str = "!"
    bot_activity_name: str = "/promo SERENITY"
    discord_invite_url: str = "https://discord.gg/4YX46cs39M"
    temp_voice_default_name: str = "{user}'s channel"
    temp_voice_default_limit: int = field(default=0, metadata={"min": 0, "max": 99})

    google_credentials_path: Path = Path("serenitypay.json")
    google_spreadsheet_id: str = field(default="", metadata={"allow_empty": True})
    report_sheet_name: str = "Неделя"
    attendance_sheet_name: str = "Явка"
    bonus_cache_path: Path = Path("cached_message_id.json")
    web_host: str = "0.0.0.0"
    web_port: int = field(default=8080, metadata={"max": 65535})
    db_pool_min: int = field(default=2, metadata={"min": 2, "max": 20})
    db_pool_max: int = field(default=10, metadata={"min": 2, "max": 50})
    log_level: str = "INFO"

    birthday_emoji: str = "🎂"
    welcome_emoji: str = "👋"
    promotion_emoji: str = "📋"
    approve_emoji: str = "✅"
    reject_emoji: str = "❌"
    voice_settings_emoji: str = "⚙️"
    voice_footer_emoji: str = "☁️"
    reminder_emoji: str = "⏳"

    def validate_runtime(self) -> None:
        """Check credentials before connecting the bot, without printing them."""
        errors = []
        if not self.token:
            errors.append("TOKEN: укажите токен Discord-бота")
        if not self.database_url:
            errors.append("DATABASE_URL: укажите строку подключения PostgreSQL")
        else:
            try:
                valid_scheme = urlsplit(self.database_url).scheme in ("postgres", "postgresql")
            except ValueError:
                valid_scheme = False
            if not valid_scheme:
                errors.append("DATABASE_URL: ожидается URI postgres:// или postgresql://")
        if errors:
            raise ConfigurationError("Ошибки конфигурации:\n" + "\n".join(errors))


def load_settings(
    env_file: Path | None = PROJECT_ROOT / ".env",
    environ: Mapping[str, str] | None = None,
) -> Settings:
    """Load settings without modifying os.environ; paths are relative to the project.

    Interpolation is disabled so passwords containing ${...} remain literal.
    Pass env_file=None to use only the provided environment (e.g. in tests/CI).
    """
    values = (
        dict(dotenv_values(env_file, encoding="utf-8-sig", interpolate=False)) if env_file else {}
    )
    values.update(os.environ if environ is None else environ)
    types = get_type_hints(Settings)
    parsed = {}
    errors = []
    for setting in fields(Settings):
        key = setting.name.upper()
        raw = values.get(key, setting.default)
        if raw is MISSING or raw is None:
            errors.append(f"{key}: обязательная настройка отсутствует")
            continue
        value = str(raw).strip()
        value_type = types[setting.name]
        if not value and not setting.metadata.get("allow_empty"):
            errors.append(f"{key}: значение не должно быть пустым")
            continue
        if value_type is int:
            minimum = setting.metadata.get("min", 1)
            maximum = setting.metadata.get("max", 2**64 - 1)
            if not value.isascii() or not value.isdigit() or not minimum <= int(value) <= maximum:
                errors.append(f"{key}: ожидается целое число от {minimum} до {maximum}")
                continue
            parsed[setting.name] = int(value)
        elif value_type == tuple[int, ...]:
            parts = [part.strip() for part in value.split(",")]
            if any(
                not part.isascii() or not part.isdigit() or not 0 < int(part) < 2**64
                for part in parts
            ):
                errors.append(f"{key}: ожидаются положительные Discord ID через запятую")
                continue
            ids = tuple(int(part) for part in parts)
            if len(ids) != len(set(ids)) or len(ids) < setting.metadata.get("min_items", 1):
                errors.append(f"{key}: список должен содержать разные ID в достаточном количестве")
                continue
            parsed[setting.name] = ids
        elif value_type is Path:
            path = Path(value).expanduser()
            parsed[setting.name] = path if path.is_absolute() else PROJECT_ROOT / path
        else:
            parsed[setting.name] = value
    if errors:
        raise ConfigurationError("Ошибки конфигурации:\n" + "\n".join(errors))
    if parsed.get("db_pool_min", 2) > parsed.get("db_pool_max", 10):
        raise ConfigurationError("DB_POOL_MIN must not exceed DB_POOL_MAX")
    if parsed.get("log_level", "INFO") not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        raise ConfigurationError("LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR or CRITICAL")
    return Settings(**parsed)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """All modules share the same immutable settings instance."""
    return load_settings()


if __name__ == "__main__":
    try:
        get_settings().validate_runtime()
    except ConfigurationError as exc:
        raise SystemExit(str(exc)) from None
    print("Конфигурация корректна. Подключения к Discord и БД не выполнялись.")
