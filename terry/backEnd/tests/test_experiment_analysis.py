import math
import asyncio
import json

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from pydantic import ValidationError

import session_reports as module
from experiment_analysis import (analyze_cohort, motion_latency, parse_physiology_csv,
                                 protocol_metrics, rmssd, validate_physiology)
from session_reports import ExperimentLabel


def row(participant='P01', condition='fixed', **extra):
    return dict(participant=participant, condition=condition, mode='brainflow', ended=True,
                trial_status='completed', condition_verified=True, end_reason='manual', **extra)


def test_questionnaire_missing_and_zero_are_distinct():
    metrics = protocol_metrics({'experiment': {'lseq_gts_items': [50, None, 80], 'relaxation_vas': 0,
                                             'kss_before': 3, 'kss_after': 5}})
    assert metrics['lseq_gts'] is None
    assert metrics['relaxation_vas'] == 0
    assert metrics['kss_change'] == 2
    assert metrics['motion_event_observed'] is None
    assert protocol_metrics({'experiment': {'lseq_gts_items': [50, 60, 70]}})['lseq_gts'] == 60


@pytest.mark.parametrize('values', [dict(baseline_start_s=0),
    dict(baseline_start_s=5, baseline_end_s=4),
    dict(baseline_start_s=0, baseline_end_s=300, intervention_start_s=250, intervention_end_s=600),
    dict(lseq_gts_items=[0, 50, 101]), dict(relaxation_vas=float('nan'))])
def test_label_rejects_invalid_phases_and_scores(values):
    with pytest.raises(ValidationError):
        ExperimentLabel(**values)


def test_csv_structured_parser_and_missing():
    data = parse_physiology_csv(b'\xef\xbb\xbftime_s,heart_rate_bpm,rr_ms,motion\n"0",60,1000,\n1,,1010,0\n')
    assert data['samples'][0]['motion'] is None
    assert data['samples'][1]['heart_rate_bpm'] is None
    assert data['samples'][0]['rr_ms'] == 1000


@pytest.mark.parametrize('payload', [b'time_s,time_s\n0,0', b'time_s,motion\n0',
    b'time_s,motion\n0,0\n0,1', b'time_s,rr_ms\n0,NaN', b'time_s,name\n0,A'])
def test_csv_rejects_bad_columns_times_and_values(payload):
    with pytest.raises(ValueError):
        parse_physiology_csv(payload)


def test_rr_missing_and_gaps_break_adjacency():
    samples = validate_physiology({'source': 'NN export', 'samples': [
        {'time_s': 0, 'rr_ms': 1000}, {'time_s': 1, 'rr_ms': 1010},
        {'time_s': 2, 'rr_ms': None}, {'time_s': 3, 'rr_ms': 1500},
        {'time_s': 30, 'rr_ms': 1000}]})['samples']
    assert rmssd(samples, (0, 40)) == 10
    assert rmssd(samples, (2, 40)) is None


def test_motion_needs_contiguous_five_minutes():
    samples = [{'time_s': t, 'motion': 0} for t in range(300, 610)]
    assert motion_latency(samples, (300, 1000), .1, 2) == 0
    samples[150]['motion'] = None
    assert motion_latency(samples, (300, 1000), .1, 2) is None
    sparse = [{'time_s': t, 'motion': 0} for t in range(300, 1000, 60)]
    assert motion_latency(sparse, (300, 1000), .1, 2) is None


def test_power_windows_exclude_boundary_crossing_and_fallback_gaps():
    windows = [{'timestamp_s': t, 'source': 'LIVE', 'status': status, 'signal_quality': 1,
                'band_power_uv2': {'values': {'alpha': [power], 'theta': [power]}},
                'waveform_model': {'window_seconds': 30}}
               for t, status, power in [(306, 'ready', 999), (342, 'ready', 10),
                                         (348, 'frozen', 20), (354, 'ready', 30), (400, 'frozen', 40)]]
    report = {'experiment': {'intervention_start_s': 300, 'intervention_end_s': 600}, 'windows': windows}
    metrics = protocol_metrics(report)
    assert metrics['alpha_intervention_uv2'] == 25
    assert metrics['fallback_observed_s'] == 12
    assert metrics['fallback_proportion'] == .5
    assert metrics['heart_rate_change_bpm'] is None


