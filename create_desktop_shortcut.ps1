
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$DesktopPath = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $DesktopPath "Context Vault.lnk"

$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)

$VbsPath = Join-Path $ScriptDir "ContextVault.vbs"
$IconPath = Join-Path $ScriptDir "assets\icon.ico"

$Shortcut.TargetPath = "wscript.exe"
$Shortcut.Arguments = "`"$VbsPath`""
$Shortcut.WorkingDirectory = $ScriptDir
$Shortcut.Description = "Context Vault - Local-first agentic file intelligence workspace"

if (Test-Path $IconPath) {
    $Shortcut.IconLocation = "$IconPath, 0"
}

$Shortcut.Save()

Write-Host "[SUCCESS] Created Desktop shortcut at: $ShortcutPath" -ForegroundColor Green
Write-Host "You can now launch Context Vault directly from your desktop!" -ForegroundColor Cyan
