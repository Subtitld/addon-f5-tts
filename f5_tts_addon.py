"""Subtitld add-on entry point for F5-TTS.

Wraps `f5-tts` (PyPI, MIT wrapper, CC-BY-NC-4.0 weights). F5-TTS is a
*voice-clone-only* model: there are no preset voices — every request
needs a 6-15 second reference clip plus (optionally) its transcript.
We expose a single voice id `f5-clone` that the host hooks up to a
per-speaker reference clip via the `voice_ref_audio` parameter.

API call shape:
    from f5_tts.api import F5TTS
    tts = F5TTS()  # default model="F5TTS_v1_Base"
    wav, sr, _spec = tts.infer(
        ref_file="ref.wav", ref_text="transcript",
        gen_text="text to synthesize", seed=None,
    )
    # wav: numpy float32 mono, sr == 24_000

Notes:
  - `ref_text=""` triggers an auto-Whisper transcription, useful when
    the host doesn't know the reference clip's transcript.
  - The model auto-downloads `model_1250000.safetensors` and the
    Vocos vocoder on first construction — ~1.5 GB total.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
from pathlib import Path

log = logging.getLogger('f5-tts')
logging.basicConfig(stream=sys.stderr, level=logging.INFO,
                    format='[f5-tts] %(levelname)s %(message)s')

PROTOCOL = 1
ADDON_ID = 'f5-tts'
VERSION = '1.0.6'


# ---------------------------------------------------------------------------
# Wire helpers
# ---------------------------------------------------------------------------
_write_lock = threading.Lock()


def write_frame(frame: dict) -> None:
    line = json.dumps(frame, ensure_ascii=False)
    with _write_lock:
        sys.stdout.write(line + '\n')
        sys.stdout.flush()


def emit_progress(rid, value, message=''):
    write_frame({'id': rid, 'type': 'progress',
                 'data': {'value': max(0.0, min(1.0, float(value))), 'message': message}})


def emit_error(rid, code, message, retryable=False):
    write_frame({'id': rid, 'type': 'error',
                 'data': {'code': code, 'message': message, 'retryable': retryable}})


def emit_result(rid, data):
    write_frame({'id': rid, 'type': 'result', 'data': data})


# ---------------------------------------------------------------------------
# Model state — loaded lazily on first request
# ---------------------------------------------------------------------------
_model_lock = threading.Lock()
_model = None
_pending_cancel: set[str] = set()
_pending_cancel_lock = threading.Lock()


def _load_model(device: str):
    global _model
    with _model_lock:
        if _model is not None:
            return _model

        try:
            from f5_tts.api import F5TTS  # type: ignore
        except ImportError as exc:
            raise RuntimeError(f'f5-tts python package not available: {exc}') from exc

        log.info('loading F5TTS_v1_Base on %s', device)
        # F5TTS picks up CUDA visibility automatically. For CPU-only, host
        # spawns the binary with CUDA_VISIBLE_DEVICES="" so torch falls back.
        # The constructor takes ~30-60 s on first run because of the
        # safetensors + vocos downloads.
        _model = F5TTS()
        return _model


# ---------------------------------------------------------------------------
# Audio writing
# ---------------------------------------------------------------------------
def _write_wav(path: str, wav, sample_rate: int) -> tuple[float, int, int]:
    import numpy as np
    import soundfile as sf

    arr = np.asarray(wav)
    if arr.ndim > 1:
        arr = arr.squeeze()
    if arr.ndim != 1:
        raise RuntimeError(f'unexpected waveform shape: {arr.shape}')

    arr = np.clip(arr.astype(np.float32, copy=False), -1.0, 1.0)
    sf.write(path, arr, int(sample_rate), subtype='PCM_16')

    duration = float(len(arr)) / float(sample_rate or 1)
    return duration, int(sample_rate), 1


# ---------------------------------------------------------------------------
# Request handling
# ---------------------------------------------------------------------------
def handle_tts_synthesize(rid: str, params: dict, defaults: dict) -> None:
    text = params.get('text')
    voice_id = params.get('voice')
    output_path = params.get('output_path')
    if not text or not voice_id or not output_path:
        emit_error(rid, 'bad_params', 'text, voice, and output_path are all required')
        return

    if voice_id not in ('f5-clone', 'f5-tts-clone'):
        emit_error(rid, 'unsupported_voice',
                   f'unknown voice id: {voice_id!r} (only f5-clone is supported)')
        return

    with _pending_cancel_lock:
        if rid in _pending_cancel:
            _pending_cancel.discard(rid)
            emit_error(rid, 'cancelled', 'cancelled before synthesis started')
            return

    speaker_wav = params.get('voice_ref_audio') or defaults.get('voice_ref_audio') or ''
    if not speaker_wav:
        emit_error(rid, 'bad_params',
                   'f5-clone voice requires `voice_ref_audio` (path to 6-15 s reference clip)')
        return
    if not Path(speaker_wav).is_file():
        emit_error(rid, 'bad_params',
                   f'voice_ref_audio path does not exist: {speaker_wav}')
        return

    # ref_text="" tells F5-TTS to auto-transcribe. The first call with auto
    # transcription is slow (Whisper download + run); cached on disk after.
    speaker_text = params.get('voice_ref_text') or defaults.get('voice_ref_text') or ''

    emit_progress(rid, 0.05, 'Loading F5-TTS (first call may download ~1.5 GB)...')
    try:
        model = _load_model(defaults['device'])
    except Exception as exc:
        log.exception('model load failed')
        emit_error(rid, 'internal', f'failed to load F5-TTS: {exc}')
        return

    emit_progress(rid, 0.4, 'Synthesizing...')
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    try:
        wav, sr, _spec = model.infer(
            ref_file=speaker_wav,
            ref_text=speaker_text,
            gen_text=text,
            seed=None,
        )
    except Exception as exc:
        log.exception('synth failed')
        emit_error(rid, 'internal', f'synthesize failed: {exc}')
        return

    try:
        duration, sample_rate, channels = _write_wav(output_path, wav, sr)
    except Exception as exc:
        log.exception('wav write failed')
        emit_error(rid, 'internal', f'failed to write {output_path}: {exc}')
        return

    emit_progress(rid, 0.99, 'Finalizing...')
    emit_result(rid, {
        'path': output_path,
        'duration_sec': duration,
        'sample_rate': sample_rate,
        'channels': channels,
    })


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def main() -> int:
    manifest_path = Path(__file__).resolve().parent / 'manifest.json'
    voices: list[dict] = []
    languages: list[str] = []
    config_defaults: dict = {}
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            voices = manifest.get('voices') or []
            languages = manifest.get('languages') or []
            config_defaults = {f.get('key'): f.get('default')
                               for f in (manifest.get('config_schema') or {}).get('fields', [])
                               if f.get('default') is not None}
        except Exception:
            log.exception('manifest parse failed')

    defaults = {
        'device': os.environ.get('F5_TTS_DEVICE') or config_defaults.get('device', 'cpu'),
        'voice_ref_audio': os.environ.get('F5_TTS_VOICE_REF_AUDIO') or '',
        'voice_ref_text':  os.environ.get('F5_TTS_VOICE_REF_TEXT')  or '',
    }

    write_frame({
        'type': 'hello',
        'protocol': PROTOCOL,
        'addon': ADDON_ID,
        'version': VERSION,
        'capabilities': [
            {'task': 'tts.synthesize', 'languages': languages, 'voices': voices,
             'voice_clone': True},
        ],
    })

    for raw_line in sys.stdin:
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            frame = json.loads(raw_line)
        except json.JSONDecodeError:
            continue

        ftype = frame.get('type')
        rid = frame.get('id', '')

        if ftype == 'shutdown':
            log.info('shutdown received; exiting')
            return 0
        if ftype == 'cancel':
            target = (frame.get('data') or {}).get('target') or frame.get('target')
            if target:
                with _pending_cancel_lock:
                    _pending_cancel.add(target)
            continue
        if ftype == 'tts.synthesize':
            threading.Thread(
                target=handle_tts_synthesize,
                args=(rid, frame.get('params') or {}, defaults),
                daemon=True,
            ).start()
            continue
        # Host control frames (`ready` confirms our hello, future-proof
        # for other host-→-addon notifications) carry no request id and
        # expect no response. Log and ignore — only error on actual
        # *requests* we don't recognise.
        if not rid:
            log.debug('ignoring host control frame: %s', ftype)
            continue

        emit_error(rid, 'bad_params', f'unknown request type: {ftype!r}')

    return 0


if __name__ == '__main__':
    sys.exit(main())
