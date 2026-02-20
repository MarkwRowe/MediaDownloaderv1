$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$launcher = Join-Path $projectDir 'Start-YouTubeDownloader.ps1'

if (-not (Test-Path $launcher)) {
    throw "Launcher script not found: $launcher"
}

$desktop = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktop 'YouTube Downloader 1080p.lnk'
$workingDir = $projectDir

$iconCandidates = @(
    "$env:SystemRoot\System32\SHELL32.dll,220",
    "$env:SystemRoot\System32\imageres.dll,2"
)
$icon = $iconCandidates[0]

$wsh = New-Object -ComObject WScript.Shell
$sc = $wsh.CreateShortcut($shortcutPath)
$sc.TargetPath = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$sc.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$launcher`""
$sc.WorkingDirectory = $workingDir
$sc.IconLocation = $icon
$sc.WindowStyle = 1
$sc.Description = 'Start YouTube Downloader (Flask + yt-dlp)'
$sc.Save()

Write-Output "Created shortcut: $shortcutPath"
Write-Output "Right-click it -> Pin to taskbar"