def test_ten_people_are_ten_not_thirty_independent_observations():
    rows = [row(f'P{i:02}', c, relaxation_vas=i + delta)
            for i in range(1, 11) for c, delta in [('fixed', 0), ('sham', 1), ('closed_loop', 2)]]
    result = analyze_cohort(rows)
    assert result['counts'] == dict(participants=10, complete_participants=10, sessions=30,
                                  eligible_sessions=30, failed_sessions=0)
    metric = result['metrics']['relaxation_vas']
    assert metric['groups']['fixed']['n'] == 10
    assert metric['complete_n'] == 10
    assert metric['paired']['fixed']['mean'] == 2
    assert metric['paired']['fixed']['p_holm'] >= metric['paired']['fixed']['p']
    assert math.isfinite(metric['friedman']['p'])
    assert result['metrics']['lseq_gts']['groups']['fixed']['n'] == 0


def test_repeats_average_before_cohort_and_bad_sessions_stay_visible():
    rows = [row('P01', 'fixed', relaxation_vas=0), row('P01', 'fixed', relaxation_vas=10),
            row('P02', 'fixed', relaxation_vas=8), row('P01', 'closed_loop', relaxation_vas=6)]
    failed = row('P03', 'fixed', relaxation_vas=10)
    failed.update(end_reason='acquisition_error')
    demo = row('DEMO', 'fixed', relaxation_vas=10)
    demo.update(mode='demo')
    running = row('P04', 'fixed', relaxation_vas=10)
    running.update(ended=False)
    unverified = row('P05', 'fixed', relaxation_vas=10)
    unverified.update(condition_verified=False)
    result = analyze_cohort(rows + [failed, demo, running, unverified])
    metric = result['metrics']['relaxation_vas']
    assert metric['groups']['fixed']['mean'] == 6.5
    assert metric['paired']['fixed']['mean'] == 1
    assert metric['paired']['fixed']['p'] is None
    assert result['counts']['failed_sessions'] == 1
    assert result['counts']['participants'] == 5
    assert result['counts']['eligible_sessions'] == 4


def test_api_import_persists_and_analysis_uses_local_reports(tmp_path, monkeypatch):
    reports = module.Reports(tmp_path)
    monkeypatch.setattr(module, 'reports', reports)
    identifier = reports.start({'mode': 'brainflow'})
    reports.finish('manual', 600)
    label = {'participant': 'P01', 'condition': 'fixed', 'trial_status': 'completed',
             'condition_verified': True, 'baseline_start_s': 0, 'baseline_end_s': 2,
             'intervention_start_s': 2, 'intervention_end_s': 4}
    assert module.label_experiment(identifier, ExperimentLabel(**label))['status'] == 'saved'
    def request(payload, content_type):
        async def receive():
            return {'type': 'http.request', 'body': payload, 'more_body': False}
        return Request({'type': 'http', 'headers': [(b'content-type', content_type.encode())]}, receive)
    response = asyncio.run(module.physiology_report(identifier, request(
        b'time_s,heart_rate_bpm\n0,70\n1,70\n2,60\n3,60', 'text/csv')))
    assert response['status'] == 'saved'
    assert module.experiment_row(reports.load(identifier))['heart_rate_change_bpm'] == -10
    result = module.experiment_analysis()
    assert result['counts']['participants'] == 1
    with pytest.raises(HTTPException) as exc:
        asyncio.run(module.physiology_report(identifier, request(json.dumps({'samples': []}).encode(), 'application/json')))
    assert exc.value.status_code == 422
    assert len(reports.load(identifier)['physiology']['samples']) == 4
