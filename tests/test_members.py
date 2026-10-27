import unittest
from unittest.mock import patch

from support import install_dependency_stubs

install_dependency_stubs()

from gateway_mcp.services import members
from gateway_mcp.services.policy import GatewayActor

NEW = GatewayActor(subject="yandex:77", email="New.Person@sibsensor.com", scopes=("skills:read",))
ADMIN = GatewayActor(subject="yandex:1", email="boss@sibsensor.com", scopes=("access:admin",))


class MemberApprovalTests(unittest.TestCase):
    def setUp(self):
        for name, value in (("member_approval_enabled", True), ("postgres_enabled", True), ("is_listed_user", False)):
            p = patch.object(members, name, return_value=value)
            p.start()
            self.addCleanup(p.stop)

    def test_new_person_gets_pending_and_request(self):
        with patch.object(members, "get_member", return_value=None), patch.object(
            members, "_known_yandex_user", return_value=False
        ), patch.object(members, "_insert_member", return_value={"status": "pending"}) as ins, patch.object(
            members, "_open_request"
        ) as req:
            with self.assertRaises(members.MemberPendingError):
                members.check_member_on_login(NEW, {})
        ins.assert_called_once()
        req.assert_called_once_with(NEW, "new.person@sibsensor.com")

    def test_person_who_logged_in_before_is_let_in(self):
        with patch.object(members, "get_member", return_value=None), patch.object(
            members, "_known_yandex_user", return_value=True
        ), patch.object(members, "_insert_member") as ins, patch.object(members, "_open_request") as req:
            self.assertEqual(members.check_member_on_login(NEW, {}), "approved")
        self.assertEqual(ins.call_args.kwargs["status"], "approved")
        req.assert_not_called()

    def test_pending_request_is_not_duplicated(self):
        with patch.object(members, "get_member", return_value={"status": "pending"}), patch.object(
            members, "_open_request"
        ) as req:
            with self.assertRaises(members.MemberPendingError):
                members.check_member_on_login(NEW, {})
        req.assert_not_called()

    def test_rejected_and_approved(self):
        with patch.object(members, "get_member", return_value={"status": "rejected"}):
            with self.assertRaises(members.MemberRejectedError):
                members.check_member_on_login(NEW, {})
        with patch.object(members, "get_member", return_value={"status": "approved"}):
            self.assertEqual(members.check_member_on_login(NEW, {}), "approved")

    def test_admins_are_never_locked_out(self):
        with patch.object(members, "get_member") as get:
            self.assertEqual(members.check_member_on_login(ADMIN, {}), "approved")
        get.assert_not_called()

    def test_disabled_switch_lets_everyone_in(self):
        with patch.object(members, "member_approval_enabled", return_value=False), patch.object(
            members, "get_member"
        ) as get:
            self.assertEqual(members.check_member_on_login(NEW, {}), "approved")
        get.assert_not_called()

    def test_decision_is_copied_to_member_table(self):
        approval = {"approval_type": "member_access", "status": "approved", "decided_by": "yandex:1",
                    "payload": {"member_key": "new.person@sibsensor.com"}}
        with patch.object(members, "set_member_status") as setter:
            members.on_approval_decided(approval)
        setter.assert_called_once_with("new.person@sibsensor.com", status="approved", decided_by="yandex:1")

    def test_refresh_is_denied_after_rejection(self):
        with patch.object(members, "get_member", return_value={"status": "rejected"}):
            with self.assertRaises(members.MemberRejectedError):
                members.check_member_on_refresh(NEW)


if __name__ == "__main__":
    unittest.main()
