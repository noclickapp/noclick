# NoClick Community installer for Windows.
#
#   irm https://noclick.com/install.ps1 | iex
#
# One command on a fresh machine. It installs Docker Desktop with Docker's
# own installer, silently, after enabling WSL2 -- Windows makes that one step
# need a restart, and the installer continues by itself after you sign back
# in -- puts a private copy of Node.js and Git under your user profile
# (nothing system-wide, no package manager needed), hands off to `npx
# noclick`, the launcher every platform shares, and opens the app in your
# browser.
#
# Re-running it is always safe: every step looks first and only does what is
# still missing, which is also how it resumes after the restart.
#
# The launcher's environment variables apply here unchanged, and survive the
# restart and the administrator relaunch:
#
#   $env:NOCLICK_DIR = 'D:\noclick'      where the source and .env live
#   $env:NOCLICK_REF = 'v1.2.3'          branch or tag to install (default: main)
#   $env:NOCLICK_REPO = '<git url>'      source to clone from
#   $env:NOCLICK_APP_URL = 'https://...' public URLs, if this is not a laptop
#   $env:NOCLICK_NO_START = '1'          set everything up, start nothing
#
# And this script's own:
#
#   $env:NOCLICK_INSTALLER_URL           where it re-fetches itself from for the
#                                        relaunch and the resume (default: the
#                                        URL above)
#   $env:NOCLICK_INSTALL_LOG = 'path'    also write everything shown to a file
#   $env:NOCLICK_ASSUME_YES = '1'        restart without asking first
#   $env:NOCLICK_INSTALLER_DRY_RUN = '1' say what would be installed, change nothing
#
# ASCII only: Windows PowerShell reads a BOM-less file as ANSI, and a stray
# non-ASCII byte in code is a syntax error there.

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # the progress bar makes downloads 10x slower in PowerShell 5
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

# `irm ... | iex` runs this inside the caller's session, where `exit` would
# close their terminal -- so a failure ends the script with `break` there, and
# with a real exit code when run from a file (`powershell -File install.ps1`).
$fromPipe = $null -eq $MyInvocation.MyCommand.Path
$installerUrl = if ($env:NOCLICK_INSTALLER_URL) { $env:NOCLICK_INSTALLER_URL } else { 'https://noclick.com/install.ps1' }
$relaunch = "-NoExit -ExecutionPolicy Bypass -Command `"irm '$installerUrl' | iex`""
$arch = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { 'arm64' } else { 'x64' }
$tools = Join-Path $env:LOCALAPPDATA 'NoClick\tools'
$appUrl = if ($env:NOCLICK_APP_URL) { $env:NOCLICK_APP_URL } else { 'http://localhost:3000' }
$dockerDesktop = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
if ($env:NOCLICK_INSTALL_LOG) { Start-Transcript -Path $env:NOCLICK_INSTALL_LOG -Append | Out-Null }
if (Get-Command Unregister-ScheduledTask -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName 'NoClick installer resume' -Confirm:$false -ErrorAction SilentlyContinue
}

function Say($text) { Write-Host "-> $text" }
# `break` at script level would end the caller's own pipeline under `iex`
# but only leaves the nearest loop inside one, so stopping is a sentinel
# exception caught once, at the bottom of this file.
function Stop-Installer($code) { throw "NOCLICK-INSTALLER-STOP:$code" }
function Fail($text) {
    Write-Host $text -ForegroundColor Red
    Stop-Installer 1
}
function Have($name) { return $null -ne (Get-Command $name -ErrorAction SilentlyContinue) }
function Test-Admin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    return ([Security.Principal.WindowsPrincipal]$identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# Native commands under 'Stop' turn stderr chatter into terminating errors;
# run them under 'Continue' and judge the exit code alone.
# The command's own output goes to the host: a function returns everything
# its inner commands emit, so left in the pipeline it would become the
# "exit code" (the launcher's whole build log did, once).
function Invoke-Native([scriptblock]$command) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $command | Out-Host
        return $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
}

# True when a native command line succeeds; cmd swallows its output, so a
# failing check never paints a red error record.
function Test-CommandLine($line) {
    & cmd /c "$line >nul 2>&1"
    return $LASTEXITCODE -eq 0
}

# Windows' own "a feature was turned on, restart to finish" flag.
function Test-RebootPending {
    return Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending'
}

# Judged from what Windows has, not from wsl.exe's exit code: the inbox stub
# answers 0 to `wsl --status` on a machine with nothing enabled.
function Test-WslInstalled {
    foreach ($feature in 'VirtualMachinePlatform', 'Microsoft-Windows-Subsystem-Linux') {
        if ((Get-WindowsOptionalFeature -Online -FeatureName $feature).State -ne 'Enabled') { return $false }
    }
    $package = Get-AppxPackage -AllUsers 'MicrosoftCorporationII.WindowsSubsystemForLinux' -ErrorAction SilentlyContinue
    return [bool]$package -or (Test-Path (Join-Path $env:ProgramFiles 'WSL\wsl.exe'))
}

function Update-SessionPath {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [Environment]::GetEnvironmentVariable('Path', 'User')
}

# Prepend for this session and persist for the next one, so `npx noclick
# logs` works from any later terminal too.
function Add-UserPath($dir) {
    if (-not (($env:Path -split ';') -contains $dir)) { $env:Path = "$dir;$env:Path" }
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    if (-not (($user -split ';') -contains $dir)) {
        [Environment]::SetEnvironmentVariable('Path', "$dir;$user", 'User')
    }
}

