"""Check extension behavior and LibSodium compatibility with generated test data."""
import base64
import json
from pathlib import Path
import subprocess
import tempfile
from nacl.public import PrivateKey, SealedBox

ROOT = Path(__file__).resolve().parents[1]
key = PrivateKey.generate()
with tempfile.TemporaryDirectory(prefix='ikuuu-extension-check-') as directory:
    fixture = Path(directory) / 'fixture.json'
    result = Path(directory) / 'result.json'
    fixture.write_text(json.dumps({'public_key':base64.b64encode(bytes(key.public_key)).decode()}))
    subprocess.run(['node', str(ROOT/'tests/test_extension.cjs'), str(fixture), str(result)], check=True)
    data = json.loads(result.read_text())
    assert SealedBox(key).decrypt(base64.b64decode(data['encrypted'])).decode() == data['expected']
print('GitHub LibSodium sealed-box compatibility: passed (generated test session only).')
