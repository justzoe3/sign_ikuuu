"""Run the reviewed WebMoniter login client once and verify the check-in response."""
from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / ".upstream" / "WebMoniter"
UPSTREAM_COMMIT = "80cb2c178d5d7bd0156b9f0ac83ff1521e2fe8a4"
BASE_URL = "https://ikuuu.top"


def accounts_from_secret(raw: str) -> list[dict[str, str]]:
    if not raw.strip():
        raise ValueError("缺少 ACCOUNTS Secret。")
    accounts = []
    for line in raw.strip().splitlines():
        if not line.strip():
            continue
        email, separator, password = line.strip().partition(":")
        if not separator or "@" not in email or not password:
            raise ValueError("ACCOUNTS 格式应为每行 邮箱:密码。")
        accounts.append({"email": email.strip(), "password": password})
    if not accounts or len(accounts) > 5:
        raise ValueError("本流程支持 1 至 5 个账号。")
    return accounts


def business_success(ret: object, message: str) -> bool:
    return ret == 1 or (ret == 0 and any(text in message for text in ("已经签到", "今日已签到", "今天已签到", "已签到过", "already checked")))


def normalize_challenge_prompt(text: str) -> str:
    # GeeTest may serve English prompts even when Chrome requests zh-CN.
    # Keep the current remaining count, which falls after each grid click.
    return re.sub(r"\bselect\s*(\d+)\s*images?\s+with\b", r"选 \1 图片", text, flags=re.IGNORECASE)


def redact(text: str, accounts: list[dict[str, str]]) -> str:
    for account in accounts:
        for value in (account["email"], account["password"], urllib.parse.quote(account["email"]), urllib.parse.quote(account["password"])):
            if value:
                text = text.replace(value, "[已隐藏]")
    text = re.sub(r"[\w.*+-]+@[\w.-]+\.[A-Za-z]{2,}", "[邮箱已隐藏]", text)
    return re.sub(r"(?i)\b(key|uid|PHPSESSID|pass_token|captcha_output|password|passwd)=([^\s;,&]+)", r"\1=[已隐藏]", text)


def summary(text: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as output:
            output.write(text.rstrip() + "\n")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def worker() -> dict:
    account = json.load(sys.stdin)
    sys.path.insert(0, str(UPSTREAM))
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    from src.tasks import ikuuu_checkin as client
    from src.tasks import ikuuu_captcha as captcha_client

    original_prompt_text = captcha_client._prompt_text
    captcha_client._prompt_text = lambda element: normalize_challenge_prompt(original_prompt_text(element))

    solver_state = {"rounds": 0, "kind": "未出现图片挑战"}
    original_solver = client.CaptchaSolver

    class ObservedSolver(original_solver):
        def solve_if_present(self, driver, **options):
            from src.tasks.ikuuu_captcha import CaptchaKind, visible_challenge, _verified
            from selenium.common.exceptions import TimeoutException
            from selenium.webdriver.support.ui import WebDriverWait

            # A visible blank panel appears before its prompt arrives. Do not
            # classify that loading frame as an unsupported CAPTCHA type.
            if options.get("wait_for_challenge"):
                try:
                    WebDriverWait(driver, 12).until(
                        lambda d: _verified(d)
                        or visible_challenge(d) in (CaptchaKind.WORD, CaptchaKind.NINE)
                    )
                except TimeoutException:
                    pass
            kind = visible_challenge(driver)
            if kind is not None:
                solver_state["kind"] = kind.value
            try:
                return super().solve_if_present(driver, **options)
            except Exception:
                prompts = []
                for element in driver.find_elements("css selector", ".geetest_text_tips, .geetest_ques_tips"):
                    if element.is_displayed():
                        text = (element.get_attribute("textContent") or "").strip()
                        if text:
                            prompts.append(text[:160])
                solver_state["prompt"] = prompts[:4]
                logging.warning("验证码类型=%s；公开挑战提示=%s；已处理轮次=%s", solver_state["kind"], prompts[:4], self.rounds)
                raise
            finally:
                solver_state["rounds"] = self.rounds

    client.CaptchaSolver = ObservedSolver
    cfg = client.CheckinConfig(
        enable=True, domain="ikuuu.top", email=account["email"], password=account["password"],
        time="07:10", accounts=[account], push_channels=[],
    )
    try:
        cookie = client._login_and_get_cookie_sync(cfg)
    except Exception as error:
        return {"success": False, "stage": "login", "kind": type(error).__name__, "message": str(error), "captcha": solver_state}
    if not cookie:
        return {"success": False, "stage": "login", "message": "未获得已认证的登录会话。", "captcha": solver_state}
    fields = dict(part.strip().split("=", 1) for part in cookie.split(";") if "=" in part)
    if not fields.get("uid") or not fields.get("key"):
        return {"success": False, "stage": "login", "message": "登录会话缺少 uid/key，停止签到。", "captcha": solver_state}

    request = urllib.request.Request(
        BASE_URL + "/user/checkin", data=b"", method="POST",
        headers={"Cookie": cookie, "Origin": BASE_URL, "Referer": BASE_URL + "/user", "X-Requested-With": "XMLHttpRequest", "User-Agent": client._IKUUU_USER_AGENT},
    )
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=30) as response:
            data = json.loads(response.read(256 * 1024))
        message = str(data.get("msg", "未收到服务端签到结果"))
        ret = data.get("ret")
        return {"success": business_success(ret, message), "stage": "checkin", "ret": ret, "message": message, "captcha": solver_state}
    except Exception as error:
        return {"success": False, "stage": "checkin", "kind": type(error).__name__, "message": str(error), "captcha": solver_state}