# NOCLICK_* must reach the administrator relaunch and the run after the
# restart, neither of which inherits this session.
function Save-Overrides {
    Get-ChildItem Env: | Where-Object { $_.Name -like 'NOCLICK_*' } | ForEach-Object {
        [Environment]::SetEnvironmentVariable($_.Name, $_.Value, 'User')
    }
}

function Assert-Elevated($why) {
    if (Test-Admin) { return }
    Say "Administrator rights are needed $why -- approve the prompt that appears"
    Save-Overrides
    Start-Process powershell.exe -Verb RunAs -ArgumentList $relaunch
    Write-Host 'Continuing in the new window.'
    Stop-Installer 0
}

# The resume is a one-shot task at this user's next sign-in, registered while
# elevated so it runs elevated too (no second prompt), and it waits for the
# network, which is not always up when the desktop appears.
$resumeTask = 'NoClick installer resume'
function Restart-AndResume($why) {
    Save-Overrides
    $wait = "for (`$i = 0; `$i -lt 60; `$i++) { try { `$s = irm '$installerUrl'; break } catch { Start-Sleep 5 } }; iex `$s"
    $user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoExit -ExecutionPolicy Bypass -Command `"& { $wait }`""
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Highest
    Register-ScheduledTask -TaskName $resumeTask -Action $action -Trigger $trigger -Principal $principal -Force | Out-Null
    Write-Host ''
    Write-Host "Windows needs to restart once $why."
    Write-Host 'The installer continues by itself after you sign back in.'
    if (-not $env:NOCLICK_ASSUME_YES) { $null = Read-Host 'Press Enter to restart now' }
    Restart-Computer -Force
    Stop-Installer 0
}

function Get-Download($url, $path) {
    (New-Object Net.WebClient).DownloadFile($url, $path)
}

# A zip unpacked under the user's profile: no installer, no administrator,
# nothing shared with whatever else is on the machine.
function Install-Portable($name, $url, $dest, $binSubdir) {
    Say "Fetching $name"
    $zip = Join-Path $env:TEMP "noclick-$name.zip"
    $stage = Join-Path $env:TEMP "noclick-$name-unpack"
    Get-Download $url $zip
    if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
    Expand-Archive -Path $zip -DestinationPath $stage
    if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
    New-Item -ItemType Directory -Force -Path (Split-Path $dest) | Out-Null
    # Node's zip wraps everything in one top-level folder; MinGit's does not.
    $entries = @(Get-ChildItem $stage)
    if ($entries.Count -eq 1 -and $entries[0].PSIsContainer) { Move-Item $entries[0].FullName $dest } else { Move-Item $stage $dest }
    Remove-Item $zip, $stage -Recurse -Force -ErrorAction SilentlyContinue
    Add-UserPath (Join-Path $dest $binSubdir)
}

