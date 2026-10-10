<#
.SYNOPSIS
  One-time setup (or undo) for 桌面分身: the Windows child session that the
  game and bd2-auto run in, so they never touch the real mouse.

.DESCRIPTION
  Run it from the repo folder. It asks for Administrator with a UAC prompt.

      powershell -NoProfile -ExecutionPolicy Bypass -File tools\clone_desktop\setup.ps1
      powershell -NoProfile -ExecutionPolicy Bypass -File tools\clone_desktop\setup.ps1 -Undo

  What it changes (-Undo puts each one back):
  - It builds CloneDesktop.exe into %LOCALAPPDATA%\bd2-auto\clone-desktop.
  - It sets HKCU\Software\Microsoft\Terminal Server Client
    RemoteDesktop_SuppressWhenMinimized = 2, so a minimised viewer keeps
    the clone desktop drawing.
  - As Administrator (one UAC prompt) it turns on Windows child sessions
    (WTSEnableChildSessions). Like BetterGI, it leaves Remote Desktop, the
    firewall and policies alone.
  - Only with -AllowRdp (a fallback, in case a PC refuses the child session
    while Remote Desktop is off): it also adds two Windows Firewall rules
    that block inbound Remote Desktop from other machines, sets
    fDenyTSConnections = 0 and starts the Remote Desktop service. It stops
    before changing anything when a Windows Firewall profile is off.

  -Undo also signs out a running child session and deletes CloneDesktop.exe.
  Every step is logged to setup.log in the same folder. The values found
  before the first setup are kept in setup-state.json for -Undo. No password
  is stored anywhere: Windows asks for it in its own sign-in box.

  The compile line and registry values come from ChildStream's
  scripts/setup.ps1 (MIT, see LICENSE-childstream.txt).
#>
param(
    [switch]$Undo,
    [switch]$NoPause,
    [switch]$AllowRdp,
    # Internal: the Administrator half, started by this script itself.
    [switch]$AdminPart,
    [string]$DataDir
)

$ErrorActionPreference = 'Stop'
if (-not $DataDir) { $DataDir = Join-Path $env:LOCALAPPDATA 'bd2-auto\clone-desktop' }
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
$logFile = Join-Path $DataDir 'setup.log'
$stateFile = Join-Path $DataDir 'setup-state.json'
$exe = Join-Path $DataDir 'CloneDesktop.exe'
$tsKey = 'HKLM:\SYSTEM\CurrentControlSet\Control\Terminal Server'
$clientKey = 'HKCU:\Software\Microsoft\Terminal Server Client'

function Say([string]$text) {
    Write-Host $text
    $line = '{0} {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $text
    Add-Content -LiteralPath $logFile -Value $line -Encoding UTF8
}

function Read-State {
    $state = @{}
    if (Test-Path -LiteralPath $stateFile) {
        $json = Get-Content -LiteralPath $stateFile -Raw -Encoding UTF8 | ConvertFrom-Json
        foreach ($p in $json.PSObject.Properties) { $state[$p.Name] = $p.Value }
    }
    $state
}

function Write-State($state) {
    $state | ConvertTo-Json | Set-Content -LiteralPath $stateFile -Encoding UTF8
}

Add-Type -Namespace Bd2Auto -Name ChildSessions -MemberDefinition @'
[DllImport("wtsapi32.dll")]
public static extern bool WTSEnableChildSessions(bool enable);
[DllImport("wtsapi32.dll")]
public static extern bool WTSIsChildSessionsEnabled(out bool enabled);
[DllImport("wtsapi32.dll")]
public static extern bool WTSGetChildSessionId(out uint sessionId);
'@

function Test-ChildSessions {
    $on = $false
    [void][Bd2Auto.ChildSessions]::WTSIsChildSessionsEnabled([ref]$on)
    $on
}

function Invoke-Native([scriptblock]$command) {
    # Windows PowerShell turns a native program's stderr into a terminating
    # error when ErrorActionPreference is Stop.
    $saved = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & $command 2>&1 | Out-String } finally { $ErrorActionPreference = $saved }
}

# Block rules, so turning Remote Desktop on lets no other machine in.
$blockRuleNames = 'bd2-auto-clone-desktop-block-rdp-tcp', 'bd2-auto-clone-desktop-block-rdp-udp'

