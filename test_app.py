"""Offline self-check: python test_app.py"""
import io
import subprocess
import tempfile
import time
from pathlib import Path

import app as appmod
from app import app

c = app.test_client()


def convert(data, timeout=30):
    """Start a convert job, poll to completion, return (final progress, file response)."""
    r = c.post("/convert", data=data, content_type="multipart/form-data")
    if r.status_code != 200:
        return r, None
    jid, seen = r.json["id"], []
    for _ in range(timeout * 10):
        s = c.get(f"/progress/{jid}").json
        seen.append(s["pct"])
        if s["done"]:
            return s, (None if s["error"] else c.get(f"/file/{jid}"))
        time.sleep(0.1)
    raise TimeoutError


assert c.get("/").status_code == 200
assert c.post("/download", data={"url": "file:///etc/passwd"}).status_code == 400
assert c.post("/convert", data={"to": "-evil"}).status_code == 400
assert c.post("/download", data={"url": "https://x.com", "quality": "4k"}).status_code == 400
assert b"/terms" in c.get("/").data
assert b"Copyright complaints" in c.get("/terms").data and b"No accounts" in c.get("/privacy").data
appmod.BLOCKED.append("blockme123")
assert c.post("/download", data={"url": "https://youtu.be/blockme123"}).status_code == 451
appmod.BLOCKED.clear()
assert c.get("/progress/nope").status_code == 404 and c.get("/file/nope").status_code == 404

# Make a 3s tone with ffmpeg, convert wav -> mp3 through the app.
wav = Path(tempfile.mkdtemp()) / "tone.wav"
subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=duration=3", str(wav)], capture_output=True, check=True)
tone = lambda br: {"to": "mp3", "bitrate": br, "file": (io.BytesIO(wav.read_bytes()), "tone.wav")}

s, r = convert(tone("192"))
assert r.status_code == 200 and len(r.data) > 1000, r.data[:300]
assert "tone.mp3" in r.headers["Content-Disposition"]
assert convert(tone("999"))[0].status_code == 400

lo, hi = convert(tone("128"))[1], convert(tone("320"))[1]
assert len(hi.data) > len(lo.data) * 2, (len(lo.data), len(hi.data))

s, r = convert({"to": "png", "file": (io.BytesIO(b"junk"), "bad.wav")})
assert r is None and s["error"].startswith("Conversion failed:"), s
assert c.post("/transcript", data={"url": "file:///etc/passwd"}).status_code == 400
vtt = """WEBVTT
Kind: captions

00:00.000 --> 00:01.000
hello <c>there</c>

00:01.000 --> 00:02.000
hello there
I&#39;m done. next
"""
assert appmod.vtt_text(vtt) == "hello there I'm done.\nnext", appmod.vtt_text(vtt)
assert appmod.pick_lang({"subtitles": {"live_chat": 1, "de": 1, "en-US": 1}}) == "en-US"
assert appmod.pick_lang({"automatic_captions": {"en": 1, "es-orig": 1}}) == "es-orig"
assert appmod.pick_lang({}) is None
print("ok")