# Docker Desktop runs Linux containers inside WSL2. `wsl --install` is the
# documented way to turn that on, but the inbox stub is temperamental about
# how it is invoked (it printed nothing and failed from an elevated user
# session on 25H2 while succeeding elsewhere), so when it fails the same two
# things are done by hand: the Windows features, and WSL's own MSI from
# Microsoft's releases. Either way Windows cannot finish without a restart.
function Enable-Wsl {
    Say 'Enabling Windows Subsystem for Linux'
    $output = ((& cmd /c "wsl --install --no-distribution --web-download 2>&1") -join "`n") -replace "\x00", ''
    if ($LASTEXITCODE -eq 0) { return }
    if ($output.Trim()) { Write-Host $output.Trim() }
    Say 'wsl --install did not finish; enabling the features and installing WSL directly'
    Enable-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform, Microsoft-Windows-Subsystem-Linux -All -NoRestart | Out-Null
    $release = Invoke-RestMethod 'https://api.github.com/repos/microsoft/WSL/releases/latest'
    $asset = $release.assets | Where-Object { $_.name -like "*.$arch.msi" } | Select-Object -First 1
    if (-not $asset) { Fail "Could not find a WSL installer for $arch in Microsoft's releases.`n  See https://learn.microsoft.com/windows/wsl/install, then run this installer again." }
    $msi = Join-Path $env:TEMP 'wsl.msi'
    Get-Download $asset.browser_download_url $msi
    $install = Start-Process msiexec.exe -ArgumentList '/i', "`"$msi`"", '/quiet', '/norestart' -Wait -PassThru
    Remove-Item $msi -ErrorAction SilentlyContinue
    if ($install.ExitCode -notin 0, 1641, 3010) {
        Fail "WSL's installer exited with code $($install.ExitCode).`n  See https://learn.microsoft.com/windows/wsl/install, then run this installer again."
    }
}

function Set-DockerDesktopAutoStart {
    $store = Join-Path $env:APPDATA 'Docker\settings-store.json'
    $settings = if (Test-Path $store) { Get-Content $store -Raw | ConvertFrom-Json } else { New-Object PSObject }
    $settings | Add-Member -NotePropertyName AutoStart -NotePropertyValue $true -Force
    New-Item -ItemType Directory -Force (Split-Path $store) | Out-Null
    Set-Content -Path $store -Value ($settings | ConvertTo-Json -Depth 8) -Encoding ascii
}

