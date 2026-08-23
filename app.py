from __future__ import annotations

import json
import hmac
import ipaddress
import mimetypes
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse


ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
STATIC = Path(os.environ.get("CDL_STATIC_DIR", ROOT / "static"))
CONFIG_DIR = Path(os.environ.get("CDL_CONFIG_DIR", Path(__file__).resolve().parent))
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_FILE = CONFIG_DIR / "config.json"
DEFAULT_DOWNLOADS = Path.home() / "Downloads" / "C DL"
DEV_DOWNLOADS = Path(__file__).resolve().parent / "downloads"
DEV_DOWNLOADS.mkdir(exist_ok=True)

HOST = "127.0.0.1"
PORT = int(os.environ.get("YTDLP_UI_PORT", "8765"))
APP_ORIGIN = f"http://{HOST}:{PORT}"
SESSION_COOKIE = "cdl_session"
SESSION_TOKEN = secrets.token_urlsafe(32)
MAX_JSON_BODY = 64 * 1024
MAX_JOBS = 100

jobs: dict[str, dict] = {}
jobs_lock = threading.Lock()
settings_lock = threading.Lock()
completed_downloads: list[dict] = []
completed_lock = threading.Lock()


class AudioValidationError(RuntimeError):
    pass


class JobLogger:
    def __init__(self, job_id: str) -> None:
        self.job_id = job_id

    def debug(self, message: str) -> None:
        if message and "[download]" in message:
            append_log(self.job_id, message)

    def warning(self, message: str) -> None:
        append_log(self.job_id, f"警告：{message}")

    def error(self, message: str) -> None:
        append_log(self.job_id, f"錯誤：{message}")


def now_id() -> str:
    return secrets.token_urlsafe(12)


