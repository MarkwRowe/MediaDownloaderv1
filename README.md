# Creator Media Toolkit

Flask-based desktop-style web app to:
- Download media from YouTube, TikTok, and Instagram
- Export as MP4 or MP3 (YouTube)
- Analyze video performance metrics

## Requirements
- Python 3.10+
- FFmpeg (recommended for best MP4/MP3 processing)

## Setup
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run
```powershell
python app.py
```

Open `http://127.0.0.1:5000`.

## Optional Environment Variables
- `FLASK_DEBUG=1` to enable debug mode
- `HOST=127.0.0.1` to change bind host
- `PORT=5000` to change port
- `FFMPEG_LOCATION=C:\path\to\ffmpeg\bin`

## Build Windows EXE
From inside `gitreadyapp`:
```powershell
.\build_exe.ps1
```

Output:
- `dist\CreatorMediaToolkit.exe`

## Notes
- Downloaded files are written to `downloads/` by default.
- Do not commit local media downloads, virtualenv files, or caches.

## Disclaimer
Use this project only where you have rights/permission to download content and in compliance with platform terms and local laws.
