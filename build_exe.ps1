$ErrorActionPreference = "Stop"

Write-Host "Installing build dependency (PyInstaller)..."
python -m pip install --upgrade pyinstaller
Write-Host "Installing app dependencies..."
python -m pip install -r requirements.txt

Write-Host "Building CreatorMediaToolkit.exe..."
python -m PyInstaller `
  --noconfirm `
  --clean `
  --onefile `
  --name CreatorMediaToolkit `
  --add-data "index.html;." `
  --add-data "mediaLogo.png;." `
  app.py

Write-Host ""
Write-Host "Build complete. EXE is at:"
Write-Host "  .\\dist\\CreatorMediaToolkit.exe"