def safe_json(handler: BaseHTTPRequestHandler, payload: dict, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    send_security_headers(handler)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def send_security_headers(handler: BaseHTTPRequestHandler) -> None:
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("X-Frame-Options", "DENY")
    handler.send_header("Referrer-Policy", "no-referrer")
    handler.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=()")


def read_json(handler: BaseHTTPRequestHandler) -> dict:
    if "application/json" not in handler.headers.get("Content-Type", "").lower():
        raise ValueError("請使用 JSON 格式送出要求。")
    try:
        length = int(handler.headers.get("Content-Length", "0"))
    except ValueError as exc:
        raise ValueError("要求大小無效。") from exc
    if length <= 0:
        return {}
    if length > MAX_JSON_BODY:
        raise ValueError("要求內容過大。")
    raw = handler.rfile.read(length)
    if len(raw) != length:
        raise ValueError("要求內容不完整。")
    return json.loads(raw.decode("utf-8"))


def valid_host(handler: BaseHTTPRequestHandler) -> bool:
    return handler.headers.get("Host", "").lower() in {f"{HOST}:{PORT}", f"localhost:{PORT}"}


def valid_session(handler: BaseHTTPRequestHandler) -> bool:
    try:
        cookies = SimpleCookie(handler.headers.get("Cookie", ""))
        value = cookies.get(SESSION_COOKIE)
        return bool(value and hmac.compare_digest(value.value, SESSION_TOKEN))
    except Exception:
        return False


def valid_post_origin(handler: BaseHTTPRequestHandler) -> bool:
    return handler.headers.get("Origin", "") in {APP_ORIGIN, f"http://localhost:{PORT}"}


def set_session_cookie(handler: BaseHTTPRequestHandler) -> None:
    handler.send_header(
        "Set-Cookie",
        f"{SESSION_COOKIE}={SESSION_TOKEN}; Path=/; Max-Age=86400; HttpOnly; SameSite=Strict",
    )


def default_settings() -> dict:
    default_dir = str(DEFAULT_DOWNLOADS if getattr(sys, "frozen", False) else DEV_DOWNLOADS)
    return {
        "download_dir": default_dir,
        "download_count": 0,
        "mode": "video",
        "quality": "best",
        "audio_quality": "192",
    }


def normalize_settings(data: dict | None) -> dict:
    settings = default_settings()
    if isinstance(data, dict):
        for key, value in data.items():
            if key not in {"download_history", "downloads", "history"}:
                settings[key] = value
    settings["download_dir"] = str(Path(settings.get("download_dir") or settings["download_dir"]).expanduser())
    try:
        settings["download_count"] = max(0, int(settings.get("download_count") or 0))
    except (TypeError, ValueError):
        settings["download_count"] = 0
    if settings.get("mode") not in {"video", "audio"}:
        settings["mode"] = "video"
    if settings.get("quality") not in {"best", "1080", "720", "small"}:
        settings["quality"] = "best"
    if str(settings.get("audio_quality")) not in {"128", "192", "320"}:
        settings["audio_quality"] = "192"
    return settings


def load_settings() -> dict:
    with settings_lock:
        if not CONFIG_FILE.exists():
            return default_settings()
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            return default_settings()
    return normalize_settings(data)


def save_settings(data: dict) -> dict:
    current = load_settings()
    next_settings = normalize_settings({**current, **(data or {})})
    path = Path(next_settings["download_dir"]).expanduser()
    if "download_dir" in (data or {}):
        path.mkdir(parents=True, exist_ok=True)
    next_settings["download_dir"] = str(path)
    with settings_lock:
        CONFIG_FILE.write_text(json.dumps(next_settings, ensure_ascii=False, indent=2), encoding="utf-8")
    return next_settings


def increment_download_count(amount: int = 1) -> int:
    settings = load_settings()
    settings["download_count"] = int(settings.get("download_count") or 0) + max(1, amount)
    save_settings(settings)
    return settings["download_count"]


def remember_completed_download(path: str, title: str = "") -> None:
    if not path:
        return
    file_path = Path(path)
    if not file_path.exists():
        return
    stat = file_path.stat()
    try:
        relative_name = file_path.resolve().relative_to(downloads_dir().resolve()).as_posix()
    except ValueError:
        relative_name = file_path.name
    item = {
        "name": relative_name,
        "title": title or file_path.stem,
        "size": readable_bytes(stat.st_size),
        "mtime": stat.st_mtime,
        "url": f"/files/{quote(relative_name)}",
    }
    with completed_lock:
        completed_downloads.insert(0, item)
        del completed_downloads[50:]


def remember_completed_downloads(paths: list[str], title: str = "") -> None:
    for path in sorted(set(paths)):
        remember_completed_download(path, title)


def downloads_dir() -> Path:
    path = Path(load_settings()["download_dir"]).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def ffmpeg_location() -> str | None:
    try:
        import imageio_ffmpeg

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and Path(exe).exists():
            return exe
    except Exception:
        return None
    return None


def append_log(job_id: str, message: str) -> None:
    message = message.strip()
    if not message:
        return
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return
        job.setdefault("logs", []).append(message)
        job["logs"] = job["logs"][-80:]


def update_job(job_id: str, **changes) -> None:
    with jobs_lock:
        if job_id in jobs:
            jobs[job_id].update(changes)


def readable_bytes(value: float | int | None) -> str:
    if not value:
        return ""
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def readable_duration(seconds: float | int | None) -> str:
    if seconds is None:
        return ""
    try:
        total = int(round(float(seconds)))
    except (TypeError, ValueError):
        return ""
    if total <= 0:
        return ""
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours} 小時 {minutes} 分 {secs} 秒"
    if minutes:
        return f"{minutes} 分 {secs} 秒"
    return f"{secs} 秒"


def validate_url(value: str) -> str:
    value = (value or "").strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or not parsed.hostname:
        raise ValueError("請貼上完整的 http 或 https 連結。")
    if parsed.username or parsed.password:
        raise ValueError("連結不可包含帳號或密碼。")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise ValueError("不可下載本機或私人網路網址。")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError("不可下載本機或私人網路網址。")
    return value


def reserve_job(job_id: str) -> None:
    with jobs_lock:
        finished = sorted(
            (job for job in jobs.values() if job.get("status") in {"finished", "error"}),
            key=lambda job: float(job.get("created_at") or 0),
        )
        while len(jobs) >= MAX_JOBS and finished:
            jobs.pop(finished.pop(0)["id"], None)
        if len(jobs) >= MAX_JOBS:
            raise RuntimeError("目前下載工作過多，請等待現有工作完成。")
        jobs[job_id] = {
            "id": job_id,
            "status": "queued",
            "phase": "排隊中",
            "progress": 0,
            "logs": [],
            "created_at": time.time(),
        }


def resolve_download_path(name: str) -> Path:
    folder = downloads_dir().resolve()
    path = (folder / (name or "")).resolve()
    if not path.is_file() or folder not in path.parents:
        raise FileNotFoundError("找不到這個下載檔案。")
    return path


