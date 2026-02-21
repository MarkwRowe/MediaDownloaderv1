import os
import re
import sys
import threading
import time
import uuid
import webbrowser
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from flask import Flask, jsonify, request, send_file, send_from_directory
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

app = Flask(__name__)

if getattr(sys, "frozen", False):
    ASSET_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    ASSET_DIR = Path(__file__).resolve().parent
    BASE_DIR = ASSET_DIR

DOWNLOAD_DIR = BASE_DIR / "downloads"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

jobs = {}
jobs_lock = threading.Lock()


def detect_ffmpeg_bin_dir() -> str | None:
    env_dir = os.environ.get("FFMPEG_LOCATION")
    if env_dir and Path(env_dir).exists():
        return env_dir

    winget_root = (
        Path.home()
        / "AppData"
        / "Local"
        / "Microsoft"
        / "WinGet"
        / "Packages"
        / "Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
    )
    if winget_root.exists():
        matches = list(winget_root.glob("**/bin/ffmpeg.exe"))
        if matches:
            return str(matches[0].parent)

    return None


def parse_duration(seconds: int | None) -> str:
    if not seconds:
        return "Unknown"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:d}:{s:02d}"


def update_job(job_id: str, **kwargs):
    with jobs_lock:
        if job_id in jobs:
            jobs[job_id].update(kwargs)


def is_valid_youtube_url(url: str) -> bool:
    if not url:
        return False
    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = (parsed.netloc or "").lower().replace("www.", "")

    if host == "youtu.be":
        return bool(parsed.path.strip("/"))

    if host in {"youtube.com", "m.youtube.com"}:
        if parsed.path == "/watch":
            return "v" in parse_qs(parsed.query)
        if parsed.path.startswith("/shorts/"):
            return bool(parsed.path.split("/shorts/", 1)[1])
        return False

    return False


def is_valid_tiktok_url(url: str) -> bool:
    if not url:
        return False
    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = (parsed.netloc or "").lower().replace("www.", "")
    if host in {"tiktok.com", "m.tiktok.com", "vm.tiktok.com", "vt.tiktok.com"}:
        return bool(parsed.path.strip("/"))
    return False


def is_valid_instagram_url(url: str) -> bool:
    if not url:
        return False
    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = (parsed.netloc or "").lower().replace("www.", "")
    if host not in {"instagram.com", "m.instagram.com"}:
        return False
    path = parsed.path or ""
    return path.startswith("/reel/") or path.startswith("/p/") or path.startswith("/tv/")


def safe_float(value) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    text = text.replace("%", "")
    text = text.replace("$", "")
    try:
        return float(text)
    except ValueError:
        return None


def score_higher_better(value: float | None, good: float, ok: float) -> int | None:
    if value is None:
        return None
    if value >= good:
        return 95
    if value >= ok:
        return 75
    return 45


def score_lower_better(value: float | None, good: float, ok: float) -> int | None:
    if value is None:
        return None
    if value <= good:
        return 95
    if value <= ok:
        return 75
    return 45


def get_format_selector(fmt: str, quality: str, sound_on: bool) -> str:
    quality_map = {
        "360p": "360",
        "720p": "720",
        "1080p60": "1080",
    }
    if quality not in quality_map:
        raise ValueError("Unsupported quality")

    max_h = quality_map[quality]

    if fmt == "mp3":
        return "bestaudio/best"

    if fmt != "mp4":
        raise ValueError("Unsupported format")

    if quality == "1080p60":
        if sound_on:
            return (
                "bestvideo[ext=mp4][height<=1080][fps>=60]+bestaudio[ext=m4a]"
                "/bestvideo[height<=1080][fps>=60]+bestaudio"
                "/best[ext=mp4][height<=1080][fps>=60]"
                "/best[height<=1080]"
            )
        return (
            "bestvideo[ext=mp4][height<=1080][fps>=60]"
            "/bestvideo[height<=1080][fps>=60]"
            "/bestvideo[height<=1080]"
        )

    if sound_on:
        return (
            f"bestvideo[ext=mp4][height<={max_h}]+bestaudio[ext=m4a]"
            f"/best[ext=mp4][height<={max_h}]"
            f"/best[height<={max_h}]"
        )

    return f"bestvideo[ext=mp4][height<={max_h}]/bestvideo[height<={max_h}]"


