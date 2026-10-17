"""Browser-based iKuuu flow; local models only, no external solving service."""
from __future__ import annotations

import logging
import os
import re
import shutil
import traceback
from urllib.parse import urlsplit

BASE_URL = "https://ikuuu.top"

# Read the site's own callback result. A visible green animation is insufficient.
# The validation values stay in the page; only a boolean crosses this boundary.
CAPTCHA_READY_JS = """
if (location.origin !== arguments[0]) return false;
const c = window.Captcha;
if (!c || !c.isReady() || !c.getResponse) return false;
const r = c.getResponse();
return !!r && ['lot_number','captcha_output','pass_token','gen_time']
  .every(k => r[k] !== undefined && r[k] !== null && String(r[k]).length > 0);
"""

# Observe responses to the page's normal form submission. Never record request
# data, headers, CAPTCHA tokens, raw responses, or cookies.
OBSERVE_LOGIN_JS = """
if (location.origin !== arguments[0] || !window.jQuery) return false;
window.__ikuuuLoginEvents = [];
jQuery(document).off('ajaxComplete.ikuuuObserver').on(
  'ajaxComplete.ikuuuObserver', function(_event, xhr, settings) {
    const u = new URL(settings.url, location.href);
    if (u.origin !== location.origin || u.pathname !== '/auth/login'
        || String(settings.type).toUpperCase() !== 'POST') return;
    const d = xhr.responseJSON || {};
    const short = v => typeof v === 'string' ? v.slice(0, 240) : '';
    window.__ikuuuLoginEvents.push({status: xhr.status,
      phase: short(d.phase), result: short(d.result), message: short(d.msg)});
    window.__ikuuuLoginEvents = window.__ikuuuLoginEvents.slice(-4);
  });
return true;
"""

PAGE_STATE_JS = """
const visible = e => !!e.getClientRects().length &&
  getComputedStyle(e).visibility !== 'hidden';
return {origin: location.origin, path: location.pathname,
  logout_links: document.querySelectorAll('a[href="/auth/logout"],a[href$="/auth/logout"]').length,
  password_fields: [...document.querySelectorAll('input[type="password"]')].filter(visible).length,
  phase: typeof loginPhase === 'string' ? loginPhase : '',
  events: window.__ikuuuLoginEvents || []};
"""

CHECKIN_JS = """
const done = arguments[arguments.length - 1];
if (location.origin !== arguments[0]) {
  done({status: 0, error: 'unexpected_origin'}); return;
}
const abort = new AbortController();
const timer = setTimeout(() => abort.abort(), 25000);
fetch('/user/checkin', {method: 'POST', credentials: 'same-origin',
  redirect: 'error', signal: abort.signal,
  headers: {'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json'}})
  .then(async r => {
    const type = r.headers.get('content-type') || '';
    if (!type.includes('application/json')) return {status: r.status, error: 'not_json'};
    const body = await r.text();
    if (body.length > 65536) return {status: r.status, error: 'oversized_response'};
    const d = JSON.parse(body);
    return {status: r.status, ret: d.ret,
      message: typeof d.msg === 'string' ? d.msg.slice(0, 500) : ''};
  })
  .then(done, () => done({status: 0, error: 'request_failed_or_redirected'}))
  .finally(() => clearTimeout(timer));
"""


class FlowError(RuntimeError):
    def __init__(self, stage: str, message: str):
        super().__init__(message)
        self.stage = stage


def normalize_prompt(text: str) -> str:
    text = re.sub(r"select\s*(\d+)\s*images?", r"选 \1 图片", text, flags=re.I)
    return re.sub(r"select\s*in\s*this\s*order", "依次点击", text, flags=re.I)


def authenticated_page(state: dict) -> bool:
    path = state.get("path", "")
    return (state.get("origin") == BASE_URL
            and (path == "/user" or path.startswith("/user/"))
            and state.get("logout_links", 0) > 0
            and state.get("password_fields", 0) == 0)


def business_success(ret: object, message: str) -> bool:
    # Reject bool, strings and broad HTTP/transport success indicators.
    if type(ret) is not int:
        return False
    if ret == 1:
        return True
    already = ("已经签到", "今日已签到", "今天已签到", "已签到过", "already checked")
    return ret == 0 and any(s in message.lower() for s in already)


