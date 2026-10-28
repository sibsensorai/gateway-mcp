import unittest
from unittest.mock import patch

from support import install_dependency_stubs

install_dependency_stubs()

from gateway_mcp.services import people


class PeopleTests(unittest.TestCase):
    def setUp(self):
        people._CACHE.clear()

    def test_name_from_yandex_info(self):
        self.assertEqual(people.name_from_yandex_info({"real_name": "Иван Шелемба"}), "Иван Шелемба")
        self.assertEqual(people.name_from_yandex_info({"first_name": "Иван", "last_name": "Шелемба"}), "Шелемба Иван")
        self.assertEqual(people.name_from_yandex_info({"display_name": "ishelemba"}), "ishelemba")
        self.assertEqual(people.name_from_yandex_info({}), "")

    def test_label_with_saved_name(self):
        row = {"actor_subject": "yandex:5", "email": "i.shelemba@sibsensor.com", "metadata": {"real_name": "Иван Шелемба"}}
        with patch.object(people, "postgres_enabled", return_value=True), patch.object(people, "_row", return_value=row):
            self.assertEqual(people.person("yandex:5")["label"], "Иван Шелемба (i.shelemba@sibsensor.com)")

    def test_name_is_fetched_once_for_old_logins(self):
        row = {"actor_subject": "yandex:6", "email": "e.kryukova@sibsensor.com", "metadata": {}}
        with patch.object(people, "postgres_enabled", return_value=True), patch.object(
            people, "_row", return_value=row
        ), patch.object(people, "_backfill_name", return_value="Елена Крюкова") as fetch:
            self.assertEqual(people.person("yandex:6")["label"], "Елена Крюкова (e.kryukova@sibsensor.com)")
            people.person("yandex:6")
        fetch.assert_called_once_with("yandex:6")

    def test_falls_back_to_email_then_subject(self):
        row = {"actor_subject": "yandex:7", "email": "worker@sibsensor.com", "metadata": {}}
        with patch.object(people, "postgres_enabled", return_value=True), patch.object(
            people, "_row", return_value=row
        ), patch.object(people, "_backfill_name", return_value=""):
            self.assertEqual(people.person("yandex:7")["label"], "worker@sibsensor.com")
        with patch.object(people, "postgres_enabled", return_value=False):
            self.assertEqual(people.person("yandex:8")["label"], "yandex:8")


if __name__ == "__main__":
    unittest.main()
