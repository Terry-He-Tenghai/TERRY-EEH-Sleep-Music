from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np

from .config import ensure_output_dirs, load_config
from .contracts import EegChunk, StateUpdate
from .music_policy import (
    MUSIC_PIPELINES,
    FiveModeMusicController,
    MusicMode,
    PolicyThresholds,
)
from .paper import build_paper_outputs
from .pipeline import (
    extract_available_archives,
    load_cohort_features,
    process_all_continuous_subjects,
    process_all_subjects,
    run_cohort_analysis,
    run_continuous_prediction_analysis,
    run_prediction_analysis,
    run_stage_analysis,
)
from .music_engine import (
    MusicState,
    generate_midi_plan,
    mix_layers,
    preset_gains,
    process_waveform,
    quality_report,
    render_symbolic_layer,
    write_midi_file,
)
from .music_engine.waveform import write_wav_file
from .music_runtime import build_music_runtime
from .replay import run_offline_replay
from .streaming import RealtimeSession
from .suno import (
    SunoCallbackServer,
    SunoClient,
    TrackRepository,
    generation_request_for_mode,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="ANPHY-Sleep 16-channel sleep-onset analysis"
    )
    parser.add_argument("--config", default="config.yaml")
    subcommands = parser.add_subparsers(dest="command", required=True)

    subcommands.add_parser("extract", help="Extract downloaded EPCTL ZIP archives")

    process = subcommands.add_parser(
        "process",
        help="Preprocess EEG and extract interpretable features",
    )
    process.add_argument("--subject", help="Optional subject ID, e.g. EPCTL11")
    process_continuous = subcommands.add_parser(
        "process-continuous",
        help="Extract record-start streams for unbiased future-N2 evaluation",
    )
    process_continuous.add_argument(
        "--subject",
        help="Optional subject ID, e.g. EPCTL11",
    )

    subcommands.add_parser(
        "analyze",
        help="Generate trajectories, topographies, QC, and statistics",
    )
    subcommands.add_parser(
        "predict",
        help="Run leave-one-subject-out future-N2 prediction",
    )
    subcommands.add_parser(
        "classify",
        help="Run 30-second W/N1/N2 LOSO classification and PSD contrasts",
    )
    subcommands.add_parser(
        "predict-continuous",
        help="Run record-start future-N2 LOSO and feature ablations",
    )

    replay = subcommands.add_parser(
        "replay",
        help="Replay historical windows and emit JSON state updates",
    )
    replay.add_argument("--subject", required=True)
    replay.add_argument(
        "--speed",
        type=float,
        default=0.0,
        help="Replay multiplier; 0 writes immediately",
    )
    subcommands.add_parser(
        "paper",
        help="Build publication-ready figures, tables, and manifest",
    )
    stream_demo = subcommands.add_parser(
        "stream-demo",
        help="Run raw continuous EEG through the realtime public API",
    )
    stream_demo.add_argument("--seconds", type=float, default=45.0)
    stream_demo.add_argument("--chunk-seconds", type=float, default=1.0)
    stream_demo.add_argument("--output")
    music_demo = subcommands.add_parser(
        "music-demo",
        help="Simulate the five-mode EEG music policy without network or audio",
    )
    music_demo.add_argument(
        "--output",
        help="Optional JSONL destination",
    )
    music_render = subcommands.add_parser(
        "music-render-demo",
        help="Render deterministic M1/M2/M3 layers, MIDI, and metrics offline",
    )
    music_render.add_argument(
        "--state",
        choices=[state.value for state in MusicState],
        default=MusicState.M1.value,
    )
    music_render.add_argument("--bars", type=int, default=8)
    music_render.add_argument("--seed", type=int, default=42)
    music_render.add_argument("--output-dir", help="Output directory")
    music_generate = subcommands.add_parser(
        "music-pregenerate",
        help="Submit one Suno task for each generative music mode",
    )
    music_generate.add_argument(
        "--callback-url",
        help="Public callback URL; overrides config",
    )
    music_approve = subcommands.add_parser(
        "music-approve",
        help="Approve one cached generated track for automatic playback",
    )
    music_approve.add_argument(
        "--mode",
        required=True,
        choices=[mode.value for mode in MusicMode],
    )
    music_approve.add_argument("--index", type=int, required=True)
    subcommands.add_parser(
        "music-cache",
        help="Print submitted Suno tasks and cached track approval state",
    )
    callback = subcommands.add_parser(
        "music-callback-server",
        help="Receive Suno callbacks into the persistent track cache",
    )
    callback.add_argument("--host", default="127.0.0.1")
    callback.add_argument("--port", type=int, default=8765)
    callback.add_argument(
        "--secret",
        help="Prefer SUNO_CALLBACK_SECRET to avoid shell history exposure",
    )
    return parser


