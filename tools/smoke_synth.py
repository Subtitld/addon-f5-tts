"""Speak real lines with the frozen add-on, as Subtitld does.

    python tools/smoke_synth.py dist/f5-tts-addon/f5-tts-addon

Downloads the model on the first line (about 1.5 GB) and clones the voice in
tools/reference.wav: Thom in Tears of Steel, (CC) Blender Foundation,
mango.blender.org, CC BY 3.0.
Fails on a line that errors, writes no audio, or takes more than the timeout:
1.0.6 failed every line: the training code imports wandb, which the bundle
leaves out.
"""

import json
import os
import subprocess
import sys
import tempfile
import threading
import wave

REFERENCE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'reference.wav')
REFERENCE_TEXT = ('Look Celia, we have to follow our passions; you have your robotics, '
                  'and I just want to be awesome in space.')
LINES = [
    ('en', 'All human beings are born free and equal in dignity and rights.'),
    ('zh-cn', '人人生而自由，在尊严和权利上一律平等。'),
]
TIMEOUT = 2400


def main(binary: str) -> int:
    out = tempfile.mkdtemp(prefix='f5-tts-smoke-')
    env = dict(os.environ, SUBTITLD_TEMP_DIR=out)
    proc = subprocess.Popen([binary], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=sys.stderr, text=True, env=env)
    timer = threading.Timer(TIMEOUT, proc.kill)
    timer.start()
    try:
        hello = json.loads(proc.stdout.readline())
        assert hello.get('type') == 'hello', hello
        voice = 'f5-clone'
        for n, (language, text) in enumerate(LINES):
            path = os.path.join(out, f'{n}.wav')
            proc.stdin.write(json.dumps({'type': 'tts.synthesize', 'id': str(n), 'params': {
                'text': text, 'voice': voice, 'language': language, 'output_path': path,
                'voice_ref_audio': REFERENCE, 'voice_ref_text': REFERENCE_TEXT}}) + '\n')
            proc.stdin.flush()
            while True:
                line = proc.stdout.readline()
                if not line:
                    raise SystemExit(f'{language}: the add-on exited (or timed out) without an answer')
                try:
                    frame = json.loads(line)
                except json.JSONDecodeError:   # anything but JSON on stdout breaks the host
                    raise SystemExit(f'{language}: not a protocol frame on stdout: {line[:300]!r}')
                if frame.get('id') != str(n) or frame.get('type') == 'progress':
                    continue
                if frame.get('type') != 'result':
                    raise SystemExit(f'{language}: {frame}')
                break
            with wave.open(path) as w:
                seconds = w.getnframes() / w.getframerate()
            assert seconds > 1.0, f'{language}: only {seconds:.2f} s of audio'
            print(f'ok {language}: {seconds:.2f} s', flush=True)
        proc.stdin.write(json.dumps({'type': 'shutdown'}) + '\n')
        proc.stdin.flush()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            # As Subtitld does after its grace period. Seen on the macOS
            # runner with Kokoro 26.11.2: every line spoken, then no exit.
            print('warning: still running 30 s after shutdown; terminating it, as Subtitld would', flush=True)
            proc.terminate()
            proc.wait(timeout=10)
    finally:
        timer.cancel()
        if proc.poll() is None:
            proc.kill()
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1]))
