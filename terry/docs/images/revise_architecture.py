"""Generate one revised architecture illustration; resume its task on rerun."""
import importlib.util
import json
import os
from pathlib import Path
import urllib.request

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
prompt = '''Create a precise clean flat vector engineering architecture infographic, landscape 16:9, white background, navy text, teal and amber accents. Large readable English labels. Title: EEG-DRIVEN STEM MIXING. Main flow has three zones: INPUT, PYTHON BACKEND, BROWSER. INPUT: 16-channel EEG / BrainFlow and Synthetic model demo. Connect both to backend Quality checks -> Causal filtering -> Spectral features -> W / N1 / N2 + Future N2 -> Quality and baseline gate -> Music control. Music control sends JSON plans via WebSocket to browser Stem mixer. Four aligned WAV stems feed Stem mixer -> Per-stem gain + Low-pass -> Audio output. Label the four stem control roles EXACTLY: piano, strings, bass, pad. These are control roles, not verified source instrument identities. Use four plain boxes with these exact labels, no instrument icons, no additional stem names. Show a distinct amber branch Scripted showcase -> Preset probabilities -> Music control, bypassing models and baseline gate. Small bottom training panel: EDF + labels -> Subject-wise training -> Model files -> Classifier, with the model arrow feeding the W / N1 / N2 + Future N2 inference box. Show only these specified modules and connections; keep the figure focused entirely on EEG-driven mixing of four existing aligned stems. Footer: Research prototype. Preset demo is not a model prediction. No clinical efficacy established. Ample whitespace, restrained arrows, no invented metrics or decorative brain anatomy.'''
(OUT / 'architecture_v3.prompt.txt').write_text(prompt + '\n')
record = OUT / 'architecture_v3_task.json'
if record.exists():
    entry = json.loads(record.read_text())
else:
    record.write_text(json.dumps({'status': 'submission_pending'}))
    task = api.request_json('POST', '/images/generations', key, {'model': 'gpt-image-2', 'prompt': prompt, 'size': '16:9', 'resolution': '2K', 'quality': 'standard', 'n': 1})
    entry = {'id': task['id'], 'model': 'gpt-image-2', 'status': task.get('status')}
    record.write_text(json.dumps(entry, indent=2))
if 'id' not in entry:
    raise SystemExit('Unresolved submission: reconcile manually, do not resubmit')
if not entry.get('file'):
    print('Existing task:', entry['id'], flush=True)
    task = api.poll_task(entry['id'], key, 10, 1200)
    entry['status'] = task.get('status')
    record.write_text(json.dumps(entry, indent=2))
    if task.get('status') == 'completed':
        url = task['results'][0]
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'image/*'})
        with urllib.request.urlopen(req, timeout=120) as response:
            mime = response.headers.get_content_type()
            data = response.read(25000000)
        suffix = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp'}[mime]
        name = 'architecture_v3' + suffix
        (OUT / name).write_bytes(data)
        entry['file'] = name
        record.write_text(json.dumps(entry, indent=2))
        print('Saved:', name, flush=True)