def login_failure(state: dict) -> FlowError | None:
    if state.get("origin") != BASE_URL:
        return FlowError("login", "登录页面跳转到了非预期域名。")
    events = state.get("events", [])
    latest = events[-1] if events else {}
    phase = latest.get("phase") or state.get("phase")
    if latest.get("status") == 429:
        return FlowError("rate_limited", "网站限制请求频率，停止本次运行。")
    if latest and not 200 <= latest.get("status", 0) < 300:
        return FlowError("login", f"登录接口 HTTP {latest.get('status', 0)}，未确认登录。")
    if phase == "email_code":
        return FlowError("email_verification", "网站要求邮箱验证码，当前尚未配置邮箱验证码读取。")
    if phase == "totp":
        return FlowError("two_factor", "网站要求身份验证器动态码，当前尚未配置。")
    if phase == "reverse_email_verify":
        return FlowError("email_verification", "网站要求反向邮件验证，尚未完成。")
    if latest and phase != "authenticated":
        result = latest.get("result", "unknown")
        # Enum-like identifiers only; response messages can contain account data.
        result = result if re.fullmatch(r"[a-z_]{1,80}", result) else "unknown"
        return FlowError("login", f"网站拒绝登录，结果类型：{result}。")
    return None


def captcha_ready(driver) -> bool:
    return driver.execute_script(CAPTCHA_READY_JS, BASE_URL) is True


def wait_for(driver, predicate, seconds: float = 20):
    from selenium.common.exceptions import StaleElementReferenceException
    from selenium.webdriver.support.ui import WebDriverWait
    return WebDriverWait(driver, seconds, poll_frequency=0.25,
                         ignored_exceptions=(StaleElementReferenceException,)).until(predicate)


def clickable(driver, selector):
    for element in driver.find_elements("css selector", selector):
        if not element.is_displayed() or not element.is_enabled():
            continue
        if driver.execute_script("""
            const e=arguments[0],r=e.getBoundingClientRect();
            const hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);
            return !!hit && (hit===e || e.contains(hit));
        """, element):
            return element
    return False


def solve_captcha(driver, state: dict) -> None:
    from selenium.common.exceptions import TimeoutException
    from src.tasks import ikuuu_captcha as cap
    from src.tasks.ikuuu_recognition import RecognitionFailedError

    original_prompt = cap._prompt_text
    cap._prompt_text = lambda e: normalize_prompt(original_prompt(e))
    # Apply the exact same authoritative success criterion inside helper waits.
    cap._verified = captcha_ready

    def snapshot():
        # A blank panel and images can appear before the prompt. Give that
        # loading state time to settle instead of treating it as unsupported.
        if cap.visible_challenge(driver) not in (cap.CaptchaKind.WORD, cap.CaptchaKind.NINE):
            return None
        return cap._snapshot(driver)

    def changed(previous):
        if captcha_ready(driver):
            return "verified"
        current = snapshot()
        return current if current is not None and current != previous else False

    def ready_or_snapshot(_driver):
        return "verified" if captcha_ready(driver) else snapshot()

    for round_number in range(1, 6):
        challenge = wait_for(driver, ready_or_snapshot, 25)
        if challenge == "verified":
            state["verified"] = True
            return
        state.update(rounds=round_number, kind=challenge.kind.value)
        logging.info("本地验证码：第 %d/5 轮，%s。", round_number, challenge.kind.value)
        state["action"] = "predict"
        try:
            selected = cap._predict_challenge(challenge)
        except RecognitionFailedError:
            selected = None
        if selected is not None:
            if len(selected) != challenge.count or len(set(selected)) != challenge.count:
                raise FlowError("captcha", "本地模型未返回完整且唯一的选择结果。")
            for choice in selected:
                state["action"] = "click_choice"
                if cap._snapshot(driver) != challenge:
                    break  # Discard stale coordinates after an automatic refresh.
                cap._click_choice(driver, challenge, choice)
            else:
                def submit_ready(_driver):
                    next_state = changed(challenge)
                    if next_state:
                        return next_state
                    button = clickable(driver, ".geetest_submit")
                    if button and "geetest_disable" not in (button.get_attribute("class") or ""):
                        return button
                    return False

                try:
                    state["action"] = "submit_captcha"
                    button_or_state = wait_for(driver, submit_ready, 8)
                    if hasattr(button_or_state, "click") and cap._snapshot(driver) == challenge:
                        button_or_state.click()
                except TimeoutException:
                    pass  # It may auto-submit or refresh without a submit button.
            try:
                state["action"] = "wait_captcha_result"
                outcome = wait_for(driver, lambda d: changed(challenge), 15)
                if outcome == "verified":
                    state["verified"] = True
                    logging.info("网站已确认验证码有效。")
                    return
                continue  # Automatic next challenge: no competing refresh request.
            except TimeoutException:
                pass
        if round_number == 5:
            break
        # Low-confidence prediction or unchanged failed challenge: one refresh.
        # Recheck immediately before clicking, as the site may have auto-refreshed.
        outcome = changed(challenge)
        if outcome:
            if outcome == "verified":
                state["verified"] = True
                return
            continue
        refresh = wait_for(driver, lambda d: clickable(d, "button.geetest_refresh"), 5)
        state["action"] = "refresh_captcha"
        refresh.click()
        wait_for(driver, lambda d: changed(challenge), 20)
    raise FlowError("captcha", "已处理 5 轮图片验证，但网站未确认通过；停止本次运行。")