def sanitize_file_basename(name: str | None) -> str | None:
    if name is None:
        return None
    text = str(name).strip()
    text = Path(text).stem if Path(text).suffix else text
    safe = re.sub(r"[^A-Za-z0-9._ -]", "_", text).strip(" .")
    return safe or None


def resolve_output_path(info: dict, fmt: str, download_dir: Path, preferred_base: str | None = None) -> Path:
    requested = info.get("requested_downloads") or []
    if requested:
        fp = requested[0].get("filepath")
        if fp:
            path = Path(fp)
            if fmt == "mp3":
                return path.with_suffix(".mp3")
            return path

    template_base = preferred_base or info.get("title") or "download"
    safe = sanitize_file_basename(template_base) or "download"
    ext = "mp3" if fmt == "mp3" else "mp4"
    return download_dir / f"{safe}.{ext}"


def run_download_job(
    job_id: str,
    url: str,
    fmt: str,
    quality: str,
    sound_on: bool,
    output_dir: str | None,
    output_name: str | None,
):
    try:
        format_selector = get_format_selector(fmt, quality, sound_on)
    except ValueError as exc:
        update_job(job_id, status="error", error=str(exc), progress=0)
        return

    target_dir = DOWNLOAD_DIR
    if output_dir:
        target_dir = Path(output_dir).expanduser()

    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        update_job(job_id, status="error", error=f"Cannot create download folder: {exc}", progress=0)
        return

    safe_name = sanitize_file_basename(output_name) or job_id
    outtmpl = str(target_dir / f"{safe_name}.%(ext)s")

    def hook(d):
        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes") or 0
            if total > 0:
                pct = int((downloaded / total) * 100)
                update_job(job_id, progress=max(1, min(pct, 99)))
        elif status == "finished":
            update_job(job_id, progress=98)

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "format": format_selector,
        "outtmpl": outtmpl,
        "progress_hooks": [hook],
    }

    ffmpeg_bin_dir = detect_ffmpeg_bin_dir()
    if ffmpeg_bin_dir:
        ydl_opts["ffmpeg_location"] = ffmpeg_bin_dir

    if fmt == "mp3":
        ydl_opts["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "320",
            }
        ]
    elif fmt == "mp4" and sound_on:
        ydl_opts["merge_output_format"] = "mp4"

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        final_path = resolve_output_path(info, fmt, target_dir, preferred_base=safe_name)

        if not final_path.exists():
            candidates = sorted(target_dir.glob(f"{safe_name}.*"), key=lambda p: p.stat().st_mtime, reverse=True)
            if candidates:
                final_path = candidates[0]

        if not final_path.exists():
            raise FileNotFoundError("Download finished but output file was not found.")

        update_job(
            job_id,
            status="completed",
            progress=100,
            file_path=str(final_path),
            file_name=final_path.name,
            saved_dir=str(final_path.parent),
        )
    except DownloadError as exc:
        msg = str(exc)
        if "Sign in to confirm your age" in msg:
            msg = "This video is age-restricted and cannot be downloaded without authentication."
        update_job(job_id, status="error", error=msg, progress=0)
    except Exception as exc:
        update_job(job_id, status="error", error=str(exc), progress=0)


