"""Protocol-specific observational metrics and participant-level comparisons."""
import math
import csv
import io
import numpy as np
from scipy import stats

CONDITIONS = ('fixed', 'sham', 'closed_loop')
METRICS = {
    'lseq_gts': ('LSEQ GTS', '0–100', 'higher'),
    'relaxation_vas': ('放松 VAS', '0–10', 'higher'),
    'sleep_difficulty_vas': ('入睡困难 VAS（补充）', '0–10', 'lower'),
    'kss_change': ('KSS 后 − 前', '分', 'descriptive'),
    'sus_score': ('SUS 系统可用性', '0–100', 'higher'),
    'transition_naturalness_vas': ('过渡自然度 VAS（非 SUS）', '0–10', 'higher'),
    'minimal_motion_latency_s': ('连续 5 分钟低活动潜伏期', 's', 'descriptive'),
    'alpha_change_uv2': ('α 功率 实验 − 基线', 'μV²', 'descriptive'),
    'theta_change_uv2': ('θ 功率 实验 − 基线', 'μV²', 'descriptive'),
    'alpha_8_12_change_uv2': ('α 8–12 Hz 功率 实验 − 基线', 'μV²', 'descriptive'),
    'alpha_relative_change': ('α 8–12 Hz 相对功率变化', '比例', 'descriptive'),
    'theta_relative_change': ('θ 4–8 Hz 相对功率变化', '比例', 'descriptive'),
    'rms_change_db': ('平均绝对 RMS 变化', 'dB', 'lower'),
    'fallback_proportion': ('已观测控制时段回退比例', '比例', 'lower'),
    'classification_ms': ('分类耗时（非端到端延迟）', 'ms', 'lower'),
    'qualified_window_ratio': ('合格重叠窗口比例', '比例', 'higher'),
    'backend_cpu_mean_percent': ('后端进程平均 CPU（单核=100%）', '%', 'descriptive'),
    'backend_process_peak_rss_mb': ('后端进程生命周期峰值内存', 'MiB', 'descriptive'),
    'musicality': ('盲听音乐性', '1–7', 'higher'),
    'songeval_musicality': ('SongEval 音乐性（探索性）', '1–5', 'descriptive'),
}