function Invoke-Installer {
$dryRun = [bool]$env:NOCLICK_INSTALLER_DRY_RUN
# -- Docker Desktop -----------------------------------------------------------
if (-not (Have docker) -and (Test-Path $dockerDesktop)) { Update-SessionPath }
if (-not (Have docker)) {
    if ($env:NOCLICK_INSTALLER_DRY_RUN) {
        Say 'Docker Desktop is not installed. This installer would enable WSL2 (Windows restarts once, then'
        Say 'the installer resumes by itself), install Docker Desktop silently, put private copies of'
        Say 'Node.js and Git under your profile, and hand off to npx noclick. Dry run: stopping here.'
        Stop-Installer 0
    }
    Assert-Elevated 'to install Docker Desktop'
    # The download comes first so it is already on disk when the machine comes
    # back from the WSL2 restart; TEMP survives that restart.
    $dockerArch = if ($arch -eq 'arm64') { 'arm64' } else { 'amd64' }
    $installer = Join-Path $env:TEMP 'DockerDesktopInstaller.exe'
    if (-not (Test-Path $installer)) {
        Say 'Downloading Docker Desktop (about 600 MB)'
        Get-Download "https://desktop.docker.com/win/main/$dockerArch/Docker%20Desktop%20Installer.exe" $installer
    }
    $platformBefore = (Get-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform).State
    if (-not (Test-WslInstalled)) { Enable-Wsl }
    if ($platformBefore -ne 'Enabled' -or (Test-RebootPending)) {
        Restart-AndResume 'to finish enabling virtualization'
    }
    Say 'Installing Docker Desktop (a few minutes, no questions asked)'
    $install = Start-Process -FilePath $installer -ArgumentList 'install', '--quiet', '--accept-license', '--backend=wsl-2' -Wait -PassThru
    Remove-Item $installer -ErrorAction SilentlyContinue
    if ($install.ExitCode -ne 0) {
        Fail "Docker Desktop's installer exited with code $($install.ExitCode).`n  Install it from https://docs.docker.com/desktop/install/windows-install/ and run this installer again."
    }
    Update-SessionPath
    if (-not (Have docker)) { Fail 'Docker Desktop is installed, but this session cannot see it yet. Open a new terminal and run this installer again.' }
}
if (-not (Test-CommandLine 'docker info')) {
    if (-not (Test-Path $dockerDesktop)) {
        Fail "Docker is installed but not running.`n  Start it, then run this installer again."
    }
    if ($dryRun) {
        Say 'Docker Desktop is installed but not running. Dry run: the installer would start it. Stopping here.'
        Stop-Installer 0
    }
    # Start Docker Desktop at sign-in, so the stack, whose services restart
    # unless stopped, is back after a reboot. Docker Desktop owns the Run
    # entry and rewrites it from its own settings store on every start, so a
    # Run entry written here was reset to a bare path with AutoStart off;
    # the setting itself is the knob, read before the first start.
    Set-DockerDesktopAutoStart
    Say 'Starting Docker Desktop (the first start takes a minute or two)'
    Start-Process $dockerDesktop
    $deadline = (Get-Date).AddMinutes(6)
    while (-not (Test-CommandLine 'docker info')) {
        if ((Get-Date) -gt $deadline) {
            Fail "Docker Desktop did not start within six minutes.`n  Open Docker Desktop from the Start menu, finish any first-run screen it shows (signing in is optional), wait until it says the engine is running, then run this installer again."
        }
        Start-Sleep -Seconds 5
    }
}

# -- Node.js and Git, private copies under your profile -----------------------
$nodeOk = $false
if (Have node) {
    $nodeVersion = (& node --version).Trim()
    $nodeOk = [int]$nodeVersion.TrimStart('v').Split('.')[0] -ge 18
}
if (-not $nodeOk) {
    # Windows PowerShell wraps a JSON array from Invoke-RestMethod as ONE object,
    # so neither the pipeline nor foreach see the elements; parse the text and
    # walk it by index instead.
    $releases = ConvertFrom-Json (Invoke-WebRequest -UseBasicParsing 'https://nodejs.org/dist/index.json').Content
    while ($releases.Count -eq 1 -and $releases[0] -is [System.Collections.IList]) { $releases = $releases[0] }
    $lts = $null
    for ($i = 0; $i -lt $releases.Count; $i++) {
        if ($releases[$i].lts) { $lts = $releases[$i].version; break }
    }
    if (-not $lts) { Fail 'Could not determine the current Node.js LTS release from nodejs.org.' }
    if ($dryRun) { Say "Dry run: would install a private Node.js $lts under $tools." }
    else { Install-Portable 'node' "https://nodejs.org/dist/$lts/node-$lts-win-$arch.zip" (Join-Path $tools 'node') '' }
}
if (-not (Have git)) {
    $gitArch = if ($arch -eq 'arm64') { 'arm64' } else { '64-bit' }
    $release = ConvertFrom-Json (Invoke-WebRequest -UseBasicParsing 'https://api.github.com/repos/git-for-windows/git/releases/latest').Content
    $asset = $null
    for ($i = 0; $i -lt $release.assets.Count; $i++) {
        $candidate = $release.assets[$i]
        if ($candidate.name -like "MinGit-*-$gitArch.zip" -and $candidate.name -notlike '*busybox*') { $asset = $candidate; break }
    }
    if (-not $asset) { Fail "Could not find a MinGit build for $gitArch in Git for Windows' latest release." }
    if ($dryRun) { Say "Dry run: would install a private Git ($($asset.name)) under $tools." }
    else { Install-Portable 'git' $asset.browser_download_url (Join-Path $tools 'git') 'cmd' }
}

# -- Hand off -----------------------------------------------------------------
# npx.cmd rather than npx: Windows PowerShell resolves a bare `npx` to npx.ps1,
# which the default Restricted execution policy refuses to run.
if ($dryRun) {
    Say 'Dry run: would hand off to npx noclick now, which fetches NoClick and starts it. Stopping here.'
    Stop-Installer 0
}
Say 'Handing off to npx noclick'
$npx = (Get-Command npx.cmd).Source
$code = Invoke-Native { & $npx -y noclick@latest }
if ($code -ne 0) { Fail "npx noclick exited with code $code." }
if (-not $env:NOCLICK_NO_START) { Start-Process $appUrl }
}

try {
    Invoke-Installer
} catch {
    $message = $_.Exception.Message
    if ($message -notlike 'NOCLICK-INSTALLER-STOP:*') { throw }
    $code = [int]$message.Split(':')[1]
    if (-not $fromPipe) { exit $code }
}
