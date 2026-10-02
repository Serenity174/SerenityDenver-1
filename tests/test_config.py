import importlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dotenv import dotenv_values

from serenity.config import PROJECT_ROOT, ConfigurationError, load_settings


class SettingsTests(unittest.TestCase):
    def setUp(self):
        # The committed file is the deployment configuration, not a secret fixture.
        self.values = dict(dotenv_values(PROJECT_ROOT / ".env", interpolate=False))
        self.values.update(TOKEN="test-token", DATABASE_URL="postgresql://user:pass@localhost/test")

    def load(self, **overrides):
        return load_settings(env_file=None, environ={**self.values, **overrides})

    def test_committed_configuration_loads(self):
        settings = self.load()
        settings.validate_runtime()
        self.assertIsInstance(settings.guild_id, int)
        self.assertGreater(len(settings.rank_role_ids), 1)

    def test_environment_overrides_file_without_mutating_environment(self):
        with patch.dict(os.environ, {"GUILD_ID": "12345"}, clear=True):
            before = dict(os.environ)
            settings = load_settings()
            self.assertEqual(settings.guild_id, 12345)
            self.assertEqual(dict(os.environ), before)

    def test_load_from_another_working_directory(self):
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                settings = load_settings(environ={})
            finally:
                os.chdir(previous)
        self.assertEqual(settings.guild_id, int(self.values["GUILD_ID"]))
        self.assertEqual(settings.bonus_cache_path.parent, PROJECT_ROOT)

    def test_missing_required_ids_are_reported_together(self):
        values = {**self.values}
        del values["GUILD_ID"]
        del values["CONTRACT_CHANNEL_ID"]
        with self.assertRaises(ConfigurationError) as result:
            load_settings(env_file=None, environ=values)
        self.assertIn("GUILD_ID", str(result.exception))
        self.assertIn("CONTRACT_CHANNEL_ID", str(result.exception))

    def test_invalid_ids_and_lists_are_rejected(self):
        for overrides in (
            {"GUILD_ID": "-1"},
            {"GUILD_ID": "abc"},
            {"GUILD_ID": "0"},
            {"GUILD_ID": ""},
            {"GUILD_ID": str(2**64)},
            {"RANK_ROLE_IDS": "1,,2"},
            {"RANK_ROLE_IDS": "1,1"},
            {"RANK_ROLE_IDS": "1"},
            {"STAFF_ROLE_IDS": "1,invalid"},
        ):
            with self.subTest(overrides=overrides), self.assertRaises(ConfigurationError):
                self.load(**overrides)

    def test_list_whitespace_and_order(self):
        self.assertEqual(self.load(RANK_ROLE_IDS=" 3, 1, 2 ").rank_role_ids, (3, 1, 2))

    def test_voice_and_port_boundaries(self):
        self.assertEqual(self.load(TEMP_VOICE_CATEGORY_ID="0").temp_voice_category_id, 0)
        self.assertEqual(self.load(TEMP_VOICE_GUILD_ID="0").temp_voice_guild_id, 0)
        for limit in ("0", "99"):
            self.assertEqual(
                self.load(TEMP_VOICE_DEFAULT_LIMIT=limit).temp_voice_default_limit, int(limit)
            )
        for overrides in (
            {"TEMP_VOICE_DEFAULT_LIMIT": "100"},
            {"WEB_PORT": "0"},
            {"WEB_PORT": "65536"},
        ):
            with self.subTest(overrides=overrides), self.assertRaises(ConfigurationError):
                self.load(**overrides)

    def test_missing_secrets_fail_runtime_validation(self):
        with self.assertRaises(ConfigurationError) as result:
            self.load(TOKEN="", DATABASE_URL="").validate_runtime()
        self.assertIn("TOKEN", str(result.exception))
        self.assertIn("DATABASE_URL", str(result.exception))

    def test_secrets_not_in_repr_or_errors(self):
        secret = "sensitive-test-value"
        settings = self.load(TOKEN=secret, DATABASE_URL=secret)
        self.assertNotIn(secret, repr(settings))
        with self.assertRaises(ConfigurationError) as result:
            settings.validate_runtime()
        self.assertNotIn(secret, str(result.exception))

    def test_dotenv_handles_utf8_bom_and_literal_password(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text(
                'TOKEN="literal-${password}#value"\nREPORT_SHEET_NAME="Неделя"\n',
                encoding="utf-8-sig",
            )
            overrides = {
                key: value
                for key, value in self.values.items()
                if key not in ("TOKEN", "REPORT_SHEET_NAME")
            }
            settings = load_settings(path, environ=overrides)
            self.assertEqual(settings.token, "literal-${password}#value")
            self.assertEqual(settings.report_sheet_name, "Неделя")

    def test_all_bot_modules_import_without_external_connections(self):
        settings = self.load()
        module_names = [
            f"serenity.cogs.{path.stem}"
            for path in (PROJECT_ROOT / "serenity/cogs").glob("*.py")
            if path.stem != "__init__"
        ]
        with (
            patch("serenity.config.get_settings", return_value=settings),
            patch("discord.ext.commands.Bot.run") as run,
            patch(
                "socket.socket.connect", side_effect=AssertionError("Unexpected network connection")
            ),
        ):
            for name in module_names:
                with self.subTest(module=name):
                    module = importlib.import_module(name)
                    self.assertIsNotNone(module.setup)
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