function Add-RdpBlockRules {
    $port = (Get-ItemProperty -Path "$tsKey\WinStations\RDP-Tcp" -ErrorAction SilentlyContinue).PortNumber
    if (-not $port) { $port = 3389 }
    foreach ($protocol in 'TCP', 'UDP') {
        $name = 'bd2-auto-clone-desktop-block-rdp-' + $protocol.ToLower()
        Remove-NetFirewallRule -Name $name -ErrorAction SilentlyContinue
        New-NetFirewallRule -Name $name -DisplayName "bd2-auto 桌面分身：擋住其他電腦連進遠端桌面 ($protocol $port)" `
            -Direction Inbound -Action Block -Protocol $protocol -LocalPort $port -Profile Any | Out-Null
    }
    Say "防火牆：已加規則擋住其他電腦連進遠端桌面（連接埠 $port，這台電腦自己連自己不受影響）"
}

function Invoke-AdminPart {
    $state = Read-State
    if ($Undo) {
        $id = [uint32]0
        if ([Bd2Auto.ChildSessions]::WTSGetChildSessionId([ref]$id) -and $id -ne 0 -and $id -ne [uint32]::MaxValue) {
            Say "登出桌面分身（工作階段 $id），裡面的程式會關掉"
            Invoke-Native { logoff.exe $id } | Out-Null
            Start-Sleep -Seconds 3
        }
        if ($state.ContainsKey('childSessionsBefore') -and $state['childSessionsBefore']) {
            Say '安裝前桌面分身功能本來就開著，保持不動'
        } else {
            [void][Bd2Auto.ChildSessions]::WTSEnableChildSessions($false)
            Say ('關閉桌面分身功能：{0}' -f $(if (Test-ChildSessions) { '失敗，還是開著' } else { '已關閉' }))
        }
        if ($state.ContainsKey('denyBefore')) {
            $deny = 1
            if ($null -ne $state['denyBefore']) { $deny = [int]$state['denyBefore'] }
            Set-ItemProperty -Path $tsKey -Name fDenyTSConnections -Value $deny -Type DWord
            Say "fDenyTSConnections 改回 $deny（1 = 不允許遠端桌面連線）"
        }
        foreach ($name in $blockRuleNames) {
            if (Get-NetFirewallRule -Name $name -ErrorAction SilentlyContinue) {
                Remove-NetFirewallRule -Name $name
                Say "已移除防火牆規則 $name"
            }
        }
        return
    }

    if ($AllowRdp) {
        $off = @(Get-NetFirewallProfile | Where-Object { "$($_.Enabled)" -ne 'True' } | ForEach-Object { $_.Name })
        if ($off.Count) {
            throw ('Windows 防火牆的 {0} 設定檔是關著的，擋不住其他電腦，所以沒有開遠端桌面，什麼都沒改' -f ($off -join '、'))
        }
    }
    if (-not $state.ContainsKey('childSessionsBefore')) {
        $state['childSessionsBefore'] = Test-ChildSessions
        Write-State $state
    }
    [void][Bd2Auto.ChildSessions]::WTSEnableChildSessions($true)
    if (-not (Test-ChildSessions)) { throw '開不了桌面分身功能（WTSEnableChildSessions 失敗）' }
    Say '桌面分身功能：已開啟'
    if (-not $AllowRdp) { return }

    if (-not $state.ContainsKey('denyBefore')) {
        $state['denyBefore'] = (Get-ItemProperty -Path $tsKey -Name fDenyTSConnections -ErrorAction SilentlyContinue).fDenyTSConnections
        Write-State $state
    }
    Add-RdpBlockRules
    Set-ItemProperty -Path $tsKey -Name fDenyTSConnections -Value 0 -Type DWord
    Say 'fDenyTSConnections = 0（允許遠端桌面連線；分身是這台電腦連自己）'
    $service = Get-Service -Name TermService
    if ($service.Status -ne 'Running') {
        if ("$($service.StartType)" -eq 'Disabled') { throw '「遠端桌面服務」(TermService) 被停用了，分身需要它' }
        Start-Service -Name TermService
        Say '已啟動「遠端桌面服務」(TermService)'
    }
}

function Invoke-Elevated {
    if (([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
            [Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Invoke-AdminPart
        return $true
    }
    $argList = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`"",
        '-AdminPart', '-DataDir', "`"$DataDir`"")
    if ($Undo) { $argList += '-Undo' }
    if ($AllowRdp) { $argList += '-AllowRdp' }
    $before = @(Get-Content -LiteralPath $logFile -Encoding UTF8).Count
    Write-Host '跳出「使用者帳戶控制」時請按「是」。'
    try {
        $p = Start-Process -FilePath powershell.exe -ArgumentList $argList -Verb RunAs -Wait -PassThru -WindowStyle Hidden
    } catch {
        Say '沒有按「是」，系統設定沒有改。'
        return $false
    }
    # Show what the hidden Administrator window logged; the callers check
    # the resulting system state rather than its exit code.
    Get-Content -LiteralPath $logFile -Encoding UTF8 | Select-Object -Skip $before | ForEach-Object { Write-Host $_ }
    $true
}

function Install {
    Say '=== 安裝桌面分身 ==='
    $edition = (Get-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion').EditionID
    if ($edition -like 'Core*') { throw "這台是 Windows 家用版（$edition），不能用桌面分身" }
    Say "Windows 版本：$edition"
    $serviceDll = (Get-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Services\TermService\Parameters' -ErrorAction SilentlyContinue).ServiceDll
    if ($serviceDll -and $serviceDll -notlike '*\termsrv.dll') {
        Say "注意：遠端桌面服務被換成 $serviceDll（像 RDP Wrapper），桌面分身可能開不了"
    }

    $csc = Join-Path $env:SystemRoot 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
    if (-not (Test-Path -LiteralPath $csc)) { $csc = Join-Path $env:SystemRoot 'Microsoft.NET\Framework\v4.0.30319\csc.exe' }
    $source = Join-Path $PSScriptRoot 'CloneDesktop.cs'
    $output = Invoke-Native {
        & $csc /nologo /codepage:65001 /target:winexe "/out:$exe" /r:System.Windows.Forms.dll /r:System.Drawing.dll `
            /r:Microsoft.CSharp.dll /r:System.Core.dll /r:System.Management.dll $source
    }
    if ($LASTEXITCODE -ne 0) {
        Say $output
        throw '編譯 CloneDesktop.exe 失敗'
    }
    Say "已建立 $exe"

    if (-not (Invoke-Elevated)) { return $false }
    if (-not (Test-ChildSessions)) { throw "桌面分身功能沒有打開，細節在 $logFile" }

    $state = Read-State
    if (-not $state.ContainsKey('suppressBefore')) {
        $state['suppressBefore'] = (Get-ItemProperty -Path $clientKey -Name RemoteDesktop_SuppressWhenMinimized -ErrorAction SilentlyContinue).RemoteDesktop_SuppressWhenMinimized
        Write-State $state
    }
    New-Item -Path $clientKey -Force | Out-Null
    Set-ItemProperty -Path $clientKey -Name RemoteDesktop_SuppressWhenMinimized -Value 2 -Type DWord
    Say 'RemoteDesktop_SuppressWhenMinimized = 2（分身視窗縮到最小也繼續畫）'

    $passwordless = (Get-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\PasswordLess\Device' -ErrorAction SilentlyContinue).DevicePasswordLessBuildVersion
    if ($passwordless -eq 2) {
        Say '注意：這台電腦設成 Microsoft 帳戶只能用 Windows Hello 登入。要先到「設定 > 帳戶 > 登入選項」最下面的「其他設定」，關掉「僅允許此裝置上的 Microsoft 帳戶使用 Windows Hello 登入」，分身才能用密碼登入（人臉和 PIN 不用關）。'
    }
    Say "完成。打開桌面分身：$exe"
    Say "全部還原：powershell -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Undo"
    $true
}

function Uninstall {
    Say '=== 還原桌面分身 ==='
    if (-not (Invoke-Elevated)) { return $false }
    Say ('現在：桌面分身功能 {0}，fDenyTSConnections = {1}' -f $(if (Test-ChildSessions) { '開著' } else { '關著' }), (Get-ItemProperty -Path $tsKey).fDenyTSConnections)

    $state = Read-State
    $before = $null
    if ($state.ContainsKey('suppressBefore')) { $before = $state['suppressBefore'] }
    if ($null -eq $before) {
        Remove-ItemProperty -Path $clientKey -Name RemoteDesktop_SuppressWhenMinimized -ErrorAction SilentlyContinue
        Say '已刪除 RemoteDesktop_SuppressWhenMinimized'
    } else {
        Set-ItemProperty -Path $clientKey -Name RemoteDesktop_SuppressWhenMinimized -Value ([int]$before) -Type DWord
        Say "RemoteDesktop_SuppressWhenMinimized 改回 $before"
    }
    foreach ($name in 'CloneDesktop.exe', 'setup-state.json') {
        $path = Join-Path $DataDir $name
        if (Test-Path -LiteralPath $path) {
            Remove-Item -LiteralPath $path -Force
            Say "已刪除 $path"
        }
    }
    Say "完成。紀錄檔留在 $DataDir（setup.log、viewer.log）。"
    $true
}

$ok = $false
try {
    if ($AdminPart) {
        Invoke-AdminPart
        exit 0
    }
    if (Get-Process -Name CloneDesktop -ErrorAction SilentlyContinue) {
        throw '桌面分身視窗還開著，先關掉它（右下角圖示按右鍵 > 關閉這個視窗）再跑一次'
    }
    if ($Undo) { $ok = Uninstall } else { $ok = Install }
} catch {
    Say ('出錯：' + $_.Exception.Message)
    if ($AdminPart) { exit 1 }
}
if (-not $NoPause) { Read-Host '按 Enter 關閉' | Out-Null }
if ($ok) { exit 0 } else { exit 1 }
