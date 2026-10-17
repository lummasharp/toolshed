"""toolshed: YouTube/TikTok downloader + file converter. Run: python app.py, open http://127.0.0.1:5000"""
import os
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
:root{--bg:#0a0a0a;--card:#121212;--line:#232323;--txt:#ededed;--dim:#7a7a7a;--acc:#fff}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--txt);font:15px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:620px;margin:0 auto;padding:56px 16px}
h1{font-size:40px;letter-spacing:-.04em;margin:0;font-weight:700}
h1 i{font-style:normal;color:var(--dim)}
.sub{color:var(--dim);margin:4px 0 40px}
section{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:22px;margin-bottom:16px}
h2{font-size:12px;text-transform:uppercase;letter-spacing:.14em;color:var(--dim);margin:0 0 16px;font-weight:600}
.row{display:flex;gap:12px;align-items:center;margin-top:12px;flex-wrap:wrap}
.k{width:64px;color:var(--dim);font-size:13px}
.pills{display:flex;gap:6px;flex-wrap:wrap;flex:1}
.pill input{position:absolute;opacity:0;pointer-events:none}
.pill span{display:inline-block;padding:6px 12px;border:1px solid var(--line);border-radius:999px;font-size:13px;cursor:pointer;color:var(--dim);transition:.15s}
.pill span:hover{color:var(--txt);border-color:#3a3a3a}
.pill input:checked+span{background:var(--acc);color:#000;border-color:var(--acc)}
.pill input:focus-visible+span{outline:2px solid var(--acc);outline-offset:2px}
input[type=url]{width:100%;background:var(--bg);border:1px solid var(--line);border-radius:10px;color:var(--txt);padding:12px 14px;font:inherit;outline:none}
input[type=url]:focus{border-color:#555}
.drop{display:block;border:1px dashed #333;border-radius:10px;padding:22px;text-align:center;color:var(--dim);cursor:pointer;transition:.15s}
.drop:hover,.drop.over{border-color:#777;color:var(--txt)}
[hidden]{display:none!important}
.drop{position:relative}.drop input{position:absolute;inset:0;opacity:0;cursor:pointer}
button{margin-top:18px;width:100%;background:var(--acc);color:#000;border:0;border-radius:10px;padding:12px;font:600 15px/1 inherit;font-family:inherit;cursor:pointer;transition:.15s}
button:hover{opacity:.85}button:disabled{opacity:.4;cursor:wait}
.msg{margin-top:10px;font-size:13px;color:var(--dim);min-height:1em;white-space:pre-wrap}.msg.err{color:#ff6b6b}
.dl .br,.cv .br,.dl .q{display:none}
.dl:has(input[value=audio]:checked) .br,.cv:has(input[value=mp3]:checked) .br,.dl:has(input[value=video]:checked) .q{display:flex}
.bar{margin-top:14px;height:4px;background:var(--line);border-radius:4px;overflow:hidden;position:relative}
.bar i{display:block;height:100%;width:0;background:var(--acc);transition:width .3s}
.bar.ind i{width:30%;position:absolute;animation:slide 1.1s ease-in-out infinite}
@keyframes slide{from{left:-30%}to{left:100%}}
footer{color:#444;font-size:12px;text-align:center;margin-top:32px}
.legal{line-height:1.7}.legal h3{font-size:15px;margin:28px 0 4px}.legal p{color:#bdbdbd;margin:0 0 10px}
.legal a,footer a{color:inherit}footer a:hover{color:var(--txt)}
</style>
<main>
<h1>tool<i>shed</i></h1>
<p class=sub>grab it. convert it. done.</p>

<section><h2>Download &middot; YouTube / TikTok</h2>
<form class=dl action=/download>
<input name=url type=url required placeholder="paste a link" aria-label="Video link">
<div class=row><span class=k>as</span><div class=pills>{kinds}</div></div>
{quality}
{br_dl}
<button>Download</button><div class=bar hidden><i></i></div><div class=msg role=status></div></form></section>

<section><h2>Convert</h2>
<form class=cv action=/convert>
<label class=drop><input name=file type=file required><span>drop a file or click to pick</span></label>
{groups}
{br_cv}
<button>Convert</button><div class=bar hidden><i></i></div><div class=msg role=status></div></form></section>
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
  const b=f.querySelector('button'),m=f.querySelector('.msg'),bar=f.querySelector('.bar'),fill=bar.querySelector('i'),label=b.textContent;
  const show=(stage,pct)=>{bar.classList.toggle('ind',pct==null);fill.style.width=pct==null?'':pct+'%';m.textContent=stage+(pct==null?'…':' · '+Math.floor(pct)+'%')};
  b.disabled=true;b.textContent='Working…';m.className='msg';bar.hidden=false;show('uploading',0);
  try{
    const {id}=await post(f.getAttribute('action'),new FormData(f),p=>show('uploading',p));
    for(;;){
      const r=await fetch('/progress/'+id);if(!r.ok)throw new Error(await r.text());
      const s=await r.json();
      if(s.error)throw new Error(s.error);
      if(s.done)break;
      show(s.stage,s.pct);await sleep(400);
    }
    show('done',100);m.textContent='Done · saving file';
    Object.assign(document.createElement('a'),{href:'/file/'+id}).click();
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
        PAGE.replace("{kinds}", pills("kind", ["video", "audio"], "video", {"video": "video · mp4", "audio": "audio · mp3"}))
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


@app.post("/download")
def download():
    url = request.form.get("url", "").strip()
    if not url.startswith(("http://", "https://")):
        return "Invalid URL", 400
    if any(b in url for b in BLOCKED):
        return "This link has been blocked after a copyright request.", 451
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