def run_social_download_job(job_id: str, url: str, output_dir: str | None, output_name: str | None):
    target_dir = DOWNLOAD_DIR
    if output_dir:
        target_dir = Path(output_dir).expanduser()

    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        update_job(job_id, status="error", error=f"Cannot create download folder: {exc}", progress=0)
        return

    safe_name = sanitize_file_basename(output_name) or job_id
    outtmpl = str(target_dir / f"{safe_name}.%(ext)s")

    def hook(d):
        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes") or 0
            if total > 0:
                pct = int((downloaded / total) * 100)
                update_job(job_id, progress=max(1, min(pct, 99)))
        elif status == "finished":
            update_job(job_id, progress=98)

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "outtmpl": outtmpl,
        "progress_hooks": [hook],
        "merge_output_format": "mp4",
    }

    ffmpeg_bin_dir = detect_ffmpeg_bin_dir()
    if ffmpeg_bin_dir:
        ydl_opts["ffmpeg_location"] = ffmpeg_bin_dir

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        final_path = resolve_output_path(info, "mp4", target_dir, preferred_base=safe_name)

        if not final_path.exists():
            candidates = sorted(target_dir.glob(f"{safe_name}.*"), key=lambda p: p.stat().st_mtime, reverse=True)
            if candidates:
                final_path = candidates[0]

        if not final_path.exists():
            raise FileNotFoundError("Download finished but output file was not found.")

        update_job(
            job_id,
            status="completed",
            progress=100,
            file_path=str(final_path),
            file_name=final_path.name,
            saved_dir=str(final_path.parent),
        )
    except DownloadError as exc:
        update_job(job_id, status="error", error=str(exc), progress=0)
    except Exception as exc:
        update_job(job_id, status="error", error=str(exc), progress=0)


