FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
# yt-dlp needs a JS runtime for YouTube.
COPY --from=denoland/deno:bin-2.4.5 /deno /usr/local/bin/deno
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
ENV PORT=8080
EXPOSE 8080
# One worker: jobs live in memory, so every request must hit the same process.
CMD gunicorn -w 1 --threads 16 --timeout 300 -b 0.0.0.0:$PORT app:app
