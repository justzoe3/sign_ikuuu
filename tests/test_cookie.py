import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock
from urllib.error import HTTPError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from run_ikuuu_cookie import checkin,normalize_cookie,redact

class CookieTests(unittest.TestCase):
    def test_cookie_header(self):
        self.assertEqual(normalize_cookie('Cookie: uid=fixture; key=session'), 'uid=fixture; key=session')

    def test_empty_optional_cookie_value_is_valid(self):
        self.assertEqual(normalize_cookie('uid=fixture; key=session; preference='),
                         'uid=fixture; key=session; preference=')

    def test_cookie_editor_json_is_domain_scoped(self):
        raw=json.dumps([{'domain':'.ikuuu.top','name':'uid','value':'fixture'},
            {'domain':'ikuuu.top','name':'key','value':'session'},
            {'domain':'elsewhere.invalid','name':'password','value':'foreign'}])
        normalized=normalize_cookie(raw)
        self.assertIn('uid=fixture',normalized)
        self.assertNotIn('foreign',normalized)

    def test_missing_or_injected_header(self):
        for raw in ('','uid=fixture','uid=fixture; key=session\r\nX-Extra: yes'):
            with self.subTest(raw=raw),self.assertRaises(ValueError):normalize_cookie(raw)

    def transport(self,body,status=200):
        response=Mock(status=status)
        response.read.return_value=body
        response.__enter__=Mock(return_value=response)
        response.__exit__=Mock(return_value=False)
        opener=Mock()
        opener.open.return_value=response
        return opener

    def test_server_success(self):
        opener=self.transport(b'{"ret":1,"msg":"fixture success"}')
        self.assertTrue(checkin('uid=fixture; key=session','https://ikuuu.top',opener)['success'])
        request=opener.open.call_args.args[0]
        self.assertEqual(request.full_url,'https://ikuuu.top/user/checkin')
        self.assertEqual(request.method,'POST')

    def test_server_already_checked_in(self):
        body=json.dumps({'ret':0,'msg':'今天已签到'}).encode()
        self.assertTrue(checkin('uid=fixture; key=session','https://ikuuu.top',self.transport(body))['success'])

    def test_false_green_responses(self):
        for body in (b'<html>Login</html>',b'{"ret":true,"msg":"ok"}',b'{"ret":0,"msg":"Login required"}',b'[]'):
            with self.subTest(body=body):
                self.assertFalse(checkin('uid=fixture; key=session','https://ikuuu.top',self.transport(body))['success'])

    def test_redirect_does_not_leak_cookie(self):
        opener=Mock()
        opener.open.side_effect=HTTPError('https://ikuuu.top/user/checkin',302,'Found',{},None)
        result=checkin('uid=fixture; key=session','https://ikuuu.top',opener)
        self.assertFalse(result['success'])
        self.assertEqual(result['stage'],'session')
        self.assertEqual(opener.open.call_count,1)

    def test_rate_limit_is_not_retried(self):
        opener=Mock()
        opener.open.side_effect=HTTPError('https://ikuuu.top/user/checkin',429,'Too many',{},None)
        result=checkin('uid=fixture; key=session','https://ikuuu.top',opener)
        self.assertEqual(result['stage'],'rate_limited')
        self.assertEqual(opener.open.call_count,1)

    def test_cookie_redaction(self):
        result=redact('uid=fixture key=session user@example.invalid','uid=fixture; key=session')
        self.assertNotIn('fixture',result)
        self.assertNotIn('session',result)
        self.assertNotIn('@',result)

if __name__=='__main__':unittest.main()