def analyze_metrics(metrics: dict) -> dict:
    views = safe_float(metrics.get("views"))
    likes = safe_float(metrics.get("likes"))
    dislikes = safe_float(metrics.get("dislikes"))
    ctr = safe_float(metrics.get("ctr"))
    avd = safe_float(metrics.get("avd"))
    apv = safe_float(metrics.get("apv"))
    impressions = safe_float(metrics.get("impressions"))
    unique_viewers = safe_float(metrics.get("unique_viewers"))
    watch_time = safe_float(metrics.get("watch_time"))
    shares = safe_float(metrics.get("shares"))
    comments = safe_float(metrics.get("comments"))
    subs_gained = safe_float(metrics.get("subs_gained"))
    subs_lost = safe_float(metrics.get("subs_lost"))
    returning_viewers = safe_float(metrics.get("returning_viewers"))
    new_viewers = safe_float(metrics.get("new_viewers"))
    end_screen_ctr = safe_float(metrics.get("end_screen_ctr"))
    card_clicks = safe_float(metrics.get("card_teaser_clicks"))
    rpm = safe_float(metrics.get("rpm"))
    cpm = safe_float(metrics.get("cpm"))
    playback_cpm = safe_float(metrics.get("playback_cpm"))
    estimated_revenue = safe_float(metrics.get("estimated_revenue"))
    audience_retention = safe_float(metrics.get("audience_retention"))
    relative_retention = safe_float(metrics.get("relative_retention"))
    sub_to_view_ratio = safe_float(metrics.get("sub_to_view_ratio"))
    engagement_rate = safe_float(metrics.get("engagement_rate"))

    if views and views > 0 and engagement_rate is None:
        total_interactions = (likes or 0) + (comments or 0) + (shares or 0)
        engagement_rate = (total_interactions / views) * 100

    if views and views > 0 and sub_to_view_ratio is None:
        sub_to_view_ratio = ((subs_gained or 0) / views) * 100

    if apv is None and avd is not None:
        duration = safe_float(metrics.get("duration_seconds"))
        if duration and duration > 0:
            apv = (avd / duration) * 100

    results = []
    tips = []

    def add_metric(name: str, value, score, low_tip: str, high_tip: str | None = None):
        if score is None:
            results.append({"name": name, "value": value, "score": None, "rating": "No data"})
            return
        rating = "Excellent" if score >= 90 else "Good" if score >= 70 else "Needs Work"
        results.append({"name": name, "value": value, "score": score, "rating": rating})
        if score < 70:
            tips.append(low_tip)
        elif high_tip:
            tips.append(high_tip)

    add_metric("CTR", ctr, score_higher_better(ctr, 6.0, 3.5), "Low CTR: test 2-3 stronger title/thumbnail combinations with clearer promise.")
    add_metric("AVD (sec)", avd, score_higher_better(avd, 240, 90), "Low AVD: tighten first 30 seconds and remove slow segments.")
    add_metric("APV (%)", apv, score_higher_better(apv, 45, 30), "Low APV: improve pacing and set up stronger open loops.")
    add_metric("Engagement Rate (%)", engagement_rate, score_higher_better(engagement_rate, 4.0, 2.0), "Low engagement: ask a specific comment question and add a stronger CTA.")
    add_metric("Audience Retention (%)", audience_retention, score_higher_better(audience_retention, 45, 30), "Low retention: inspect drop-off timestamps and trim weak sections.")
    add_metric("Relative Retention (%)", relative_retention, score_higher_better(relative_retention, 100, 80), "Relative retention is below peers: tighten storytelling and add pattern interrupts.")
    add_metric("Sub-to-View Ratio (%)", sub_to_view_ratio, score_higher_better(sub_to_view_ratio, 1.0, 0.3), "Low subscriber conversion: explicitly state why viewers should subscribe.")
    add_metric("End Screen CTR (%)", end_screen_ctr, score_higher_better(end_screen_ctr, 1.0, 0.5), "Low end-screen CTR: simplify to one clear next-video recommendation.")
    add_metric("Shares", shares, score_higher_better(shares, 50, 10), "Low shares: add practical takeaways people can send to others.")
    add_metric("Comments", comments, score_higher_better(comments, 25, 5), "Low comments: pin a polarizing or specific question.")
    add_metric("Subscribers Gained", subs_gained, score_higher_better(subs_gained, 20, 5), "Few subscribers gained: clarify channel value proposition in intro and outro.")
    add_metric("Subscribers Lost", subs_lost, score_lower_better(subs_lost, 5, 20), "High subscriber loss: align content topic with audience expectations.")
    add_metric("Returning Viewers", returning_viewers, score_higher_better(returning_viewers, 1000, 200), "Low returning viewers: publish consistent series and recurring formats.")
    add_metric("New Viewers", new_viewers, score_higher_better(new_viewers, 1000, 200), "Low new viewers: improve search intent alignment and topic selection.")
    add_metric("Card Teaser Clicks", card_clicks, score_higher_better(card_clicks, 30, 8), "Low card clicks: place cards at high-retention moments.")
    add_metric("RPM", rpm, score_higher_better(rpm, 4.0, 1.5), "Low RPM: target higher-intent topics and optimize audience geography.")
    add_metric("CPM", cpm, score_higher_better(cpm, 8.0, 3.0), "Low CPM: adjust content niche toward stronger advertiser demand.")
    add_metric("Playback-based CPM", playback_cpm, score_higher_better(playback_cpm, 8.0, 3.0), "Low playback CPM: improve ad-friendly pacing and topic fit.")
    add_metric("Estimated Revenue", estimated_revenue, score_higher_better(estimated_revenue, 100, 20), "Low revenue: focus on videos with stronger retention and ad suitability.")

    if views is not None and impressions is not None and impressions > 0:
        view_from_impressions = (views / impressions) * 100
        add_metric(
            "View/Impression Ratio (%)",
            view_from_impressions,
            score_higher_better(view_from_impressions, 6.0, 3.0),
            "Low views from impressions: test new packaging (title/thumbnail) and improve hook delivery.",
        )

    if likes is not None and dislikes is not None and (likes + dislikes) > 0:
        like_ratio = (likes / (likes + dislikes)) * 100
        add_metric(
            "Like Ratio (%)",
            like_ratio,
            score_higher_better(like_ratio, 95, 85),
            "Low like ratio: clarify expectations in title and deliver on promise sooner.",
        )

    numeric_scores = [r["score"] for r in results if isinstance(r.get("score"), int)]
    overall_score = int(sum(numeric_scores) / len(numeric_scores)) if numeric_scores else 0

    if overall_score >= 85:
        verdict = "Strong performance"
    elif overall_score >= 70:
        verdict = "Healthy, but with optimization room"
    else:
        verdict = "Underperforming"

    if not tips:
        tips.append("Metrics look healthy. Keep testing titles, thumbnails, and first-30-second hooks.")

    return {
        "overall_score": overall_score,
        "verdict": verdict,
        "metrics": results,
        "tips": tips[:12],
        "notes": [
            "Most advanced metrics (CTR, AVD, APV, retention, revenue, RPM/CPM) are YouTube Studio analytics inputs.",
            "Public fetch can auto-fill only limited fields like views/likes/comments/title/duration.",
        ],
    }


