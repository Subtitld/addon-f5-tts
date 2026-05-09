# F5-TTS add-on for Subtitld

Voice-clone-only neural TTS based on
[SWivid/F5-TTS](https://github.com/SWivid/F5-TTS), `F5TTS_v1_Base`. Heavy:
the model is ~1.5 GB, peak RAM around 4 GB, CPU inference is several
seconds per line.

There are no preset voices — every request needs a 6-15 second reference
clip plus (optionally) its transcript. The single voice id is `f5-clone`;
the host wires up the reference via the `voice_ref_audio` parameter.

## Languages

Two: English and Mandarin Chinese. The `F5TTS_v1_Base` checkpoint was
trained on Emilia ZH-EN (~100k hours). Community-trained checkpoints for
other languages exist (ja, fr, de, hi, it, ru, es, fi) but require
swapping the model file — out of scope for this v1 add-on.

## Building

```bash
pip install pyinstaller
pip install torch --extra-index-url https://download.pytorch.org/whl/cpu
# f5-tts pulls a big stack: torchaudio, vocos, transformers,
# x_transformers, ema_pytorch, torchdiffeq, descript-audio-codec,
# pydub, librosa, pypinyin, jieba.
pip install f5-tts
pyinstaller f5-tts-addon.spec --distpath dist/
cd dist/f5-tts-addon
zip -r ../f5-tts-1.0.0-linux-x86_64.zip . ../../manifest.json ../../LICENSE ../../README.md
```

`ffmpeg` is required at runtime for arbitrary reference audio decoding.
Most desktop installs already have it; if not, it's `apt install ffmpeg`
or `brew install ffmpeg` or the bundled binary on Windows.

## Voice cloning

The `f5-clone` voice id treats the per-request `voice_ref_audio`
parameter as the reference (any 6-15 second mono WAV; at least 6 s, no
more than 15 s for stability). Without an explicit reference, the
add-on falls back to the addon-config-level `voice_ref_audio` (a default
reference clip the user picks once).

If the reference clip's transcript is provided in `voice_ref_text` (or
in the addon config), F5-TTS uses it directly. If left empty, F5-TTS
auto-transcribes via Whisper — slower on the first call (Whisper
download), cached afterwards.

## License

The wrapper code in this repo is MIT. The `F5TTS_v1_Base` model weights
are **CC-BY-NC-4.0** (non-commercial only) — commercial use is **not**
permitted under the model license. If you need a permissive-licensed
voice-clone TTS, use Coqui XTTS-v2 with a paid Coqui license, or stick
with Qwen3-TTS (Apache-2.0 with voice cloning via the Base variant).
