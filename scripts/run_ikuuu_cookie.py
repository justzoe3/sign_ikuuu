"""Run the reviewed Cookie check-in client and require a real success result."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / ".upstream" / "ikuuu-auto-checkin" / "checkin.py"
UPSTREAM_COMMIT = "601a929e9caac126920c9fccd70c467ed63315e5"


def append_summary(text: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as output:
            output.write(text.rstrip() + "\n")


def fail(message: str) -> int:
    print(f"::error title=iKuuu 签到未完成::{message}")
    append_summary("## ❌ iKuuu 签到未完成\n\n" + message)
    return 1


def configuration() -> tuple[str, str]:
    cookie = os.environ.get("IKUUU_COOKIE", "").strip()
    if cookie.lower().startswith("cookie:"):
        cookie = cookie[7:].strip()
    if not cookie:
        raise ValueError(
            "缺少 IKUUU_COOKIE。请在仓库 Settings → Secrets and variables → Actions "
            "添加同名 Repository secret，填入你登录 iKuuu 后的完整 Cookie 请求头。"
        )
    if "\n" in cookie or "\r" in cookie or "=" not in cookie:
        raise ValueError("IKUUU_COOKIE 应是一行 Cookie 请求头，不是邮箱、密码或 JSON。")
    fields = dict(part.strip().split("=", 1) for part in cookie.split(";") if "=" in part)
    if not fields.get("uid") or not fields.get("key"):
        raise ValueError("Cookie 缺少已登录的 uid/key。请从登录后的用户中心请求复制完整 Cookie。")
    base_url = os.environ.get("IKUUU_BASE_URL", "https://ikuuu.top").strip().rstrip("/")
    parsed = urlsplit(base_url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"ikuuu.top", "ikuuu.pw"}
        or parsed.netloc != parsed.hostname
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("IKUUU_BASE_URL 只能是 https://ikuuu.top 或 https://ikuuu.pw。")
    return cookie, base_url


def redact(text: str, cookie: str) -> str:
    values = {cookie}
    for part in cookie.split(";"):
        if "=" in part:
            _, value = part.strip().split("=", 1)
            if len(value) >= 4:
                values.update((value, unquote(value)))
    for value in sorted(values, key=len, reverse=True):
        if value:
            text = text.replace(value, "[已隐藏]")
    return re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[邮箱已隐藏]", text)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-config", action="store_true")
    args = parser.parse_args()
    try:
        cookie, base_url = configuration()
    except ValueError as error:
        return fail(str(error))
    if args.check_config:
        print("Cookie 格式与目标域名检查通过；登录有效性将在签到时验证。")
        return 0
    if not UPSTREAM.is_file():
        return fail("没有找到已固定版本的上游签到脚本，请检查检出上游项目的步骤。")

    environment = os.environ.copy()
    environment.update({"IKUUU_COOKIE": cookie, "IKUUU_BASE_URL": base_url, "PYTHONUNBUFFERED": "1"})
    with tempfile.TemporaryDirectory(prefix="ikuuu-summary-") as temporary:
        summary_file = Path(temporary) / "summary.md"
        environment["GITHUB_STEP_SUMMARY"] = str(summary_file)
        try:
            result = subprocess.run(
                [sys.executable, str(UPSTREAM)],
                cwd=UPSTREAM.parent,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=180,
            )
        except subprocess.TimeoutExpired:
            return fail("签到超过 180 秒，已终止；请检查域名、网络或更新登录 Cookie。")
        output = redact(result.stdout, cookie)
        print(output, end="" if output.endswith("\n") else "\n")
        summary = redact(summary_file.read_text(encoding="utf-8") if summary_file.exists() else "", cookie)
        success = result.returncode == 0 and "## ✅ ikuuu 签到" in summary and "## ❌" not in summary
        if summary:
            append_summary(summary)
        if not success:
            if output:
                append_summary("\n<details><summary>脱敏诊断日志</summary>\n\n```text\n" + output[-6000:] + "\n```\n</details>")
            return fail("未获得服务端签到成功或今日已签到的确认，具体原因见本次日志。")
        append_summary(
            "\n使用 [viceren/ikuuu-auto-checkin](https://github.com/viceren/ikuuu-auto-checkin) "
            f"固定版本 `{UPSTREAM_COMMIT[:12]}`；日志和摘要中的 Cookie、邮箱已脱敏。"
        )
        return 0


if __name__ == "__main__":
    sys.exit(main())
