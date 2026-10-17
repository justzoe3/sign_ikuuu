"""Load our extension in isolated Chrome for Testing; never contact iKuuu."""
from pathlib import Path
import os
import tempfile
import urllib.request
import zipfile
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait

ROOT = Path(__file__).resolve().parents[1]
VERSION = '155.0.8059.84'
with tempfile.TemporaryDirectory(prefix='ikuuu-extension-browser-') as temporary:
    folder = Path(temporary)
    for kind in ('chrome','chromedriver'):
        # Official Chrome for Testing distribution, pinned to the version tested.
        url = f'https://storage.googleapis.com/chrome-for-testing-public/{VERSION}/linux64/{kind}-linux64.zip'
        archive = folder / (kind+'.zip')
        urllib.request.urlretrieve(url, archive)
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                destination = (folder/info.filename).resolve()
                assert destination.is_relative_to(folder.resolve())
                z.extract(info, folder)
                mode = (info.external_attr >> 16) & 0o777
                if mode:
                    os.chmod(destination, mode)
        archive.unlink()
    options = webdriver.ChromeOptions()
    options.binary_location = str(folder/'chrome-linux64/chrome')
    for flag in ('--headless=new','--no-sandbox','--disable-dev-shm-usage',
                 '--window-size=900,900', '--load-extension='+str(ROOT/'browser-extension'),
                 '--disable-extensions-except='+str(ROOT/'browser-extension')):
        options.add_argument(flag)
    driver = webdriver.Chrome(service=Service(str(folder/'chromedriver-linux64/chromedriver')), options=options)
    try:
        wait = WebDriverWait(driver,20)
        def worker(d):
            for target in d.execute_cdp_cmd('Target.getTargets',{})['targetInfos']:
                url = target.get('url','')
                if url.startswith('chrome-extension://') and url.endswith('/background.js'):
                    return url.split('/')[2]
            return False
        extension_id = wait.until(worker)
        driver.get('chrome-extension://' + extension_id + '/popup.html')
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
