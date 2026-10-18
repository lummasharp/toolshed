"""toolshed: YouTube/TikTok downloader, transcripts + file converter. Run: python app.py, open http://127.0.0.1:5000"""
import html
import os
import re
import shutil
import subprocess
import tempfile
import threading
import uuid
from pathlib import Path

import yt_dlp
from flask import Flask, request, send_file
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1024**3  # 1 GB upload cap

# Allowlists so user input never reaches ffmpeg as an arbitrary argument.
GROUPS = {
    "video": ["mp4", "mkv", "webm", "mov", "avi", "gif"],
    "audio": ["mp3", "wav", "ogg", "flac", "m4a", "aac"],
    "image": ["png", "jpg", "webp", "bmp"],
}
FORMATS = [f for fs in GROUPS.values() for f in fs]
BITRATES = ["128", "192", "256", "320"]
TMP_PREFIX = "toolshed-"
QUALITIES = ["best", "1080", "720", "480", "360"]


def pills(name, values, checked, labels=None):
    return "".join(
        f'<label class=pill><input type=radio name={name} value={v}{" checked" if v == checked else ""}>'
        f"<span>{(labels or {}).get(v, v)}</span></label>"
        for v in values
    )


def bitrate_row(cls):
    return f'<div class="row {cls}"><span class=k>bitrate</span><div class=pills>{pills("bitrate", BITRATES, "192", {b: b + "k" for b in BITRATES})}</div></div>'


