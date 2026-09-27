"""Generate two authorized documentation illustrations; resume recorded tasks, never auto-retry POST."""
import importlib.util
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

api = load('aisaago_docs', ROOT / 'script/aisaago.py')
config = load('local_env_docs', ROOT / 'backEnd/src/anphy_sleep/config.py')
config.load_local_env(ROOT / 'backEnd')
key = os.environ.get('AISAASGO_API_KEY')
if not key:
    raise SystemExit('Missing AISAASGO_API_KEY; no requests submitted')

prompts = {
    'architecture': '''Create a precise clean flat vector engineering infographic, landscape 16:9, white background, navy text, teal and amber accents. Title: EEG TO ADAPTIVE AUDIO. Use only these short English labels, large readable typography. Three horizontal zones: INPUT, PYTHON BACKEND, BROWSER. INPUT has two sources: 16-channel EEG / BrainFlow and Synthetic demo. Both connect to backend boxes Quality checks -> Causal filtering -> Spectral features -> W / N1 / N2 + Future N2 -> Music control. Browser receives JSON plans via WebSocket. Split browser playback into two clearly separate paths: Four WAV stems -> Gain + low-pass -> Audio output; Uploaded WAV + Synth notes -> Mixer -> Audio output. Small separate amber branch: Scripted showcase -> Preset probabilities -> Music control, explicitly bypassing classifier. Bottom side panel: Offline EDF + labels -> Subject-wise training -> Model files -> Classifier. Footer: Research prototype. Scripted probabilities are not model predictions. No efficacy claims. Do not add brain anatomy, graphs of accuracy, invented statistics, cloud inference, MIDI on the stem path, logos or decorative arrows. Make architecture easy to read with ample whitespace.''',
    'ml_pipeline': '''Create a clean publication-style explanatory infographic, landscape 16:9, white background, navy text and muted teal, readable large English labels. Title: TWO EEG MACHINE LEARNING TASKS. Two separated horizontal swimlanes. Top lane OFFLINE TRAINING: EDF + sleep labels -> 16 channels / 250 Hz -> Average reference / 50 Hz notch / Causal 5-50 Hz bandpass -> 6 s windows / 3 s step -> Welch band powers / Regional log features / Past-only slopes -> Subject-wise validation -> Saved models. Bottom lane ONLINE INFERENCE: Live chunks -> Quality checks -> Stateful causal filter -> Same feature definitions -> Two parallel boxes: W / N1 / N2 probabilities; First stable N2 within 5 min -> Baseline and quality gate -> Music control. Add a separate small baseline box: 300 s robust baseline, used for music gating, not a direct classifier input. Add footer notes: No N3 or REM classification. No clinical efficacy established. Scripted showcase bypasses these models. Draw only conceptual pipeline boxes and arrows, no numerical performance chart, no invented brain map, no claims of validated train-stream equivalence. Keep training and online lanes clearly distinct.'''
}
manifest_path = OUT / 'generation_tasks.json'
manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
for name, prompt in prompts.items():
    (OUT / f'{name}.prompt.txt').write_text(prompt + '\n')
    if name not in manifest:
        # Mark intent before POST: uncertain network outcomes require manual reconciliation.
        manifest[name] = {'status': 'submission_pending', 'model': 'gpt-image-2'}
        manifest_path.write_text(json.dumps(manifest, indent=2))
        try:
            task = api.request_json('POST', '/images/generations', key, {'model': 'gpt-image-2', 'prompt': prompt, 'size': '16:9', 'resolution': '2K', 'quality': 'standard', 'n': 1})
            manifest[name] = {'id': task['id'], 'status': task.get('status'), 'model': 'gpt-image-2'}
            manifest_path.write_text(json.dumps(manifest, indent=2))
        except Exception as exc:
            print(name, 'submission unresolved:', type(exc).__name__, flush=True)
            continue
    entry = manifest[name]
    if 'id' not in entry or entry.get('file') or entry.get('status') == 'failed':
        continue
    print(name, 'task', entry['id'], flush=True)
    try:
        task = api.poll_task(entry['id'], key, 10, 1200)
        entry['status'] = task.get('status')
        if entry['status'] == 'completed':
            files = api.download_results(task, OUT)
            if files:
                target = OUT / (name + files[0].suffix)
                files[0].replace(target)
                entry['file'] = target.name
        manifest_path.write_text(json.dumps(manifest, indent=2))
        print(name, entry['status'], entry.get('file', ''), flush=True)
    except Exception as exc:
        manifest_path.write_text(json.dumps(manifest, indent=2))
        print(name, 'resume required:', type(exc).__name__, getattr(exc, 'code', ''), flush=True)
