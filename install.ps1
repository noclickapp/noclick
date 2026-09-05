# NoClick Community installer for Windows.
#
#   irm https://noclick.com/install.ps1 | iex
#
# Checks this machine, installs Node.js and Git through winget when they are
# missing, and hands off to `npx noclick` -- the launcher every platform
# shares, so one place fetches the source, writes .env and starts the stack.
# Docker Desktop is deliberately never installed on your behalf: it needs an
# administrator, WSL2 and a reboot, so the link is printed instead.
#
# The launcher's environment variables apply here unchanged:
#
#   $env:NOCLICK_DIR = 'D:\noclick'      where the source and .env live
#   $env:NOCLICK_REF = 'v1.2.3'          branch or tag to install (default: main)
#   $env:NOCLICK_REPO = '<git url>'      source to clone from
#   $env:NOCLICK_APP_URL = 'https://...' public URLs, if this is not a laptop
#   $env:NOCLICK_NO_START = '1'          set everything up, start nothing
#
# ASCII only: Windows PowerShell reads a BOM-less file as ANSI, and a stray
# non-ASCII byte in code is a syntax error there.

$ErrorActionPreference = 'Stop'

# `irm ... | iex` runs this inside the caller's session, where `exit` would
# close their terminal -- so a failure ends the script with `break` there, and
# with a real exit code when run from a file (`powershell -File install.ps1`).
$fromPipe = $null -eq $MyInvocation.MyCommand.Path

function Say($text) { Write-Host "-> $text" }
function Fail($text) {
    Write-Host $text -ForegroundColor Red
    if ($fromPipe) { break } else { exit 1 }
}
function Have($name) { return $null -ne (Get-Command $name -ErrorAction SilentlyContinue) }

# Native commands under 'Stop' turn stderr chatter into terminating errors;
# run them under 'Continue' and judge the exit code alone.
function Invoke-Native([scriptblock]$command, [switch]$Quiet) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        if ($Quiet) { & $command *> $null } else { & $command }
        return $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
}

# winget installs land in the registry PATH, not this session's copy.
function Update-SessionPath {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [Environment]::GetEnvironmentVariable('Path', 'User')
}

# -- Docker -------------------------------------------------------------------
if (-not (Have docker)) {
    Fail @'
Docker Desktop is required.
  https://docs.docker.com/desktop/install/windows-install/
  Install it, start it once so it finishes setting up WSL2, then run this
  installer again.
'@
}
if ((Invoke-Native { docker info } -Quiet) -ne 0) {
    Fail @'
Docker is installed but not running.
  Start Docker Desktop, wait until it says it is running, then run this
  installer again.
'@
}

# -- Node.js and Git ----------------------------------------------------------
$byHand = @{
    'OpenJS.NodeJS.LTS' = 'Node.js 18+   https://nodejs.org'
    'Git.Git'           = 'Git           https://git-scm.com/download/win'
}
$missing = @()
if (Have node) {
    $nodeVersion = (& node --version).Trim()
    if ([int]$nodeVersion.TrimStart('v').Split('.')[0] -lt 18) {
        Fail "Node.js 18 or newer is required; this machine has $nodeVersion.`n  Update it from https://nodejs.org, open a new terminal, then run this installer again."
    }
} else {
    $missing += 'OpenJS.NodeJS.LTS'
}
if (-not (Have git)) { $missing += 'Git.Git' }

if ($missing.Count -gt 0) {
    if (-not (Have winget)) {
        $links = ($missing | ForEach-Object { '  ' + $byHand[$_] }) -join "`n"
        Fail "winget is not available to install what is missing:`n$links`n  Install what is listed, open a new terminal, then run this installer again."
    }
    foreach ($id in $missing) {
        Say "Installing $id with winget"
        $code = Invoke-Native { winget install --id $id --exact --silent --accept-package-agreements --accept-source-agreements }
        if ($code -ne 0) {
            Fail "winget could not install $id (exit code $code).`n  $($byHand[$id])`n  Install it by hand, open a new terminal, then run this installer again."
        }
    }
    Update-SessionPath
    if (-not ((Have node) -and (Have git))) {
        Fail 'Node.js and Git were installed but this session cannot see them yet. Open a new terminal and run this installer again.'
    }
}

# -- Hand off -----------------------------------------------------------------
# npx.cmd rather than npx: Windows PowerShell resolves a bare `npx` to npx.ps1,
# which the default Restricted execution policy refuses to run.
Say 'Handing off to npx noclick'
$code = Invoke-Native { npx.cmd -y noclick@latest }
if ($code -ne 0) { Fail "npx noclick exited with code $code." }