@app.route("/")
def index():
    return send_from_directory(ASSET_DIR, "index.html")


@app.route("/mediaLogo.png")
def media_logo():
    return send_from_directory(ASSET_DIR, "mediaLogo.png")


@app.route("/favicon.ico")
def favicon():
    return send_from_directory(ASSET_DIR, "mediaLogo.png")


@app.route("/fetch_info", methods=["POST"])
def fetch_info():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()

    if not is_valid_youtube_url(url):
        return jsonify({"error": "Invalid YouTube URL."}), 400

    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "extract_flat": False,
    }

    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)

        return jsonify(
            {
                "title": info.get("title", "Unknown title"),
                "thumbnail": info.get("thumbnail", ""),
                "duration": parse_duration(info.get("duration")),
                "duration_seconds": info.get("duration"),
                "views": info.get("view_count"),
                "likes": info.get("like_count"),
                "dislikes": info.get("dislike_count"),
                "comments": info.get("comment_count"),
                "channel": info.get("channel") or info.get("uploader"),
                "upload_date": info.get("upload_date"),
            }
        )
    except DownloadError as exc:
        msg = str(exc)
        if "Sign in to confirm your age" in msg:
            msg = "Age-restricted video detected. Sign-in/auth cookies are required."
        return jsonify({"error": msg}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/analyze_video", methods=["POST"])
def analyze_video():
    data = request.get_json(silent=True) or {}
    metrics = data.get("metrics") or {}
    if not isinstance(metrics, dict):
        return jsonify({"error": "metrics must be an object."}), 400
    return jsonify(analyze_metrics(metrics))


@app.route("/download", methods=["POST"])
def start_download():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    fmt = (data.get("format") or "mp4").strip().lower()
    quality = (data.get("quality") or "1080p60").strip()
    sound_on = bool(data.get("sound_on", True))
    output_dir_raw = (data.get("output_dir") or "").strip()
    output_name_raw = (data.get("output_name") or "").strip()

    if not is_valid_youtube_url(url):
        return jsonify({"error": "Invalid YouTube URL."}), 400

    if fmt not in {"mp4", "mp3"}:
        return jsonify({"error": "Format must be mp4 or mp3."}), 400

    if quality not in {"360p", "720p", "1080p60"}:
        return jsonify({"error": "Quality must be 360p, 720p, or 1080p60."}), 400

    if fmt == "mp3" and not sound_on:
        return jsonify({"error": "Sound Off is not valid for MP3 downloads."}), 400

    output_dir = None
    if output_dir_raw:
        try:
            output_dir = str(Path(output_dir_raw).expanduser())
        except Exception:
            return jsonify({"error": "Invalid output folder path."}), 400

    output_name = None
    if output_name_raw:
        output_name = sanitize_file_basename(output_name_raw)
        if not output_name:
            return jsonify({"error": "Invalid output file name."}), 400

    job_id = uuid.uuid4().hex
    with jobs_lock:
        jobs[job_id] = {
            "status": "queued",
            "progress": 0,
            "error": None,
            "file_path": None,
            "file_name": None,
            "saved_dir": None,
            "created_at": time.time(),
        }

    t = threading.Thread(
        target=run_download_job,
        args=(job_id, url, fmt, quality, sound_on, output_dir, output_name),
        daemon=True,
    )
    t.start()

    return jsonify({"job_id": job_id})


def parse_output_settings(data: dict) -> tuple[str | None, str | None, str | None]:
    output_dir_raw = (data.get("output_dir") or "").strip()
    output_name_raw = (data.get("output_name") or "").strip()

    output_dir = None
    if output_dir_raw:
        try:
            output_dir = str(Path(output_dir_raw).expanduser())
        except Exception:
            return None, None, "Invalid output folder path."

    output_name = None
    if output_name_raw:
        output_name = sanitize_file_basename(output_name_raw)
        if not output_name:
            return None, None, "Invalid output file name."

    return output_dir, output_name, None


def create_job() -> str:
    job_id = uuid.uuid4().hex
    with jobs_lock:
        jobs[job_id] = {
            "status": "queued",
            "progress": 0,
            "error": None,
            "file_path": None,
            "file_name": None,
            "saved_dir": None,
            "created_at": time.time(),
        }
    return job_id


@app.route("/download_tiktok", methods=["POST"])
def download_tiktok():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not is_valid_tiktok_url(url):
        return jsonify({"error": "Invalid TikTok URL."}), 400

    output_dir, output_name, error = parse_output_settings(data)
    if error:
        return jsonify({"error": error}), 400

    job_id = create_job()
    t = threading.Thread(
        target=run_social_download_job,
        args=(job_id, url, output_dir, output_name),
        daemon=True,
    )
    t.start()
    return jsonify({"job_id": job_id})


@app.route("/download_instagram", methods=["POST"])
def download_instagram():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not is_valid_instagram_url(url):
        return jsonify({"error": "Invalid Instagram URL."}), 400

    output_dir, output_name, error = parse_output_settings(data)
    if error:
        return jsonify({"error": error}), 400

    job_id = create_job()
    t = threading.Thread(
        target=run_social_download_job,
        args=(job_id, url, output_dir, output_name),
        daemon=True,
    )
    t.start()
    return jsonify({"job_id": job_id})


@app.route("/progress/<job_id>", methods=["GET"])
def get_progress(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)

    if not job:
        return jsonify({"error": "Job not found."}), 404

    payload = {
        "status": job["status"],
        "progress": job["progress"],
        "error": job["error"],
    }

    if job["status"] == "completed":
        payload["download_url"] = f"/file/{job_id}"
        payload["file_name"] = job["file_name"]
        payload["saved_path"] = job["file_path"]
        payload["saved_dir"] = job["saved_dir"]

    return jsonify(payload)


@app.route("/file/<job_id>", methods=["GET"])
def get_file(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)

    if not job:
        return jsonify({"error": "Job not found."}), 404

    if job.get("status") != "completed" or not job.get("file_path"):
        return jsonify({"error": "File is not ready."}), 400

    path = Path(job["file_path"])
    if not path.exists():
        return jsonify({"error": "File no longer exists."}), 404

    return send_file(path, as_attachment=True, download_name=job.get("file_name") or path.name)


if __name__ == "__main__":
    debug_mode = os.environ.get("FLASK_DEBUG", "").strip() in {"1", "true", "True"}
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))

    # Open the app UI automatically when launched as EXE/non-debug run.
    if not debug_mode or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        app_url = f"http://{host}:{port}"
        threading.Timer(1.0, lambda: webbrowser.open_new_tab(app_url)).start()

    app.run(host=host, port=port, debug=debug_mode)


