# Creator Media Toolkit

A simple app that lets you download videos from:
- YouTube
- TikTok
- Instagram

You paste a link, choose format/quality, and download.

## Quick Start (Easiest Way)
If you already have the EXE:

1. Open the `dist` folder.
2. Double-click `CreatorMediaToolkit.exe`.
3. Wait a few seconds.
4. Your browser should open automatically.
5. If it does not open, go to: `http://127.0.0.1:5000`

## How To Use The App

1. Paste a video link into the URL box.
2. Click `Fetch Details` (YouTube only).
3. Pick your format:
   - `MP4` for video
   - `MP3` for audio
4. Pick quality (for YouTube video downloads).
5. Optional: choose a folder and custom file name.
6. Click `Download`.
7. Wait for progress to reach 100%.

## Install and Run From Source (Beginner Steps)

Use this if you want to run the code yourself.

1. Install Python 3.10 or newer.
2. Open PowerShell in this folder (`gitreadyapp`).
3. Create a virtual environment:
```powershell
python -m venv .venv
```
4. Turn on the virtual environment:
```powershell
.\.venv\Scripts\Activate.ps1
```
5. Install required packages:
```powershell
pip install -r requirements.txt
```
6. Start the app:
```powershell
python app.py
```
7. Open your browser to:
`http://127.0.0.1:5000`

## Build the EXE (Windows)

1. Open PowerShell in `gitreadyapp`.
2. Run:
```powershell
.\build_exe.ps1
```
3. Your EXE will be here:
`dist\CreatorMediaToolkit.exe`

## Optional Settings (Advanced)
- `FLASK_DEBUG=1` turns on debug mode.
- `HOST=127.0.0.1` changes host.
- `PORT=5000` changes port.
- `FFMPEG_LOCATION=C:\path\to\ffmpeg\bin` sets FFmpeg path.

## Troubleshooting

1. EXE opens but page does not load:
   - Manually open `http://127.0.0.1:5000`
2. Build fails with file access error:
   - Close any running `CreatorMediaToolkit.exe`
   - Run `.\build_exe.ps1` again
3. Some downloads fail:
   - Update app dependencies
   - Make sure FFmpeg is installed for best MP4/MP3 support

## Legal Notice
Only download content you own or have permission to download.
Follow each platform's rules and your local laws.
