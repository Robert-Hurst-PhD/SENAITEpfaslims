<#
  Raw-data conversion on a Windows PC: the fallback when the server's
  converter (pfas-convert, Wine) does not read a vendor's MRM data faithfully
  (docs/RAW_DATA.md). Needs ProteoWizard installed on this PC (its vendor
  readers, under their licences) and write access to the folder the LIMS
  worker reads (System > Raw data share). Run it from Task Scheduler every
  few minutes; set PFAS_CONVERTER=native for the worker.

  Each <name>.raw folder in -Share with no <name>.mzML beside it, and with no
  file changed for -SettleMinutes, is converted with the LIMS's conversion
  profile (the same as the server's: --mzML --64 --zlib). The mzML is written
  to a local temporary folder, copied to <name>.mzML.part in -OutDir and only
  then renamed to <name>.mzML, so the worker never reads a partial file.
#>
param(
    [Parameter(Mandatory = $true)][string]$Share,
    [string]$OutDir = $Share,
    [int]$SettleMinutes = 10,
    [string]$Msconvert = "msconvert.exe"
)
$ErrorActionPreference = "Stop"
$profileArgs = "--mzML --64 --zlib".Split(" ")

Get-ChildItem -Path $Share -Directory -Filter "*.raw" | ForEach-Object {
    $name = $_.BaseName
    $target = Join-Path $OutDir ($name + ".mzML")
    if (Test-Path $target) { return }
    $files = Get-ChildItem -Path $_.FullName -Recurse -File
    if (-not $files) { return }
    $newest = ($files | Measure-Object -Property LastWriteTime -Maximum).Maximum
    if (((Get-Date) - $newest).TotalMinutes -lt $SettleMinutes) { return }   # still being acquired
    $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("pfas-convert-" + [guid]::NewGuid())
    New-Item -ItemType Directory -Path $tmp | Out-Null
    try {
        & $Msconvert $_.FullName @profileArgs -o $tmp
        if ($LASTEXITCODE -ne 0) { Write-Warning "$name : msconvert exited $LASTEXITCODE"; return }
        $made = Join-Path $tmp ($name + ".mzML")
        if (-not (Test-Path $made)) { Write-Warning "$name : msconvert wrote no mzML"; return }
        $part = Join-Path $OutDir ($name + ".mzML.part")
        Copy-Item -Path $made -Destination $part -Force
        Rename-Item -Path $part -NewName ($name + ".mzML")
    } finally {
        Remove-Item -Path $tmp -Recurse -Force -ErrorAction SilentlyContinue
    }
}
