"""Operational commands which never connect to Discord."""

import argparse
import asyncio

from serenity.config import get_settings
from serenity.database import Database
from serenity.logging_setup import configure_logging


async def database_command(command, settings):
    if not settings.database_url:
        raise SystemExit("DATABASE_URL is required")
    database = Database(settings.database_url)
    try:
        await database.open()
        if command == "db-check":
            print(
                "PostgreSQL connection OK; migrations:",
                await database.pool.fetchval("SELECT count(*) FROM public.schema_migrations"),
            )
        else:
            print("Migrations applied successfully")
    finally:
        await database.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["check-config", "migrate", "db-check"])
    args = parser.parse_args()
    settings = get_settings()
    configure_logging(settings)
    if args.command == "check-config":
        settings.validate_runtime()
        print("Configuration OK")
    else:
        asyncio.run(database_command(args.command, settings))


if __name__ == "__main__":
    main()