def finite(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def mean(values):
    valid = [v for v in values if finite(v)]
    return float(np.mean(valid)) if valid else None


def difference(a, b):
    return a - b if finite(a) and finite(b) else None


def phase_bounds(label, phase):
    start, end = label.get(f'{phase}_start_s'), label.get(f'{phase}_end_s')
    return (start, end) if finite(start) and finite(end) and end > start else None


def inside(time, bounds):
    return bounds is not None and finite(time) and bounds[0] <= time < bounds[1]


def validate_physiology(data):
    if not isinstance(data, dict) or not isinstance(data.get('samples'), list):
        raise ValueError('Expected a samples array')
    if not isinstance(data.get('source'), str) or not data['source'].strip() or len(data['source']) > 200:
        raise ValueError('Device/source is required (max 200 characters)')
    samples = data['samples']
    if not 1 <= len(samples) <= 100000:
        raise ValueError('Expected 1–100000 samples')
    allowed = {'time_s', 'heart_rate_bpm', 'rr_ms', 'motion'}
    previous = -1
    clean = []
    for sample in samples:
        if not isinstance(sample, dict) or set(sample) - allowed:
            raise ValueError('Allowed columns: time_s, heart_rate_bpm, rr_ms, motion')
        t = sample.get('time_s')
        if not finite(t) or t < 0 or t <= previous:
            raise ValueError('time_s must be strictly increasing, nonnegative seconds from EEG session start')
        previous = t
        row = {'time_s': t}
        for key, limits in [('heart_rate_bpm', (20, 250)), ('rr_ms', (200, 3000)), ('motion', (0, 1e12))]:
            v = sample.get(key)
            if v is not None and (not finite(v) or not limits[0] <= v <= limits[1]):
                raise ValueError(f'Invalid {key}; missing values must be null')
            row[key] = v
        clean.append(row)
    return {'source': data['source'], 'samples': clean, 'time_origin': 'EEG session start',
            'rr_scope': 'Consecutive NN intervals required; uncorrected RR is exploratory only'}


def parse_physiology_csv(payload):
    reader = csv.DictReader(io.StringIO(payload.decode('utf-8-sig')), strict=True)
    headers = reader.fieldnames or []
    allowed = {'time_s', 'heart_rate_bpm', 'rr_ms', 'motion'}
    if 'time_s' not in headers or set(headers) - allowed or len(set(headers)) != len(headers):
        raise ValueError('CSV columns: time_s, heart_rate_bpm, rr_ms, motion; blanks are missing')
    samples = []
    for row in reader:
        if None in row or any(v is None for v in row.values()):
            raise ValueError('Inconsistent CSV columns')
        samples.append({k: float(v) if v.strip() else None for k, v in row.items()})
        if len(samples) > 100000:
            raise ValueError('Expected at most 100000 samples')
    return validate_physiology({'source': 'Aligned local physiology CSV', 'samples': samples})


def rmssd(samples, bounds):
    # Missing intervals break pairs. Large timing gaps must not create artificial adjacency.
    pairs = []
    for a, b in zip(samples, samples[1:]):
        if not inside(a['time_s'], bounds) or not inside(b['time_s'], bounds):
            continue
        if finite(a.get('rr_ms')) and finite(b.get('rr_ms')) and b['time_s'] - a['time_s'] <= 2 * b['rr_ms'] / 1000:
            pairs.append((b['rr_ms'] - a['rr_ms']) ** 2)
    return float(np.sqrt(np.mean(pairs))) if pairs else None


def motion_latency(samples, bounds, threshold, max_gap):
    if bounds is None or not finite(threshold):
        return None
    start = previous = None
    for row in samples:
        t = row['time_s']
        if not inside(t, bounds):
            continue
        if not finite(row.get('motion')) or row['motion'] > threshold:
            start = previous = None
            continue
        if previous is None or t - previous > max_gap:
            start = t
        previous = t
        if t - start >= 300:
            return start - bounds[0]
    return None


def protocol_metrics(report):
    label = report.get('experiment') or {}
    baseline, intervention = [phase_bounds(label, p) for p in ('baseline', 'intervention')]
    samples = (report.get('physiology') or {}).get('samples', [])
    windows = sorted(report.get('windows', []), key=lambda w: w.get('timestamp_s') or 0)
    items = label.get('lseq_gts_items') or [None] * 3
    result = {key: label.get(key) for key in ('visit', 'sequence', 'protocol_version', 'condition_verified',
              'trial_status', 'sham_trajectory_id', 'prior_sleep_hours', 'caffeine_mg', 'medication_notes',
              'adverse_event', 'sound_pressure_dba', 'audio_material_id', 'relaxation_vas', 'sleep_difficulty_vas',
              'kss_before', 'kss_after', 'transition_naturalness_vas', 'baseline_start_s', 'baseline_end_s', 'intervention_start_s', 'intervention_end_s')}
    sus = label.get('sus_items') or [None] * 10
    result['sus_score'] = 2.5 * sum(v - 1 if i % 2 == 0 else 5 - v for i, v in enumerate(sus)) if len(sus) == 10 and all(finite(v) and 1 <= v <= 5 for v in sus) else None
    result.update({f'sus_{i+1}': v for i, v in enumerate(sus)})
    result.update(lseq_gts=mean(items) if len(items) == 3 and all(finite(v) for v in items) else None,
                  kss_change=difference(label.get('kss_after'), label.get('kss_before')),
                  physiology_source=(report.get('physiology') or {}).get('source'),
                  minimal_motion_latency_s=motion_latency(samples, intervention, label.get('motion_threshold'), label.get('motion_max_gap_s', 2)))
    for i, item in enumerate(items):
        result[f'lseq_gts_{i+1}'] = item
    for name, bounds in [('baseline', baseline), ('intervention', intervention)]:
        values = [s.get('heart_rate_bpm') for s in samples if inside(s['time_s'], bounds)]
        result[f'heart_rate_{name}_bpm'] = mean(values)
        result[f'rmssd_{name}_ms'] = rmssd(samples, bounds)
        for band in ('alpha', 'theta', 'alpha_8_12'):
            # A window end in a phase is insufficient: exclude windows crossing its boundary.
            powers = [mean((w.get('band_power_uv2') or {}).get('values', {}).get(band, []))
                      for w in windows if w.get('signal_quality') == 1 and inside(w.get('timestamp_s'), bounds)
                      and w['timestamp_s'] - 40 >= bounds[0]]
            result[f'{band}_{name}_uv2'] = mean(powers)
        for band in ('alpha', 'theta'):
            result[f'{band}_{name}_relative'] = mean([
                mean((w.get('band_power_uv2') or {}).get('relative', {}).get(band, []))
                for w in windows if w.get('signal_quality') == 1 and inside(w.get('timestamp_s'), bounds)
                and w['timestamp_s'] - 40 >= bounds[0]])
    result['heart_rate_change_bpm'] = difference(result['heart_rate_intervention_bpm'], result['heart_rate_baseline_bpm'])
    result['rmssd_change_ms'] = difference(result['rmssd_intervention_ms'], result['rmssd_baseline_ms'])
    for band in ('alpha', 'theta', 'alpha_8_12'):
        result[f'{band}_change_uv2'] = difference(result[f'{band}_intervention_uv2'], result[f'{band}_baseline_uv2'])
    for band in ('alpha', 'theta'):
        result[f'{band}_relative_change'] = difference(result[f'{band}_intervention_relative'], result[f'{band}_baseline_relative'])
    # Audio clock and acquisition clock require explicit synchronization; do not assume t=0 matches.
    frames = ((report.get('audio') or {}).get('metrics') or {}).get('frames', [])
    result['rms_change_db'] = mean([abs(b['rms_dbfs'] - a['rms_dbfs']) for a, b in zip(frames, frames[1:])
                                  if finite(a.get('rms_dbfs')) and finite(b.get('rms_dbfs'))])
    covered = fallback = 0.
    control_windows = report.get('control_windows', []) if label.get('condition') == 'sham' else windows
    for a, b in zip(control_windows, control_windows[1:]):
        if not finite(a.get('timestamp_s')) or not finite(b.get('timestamp_s')):
            continue
        dt = b['timestamp_s'] - a['timestamp_s']
        if label.get('condition') != 'fixed' and 0 < dt <= 12 and (a.get('source') == 'LIVE' or (label.get('condition') == 'sham' and a.get('demo_scripted'))) and a.get('status') in ('ready', 'frozen') and intervention:
            dt = max(0, min(b['timestamp_s'], intervention[1]) - max(a['timestamp_s'], intervention[0]))
            covered += dt
            if a.get('status') == 'frozen':
                fallback += dt
    result.update(fallback_proportion=fallback / covered if covered else None,
                  fallback_observed_s=covered, fallback_seconds=fallback if covered else None,
                  fallback_scope='Observed ready/frozen control intervals within intervention; gaps >12s excluded; fixed external audio not measured',
                  rms_change_scope='Uploaded audio; phase alignment not verified',
                  motion_event_observed=(result['minimal_motion_latency_s'] is not None
                                         if intervention and finite(label.get('motion_threshold')) and any(
                                             inside(s['time_s'], intervention) and finite(s.get('motion')) for s in samples)
                                         else None),
                  motion_observation_scope='No detected run is not evidence of no event when coverage is incomplete')
    return result


def describe(values):
    values = [v for v in values if finite(v)]
    return {'n': len(values), 'mean': mean(values),
            'sd': float(np.std(values, ddof=1)) if len(values) > 1 else None,
            'median': float(np.median(values)) if values else None}


def analyze_cohort(rows, include_demo=False):
    enrolled = [r for r in rows if r.get('participant') and r.get('condition') in CONDITIONS and (include_demo or r.get('mode') == 'brainflow')]
    eligible = [r for r in enrolled if r.get('ended') and r.get('trial_status') == 'completed' and r.get('condition_verified')
                and r.get('end_reason') not in ('acquisition_error', 'inference_error', 'unexpected_end')]
    ids = sorted({r['participant'] for r in enrolled})
    participants = []
    for identifier in ids:
        conditions = {}
        for condition in CONDITIONS:
            all_rows = [r for r in enrolled if r['participant'] == identifier and r['condition'] == condition]
            valid = [r for r in eligible if r['participant'] == identifier and r['condition'] == condition]
            conditions[condition] = {'sessions': len(all_rows), 'eligible_sessions': len(valid),
                                     'metrics': {key: mean([r.get(key) for r in valid]) for key in METRICS}}
        participants.append({'participant': identifier, 'conditions': conditions,
                             'complete': all(conditions[c]['eligible_sessions'] for c in CONDITIONS)})
    metrics = {}
    for key, (label, unit, direction) in METRICS.items():
        triples = [[p['conditions'][c]['metrics'][key] for c in CONDITIONS] for p in participants]
        complete = [v for v in triples if all(finite(x) for x in v)]
        omnibus = None
        if len(complete) >= 3 and any(len(set(v)) > 1 for v in complete):
            test = stats.friedmanchisquare(*np.asarray(complete).T)
            if finite(float(test.pvalue)):
                omnibus = {'method': 'Friedman', 'n': len(complete), 'statistic': float(test.statistic), 'p': float(test.pvalue)}
        paired = {}
        for control in ('fixed', 'sham'):
            differences = [p['conditions']['closed_loop']['metrics'][key] - p['conditions'][control]['metrics'][key]
                           for p in participants if finite(p['conditions']['closed_loop']['metrics'][key])
                           and finite(p['conditions'][control]['metrics'][key])]
            pvalue = None
            if len(differences) >= 3:
                pvalue = float(stats.wilcoxon(differences, method='auto').pvalue) if any(differences) else 1.
            paired[control] = {**describe(differences), 'p': pvalue, 'p_holm': None, 'method': 'Wilcoxon signed-rank'}
        metrics[key] = {'label': label, 'unit': unit, 'direction': direction,
                        'groups': {c: describe([p['conditions'][c]['metrics'][key] for p in participants]) for c in CONDITIONS},
                        'complete_n': len(complete), 'friedman': omnibus, 'paired': paired}
    # One family across all exploratory paired tests, not separate correction per metric.
    tests = sorted([(comparison['p'], comparison) for m in metrics.values() for comparison in m['paired'].values()
                    if comparison['p'] is not None], key=lambda item: item[0])
    previous = 0
    for i, (p, comparison) in enumerate(tests):
        previous = min(1., max(previous, p * (len(tests) - i)))
        comparison['p_holm'] = previous
    return {'participants': participants, 'metrics': metrics,
            'counts': {'participants': len(ids), 'complete_participants': sum(p['complete'] for p in participants),
                       'sessions': len(enrolled), 'eligible_sessions': len(eligible),
                       'failed_sessions': sum(r.get('end_reason') in ('acquisition_error', 'inference_error', 'unexpected_end') or r.get('trial_status') in ('interrupted', 'withdrawn') for r in enrolled)},
            'scope': 'Participant means per condition; completed and verified sessions only. Missing remains missing. Exploratory tests; no clinical sleep inference.'}
