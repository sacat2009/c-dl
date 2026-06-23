# Privacy

C DL is a local desktop application.

## What is stored locally

- Download folder path
- Download mode and quality settings
- Historical download count

On Windows packaged builds, settings are stored under the user's application
data folder for C DL. Development mode stores local runtime files inside the
project folder.

## What is not collected by C DL

- No analytics
- No telemetry
- No account system
- No cloud database
- No upload of downloaded files

## Network access

C DL uses `yt-dlp` to request media metadata and download content from URLs
entered by the user. Those requests are made directly from the user's computer
to the source website.

## Third-party projects

C DL bundles or uses open-source projects including:

- yt-dlp: https://github.com/yt-dlp/yt-dlp
- FFmpeg: https://ffmpeg.org/
- Electron: https://www.electronjs.org/

Users are responsible for complying with the source website terms and content
licenses.
