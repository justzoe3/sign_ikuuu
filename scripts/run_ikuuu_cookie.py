"""Sign in using an existing session; never start an automatic login attempt."""
from __future__ import annotations
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from urllib.parse import unquote, urlsplit
from ikuuu_browser import business_success


def normalize_cookie(raw: str) -> str:
    raw = raw.strip()
    if raw.lower().startswith('cookie:'):
        raw = raw[7:].strip()
    if raw.startswith('['):
        try:
            entries = json.loads(raw)
        except ValueError:
            raise ValueError('Cookie JSON 格式不正确。') from None
        if not isinstance(entries, list):
            raise ValueError('Cookie JSON 应为浏览器导出的 Cookie 列表。')
        pairs = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            domain = str(entry.get('domain', '')).lstrip('.')
            if domain != 'ikuuu.top':
                continue
            name, value = entry.get('name'), entry.get('value')
            if isinstance(name, str) and isinstance(value, str):
                pairs.append(f'{name}={value}')
        raw = '; '.join(pairs)
    if not raw:
        raise ValueError('缺少 IKUUU_COOKIE：需要一份已正常登录的 iKuuu 会话。')
    if '\r' in raw or '\n' in raw or len(raw) > 16384:
        raise ValueError('Cookie 必须是一行请求头，长度不超过 16 KB。')
    fields = {}
    for part in raw.split(';'):
        if not part.strip():
            continue
        name, sep, value = part.strip().partition('=')
        if not sep or not re.fullmatch(r'[A-Za-z0-9_\-]+', name):
            raise ValueError('Cookie 字段格式不正确。')
        fields[name] = value
    if not fields.get('uid') or not fields.get('key'):
        raise ValueError('当前会话缺少 uid/key，请在 iKuuu 正常登录后重新同步。')
    return raw


def configuration() -> tuple[str, str]:
    cookie = normalize_cookie(os.environ.get('IKUUU_COOKIE', ''))
    base = os.environ.get('IKUUU_BASE_URL', 'https://ikuuu.top').strip().rstrip('/')
    parsed = urlsplit(base)
    if (parsed.scheme != 'https' or parsed.netloc != 'ikuuu.top'
            or parsed.path or parsed.query or parsed.fragment):
        raise ValueError('签到目标只能是 https://ikuuu.top。')
    return cookie, base


def redact(text: str, cookie: str) -> str:
    values = {cookie}
    for part in cookie.split(';'):
        if '=' in part:
            value = part.strip().split('=', 1)[1]
            if len(value) >= 4:
                values.update((value, unquote(value)))
    for value in sorted(values, key=len, reverse=True):
        text = text.replace(value, '[已隐藏]')
    text = re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', '[邮箱已隐藏]', text)
    return re.sub(r'(?i)\b(uid|key|PHPSESSID|session_version)=[^\s;,]+', r'\1=[已隐藏]', text)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def checkin(cookie: str, base: str, opener=None) -> dict:
    request = urllib.request.Request(base + '/user/checkin', data=b'', method='POST', headers={
        'Cookie': cookie, 'Origin': base, 'Referer': base + '/user',
        'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest',
        'User-Agent': 'iKuuu-GitHub-Actions/1.0'})
    try:
        with (opener or urllib.request.build_opener(NoRedirect())).open(request, timeout=30) as response:
            raw = response.read(65537)
            status = response.status
        if len(raw) > 65536:
            return {'success': False, 'stage': 'response', 'message': '签到响应过大，未确认结果。'}
        try:
            data = json.loads(raw.decode('utf-8-sig'))
        except (ValueError, UnicodeError):
            return {'success': False, 'stage': 'session', 'message': '签到返回了非 JSON 内容，登录会话可能已失效。'}
        if status != 200 or not isinstance(data, dict):
            return {'success': False, 'stage': 'response', 'message': '签到接口未返回成功的结构化结果。'}
        message = str(data.get('msg', ''))[:500]
        success = business_success(data.get('ret'), message)
        return {'success': success, 'stage': 'checkin', 'ret': data.get('ret'),
                'message': message or '网站未返回明确签到结果。'}
    except urllib.error.HTTPError as error:
        if error.code in (301,302,303,307,308,401):
            return {'success': False, 'stage': 'session', 'message': '登录会话已失效，请在本机正常登录并同步。'}
        if error.code == 429:
            return {'success': False, 'stage': 'rate_limited', 'message': '网站限制请求频率，本次没有重试。'}
        return {'success': False, 'stage': 'http', 'message': f'签到请求 HTTP {error.code}，未确认成功。'}
    except (OSError, TimeoutError):
        return {'success': False, 'stage': 'network', 'message': '签到网络请求失败或超时，本次没有重试。'}


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument('--check-config', action='store_true')
    args=parser.parse_args()
    try:
        cookie, base=configuration()
    except ValueError as error:
        print(f'::error::{error}')
        return 1
    if args.check_config:
        print('会话格式通过；登录有效性将在签到时验证。')
        return 0
    result=checkin(cookie,base)
    message=redact(result['message'],cookie)
    label='✅' if result['success'] else '❌'
    detail=f'{label} iKuuu 签到：{message}（阶段：{result["stage"]}）'
    print(detail)
    summary=os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary,'a',encoding='utf-8') as output:
            output.write('## '+detail+'\n\n结果以网站响应为准。失效的会话需要在本机重新登录并同步。\n')
    if not result['success']:
        print('::error::网站没有确认签到成功。')
    return 0 if result['success'] else 1


if __name__=='__main__':
    sys.exit(main())