def main() -> None:
    args = _parser().parse_args()
    config, _ = load_config(args.config)
    ensure_output_dirs(config)

    if args.command == "extract":
        paths = extract_available_archives(config)
        print(json.dumps([str(path) for path in paths], indent=2))
        return

    if args.command == "process":
        paths = process_all_subjects(config, subject_id=args.subject)
        print(json.dumps([str(path) for path in paths], indent=2))
        return

    if args.command == "process-continuous":
        paths = process_all_continuous_subjects(
            config,
            subject_id=args.subject,
        )
        print(json.dumps([str(path) for path in paths], indent=2))
        return

    if args.command == "analyze":
        print(json.dumps(run_cohort_analysis(config), indent=2))
        return

    if args.command == "predict":
        metrics, lead_times = run_prediction_analysis(config)
        print(metrics.to_string(index=False))
        print(lead_times.groupby("model").agg(
            median_lead_min=("first_sustained_alert_lead_min", "median"),
            valid_alert_rate=("alert_within_target_5m", "mean"),
        ).to_string())
        return

    if args.command == "classify":
        metrics, confusion = run_stage_analysis(config)
        print(metrics.to_string(index=False))
        print(confusion.to_string())
        return

    if args.command == "predict-continuous":
        metrics, events = run_continuous_prediction_analysis(config)
        print(metrics.to_string(index=False))
        print(
            events.groupby("model").agg(
                target_event_sensitivity=("target_event_detected", "mean"),
                median_target_lead_min=(
                    "first_target_alert_lead_min",
                    "median",
                ),
                median_false_alerts_per_hour=(
                    "false_alerts_per_pretarget_hour",
                    "median",
                ),
            ).to_string()
        )
        return

    if args.command == "replay":
        features = load_cohort_features(config)
        model_dir = Path(config["data"]["results_dir"]) / "models"
        output = Path(config["data"]["results_dir"]) / "replay" / f"{args.subject}.jsonl"
        destination = run_offline_replay(
            features=features,
            prediction_model_path=model_dir / "logistic_regression.joblib",
            state_model_path=model_dir / "sleep_state_logistic.joblib",
            output_path=output,
            subject_id=args.subject,
            speed=args.speed,
        )
        print(destination)
        return

    if args.command == "paper":
        print(
            json.dumps(
                build_paper_outputs(config),
                indent=2,
                ensure_ascii=False,
            )
        )
        return

    if args.command == "stream-demo":
        sfreq = float(config["signal"]["target_sfreq_hz"])
        channels = tuple(config["channels"]["target"])
        chunk_samples = int(round(args.chunk_seconds * sfreq))
        total_samples = int(round(args.seconds * sfreq))
        if chunk_samples <= 0 or total_samples < chunk_samples:
            raise ValueError("Demo duration must contain at least one positive chunk")
        model_dir = Path(config["data"]["results_dir"]) / "models"
        runtime = None
        if bool(config.get("music", {}).get("enabled", False)):
            runtime = build_music_runtime(config)
            runtime.start(pregenerate=False)
        session = RealtimeSession(
            config,
            prediction_model_path=(
                model_dir / "future_n2_logistic_continuous.joblib"
            ),
            state_model_path=model_dir / "sleep_state_logistic_30s.joblib",
            session_id="stream-demo",
            music_controller=runtime,
        )
        output = (
            Path(args.output)
            if args.output
            else Path(config["data"]["results_dir"])
            / "realtime"
            / "stream_demo.jsonl"
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        rng = np.random.default_rng(int(config["project"]["random_seed"]))
        with output.open("w", encoding="utf-8") as handle:
            for start in range(0, total_samples - chunk_samples + 1, chunk_samples):
                time_s = (start + np.arange(chunk_samples)) / sfreq
                signals = np.vstack(
                    [
                        12e-6
                        * np.sin(
                            2 * np.pi * (8.0 + index % 5) * time_s
                            + index * 0.3
                        )
                        + rng.normal(0, 1e-6, size=chunk_samples)
                        for index in range(len(channels))
                    ]
                )
                chunk = EegChunk(
                    timestamp_s=start / sfreq,
                    sample_rate_hz=sfreq,
                    channel_names=channels,
                    samples=signals,
                    unit="V",
                    session_id="stream-demo",
                )
                for result in session.push(chunk):
                    handle.write(
                        json.dumps(result.to_dict(), ensure_ascii=False) + "\n"
                    )
        if runtime is not None:
            runtime.shutdown()
        print(output)
        return

    if args.command == "music-render-demo":
        sample_rate = 22_050
        bpm = 60.0
        duration_seconds = args.bars * 4 * 60.0 / bpm
        state = MusicState(args.state)
        notes = generate_midi_plan(state.value, seed=args.seed, bars=args.bars)
        output_dir = (
            Path(args.output_dir)
            if args.output_dir
            else Path(config["data"]["results_dir"]) / "music" / "renders" / state.value
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        layer_audio = {
            "pad": render_symbolic_layer(notes, sample_rate, duration_seconds, "pad", bpm=bpm),
            "bass": render_symbolic_layer(notes, sample_rate, duration_seconds, "bass", bpm=bpm),
            "melody": render_symbolic_layer(notes, sample_rate, duration_seconds, "melody", bpm=bpm),
        }
        rng = np.random.default_rng(args.seed)
        texture = rng.normal(0.0, 0.012, size=(2, int(round(duration_seconds * sample_rate))))
        layer_audio["texture"] = texture.astype(np.float32)
        for layer_name, audio in layer_audio.items():
            write_wav_file(audio, output_dir / f"{layer_name}.wav", sample_rate)
        mixed = mix_layers(layer_audio, preset_gains(state))
        rendered, metrics = process_waveform(mixed, sample_rate)
        write_wav_file(rendered, output_dir / "mix.wav", sample_rate)
        write_midi_file(notes, output_dir / "arrangement.mid", bpm=int(bpm))
        manifest = {
            "schema_version": "1.0",
            "state": state.value,
            "seed": args.seed,
            "bars": args.bars,
            "bpm": bpm,
            "sample_rate_hz": sample_rate,
            "layers": sorted(layer_audio),
            "gains": preset_gains(state).as_dict(),
            "midi_quality": quality_report(notes, bars=args.bars).__dict__,
            "waveform_metrics": metrics.__dict__,
            "adaptive_role_to_pipeline": {"warm_pad": "alpha_stabilization", "transition": "theta_transition", "minimal_drone": "sleep_protection", "repair": "micro_arousal_repair"},
        }
        (output_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(output_dir)
        return

    if args.command == "music-demo":
        controller = FiveModeMusicController(
            PolicyThresholds.from_config(config)
        )
        sequence = [
            (30, {"W": 0.90, "N1": 0.08, "N2": 0.02}, 0.20, 1.2, -0.4, -0.2),
            (60, {"W": 0.88, "N1": 0.10, "N2": 0.02}, 0.25, -0.4, 1.1, 0.0),
            (90, {"W": 0.82, "N1": 0.16, "N2": 0.02}, 0.30, -0.5, 1.2, 0.1),
            (120, {"W": 0.30, "N1": 0.64, "N2": 0.06}, 0.58, -0.6, -0.3, 0.9),
            (150, {"W": 0.22, "N1": 0.70, "N2": 0.08}, 0.68, -0.7, -0.6, 1.1),
            (180, {"W": 0.10, "N1": 0.25, "N2": 0.65}, 0.80, -0.8, -0.4, 1.3),
            (210, {"W": 0.05, "N1": 0.18, "N2": 0.77}, 0.86, -0.9, -0.3, 1.4),
            (240, {"W": 0.03, "N1": 0.12, "N2": 0.85}, 0.90, -0.9, -0.2, 1.5),
        ]
        lines = []
        for (
            time_s,
            probabilities,
            future_n2,
            beta_z,
            alpha_z,
            theta_z,
        ) in sequence:
            state = StateUpdate(
                session_id="music-demo",
                window_end_s=float(time_s),
                signal_quality=1.0,
                status="ok",
                baseline_ready=True,
                n2_within_5m_probability=float(future_n2),
                aasm_state_probabilities=probabilities,
                interpretable_features={
                    "frontal_beta_z": float(beta_z),
                    "posterior_alpha_z": float(alpha_z),
                    "central_theta_z": float(theta_z),
                },
            )
            lines.append(
                {
                    "time_s": time_s,
                    "state_probabilities": probabilities,
                    "command": controller.update(state).to_dict(),
                }
            )
        text = "\n".join(
            json.dumps(line, ensure_ascii=False) for line in lines
        )
        if args.output:
            destination = Path(args.output)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(text + "\n", encoding="utf-8")
            print(destination)
        else:
            print(text)
        return

    if args.command == "music-pregenerate":
        music_config = config["music"]
        callback_url = (
            args.callback_url
            or music_config.get("suno", {}).get("callback_url")
        )
        if not callback_url:
            raise ValueError(
                "Provide --callback-url or music.suno.callback_url"
            )
        repository = TrackRepository(music_config["cache_file"])
        client = SunoClient(
            base_url=music_config["suno"]["base_url"],
        )
        submitted = {}
        for mode, pipeline in MUSIC_PIPELINES.items():
            if not pipeline.generate_with_suno:
                continue
            if repository.task_exists(mode):
                submitted[mode.value] = "already_submitted"
                continue
            task_id = client.generate(
                generation_request_for_mode(
                    mode,
                    callback_url,
                    music_config["suno"]["model"],
                )
            )
            repository.register_task(mode, task_id)
            if str(music_config.get("result_source", "poll")) == "poll":
                record = client.wait_for_completion(
                    task_id,
                    interval_seconds=float(
                        music_config.get("poll_interval_seconds", 30.0)
                    ),
                    timeout_seconds=float(
                        music_config.get("poll_timeout_seconds", 360.0)
                    ),
                )
                added = repository.ingest_callback(record)
                submitted[mode.value] = {
                    "task_id": task_id,
                    "tracks_added": added,
                }
            else:
                submitted[mode.value] = task_id
        print(json.dumps(submitted, indent=2, ensure_ascii=False))
        return

    if args.command == "music-approve":
        repository = TrackRepository(config["music"]["cache_file"])
        track = repository.approve(
            MusicMode(args.mode),
            args.index,
        )
        print(json.dumps(track.__dict__, indent=2, ensure_ascii=False))
        return

    if args.command == "music-cache":
        repository = TrackRepository(config["music"]["cache_file"])
        print(json.dumps(repository.data, indent=2, ensure_ascii=False))
        return

    if args.command == "music-callback-server":
        repository = TrackRepository(config["music"]["cache_file"])
        callback_secret = args.secret or os.environ.get(
            "SUNO_CALLBACK_SECRET"
        )
        if not callback_secret:
            raise ValueError(
                "Set SUNO_CALLBACK_SECRET or provide --secret"
            )
        server = SunoCallbackServer(
            repository,
            host=args.host,
            port=args.port,
            secret=callback_secret,
        )
        print(
            f"Listening on http://{args.host}:{args.port} "
            "using the configured secret callback path"
        )
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            server.shutdown()
        return


if __name__ == "__main__":
    main()