PAGE = """<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>toolshed</title>
<style>
:root{--bg:#09090b;--card:#111113;--line:#222226;--hi:#34343a;--txt:#ececee;--dim:#76767e;--acc:#fff}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--txt);font:14px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:540px;margin:0 auto;padding:48px 16px}
header{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:14px}
h1{font-size:24px;letter-spacing:-.04em;margin:0;font-weight:700}
h1 i{font-style:normal;color:var(--dim)}
.sub{color:var(--dim);margin:4px 0 32px}
.pills{display:flex;gap:4px;flex-wrap:wrap;flex:1}
.pill input{position:absolute;opacity:0;pointer-events:none}
.pill span{display:inline-block;padding:3px 10px;border:1px solid var(--line);border-radius:999px;font-size:12px;cursor:pointer;color:var(--dim);transition:.15s}
.pill span:hover{color:var(--txt);border-color:var(--hi)}
.pill input:checked+span{background:var(--acc);color:#000;border-color:var(--acc)}
.pill input:focus-visible+span{outline:2px solid var(--acc);outline-offset:2px}
.tabs{flex:none;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:3px;gap:2px}
.tabs .pill span{border:0;border-radius:7px;padding:4px 12px;font-size:13px}
section{display:none;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px}
main:has([name=tab][value=download]:checked) #download,main:has([name=tab][value=convert]:checked) #convert,main:has([name=tab][value=transcript]:checked) #transcript{display:block}
.top{display:flex;gap:6px}
.top>:first-child{flex:1;min-width:0}
input[type=url],.drop{display:block;background:var(--bg);border:1px solid var(--line);border-radius:8px;color:var(--txt);padding:9px 12px;font:inherit;outline:none;transition:.15s}
input[type=url]:focus,.drop:hover,.drop.over{border-color:var(--hi)}
.drop{position:relative;border-style:dashed;color:var(--dim);cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.drop input{position:absolute;inset:0;opacity:0;cursor:pointer}
.go{flex:none;background:var(--acc);color:#000;border:0;border-radius:8px;padding:0 16px;font:600 13px/1 inherit;font-family:inherit;cursor:pointer;transition:.15s}
.go:hover{opacity:.85}.go:disabled{opacity:.4;cursor:wait}
.row{display:flex;gap:10px;align-items:center;margin-top:8px}
.k{width:52px;flex:none;color:var(--dim);font-size:12px}
[hidden]{display:none!important}
.dl .br,.cv .br,.dl .q{display:none}
.dl:has(input[value=audio]:checked) .br,.cv:has(input[value=mp3]:checked) .br,.dl:has(input[value=video]:checked) .q{display:flex}
.bar{margin-top:12px;height:3px;background:var(--line);border-radius:3px;overflow:hidden;position:relative}
.bar i{display:block;height:100%;width:0;background:var(--acc);transition:width .3s}
.bar.ind i{width:30%;position:absolute;animation:slide 1.1s ease-in-out infinite}
@keyframes slide{from{left:-30%}to{left:100%}}
.msg{margin-top:6px;font-size:12px;color:var(--dim);white-space:pre-wrap}.msg:empty{display:none}.msg.err{color:#ff6b6b}
.out pre{max-height:320px;overflow:auto;white-space:pre-wrap;background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:10px 12px;margin:10px 0 0;font:13px/1.6 inherit;font-family:inherit}
.acts{display:flex;gap:4px;margin-top:8px}
.ghost{background:none;border:1px solid var(--line);color:var(--dim);border-radius:999px;padding:3px 10px;font:12px/1.5 inherit;font-family:inherit;cursor:pointer;text-decoration:none;transition:.15s}
.ghost:hover{color:var(--txt);border-color:var(--hi)}
footer{color:#444;font-size:12px;text-align:center;margin-top:20px}
.legal{line-height:1.7}.legal h1{font-size:32px}.legal h3{font-size:15px;margin:28px 0 4px}.legal p{color:#bdbdbd;margin:0 0 10px}
.legal a,footer a{color:inherit}footer a:hover{color:var(--txt)}
</style>
<main>
<header><h1>tool<i>shed</i></h1><nav class="pills tabs" aria-label=Tools>{tabs}</nav></header>

<section id=download><form class=dl action=/download>
<div class=top><input name=url type=url required placeholder="YouTube or TikTok link" aria-label="Video link"><button class=go>Get</button></div>
<div class=row><span class=k>as</span><div class=pills>{kinds}</div></div>
{quality}
{br_dl}
<div class=bar hidden><i></i></div><div class=msg role=status></div></form></section>

<section id=convert><form class=cv action=/convert>
<div class=top><label class=drop><input name=file type=file required><span>drop a file or click to pick</span></label><button class=go>Convert</button></div>
{groups}
{br_cv}
<div class=bar hidden><i></i></div><div class=msg role=status></div></form></section>

<section id=transcript><form class=tr action=/transcript data-text>
<div class=top><input name=url type=url required placeholder="YouTube or TikTok link" aria-label="Video link"><button class=go>Transcribe</button></div>
<div class=bar hidden><i></i></div><div class=msg role=status></div>
<div class=out hidden><pre></pre><div class=acts><button type=button class=ghost data-copy>copy</button><a class=ghost>save .txt</a></div></div></form></section>
<footer>files are deleted once you have them &middot; <a href=/terms>terms</a> &middot; <a href=/privacy>privacy</a></footer>
</main>
<script>
document.querySelectorAll('.drop').forEach(d=>{
  const i=d.querySelector('input'),t=d.querySelector('span');
  i.onchange=()=>{
    const file=i.files[0];t.textContent=file?.name||'drop a file or click to pick';
    const ext=(file?.name.split('.').pop()||'').toLowerCase(),kind=(file?.type||'').split('/')[0];
    const g=kind||[...d.form.querySelectorAll('[data-g]')].find(r=>r.querySelector(`input[value="${ext}"]`))?.dataset.g;
    const allow={video:['video','audio'],audio:['audio'],image:['image']}[g]; // unknown type: show everything
    d.form.querySelectorAll('[data-g]').forEach(r=>{
      r.hidden=allow&&!allow.includes(r.dataset.g);
      r.querySelectorAll('.pill').forEach(p=>p.hidden=p.querySelector('input').value===ext);
    });
    const cur=d.form.querySelector('input[name=to]:checked');
    if(!cur||cur.closest('[hidden]'))d.form.querySelector('[data-g]:not([hidden]) .pill:not([hidden]) input').checked=true;
  };
  d.ondragover=e=>{e.preventDefault();d.classList.add('over')};
  d.ondragleave=()=>d.classList.remove('over');
  d.ondrop=e=>{e.preventDefault();d.classList.remove('over');i.files=e.dataTransfer.files;i.onchange()};
});
document.querySelectorAll('[data-copy]').forEach(b=>b.onclick=async()=>{
  await navigator.clipboard.writeText(b.closest('.out').querySelector('pre').textContent);
  b.textContent='copied';setTimeout(()=>b.textContent='copy',1200);
});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
// XHR instead of fetch: fetch can't report upload progress.
const post=(url,fd,onUp)=>new Promise((res,rej)=>{
  const x=new XMLHttpRequest();x.open('POST',url);
  x.upload.onprogress=e=>e.lengthComputable&&onUp(e.loaded/e.total*100);
  x.onload=()=>x.status<300?res(JSON.parse(x.responseText)):rej(new Error(x.responseText));
  x.onerror=()=>rej(new Error('Server not reachable'));x.send(fd);
});
document.querySelectorAll('form').forEach(f=>f.onsubmit=async e=>{
  e.preventDefault();
  const b=f.querySelector('.go'),m=f.querySelector('.msg'),bar=f.querySelector('.bar'),fill=bar.querySelector('i'),out=f.querySelector('.out'),label=b.textContent;
  const show=(stage,pct)=>{bar.classList.toggle('ind',pct==null);fill.style.width=pct==null?'':pct+'%';m.textContent=stage+(pct==null?'…':' · '+Math.floor(pct)+'%')};
  b.disabled=true;b.textContent='…';m.className='msg';bar.hidden=false;if(out)out.hidden=true;show('uploading',0);
  try{
    const {id}=await post(f.getAttribute('action'),new FormData(f),p=>show('uploading',p));
    for(;;){
      const r=await fetch('/progress/'+id);if(!r.ok)throw new Error(await r.text());
      const s=await r.json();
      if(s.error)throw new Error(s.error);
      if(s.done)break;
      show(s.stage,s.pct);await sleep(400);
    }
    if(out){
      const r=await fetch('/file/'+id),text=await r.text(),cd=r.headers.get('content-disposition')||'';
      const name=decodeURIComponent((cd.match(/filename\\*=UTF-8''([^;]+)/i)||cd.match(/filename="?([^";]+)/i)||[,'transcript.txt'])[1]);
      const a=out.querySelector('a');URL.revokeObjectURL(a.href);
      Object.assign(a,{href:URL.createObjectURL(new Blob([text],{type:'text/plain'})),download:name});
      out.querySelector('pre').textContent=text;out.hidden=false;bar.hidden=true;m.textContent='';
    }else{
      show('done',100);m.textContent='Done · saving file';
      Object.assign(document.createElement('a'),{href:'/file/'+id}).click();
    }
  }catch(err){bar.hidden=true;m.className='msg err';m.textContent=err.message}
  b.disabled=false;b.textContent=label;
});
</script>"""


