"""Regression tests for false success and phase handling; no live credentials."""
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import ikuuu_browser as b
from run_actions import accounts_from_secret, redact


class CheckinResultTests(unittest.TestCase):
    def test_explicit_success(self):
        self.assertTrue(b.business_success(1, "获得 1234 MB 流量"))

    def test_already_signed_in(self):
        for message in ("您今天已签到", "今日已签到，请明天再来", "Already checked in today"):
            with self.subTest(message=message):
                self.assertTrue(b.business_success(0, message))

    def test_transport_or_login_success_is_not_checkin(self):
        for ret in (True, "1", None, 200, 0, 1.0):
            with self.subTest(ret=ret):
                self.assertFalse(b.business_success(ret, "验证码通过 / 登录成功"))

    def test_errors_remain_failed(self):
        for message in ("请先登录", "签到失败", "流量不足", "服务器错误", ""):
            self.assertFalse(b.business_success(0, message))


class LoginTests(unittest.TestCase):
    def state(self, **overrides):
        return dict(origin=b.BASE_URL, path="/auth/login", phase="password", **overrides)

    def test_password_page_without_response_waits(self):
        self.assertIsNone(b.login_failure(self.state(events=[])))

    def test_explicit_rejection_stops(self):
        failure = b.login_failure(self.state(events=[{
            "status": 200, "phase": "password", "result": "invalid_password",
            "message": "private account data"}]))
        self.assertEqual(failure.stage, "login")
        self.assertIn("invalid_password", str(failure))
        self.assertNotIn("private account data", str(failure))

    def test_email_and_totp_are_distinct_required_steps(self):
        for phase, stage in (("email_code", "email_verification"), ("totp", "two_factor"),
                             ("reverse_email_verify", "email_verification")):
            with self.subTest(phase=phase):
                failure = b.login_failure(self.state(events=[{"status": 200, "phase": phase}]))
                self.assertEqual(failure.stage, stage)

    def test_rate_limit_is_not_retried_as_captcha(self):
        failure = b.login_failure(self.state(events=[{"status": 429, "phase": "email_code"}]))
        self.assertEqual(failure.stage, "rate_limited")

    def test_malformed_or_non_json_login_response_is_failure(self):
        failure = b.login_failure(self.state(events=[{"status": 200, "phase": ""}]))
        self.assertEqual(failure.stage, "login")

    def test_authenticated_response_still_requires_user_page(self):
        state = self.state(events=[{"status": 200, "phase": "authenticated"}])
        self.assertIsNone(b.login_failure(state))
        self.assertFalse(b.authenticated_page(state))

    def test_external_origin_is_not_trusted(self):
        state = {"origin": "https://elsewhere.invalid", "path": "/user", "logout_links": 1}
        self.assertFalse(b.authenticated_page(state))
        self.assertIsNotNone(b.login_failure(state))

    def test_closed_logout_menu_can_still_prove_authentication(self):
        state = {"origin": b.BASE_URL, "path": "/user", "logout_links": 1, "password_fields": 0}
        self.assertTrue(b.authenticated_page(state))
        state["password_fields"] = 1
        self.assertFalse(b.authenticated_page(state))

    def test_bilingual_challenge_prompts(self):
        self.assertEqual(b.normalize_prompt("Select 3 images with"), "选 3 图片 with")
        self.assertEqual(b.normalize_prompt("Select in this order"), "依次点击")
        self.assertEqual(b.normalize_prompt("依次点击"), "依次点击")


class BrowserBoundaryTests(unittest.TestCase):
    def test_visual_success_does_not_override_site_validation(self):
        driver = Mock()
        driver.execute_script.return_value = False
        driver.find_elements.return_value = [Mock(is_displayed=lambda: True)]
        self.assertFalse(b.captcha_ready(driver))
        driver.find_elements.assert_not_called()

    def test_checkin_stays_in_browser_and_no_cookie_export(self):
        driver = Mock()
        driver.current_url = b.BASE_URL + "/auth/login"
        driver.execute_script.return_value = True
        driver.execute_async_script.return_value = {
            "status": 200, "ret": 1, "message": "获得 1234 MB 流量"}
        with patch.object(b, "create_driver", return_value=driver), \
             patch.object(b, "wait_for", return_value=Mock()), \
             patch.object(b, "captcha_ready", return_value=True):
            result = b.run_browser({"email": "test@example.invalid", "password": "test"}, {})
        self.assertTrue(result["success"])
        self.assertEqual(result["stage"], "checkin")
        driver.get_cookies.assert_not_called()
        driver.execute_async_script.assert_called_once_with(b.CHECKIN_JS, b.BASE_URL)
        driver.quit.assert_called_once()

    def test_probe_cannot_report_checkin_success(self):
        driver = Mock()
        driver.current_url = b.BASE_URL + "/auth/login"
        driver.execute_script.return_value = True
        with patch.object(b, "create_driver", return_value=driver), \
             patch.object(b, "wait_for", return_value=Mock()), \
             patch.object(b, "captcha_ready", return_value=True):
            result = b.run_browser({}, {}, probe_only=True)
        self.assertFalse(result["success"])
        self.assertEqual(result["stage"], "captcha_probe")
        driver.execute_async_script.assert_not_called()

    def test_browser_exception_does_not_expose_input_or_cookie(self):
        driver = Mock()
        driver.get.side_effect = RuntimeError("secret password or Cookie=private")
        with patch.object(b, "create_driver", return_value=driver):
            result = b.run_browser({}, {})
        self.assertFalse(result["success"])
        self.assertNotIn("private", json.dumps(result))
        self.assertNotIn("secret password", json.dumps(result))
        driver.quit.assert_called_once()

    def test_redirected_or_html_checkin_fails(self):
        for response in ({"status": 200, "error": "not_json"},
                         {"status": 0, "error": "request_failed_or_redirected"},
                         {"status": 429, "ret": 1}):
            with self.subTest(response=response):
                driver = Mock()
                driver.current_url = b.BASE_URL + "/auth/login"
                driver.execute_script.return_value = True
                driver.execute_async_script.return_value = response
                with patch.object(b, "create_driver", return_value=driver), \
                     patch.object(b, "wait_for", return_value=Mock()), \
                     patch.object(b, "captcha_ready", return_value=True):
                    result = b.run_browser({"email": "x@example.invalid", "password": "test"}, {})
                self.assertFalse(result["success"])


class SecretHandlingTests(unittest.TestCase):
    def test_password_colons_are_preserved(self):
        accounts = accounts_from_secret("test@example.invalid:a:b:c")
        self.assertEqual(accounts[0]["password"], "a:b:c")

    def test_missing_secret_fails(self):
        with self.assertRaises(ValueError):
            accounts_from_secret("")

    def test_log_redaction(self):
        accounts = [{"email": "test@example.invalid", "password": "sample-password"}]
        result = redact("test@example.invalid sample-password uid=123 key=abc", accounts)
        for private in ("test@example.invalid", "sample-password", "123", "abc"):
            self.assertNotIn(private, result)


if __name__ == "__main__":
    unittest.main()
