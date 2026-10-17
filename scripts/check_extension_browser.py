"""Load our extension in an isolated CI browser; never contact iKuuu or sign in."""
from pathlib import Path
import shutil
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait

ROOT = Path(__file__).resolve().parents[1]
options = webdriver.ChromeOptions()
options.binary_location = shutil.which('google-chrome') or shutil.which('chromium')
for flag in ('--headless=new','--no-sandbox','--disable-dev-shm-usage',
             '--window-size=900,900','--enable-unsafe-extension-debugging'):
    options.add_argument(flag)
driver = webdriver.Chrome(service=Service(shutil.which('chromedriver')), options=options)
try:
    loaded = driver.execute_cdp_cmd('Extensions.loadUnpacked', {'path':str(ROOT/'browser-extension')})
    extension_id = loaded['id']
    driver.get('chrome-extension://' + extension_id + '/popup.html')
    wait = WebDriverWait(driver,20)
    wait.until(lambda d: '先完成 GitHub 配置' in d.find_element('id','status').text)
    assert driver.find_element('id','repo').get_attribute('value') == 'justzoe3/sign_ikuuu'
    assert driver.find_element('id','token').get_attribute('value') == ''
    driver.find_element('id','sync').click()
    wait.until(lambda d: '先配置 GitHub' in d.find_element('id','status').text)
    permissions = driver.execute_async_script(
        'const done=arguments[arguments.length-1];chrome.permissions.getAll(done);')
    assert set(permissions['permissions']) == {'cookies','storage','alarms'}
    assert set(permissions['origins']) == {'https://ikuuu.top/*','https://api.github.com/*'}
    output = ROOT/'integration'
    output.mkdir(exist_ok=True)
    driver.save_screenshot(str(output/'extension-popup.png'))
    print('Real Chrome: unpacked extension loaded, service worker responded, popup controls worked, host permissions verified. No website login or real session used.')
finally:
    driver.quit()
