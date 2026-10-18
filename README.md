# toolshed

Grab videos from YouTube and TikTok, or convert a file to another format. One page, no accounts.

## What it does

- **Download** a YouTube or TikTok link as mp4 (best, 1080p, 720p, 480p, 360p) or mp3 (128k to 320k).
- **Transcribe** a YouTube or TikTok link to plain text from its captions, to copy or save as .txt.
- **Convert** video, audio and images between common formats. It only offers formats that make sense for the file you drop in.
- Shows live progress for downloads, uploads and conversions.

## Run it locally

You need Python 3.11+ and [ffmpeg](https://ffmpeg.org/download.html) on your PATH.

```
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000.

For YouTube, also install [deno](https://deno.com). yt-dlp uses it to read YouTube's player, and some formats are missing without it.

## Run it with Docker

```
docker build -t toolshed .
docker run -p 8080:8080 toolshed
```

## Tests

```
python test_app.py
```

## How it works

A small Flask app. [yt-dlp](https://github.com/yt-dlp/yt-dlp) handles downloads and ffmpeg handles conversions. Each job runs in a background thread, the page polls for progress, and the temp files are deleted once the result is sent.

Jobs are kept in memory, so run a single process.

## Notes

- Only download things you have the right to.
- YouTube changes often. If downloads break, update yt-dlp: `pip install -U yt-dlp`.
