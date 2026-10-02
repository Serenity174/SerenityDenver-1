import logging
import unittest
from decimal import Decimal
from types import SimpleNamespace

from serenity.cogs.birthday import parse_birthday
from serenity.logging_setup import RedactingFormatter
from serenity.services.reporting import report_total
from serenity.services.workflows import promotion_target


class LogicTests(unittest.TestCase):
    def test_real_calendar_dates(self):
        self.assertEqual(parse_birthday("29.02"), (29, 2))
        self.assertEqual(parse_birthday(" 1.7 "), (1, 7))
        for value in ("31.04", "30.02", "00.12", "1.13", "1/7", "12.7.3"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_birthday(value)

    def test_exact_money_rounding(self):
        self.assertEqual(report_total("Тёмный горбыль", 5), Decimal("3.97"))
        self.assertEqual(report_total("Марлин", 1000), Decimal("858.00"))
        for quantity in (0, -1, 1_000_001):
            with self.assertRaises(ValueError):
                report_total("Марлин", quantity)
        with self.assertRaises(ValueError):
            report_total("unknown", 1)

    def test_promotion_uses_highest_rank_without_exceeding_maximum(self):
        member = SimpleNamespace(get_role=lambda role_id: role_id if role_id in (10, 20) else None)
        self.assertEqual(promotion_target(member, (10, 20, 30)), 30)
        self.assertEqual(promotion_target(member, (10, 20)), 20)
        with self.assertRaises(ValueError):
            promotion_target(member, (30, 40))

    def test_logs_redact_secrets_and_database_uris(self):
        formatter = RedactingFormatter(("secret-token",))
        record = logging.LogRecord(
            "test",
            logging.ERROR,
            "test",
            1,
            "Failed secret-token postgresql://name:password@host/db",
            (),
            None,
        )
        text = formatter.format(record)
        self.assertNotIn("secret-token", text)
        self.assertNotIn("password", text)