# Set with `fly secrets set CONTACT_EMAIL=... BLOCKED=id1,id2` so they stay out of the public repo.
CONTACT = os.environ.get("CONTACT_EMAIL", "")
# Links reported in takedown requests: any link containing one of these (e.g. a video id) is refused.
BLOCKED = [b.strip() for b in os.environ.get("BLOCKED", "").split(",") if b.strip()]

UPDATED = "October 18, 2026"

TERMS = """<h3>What this is</h3>
<p>toolshed is a free tool that fetches media from a link you give it, or converts a file you upload, and hands the result back to you. It does not host, store or index any content.</p>
<h3>Your responsibility</h3>
<p>You may only use toolshed for content you own, content you have permission to download, or content the law lets you copy where you live. You are responsible for what you download and convert and for how you use it. Do not use toolshed to infringe anyone's copyright or to break the terms of the site you are downloading from.</p>
<h3>No affiliation</h3>
<p>toolshed is not affiliated with, endorsed by or connected to YouTube, Google, TikTok or ByteDance. All trademarks belong to their owners.</p>
<h3>No warranty</h3>
<p>toolshed is provided as is, without any warranty. It may break, go offline, change or stop at any time. To the extent the law allows, we are not liable for any loss or damage from using it.</p>
<h3>Abuse</h3>
<p>We may block links, limit use or refuse service to anyone, for example to stop abuse or after a copyright complaint.</p>
<h3>Copyright complaints</h3>
<p>If you own the rights to something and want toolshed to stop fetching it, email {contact} with: the work you own, the link or links to block, your name and contact details, and a statement that you are the rights holder (or are allowed to act for them) and believe in good faith that the use is not authorized. We will block the reported links. Because files are deleted as soon as they are delivered, there is nothing stored on our side to remove.</p>
<h3>Changes</h3>
<p>We may update these terms. The date at the top shows the latest version. Using toolshed after a change means you accept the new terms.</p>"""

PRIVACY = """<h3>The short version</h3>
<p>No accounts, no cookies, no analytics, no ads. We do not sell or share your data.</p>
<h3>What we handle</h3>
<p>The links you paste and the files you upload, only to do the job you asked for. Uploaded files and results sit in temporary storage while the job runs and are deleted once you download the result, or when the server restarts.</p>
<h3>Logs</h3>
<p>toolshed runs on Fly.io in Frankfurt, Germany. Like most web servers it keeps basic request logs, which include your IP address and the pages you request, for a limited time. They are used only to keep the service running and to stop abuse.</p>
<h3>Other sites</h3>
<p>When you paste a link, our server contacts that site (for example YouTube or TikTok) to fetch the media. That site sees our server, not you.</p>
<h3>Your rights</h3>
<p>Because we keep nothing beyond short-lived logs, there is usually nothing to access or delete. If you have a question or a request about your data, email {contact}.</p>"""


