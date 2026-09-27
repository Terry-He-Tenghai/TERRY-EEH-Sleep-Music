"""Download already-created image tasks only; no generation POST requests."""
import importlib.util
import json
import os
from pathlib import Path
import urllib.request
import urllib.parse

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

api = load('image_api', ROOT / 'script/aisaago.py')
config = load('env_config', ROOT / 'backEnd/src/anphy_sleep/config.py')
config.load_local_env(ROOT / 'backEnd')
key = os.environ['AISAASGO_API_KEY']
manifest_path = OUT / 'generation_tasks.json'
manifest = json.loads(manifest_path.read_text())
for name, entry in manifest.items():
    if entry.get('file'):
        continue
    task = api.request_json('GET', '/tasks/' + entry['id'], key, retries=2)
    for url in (task.get('results') or [])[:1]:
        print(name, 'download host:', urllib.parse.urlparse(url).hostname, flush=True)
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'image/avif,image/webp,image/png,image/*;q=0.8,*/*;q=0.5'})
            with urllib.request.urlopen(req, timeout=120) as response:
                data = response.read(25000000)
                mime = response.headers.get_content_type()
            suffix = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp'}.get(mime)
            if not suffix:
                print('Unexpected response type:', mime)
                continue
            path = OUT / (name + suffix)
            path.write_bytes(data)
            entry['file'] = path.name
            manifest_path.write_text(json.dumps(manifest, indent=2))
            print(name, 'saved', path.name, len(data), flush=True)
        except Exception as exc:
            print(name, type(exc).__name__, getattr(exc, 'code', ''), flush=True)