def run_account(account: dict[str, str]) -> tuple[dict, str]:
    environment = os.environ.copy()
    environment.pop("ACCOUNTS", None)
    process = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--worker"], cwd=UPSTREAM, env=environment,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", start_new_session=True,
    )
    try:
        output, diagnostic = process.communicate(json.dumps(account), timeout=240)
        try:
            result = json.loads(output)
            if not isinstance(result, dict):
                raise ValueError("invalid reply")
        except (ValueError, TypeError):
            return {"success": False, "stage": "runtime", "message": "运行客户端未返回有效的结构化结果。"}, diagnostic
        if process.returncode:
            result["success"] = False
        return result, diagnostic
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        _, diagnostic = process.communicate()
        return {"success": False, "stage": "timeout", "message": "自动登录与签到超过 240 秒，已停止本次测试。"}, diagnostic
    finally:
        # The child owns this process group, including its browser and driver.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-config", action="store_true")
    parser.add_argument("--worker", action="store_true")
    args = parser.parse_args()
    if args.worker:
        try:
            with contextlib.redirect_stdout(sys.stderr):
                result = worker()
        except Exception as error:
            result = {"success": False, "stage": "runtime", "kind": type(error).__name__, "message": str(error)}
        print(json.dumps(result, ensure_ascii=False))
        return 0
    try:
        accounts = accounts_from_secret(os.environ.get("ACCOUNTS", ""))
    except ValueError as error:
        print(f"::error::{error}")
        summary(f"## ❌ iKuuu 测试未完成\n\n{error}")
        return 1
    if args.check_config:
        print(f"账号配置格式通过：{len(accounts)} 个账号；凭据不写入日志。")
        return 0
    revision = subprocess.run(["git", "-C", str(UPSTREAM), "rev-parse", "HEAD"], capture_output=True, text=True)
    if revision.returncode or revision.stdout.strip() != UPSTREAM_COMMIT:
        print("::error::上游版本校验失败，停止运行。")
        return 1
    summary(f"## iKuuu WebMoniter 试运行\n\n目标：`{BASE_URL}`；上游固定版本 `{UPSTREAM_COMMIT[:12]}`。\n")
    all_success = True
    for index, account in enumerate(accounts, 1):
        print(f"账号 #{index}：开始自动登录、本地验证码识别与签到。", flush=True)
        result, diagnostic = run_account(account)
        success = result.get("success") is True and result.get("stage") == "checkin" and business_success(result.get("ret"), str(result.get("message", "")))
        all_success = all_success and success
        safe_message = redact(str(result.get("message", "未知结果")), accounts)
        safe_diagnostic = redact(diagnostic[-12000:], accounts)
        if safe_diagnostic:
            print(safe_diagnostic, end="" if safe_diagnostic.endswith("\n") else "\n")
        label = "✅" if success else "❌"
        captcha = result.get("captcha", {})
        detail = f"账号 #{index} {label} 阶段：{result.get('stage')}；{safe_message}；验证码轮次：{captcha.get('rounds', 0)}。"
        print(detail, flush=True)
        summary(detail + "\n")
        if not success:
            print("::error::本次未获得服务端签到成功确认，具体原因见脱敏摘要。")
            summary(f"\n失败类型：`{result.get('kind', 'not_confirmed')}`。\n")
            if safe_diagnostic:
                summary("<details><summary>脱敏诊断日志</summary>\n\n```text\n" + safe_diagnostic + "\n```\n</details>")
    summary("\n本流程不上传 Cookie、浏览器配置、截图或原始日志。")
    return 0 if all_success else 1


if __name__ == "__main__":
    sys.exit(main())