def legal(title, body):
    head = PAGE.split("</style>")[0].replace("<title>toolshed</title>", f"<title>{title} · toolshed</title>")
    contact = f"<a href=mailto:{CONTACT}>{CONTACT}</a>" if CONTACT else "the contact address listed on the GitHub project"
    return (
        f"{head}</style><main class=legal><p><a href=/>&larr; toolshed</a></p><h1>{title}</h1>"
        f"<p class=sub>Last updated {UPDATED}</p>{body.replace('{contact}', contact)}</main>"
    )


@app.get("/terms")
def terms():
    return legal("Terms", TERMS)


@app.get("/privacy")
def privacy():
    return legal("Privacy", PRIVACY)


@app.get("/")
def index():
    groups = "".join(f'<div class=row data-g={g}><span class=k>{g}</span><div class=pills>{pills("to", fs, "mp4")}</div></div>' for g, fs in GROUPS.items())
    return (
        PAGE.replace("{tabs}", pills("tab", ["download", "convert", "transcript"], "download"))
        .replace("{kinds}", pills("kind", ["video", "audio"], "video", {"video": "video · mp4", "audio": "audio · mp3"}))
        .replace("{quality}", f'<div class="row q"><span class=k>quality</span><div class=pills>{pills("quality", QUALITIES, "best", {q: q + "p" for q in QUALITIES[1:]})}</div></div>')
        .replace("{br_dl}", bitrate_row("br"))
        .replace("{br_cv}", bitrate_row("br"))
        .replace("{groups}", groups)
    )


def send_and_cleanup(path: Path, tmp: str):
    # Stream from disk; delete the temp dir only after the response closes the file (Windows locks open files).
    resp = send_file(path, as_attachment=True, download_name=path.name)
    resp.direct_passthrough = False  # passthrough skips on_close callbacks; this still streams in chunks
    resp.call_on_close(lambda: shutil.rmtree(tmp, ignore_errors=True))
    return resp


# shortcut: jobs live in memory and are only removed when their file is fetched; fine for one local user.
JOBS = {}


def start_job(work, tmp, *args):
    """Run work(job, *args) in a thread; it returns the output path. pct=None means 'busy, no % known'."""
    jid = uuid.uuid4().hex
    job = JOBS[jid] = {"pct": 0, "stage": "starting", "done": False, "error": None, "tmp": tmp, "path": None}

    def run():
        try:
            job["path"] = work(job, *args)
        except Exception as e:
            job["error"] = str(e)
            shutil.rmtree(tmp, ignore_errors=True)
        job["done"] = True

    threading.Thread(target=run, daemon=True).start()
    return {"id": jid}


@app.get("/progress/<jid>")
def progress(jid):
    job = JOBS.get(jid)
    if not job:
        return "Unknown job", 404
    return {k: job[k] for k in ("pct", "stage", "done", "error")}


@app.get("/file/<jid>")
def file(jid):
    job = JOBS.get(jid)
    if not job or not job["done"] or job["error"]:
        return "Not ready", 404
    del JOBS[jid]
    return send_and_cleanup(job["path"], job["tmp"])


def do_download(job, url, opts):
    def on_progress(d):
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            job["stage"] = "downloading"
            job["pct"] = d["downloaded_bytes"] * 100 / total if total else None

    def on_postprocess(d):
        if d["status"] == "started":
            job["stage"], job["pct"] = "processing", None

    opts |= {"progress_hooks": [on_progress], "postprocessor_hooks": [on_postprocess]}
    job["stage"] = "fetching info"
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])
    return next(Path(job["tmp"]).iterdir())


def duration(src):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(src)], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return None  # images and some formats have no duration


def do_convert(job, src, out, extra):
    job["stage"] = "converting"
    dur = duration(src)
    job["pct"] = 0 if dur else None
    log = Path(job["tmp"]) / "ffmpeg.log"
    # stderr goes to a file so a full pipe can't stall ffmpeg while we read progress from stdout.
    with open(log, "w") as err:
        p = subprocess.Popen(["ffmpeg", "-y", "-nostats", "-progress", "pipe:1", "-i", str(src), *extra, str(out)], stdout=subprocess.PIPE, stderr=err, text=True)
        for line in p.stdout:
            key, _, val = line.strip().partition("=")
            if dur and key == "out_time_us" and val.isdigit():
                job["pct"] = min(99.0, int(val) / 1e4 / dur)
        p.wait()
    if p.returncode != 0:
        last = (log.read_text(errors="replace").strip().splitlines() or ["unknown error"])[-1]
        raise RuntimeError(f"Conversion failed: {last}")
    return out