def import_yt_dlp():
    try:
        import yt_dlp

        return yt_dlp
    except Exception as exc:  # pragma: no cover - shown to user at runtime
        raise RuntimeError("yt-dlp 尚未安裝完成，請重新執行 start.ps1。") from exc


def progress_hook(job_id: str):
    def hook(data: dict) -> None:
        status = data.get("status")
        if status == "downloading":
            total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
            downloaded = data.get("downloaded_bytes") or 0
            percent = round((downloaded / total) * 100, 1) if total else 0
            speed = readable_bytes(data.get("speed"))
            eta = data.get("eta")
            update_job(
                job_id,
                status="downloading",
                phase="正在下載",
                progress=percent,
                downloaded=readable_bytes(downloaded),
                total=readable_bytes(total),
                speed=f"{speed}/s" if speed else "",
                eta=readable_duration(eta),
                eta_seconds=eta or 0,
            )
        elif status == "finished":
            filename = data.get("filename") or ""
            update_job(
                job_id,
                status="processing",
                phase="正在合併或轉檔",
                progress=100,
                filename=str(filename),
            )

    return hook


def build_format(mode: str, quality: str, compatibility_mode: bool = False) -> str:
    if mode == "audio":
        return "bestaudio[ext=m4a]/bestaudio/best"
    if compatibility_mode:
        if quality == "1080":
            return "b[ext=mp4][vcodec^=avc1][acodec!=none][height<=1080]/b[ext=mp4][acodec!=none][height<=1080]/b[acodec!=none][height<=1080]/bv*[ext=mp4][vcodec^=avc1][height<=1080]+ba[ext=m4a]/bv*[ext=mp4][height<=1080]+ba[ext=m4a]/best[height<=1080]/best"
        if quality == "720":
            return "b[ext=mp4][vcodec^=avc1][acodec!=none][height<=720]/b[ext=mp4][acodec!=none][height<=720]/b[acodec!=none][height<=720]/bv*[ext=mp4][vcodec^=avc1][height<=720]+ba[ext=m4a]/bv*[ext=mp4][height<=720]+ba[ext=m4a]/best[height<=720]/best"
        if quality == "small":
            return "b[ext=mp4][vcodec^=avc1][acodec!=none][height<=480]/b[ext=mp4][acodec!=none][height<=480]/b[acodec!=none][height<=480]/bv*[ext=mp4][vcodec^=avc1][height<=480]+ba[ext=m4a]/bv*[ext=mp4][height<=480]+ba[ext=m4a]/best[height<=480]/best"
        return "b[ext=mp4][vcodec^=avc1][acodec!=none]/b[ext=mp4][acodec!=none]/b[acodec!=none]/bv*[ext=mp4][vcodec^=avc1]+ba[ext=m4a]/bv*[ext=mp4]+ba[ext=m4a]/best"
    if quality == "1080":
        return "bv*[ext=mp4][vcodec^=avc1][height<=1080]+ba[ext=m4a]/bv*[ext=mp4][height<=1080]+ba[ext=m4a]/bv*[height<=1080]+ba/b[ext=mp4][height<=1080][acodec!=none]/b[height<=1080][acodec!=none]/best[height<=1080]/best"
    if quality == "720":
        return "bv*[ext=mp4][vcodec^=avc1][height<=720]+ba[ext=m4a]/bv*[ext=mp4][height<=720]+ba[ext=m4a]/bv*[height<=720]+ba/b[ext=mp4][height<=720][acodec!=none]/b[height<=720][acodec!=none]/best[height<=720]/best"
    if quality == "small":
        return "b[ext=mp4][height<=480][acodec!=none]/b[height<=480][acodec!=none]/bv*[ext=mp4][vcodec^=avc1][height<=480]+ba[ext=m4a]/bv*[ext=mp4][height<=480]+ba[ext=m4a]/bv*[height<=480]+ba/best[height<=480]/best"
    return "bv*[ext=mp4][vcodec^=avc1]+ba[ext=m4a]/bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4][acodec!=none]/bv*+ba/b[acodec!=none]/best"