def create_driver():
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    chrome = os.environ.get("CHROME_BIN") or shutil.which("google-chrome") or shutil.which("chromium")
    chromedriver = os.environ.get("CHROMEDRIVER_PATH") or shutil.which("chromedriver")
    if not chrome or not chromedriver:
        raise FlowError("environment", "缺少 Chrome 或匹配的 ChromeDriver。")
    options = webdriver.ChromeOptions()
    options.binary_location = chrome
    for flag in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
                 "--window-size=1280,1000", "--lang=zh-CN"):
        options.add_argument(flag)
    options.add_experimental_option("prefs", {"intl.accept_languages": "zh-CN,zh,en"})
    driver = webdriver.Chrome(service=Service(chromedriver), options=options)
    driver.set_page_load_timeout(45)
    driver.set_script_timeout(35)
    return driver


def run_browser(account: dict, state: dict, *, probe_only: bool = False) -> dict:
    driver = None
    stage = "environment"
    try:
        driver = create_driver()
        stage = "login_page"
        logging.info("打开登录页并等待验证组件。")
        driver.get(BASE_URL + "/auth/login")
        if urlsplit(driver.current_url).netloc != urlsplit(BASE_URL).netloc:
            raise FlowError("login_page", "登录入口跳转到了非预期域名。")
        wait_for(driver, lambda d: d.execute_script(
            "return !!window.Captcha && !!window.Captcha.isLoaded() && !!window.jQuery"), 30)
        if not driver.execute_script(OBSERVE_LOGIN_JS, BASE_URL):
            raise FlowError("login_page", "登录页面接口发生变化，无法确认请求结果。")
        if not probe_only:
            for selector, value in (("#email", account["email"]), ("#password", account["password"])):
                field = wait_for(driver, lambda d: clickable(d, selector))
                field.clear()
                field.send_keys(value)
        stage = "captcha"
        logging.info("开始确认网站验证码结果。")
        if not captcha_ready(driver):
            button = wait_for(driver, lambda d: clickable(d, ".geetest_btn_click,.geetest_holder,.geetest_btn"))
            button.click()
            solve_captcha(driver, state)
        state["verified"] = captcha_ready(driver)
        if not state["verified"]:
            raise FlowError("captcha", "验证结果未就绪，尚未提交账号。")
        if probe_only:
            return {"success": False, "stage": "captcha_probe", "captcha_verified": True,
                    "message": "匿名验证码测试通过；未提交登录或签到。", "captcha": state}

        stage = "login"
        logging.info("验证码结果就绪，提交网站原生登录表单。")
        # Submit through the site's form so all current phase/CSRF/CAPTCHA fields
        # are generated by the page. Never invoke a stale protocol imitation.
        button = wait_for(driver, lambda d: clickable(d, "button.login[type='submit']"), 12)
        if not captcha_ready(driver):
            raise FlowError("captcha", "验证码在提交前已失效。")
        button.click()

        def completed(d):
            page = d.execute_script(PAGE_STATE_JS)
            if authenticated_page(page):
                return True
            failure = login_failure(page)
            if failure:
                raise failure
            return False

        wait_for(driver, completed, 35)
        logging.info("已确认进入同域已登录用户页面。")
        stage = "checkin"
        response = driver.execute_async_script(CHECKIN_JS, BASE_URL)
        if not isinstance(response, dict):
            raise FlowError("checkin", "签到接口未返回可识别结果。")
        if response.get("status") == 429:
            raise FlowError("rate_limited", "签到接口限制请求频率，停止本次运行。")
        ret, message = response.get("ret"), str(response.get("message", ""))
        if response.get("status") != 200 or response.get("error"):
            raise FlowError("checkin", "签到接口未返回成功的 JSON 响应，登录可能已失效。")
        return {"success": business_success(ret, message), "stage": stage, "ret": ret,
                "message": message or "没有收到明确签到结果。", "captcha": state}
    except FlowError as exc:
        return {"success": False, "stage": exc.stage, "kind": type(exc).__name__,
                "message": str(exc), "captcha": state}
    except Exception as exc:
        # Browser exceptions can include page source, URLs or element input values.
        # Emit only the exception type, never its potentially sensitive repr.
        frames = traceback.extract_tb(exc.__traceback__)
        logging.warning("失败位置：%s", " > ".join(
            f"{os.path.basename(f.filename)}:{f.lineno}:{f.name}" for f in frames[-8:]))
        logging.warning("验证码动作=%s，轮次=%s，网站确认=%s。",
                        state.get("action", "not_started"), state.get("rounds", 0), state.get("verified", False))
        return {"success": False, "stage": stage, "kind": type(exc).__name__,
                "message": f"{stage} 阶段未完成（{type(exc).__name__}）。", "captcha": state}
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass
