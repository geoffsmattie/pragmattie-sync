<#
.SYNOPSIS
  Reset and check the PragMattie Sync demo, in one command each.

.DESCRIPTION
  reset     Put the demo back to a clean start: the CRM's demo data reseeded, the simulated
            engineering history regenerated for today, and GitHub back to the recorded baseline
            (demo issues closed, demo PRs closed with their branches and agent comments removed).
            Demo items are the ones labelled `demo` or on a `demo-` branch; real work is kept.
            A dry run unless you add -Apply. The agent loop is paused while it runs.
  check     The pre-demo checklist: containers, both APIs, the web app, the data, today's
            forecasts, GitHub access, no leftovers from a previous demo, ORCHESTRATOR_MODE.
            Add -Smoke to also score one PR and triage one issue with Claude (about 5 cents).
  baseline  Record the repository's current state as the clean start (only when it is clean).
            Add -Force to replace an existing baseline.

.EXAMPLE
  .\scripts\demo.ps1 reset            # what a reset would do; changes nothing
  .\scripts\demo.ps1 reset -Apply     # do it, then run the checklist
  .\scripts\demo.ps1 check -Smoke
#>
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet('reset', 'check', 'baseline')]
    [string]$Command,
    [switch]$Apply,
    [switch]$Smoke,
    [switch]$Force
)

# Continue, not Stop: Docker writes ordinary progress to stderr, which Windows PowerShell 5.1
# would otherwise treat as an error. Every docker call is checked by its exit code instead.
$ErrorActionPreference = 'Continue'
Set-Location (Split-Path -Parent $PSScriptRoot)   # the repository root, wherever this is run from

function Get-RunningServices {
    $names = docker compose ps --status running --services 2>$null
    if ($LASTEXITCODE -ne 0) { return @() }
    return @($names)
}

function Invoke-Orchestrator([string[]]$Arguments) {
    docker compose exec -T orchestrator python @Arguments | Out-Host  # keep it out of the return value
    return $LASTEXITCODE
}

function Test-Stack {
    $running = Get-RunningServices
    $failed = 0
    foreach ($service in 'db', 'api', 'orchestrator', 'web') {
        if ($running -contains $service) {
            Write-Host ("  PASS  {0,-24} running" -f "Container: $service")
        } else {
            Write-Host ("  FAIL  {0,-24} not running: docker compose up -d" -f "Container: $service")
            $failed++
        }
    }
    if ($running -contains 'agent') {
        Write-Host ("  PASS  {0,-24} running" -f 'Agent loop')
    } else {
        Write-Host ("  FAIL  {0,-24} not running: docker compose --profile agents up -d" -f 'Agent loop')
        $failed++
    }
    try {
        $web = Invoke-WebRequest -Uri 'http://localhost:5173/' -UseBasicParsing -TimeoutSec 10 -ErrorAction Stop
        Write-Host ("  PASS  {0,-24} answering on http://localhost:5173 ({1})" -f 'Web app', $web.StatusCode)
    } catch {
        Write-Host ("  FAIL  {0,-24} not answering on http://localhost:5173" -f 'Web app')
        $failed++
    }
    return $failed
}

switch ($Command) {
    'baseline' {
        $arguments = @('-m', 'sdlc.demo_reset', 'baseline')
        if ($Force) { $arguments += '--force' }
        exit (Invoke-Orchestrator $arguments)
    }

    'check' {
        Write-Host 'Pre-demo checklist'
        $failed = Test-Stack
        $arguments = @('-m', 'sdlc.demo_check')
        if ($Smoke) { $arguments += @('--smoke', '--yes') }
        $code = Invoke-Orchestrator $arguments
        if ($failed -gt 0) {
            Write-Host "Not ready: $failed container or web check(s) failed (above)."
            exit 1
        }
        exit $code
    }

    'reset' {
        $running = Get-RunningServices
        foreach ($service in 'db', 'api', 'orchestrator') {
            if ($running -notcontains $service) {
                Write-Host "The $service container isn't running. Start the stack first: docker compose up -d"
                exit 1
            }
        }
        if (-not $Apply) {
            Write-Host 'CRM: would reseed the demo data (python -m app.seed --reset).'
            exit (Invoke-Orchestrator @('-m', 'sdlc.demo_reset'))
        }

        $started = Get-Date
        $agentWasRunning = $running -contains 'agent'
        if ($agentWasRunning) {
            Write-Host 'Pausing the agent loop...'
            docker compose stop agent | Out-Null
        }
        try {
            Write-Host 'Reseeding the CRM demo data...'
            docker compose exec -T api python -m app.seed --reset
            if ($LASTEXITCODE -ne 0) { throw 'The CRM reseed failed.' }
            Write-Host 'Resetting GitHub and the engineering history...'
            $code = Invoke-Orchestrator @('-m', 'sdlc.demo_reset', '--apply')
            if ($code -ne 0) { throw 'The orchestrator reset failed.' }
        } finally {
            if ($agentWasRunning) {
                Write-Host 'Restarting the agent loop...'
                docker compose --profile agents up -d agent | Out-Null
            }
        }
        $seconds = [int]((Get-Date) - $started).TotalSeconds
        Write-Host "Reset done in $seconds seconds."
        Write-Host ''
        & $PSCommandPath check
        exit $LASTEXITCODE
    }
}
