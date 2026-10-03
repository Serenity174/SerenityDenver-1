import asyncio
import logging
import signal

from serenity.config import ConfigurationError, get_settings
from serenity.logging_setup import configure_logging


async def run(settings):
    from serenity.bot import SerenityBot

    async with SerenityBot(settings) as bot:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, lambda: bot.spawn(bot.close(), name="shutdown"))
            except NotImplementedError:
                pass  # Windows uses KeyboardInterrupt; Railway runs on Linux.
        await bot.start(settings.token)


def main():
    try:
        settings = get_settings()
        settings.validate_runtime()
        configure_logging(settings)
        asyncio.run(run(settings))
    except ConfigurationError as exc:
        raise SystemExit(str(exc)) from None
    except KeyboardInterrupt:
        pass
    except Exception:
        logging.getLogger(__name__).exception("Bot startup or runtime failed")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
