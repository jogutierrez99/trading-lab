<#
.SYNOPSIS
Outputs a disabled Task Scheduler definition for GitHub intake.
#>
param(
    [ValidateRange(5, 60)]
    [int]$IntervalMinutes = 15
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$python = (Resolve-Path -LiteralPath (Join-Path $repo '.venv\Scripts\python.exe')).Path
$script = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'github_strategy_intake.py')).Path
$secrets = (Resolve-Path -LiteralPath (Join-Path $repo '.env')).Path
$root = Join-Path $env:LOCALAPPDATA 'TradingLab\GitHubIntake53'
$database = Join-Path $root 'queue.sqlite3'
$logs = Join-Path $root 'logs'
$arguments = '-B "{0}" --db "{1}" --env-file "{2}" --log-dir "{3}" poll --author-id 64194024 --live-read' -f $script, $database, $secrets, $logs
$start = [DateTimeOffset]::Now.AddMinutes($IntervalMinutes).ToString('yyyy-MM-ddTHH:mm:sszzz')
$sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$escapedArgs = [Security.SecurityElement]::Escape($arguments)
$escapedPython = [Security.SecurityElement]::Escape($python)
$escapedRepo = [Security.SecurityElement]::Escape($repo)

@"
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Trading Lab 5.3 GitHub intake into the manual review queue</Description>
  </RegistrationInfo>
  <Triggers>
    <TimeTrigger>
      <Repetition><Interval>PT${IntervalMinutes}M</Interval></Repetition>
      <StartBoundary>$start</StartBoundary>
      <Enabled>true</Enabled>
    </TimeTrigger>
  </Triggers>
  <Principals>
    <Principal id="Operator">
      <UserId>$sid</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <Enabled>false</Enabled>
    <ExecutionTimeLimit>PT3M</ExecutionTimeLimit>
  </Settings>
  <Actions Context="Operator">
    <Exec>
      <Command>$escapedPython</Command>
      <Arguments>$escapedArgs</Arguments>
      <WorkingDirectory>$escapedRepo</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@
