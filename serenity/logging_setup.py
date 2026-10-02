import logging
import re
import sys


class RedactingFormatter(logging.Formatter):
    def __init__(self, secrets=()):
        super().__init__("%(asctime)s %(levelname)s %(name)s %(message)s")
        self.secrets = tuple(value for value in secrets if value)

    def format(self, record):
        result = super().format(record)
        for value in self.secrets:
            result = result.replace(value, "[redacted]")
        return re.sub(r"postgres(?:ql)?://[^\s]+", "[database URI redacted]", result)


def configure_logging(settings):
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(RedactingFormatter((settings.token, settings.database_url)))
    logging.basicConfig(level=settings.log_level, handlers=[handler], force=True)