def url_error(url):
    if not url.startswith(("http://", "https://")):
        return "Invalid URL", 400
    if any(b in url for b in BLOCKED):
        return "This link has been blocked after a copyright request.", 451


def vtt_text(vtt):
    out = []
    for line in vtt.splitlines():
        line = html.unescape(re.sub(r"<[^>]+>", "", line)).strip()
        if not line or "-->" in line or line.isdigit() or line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")):
            continue
        if line not in out[-2:]:  # auto captions repeat the previous lines as they scroll
            out.append(line)
    return re.sub(r"([.!?])\s+", r"\1\n", " ".join(out))  # caption lines break mid-sentence; reflow


def pick_lang(info):
    """Manual subs first (English if there), else auto captions in the video's own language."""
    manual = [l for l in info.get("subtitles") or {} if l != "live_chat"]
    if manual:
        return next((l for l in manual if l.startswith("en")), manual[0])
    auto = list(info.get("automatic_captions") or {})
    return next((l for l in auto if l.endswith("-orig")), None) or next((l for l in auto if l.startswith("en")), None)


def do_transcript(job, url, opts):
    job["stage"], job["pct"] = "fetching captions", None
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False, process=False)
        lang = pick_lang(info)
        if not lang:
            raise RuntimeError("This video has no captions to transcribe.")
        ydl.params["subtitleslangs"] = [lang]
        ydl.process_ie_result(info, download=True)
    sub = next(Path(job["tmp"]).iterdir())  # title.<lang>.vtt, the only file written
    txt = sub.with_name(sub.name.removesuffix(f".{lang}{sub.suffix}") + ".txt")
    txt.write_text(vtt_text(sub.read_text(encoding="utf-8", errors="replace")), encoding="utf-8")
    sub.unlink()
    return txt


@app.post("/transcript")
def transcript():
    url = request.form.get("url", "").strip()
    if err := url_error(url):
        return err
    tmp = tempfile.mkdtemp(prefix=TMP_PREFIX)
    opts = {
        "outtmpl": f"{tmp}/%(title).80s.%(ext)s",
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitlesformat": "vtt/best",
        "noplaylist": True,
        "quiet": True,
        "noprogress": True,
    }
    return start_job(do_transcript, tmp, url, opts)


@app.post("/download")
def download():
    url = request.form.get("url", "").strip()
    if err := url_error(url):
        return err
    audio = request.form.get("kind") == "audio"
    bitrate = request.form.get("bitrate", "192")
    quality = request.form.get("quality", "best")
    if bitrate not in BITRATES or quality not in QUALITIES:
        return "Invalid bitrate or quality", 400
    tmp = tempfile.mkdtemp(prefix=TMP_PREFIX)
    opts = {
        "outtmpl": f"{tmp}/%(title).80s.%(ext)s",
        "noplaylist": True,
        "quiet": True,
        "noprogress": True,
    }
    if audio:
        opts |= {"format": "bestaudio/best", "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": bitrate}]}
    else:
        h = "" if quality == "best" else f"[height<={quality}]"
        # Prefer mp4/m4a so merging needs no re-encode; fall back to anything at that height.
        opts |= {"format": f"bv*{h}[ext=mp4]+ba[ext=m4a]/b{h}[ext=mp4]/bv*{h}+ba/b{h}/b", "merge_output_format": "mp4"}
    return start_job(do_download, tmp, url, opts)


@app.post("/convert")
def convert():
    f = request.files.get("file")
    to = request.form.get("to", "")
    if not f or to not in FORMATS:
        return "Pick a file and a valid format", 400
    bitrate = request.form.get("bitrate", "192")
    if bitrate not in BITRATES:
        return "Invalid bitrate", 400
    tmp = tempfile.mkdtemp(prefix=TMP_PREFIX)
    src = Path(tmp) / (secure_filename(f.filename) or "input")
    f.save(src)
    out = Path(tmp) / "out" / f"{src.stem}.{to}"
    out.parent.mkdir()
    extra = ["-b:a", f"{bitrate}k"] if to == "mp3" else []
    return start_job(do_convert, tmp, src, out, extra)


if __name__ == "__main__":
    # Jobs cut off by a previous shutdown leave their temp dirs behind; clear them on start.
    for d in Path(tempfile.gettempdir()).glob(TMP_PREFIX + "*"):
        shutil.rmtree(d, ignore_errors=True)
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)))
