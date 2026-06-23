# C DL

C DL is a Windows desktop downloader built around `yt-dlp`, with a Traditional
Chinese interface, local settings, queue support, playlist folders, MP4 video
downloads, and MP3 audio extraction.

## Features

- Traditional Chinese desktop UI
- Apple-inspired dark interface and link animation
- Automatic link analysis after pasting a URL
- Video MP4 and audio MP3 modes
- Video quality options: best, 1080p, 720p, 480p
- MP3 quality options: 320 kbps, 192 kbps, 128 kbps
- Custom download folder with saved preferences
- Download queue
- Playlist downloads are saved into a generated folder
- Historical download count
- Bundled FFmpeg support for packaged builds
- Windows portable EXE and NSIS installer builds

## Important Notice

C DL is a wrapper around `yt-dlp`. Supported websites depend on yt-dlp
extractors and the source website behavior. Users are responsible for complying
with website terms of service and content licenses.

## Development Requirements

- Windows
- Python 3.10 or newer
- Node.js and npm

## Run In Development

```powershell
.\app-start.ps1
```

The script creates a local Python virtual environment, installs Python
dependencies, installs Electron dependencies if needed, and opens the desktop
app.

Browser-only fallback:

```powershell
.\start.ps1
```

## Build Packaged Apps

Install dependencies first:

```powershell
npm.cmd install
.\.venv\Scripts\python.exe -m pip install --upgrade -r requirements.txt
```

Build the Python backend folder used by Electron:

```powershell
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onedir --name backend --distpath py-dist --workpath py-build --specpath py-build --collect-all imageio_ffmpeg --collect-all yt_dlp --collect-all yt_dlp_ejs app.py
Copy-Item -LiteralPath .\py-dist\backend -Destination .\backend -Recurse -Force
```

Build the portable EXE:

```powershell
npm.cmd run dist
```

Build the installer:

```powershell
npm.cmd run installer
```

Outputs are created in `dist/`.

## Project Structure

- `app.py` - local Python HTTP backend and yt-dlp integration
- `static/` - frontend HTML, CSS, JavaScript, and logo asset
- `desktop/` - Electron main/preload scripts
- `requirements.txt` - Python dependencies
- `package.json` - Electron build configuration

## Privacy

See [PRIVACY.md](PRIVACY.md).

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).
