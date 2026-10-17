"""Run the standalone browser flow against a local test site, using fake data."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import shutil
import threading
import ikuuu_browser as client

scenario = 'success'
login_posts = 0
checkin_posts = 0

class Fixture(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def send(self, body, kind='text/html', headers=None):
        data = body.encode()
        self.send_response(200)
        self.send_header('Content-Type', kind)
        for name,value in (headers or {}).items(): self.send_header(name,value)
        self.send_header('Content-Length',str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == '/user':
            assert 'fixture_session=1' in self.headers.get('Cookie','')
            self.send('<html><a href="/auth/logout">Logout</a><p>Fixture user</p></html>')
            return
        ready = 'false' if scenario == 'forbidden' else 'true'
        html = '''<html><body><form><input id="email" type="email"><input id="password" type="password">
          <div class="geetest_btn_click" style="width:300px;height:50px;background:#ddd">Fixture verification</div>
          <button class="login" type="submit">Login</button></form><script>
          var loginPhase='password';
          window.Captcha={isLoaded:()=>true,isReady:()=>READY,
            getResponse:()=>({lot_number:'fixture',captcha_output:'fixture',pass_token:'fixture',gen_time:'1'})};
          window.jQuery=()=>({off(){return this},on(_name,cb){window.observer=cb;return this}});
          document.querySelector('.geetest_btn_click').onclick=()=>{
            const e=document.createElement('div');e.className='geetest_captcha geetest_lock_error';
            e.textContent='极验封禁 60500';document.body.appendChild(e);
          };
          document.querySelector('form').onsubmit=async event=>{
            event.preventDefault();
            const r=await fetch('/auth/login',{method:'POST',body:'fixture=true'});
            const data=await r.json();loginPhase=data.phase;
            if(window.observer)window.observer(null,{status:r.status,responseJSON:data},{url:'/auth/login',type:'POST'});
            if(data.phase==='authenticated')location.assign('/user');
          };
          </script></body></html>'''.replace('READY',ready)
        self.send(html)

    def do_POST(self):
        global login_posts,checkin_posts
        self.rfile.read(int(self.headers.get('Content-Length','0')))
        if self.path == '/auth/login':
            login_posts += 1
            phase='email_code' if scenario=='email_code' else 'authenticated'
            self.send(json.dumps({'phase':phase,'result':'verification_required'}),
                      'application/json',{'Set-Cookie':'fixture_session=1; HttpOnly; Path=/'})
        elif self.path == '/user/checkin':
            checkin_posts += 1
            assert 'fixture_session=1' in self.headers.get('Cookie','')
            # Legacy PHP sites can return JSON with a text/html content type.
            self.send(json.dumps({'ret':1,'msg':'fixture check-in confirmed'}),'text/html')
        else:
            self.send('{}','application/json')

server=ThreadingHTTPServer(('127.0.0.1',0),Fixture)
threading.Thread(target=server.serve_forever,daemon=True).start()
client.BASE_URL=f'http://127.0.0.1:{server.server_port}'
os.environ['CHROME_BIN']=shutil.which('google-chrome') or shutil.which('chromium') or ''
os.environ['CHROMEDRIVER_PATH']=shutil.which('chromedriver') or ''
try:
    for case,expected in [('success','checkin'),('email_code','email_verification'),('forbidden','captcha_blocked')]:
        scenario=case
        login_posts=checkin_posts=0
        result=client.run_browser({'email':'fixture@example.invalid','password':'fixture-only'}, {})
        assert result['stage']==expected, (case,result)
        assert result['success'] is (case=='success'), (case,result)
        if case=='success': assert login_posts==1 and checkin_posts==1
        if case=='email_code': assert login_posts==1 and checkin_posts==0
        if case=='forbidden': assert login_posts==0 and checkin_posts==0
        print(f'Real Chrome local fixture passed: {case}.')
    print('All browser flows tested locally with generated fixture data; no iKuuu request or real account used.')
finally:
    server.shutdown()