def file_has_audio(path: str, ffmpeg: str | None) -> bool | None:
    if not ffmpeg:
        return None
    file_path = Path(path)
    if not file_path.is_file():
        return None
    try:
        result = subprocess.run(
            [ffmpeg, "-hide_banner", "-i", str(file_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except Exception:
        return None
    probe_text = f"{result.stdout}\n{result.stderr}"
    if "Audio:" in probe_text:
        return True
    if "Video:" in probe_text:
        return False
    return None


def validate_video_audio(paths: list[str], ffmpeg: str | None, job_id: str) -> None:
    if not paths:
        raise AudioValidationError("下載完成後找不到輸出檔，無法確認音訊。")
    if not ffmpeg:
        raise AudioValidationError("找不到內建 FFmpeg，無法確認或合併音訊。")
    no_audio: list[str] = []
    unknown: list[str] = []
    for path in paths:
        suffix = Path(path).suffix.lower()
        if suffix in {".mp3", ".m4a", ".aac", ".wav", ".flac", ".opus"}:
            continue
        has_audio = file_has_audio(path, ffmpeg)
        if has_audio is False:
            no_audio.append(Path(path).name)
        elif has_audio is None:
            unknown.append(Path(path).name)
    if no_audio:
        raise AudioValidationError(f"成品缺少音訊軌：{', '.join(no_audio[:3])}")
    if unknown:
        append_log(job_id, f"警告：無法確認部分檔案的音訊軌，已保留檔案：{', '.join(unknown[:3])}")


def remove_recent_outputs(paths: list[str], started_at: float) -> None:
    folder = downloads_dir().resolve()
    for item in paths:
        path = Path(item)
        try:
            resolved = path.resolve()
            if not resolved.is_file() or folder not in resolved.parents:
                continue
            if resolved.stat().st_mtime < started_at - 2:
                continue
            resolved.unlink()
        except Exception:
            pass


def request_headers(url: str) -> dict:
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").rstrip(".").lower()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    }
    if hostname in {"bilibili.com", "b23.tv"} or hostname.endswith((".bilibili.com", ".b23.tv")):
        headers["Origin"] = "https://www.bilibili.com"
        headers["Referer"] = "https://www.bilibili.com/"
    return headers


def output_template(url: str, target_dir: Path) -> dict:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    is_playlist = parsed.path.rstrip("/").endswith("/playlist") or bool(query.get("list"))
    if is_playlist:
        return {
            "default": str(
                target_dir
                / "%(playlist_title).180B"
                / "%(playlist_index)03d - %(title).180B [%(id)s].%(ext)s"
            )
        }
    return {"default": str(target_dir / "%(title).180B [%(id)s].%(ext)s")}


def iter_info_entries(info: dict | None):
    if not isinstance(info, dict):
        return
    entries = info.get("entries")
    if isinstance(entries, list):
        for entry in entries:
            if isinstance(entry, dict):
                yield from iter_info_entries(entry)
    elif info.get("id") or info.get("requested_downloads"):
        yield info


def downloaded_count(info: dict | None, file_count: int) -> int:
    if file_count:
        return file_count
    entries = [entry for entry in iter_info_entries(info)]
    if entries:
        return len(entries)
    return 1


def locate_downloaded_files(info: dict, started_at: float) -> list[str]:
    ids = {str(entry.get("id")) for entry in iter_info_entries(info) if entry.get("id")}
    candidates: list[Path] = []
    folder = downloads_dir()
    for path in folder.rglob("*"):
        if not path.is_file() or path.suffix in {".part", ".ytdl"}:
            continue
        if path.stat().st_mtime >= started_at - 2:
            if not ids or any(f"[{video_id}]" in path.name or video_id in path.name for video_id in ids):
                candidates.append(path)
    if candidates:
        candidates.sort(key=lambda item: item.stat().st_mtime, reverse=True)
        return [str(path) for path in candidates]
    found: list[str] = []
    for entry in iter_info_entries(info):
        requested = entry.get("requested_downloads") or []
        for item in requested:
            filepath = item.get("filepath")
            if filepath and Path(filepath).exists():
                found.append(str(Path(filepath)))
    return found


def make_ydl_opts(
    job_id: str,
    url: str,
    mode: str,
    quality: str,
    target_dir: Path,
    ffmpeg: str | None,
    compatibility_mode: bool = False,
    overwrite: bool = False,
) -> dict:
    ydl_opts = {
        "format": build_format(mode, quality, compatibility_mode),
        "outtmpl": output_template(url, target_dir),
        "windowsfilenames": True,
        "overwrites": overwrite,
        "ignoreerrors": False,
        "merge_output_format": "mp4",
        "format_sort": ["res", "ext:mp4:m4a"],
        "retries": 10,
        "fragment_retries": 10,
        "extractor_retries": 3,
        "file_access_retries": 3,
        "geo_bypass": True,
        "http_headers": request_headers(url),
        "progress_hooks": [progress_hook(job_id)],
        "logger": JobLogger(job_id),
        "quiet": True,
        "no_warnings": False,
    }
    if ffmpeg:
        ydl_opts["ffmpeg_location"] = ffmpeg

    if mode == "audio":
        ydl_opts["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": quality if quality in {"128", "192", "320"} else "192",
                }
            ]
    return ydl_opts


def run_download(job_id: str, payload: dict) -> None:
    started_at = time.time()
    try:
        yt_dlp = import_yt_dlp()
        url = validate_url(payload.get("url", ""))
        mode = payload.get("mode", "video")
        quality = str(payload.get("quality", "192" if mode == "audio" else "best"))
        if mode == "audio":
            if quality not in {"128", "192", "320"}:
                quality = "192"
            save_settings({"mode": mode, "audio_quality": quality})
        else:
            if quality not in {"best", "1080", "720", "small"}:
                quality = "best"
            save_settings({"mode": mode, "quality": quality})

        update_job(job_id, status="starting", phase="正在準備 yt-dlp", progress=0)
        target_dir = downloads_dir()
        ffmpeg = ffmpeg_location()

        def download_once(compatibility_mode: bool = False, overwrite: bool = False) -> tuple[dict, list[str]]:
            ydl_opts = make_ydl_opts(
                job_id,
                url,
                mode,
                quality,
                target_dir,
                ffmpeg,
                compatibility_mode=compatibility_mode,
                overwrite=overwrite,
            )
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                next_info = ydl.extract_info(url, download=True) or {}
            next_files = locate_downloaded_files(next_info, started_at)
            if mode != "audio":
                try:
                    validate_video_audio(next_files, ffmpeg, job_id)
                except AudioValidationError as exc:
                    exc.paths = next_files
                    raise
            return next_info, next_files

        info: dict = {}
        files: list[str] = []
        for attempt in range(1, 3):
            try:
                info, files = download_once()
                break
            except AudioValidationError as exc:
                if mode == "audio":
                    raise
                append_log(job_id, f"{exc} 正在改用相容格式重新下載一次...")
                update_job(job_id, status="retrying", phase="成品缺少音訊，正在自動修復", progress=0)
                remove_recent_outputs(getattr(exc, "paths", []), started_at)
                info, files = download_once(compatibility_mode=True, overwrite=True)
                append_log(job_id, "音訊檢查通過。")
                break
            except Exception:
                if attempt >= 2:
                    raise
                append_log(job_id, "第 1 次下載失敗，正在自動重試一次...")
                update_job(job_id, status="retrying", phase="下載失敗，正在自動重試一次", progress=0)
                time.sleep(1)

        title = info.get("title") or ""
        amount = downloaded_count(info, len(files))
        total_count = increment_download_count(amount)
        remember_completed_downloads(files, title)
        update_job(
            job_id,
            status="finished",
            phase="下載完成",
            progress=100,
            filename=files[0] if files else "",
            title=title,
            download_count=total_count,
            completed_count=amount,
        )
    except Exception as exc:
        append_log(job_id, traceback.format_exc())
        update_job(job_id, status="error", phase="下載失敗", error=str(exc))


def extract_info(payload: dict) -> dict:
    yt_dlp = import_yt_dlp()
    url = validate_url(payload.get("url", ""))
    ffmpeg = ffmpeg_location()
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
        "http_headers": request_headers(url),
    }
    if ffmpeg:
        opts["ffmpeg_location"] = ffmpeg
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    return {
        "title": info.get("title") or "未命名",
        "uploader": info.get("uploader") or info.get("channel") or "未知來源",
        "duration": info.get("duration") or 0,
        "thumbnail": info.get("thumbnail") or "",
        "webpage_url": info.get("webpage_url") or url,
        "extractor": info.get("extractor_key") or info.get("extractor") or "",
        "playlist_count": len(info.get("entries") or []) if isinstance(info.get("entries"), list) else 0,
    }


def list_downloads() -> list[dict]:
    folder = downloads_dir().resolve()
    items = []
    with completed_lock:
        source = list(completed_downloads)
    for item in source:
        path = (folder / item["name"]).resolve()
        if path.is_file() and folder in path.parents:
            items.append(item)
    return items


class Handler(BaseHTTPRequestHandler):
    server_version = "YtDlpChineseUI/1.0"

    def log_message(self, fmt: str, *args) -> None:
        return

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        safe_json(self, {"ok": False, "error": message or HTTPStatus(code).phrase}, code)

    def do_GET(self) -> None:
        if not valid_host(self):
            self.send_error(HTTPStatus.MISDIRECTED_REQUEST)
            return
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.serve_file(STATIC / "index.html", issue_session=True)
            return
        if parsed.path.startswith("/static/"):
            name = parsed.path.removeprefix("/static/")
            self.serve_file(STATIC / name)
            return
        if (parsed.path.startswith("/api/") or parsed.path.startswith("/files/")) and not valid_session(self):
            safe_json(self, {"ok": False, "error": "未授權的本機要求。"}, 403)
            return
        if parsed.path == "/api/job":
            query = parse_qs(parsed.query)
            job_id = (query.get("id") or [""])[0]
            with jobs_lock:
                job = dict(jobs.get(job_id) or {})
            if not job:
                safe_json(self, {"ok": False, "error": "找不到這個下載工作。"}, 404)
                return
            safe_json(self, {"ok": True, "job": job})
            return
        if parsed.path == "/api/downloads":
            safe_json(
                self,
                {
                    "ok": True,
                    "items": list_downloads(),
                    "download_count": load_settings().get("download_count", 0),
                },
            )
            return
        if parsed.path == "/api/settings":
            settings = load_settings()
            settings["ffmpeg_ready"] = bool(ffmpeg_location())
            safe_json(self, {"ok": True, "settings": settings})
            return
        if parsed.path.startswith("/files/"):
            filename = unquote(parsed.path.removeprefix("/files/"))
            self.serve_download(filename)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if not valid_host(self) or not valid_session(self) or not valid_post_origin(self):
            safe_json(self, {"ok": False, "error": "未授權的本機要求。"}, 403)
            return
        try:
            payload = read_json(self)
            if self.path == "/api/info":
                safe_json(self, {"ok": True, "info": extract_info(payload)})
                return
            if self.path == "/api/download":
                validate_url(payload.get("url", ""))
                job_id = now_id()
                reserve_job(job_id)
                worker = threading.Thread(target=run_download, args=(job_id, payload), daemon=True)
                worker.start()
                safe_json(self, {"ok": True, "job_id": job_id})
                return
            if self.path == "/api/settings":
                safe_json(self, {"ok": True, "settings": save_settings(payload)})
                return
            if self.path == "/api/open-file":
                path = resolve_download_path(str(payload.get("name") or ""))
                os.startfile(str(path))
                safe_json(self, {"ok": True})
                return
            safe_json(self, {"ok": False, "error": "未知的 API。"}, 404)
        except Exception as exc:
            safe_json(self, {"ok": False, "error": str(exc)}, 400)

    def serve_file(self, path: Path, issue_session: bool = False) -> None:
        path = path.resolve()
        if not path.is_file() or STATIC.resolve() not in path.parents and path != (STATIC / "index.html").resolve():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store" if issue_session else "public, max-age=3600")
        if issue_session:
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: https:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
            )
            set_session_cookie(self)
        send_security_headers(self)
        self.end_headers()
        self.wfile.write(data)

    def serve_download(self, filename: str) -> None:
        try:
            path = resolve_download_path(filename)
        except FileNotFoundError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        size = path.stat().st_size
        filename = path.name.replace('"', "_").replace("\r", "_").replace("\n", "_")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"; filename*=UTF-8\'\'{quote(filename)}')
        self.send_header("Content-Length", str(size))
        self.send_header("Cache-Control", "no-store")
        send_security_headers(self)
        self.end_headers()
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                self.wfile.write(chunk)

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.METHOD_NOT_ALLOWED)
        self.send_header("Allow", "GET, POST")
        send_security_headers(self)
        self.end_headers()


def port_is_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.2)
        return probe.connect_ex((host, port)) != 0


def main() -> None:
    if not port_is_free(HOST, PORT):
        raise SystemExit(f"連接埠 {PORT} 已被使用。可改用：$env:YTDLP_UI_PORT=8766; .\\start.ps1")
    url = f"http://{HOST}:{PORT}"
    print(f"中文 yt-dlp 介面已啟動：{url}")
    print(f"下載資料夾：{downloads_dir()}")
    if os.environ.get("YTDLP_UI_NO_BROWSER") != "1":
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    server.serve_forever()


if __name__ == "__main__":
    main()
