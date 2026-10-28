param(
    [string]$Version = "v1.2.3",
    # The version our patched launcher reports. Installed launchers replace
    # themselves only with a higher one (ok's update_pyappify), so bump this
    # whenever the launcher patches below change.
    [string]$LauncherVersion = "1.2.13",
    [string]$BuildDir = "pyappify_build",
    [ValidateSet("zlib", "lzma")]
    [string]$NsisCompression = "lzma",
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"

$cargoBin = Join-Path $env:USERPROFILE ".cargo\bin"
if ((Test-Path -LiteralPath $cargoBin) -and ($env:PATH -notlike "*$cargoBin*")) {
    $env:PATH = "$cargoBin;$env:PATH"
}

function Ensure-Command {
    param(
        [string]$Name,
        [string]$InstallDescription
    )

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name is required but was not found. $InstallDescription"
    }
}

function Ensure-Pnpm {
    if (Get-Command pnpm -ErrorAction SilentlyContinue) {
        return
    }

    Ensure-Command -Name "npm" -InstallDescription "Install Node.js/npm first."
    npm install -g pnpm
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install pnpm."
    }
    Ensure-Command -Name "pnpm" -InstallDescription "npm installed pnpm, but it is still not available on PATH."
}

function Ensure-Cargo {
    if (Get-Command cargo -ErrorAction SilentlyContinue) {
        return
    }

    $isWindows = [System.Runtime.InteropServices.RuntimeInformation]::IsOSPlatform(
        [System.Runtime.InteropServices.OSPlatform]::Windows
    )
    if (-not $isWindows) {
        throw "cargo is required but was not found. Install Rust before running this script."
    }

    $rustupInitPath = Join-Path ([System.IO.Path]::GetTempPath()) "rustup-init.exe"
    Invoke-WebRequest -Uri "https://win.rustup.rs/x86_64" -OutFile $rustupInitPath
    & $rustupInitPath -y --no-modify-path --default-toolchain stable
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install Rust."
    }

    if ((Test-Path -LiteralPath $cargoBin) -and ($env:PATH -notlike "*$cargoBin*")) {
        $env:PATH = "$cargoBin;$env:PATH"
    }
    Ensure-Command -Name "cargo" -InstallDescription "Rust was installed, but cargo is still not available on PATH."
}

function Update-InstallerNsiTemplate {
    param(
        [string]$BuildDirPath
    )

    # BUG-20260905-06: the upstream pyappify/Tauri NSIS template aborts with a bare
    # "unable to uninstall" message when the previous install's registered
    # uninstaller no longer exists (deleted install dir, moved app, ...), which
    # hard-blocks upgrading users. Patch the template right after cloning so the
    # generated installer tolerates stale uninstall entries. Every patch must hit
    # exactly once or the build fails loudly - a silently skipped patch would ship
    # an unfixed installer.

    $nsiPath = Join-Path $BuildDirPath "src-tauri\nsis\installer.nsi"
    if (-not (Test-Path -LiteralPath $nsiPath)) {
        throw "installer.nsi template not found at $nsiPath"
    }

    # -Encoding UTF8 is required: the template is UTF-8 (it already contains
    # Chinese messages) and Windows PowerShell would otherwise decode it as ANSI.
    $content = (Get-Content -LiteralPath $nsiPath -Raw -Encoding UTF8) -replace "`r`n", "`n"

    $uninstallBranchSearch = @'
    ${Else}
      ReadRegStr $4 SHCTX "${MANUPRODUCTKEY}" ""
      ReadRegStr $R1 SHCTX "${UNINSTKEY}" "UninstallString"
      ${IfThen} $UpdateMode = 1 ${|} StrCpy $R1 "$R1 /UPDATE" ${|} ; append /UPDATE
      ${IfThen} $PassiveMode = 1 ${|} StrCpy $R1 "$R1 /P" ${|} ; append /P
      StrCpy $R1 "$R1 _?=$4" ; append uninstall directory
      ExecWait '$R1' $0
    ${EndIf}
'@
    $uninstallBranchReplacement = @'
    ${Else}
      ReadRegStr $4 SHCTX "${MANUPRODUCTKEY}" ""
      ReadRegStr $R1 SHCTX "${UNINSTKEY}" "UninstallString"

      ; BUG-20260905-06: tolerate a stale/malformed previous-uninstall entry.
      ; $R3 = UninstallString with surrounding quotes stripped ($R1 keeps the
      ; registered form for the ExecWait command below).
      StrCpy $R3 $R1
      StrCpy $R2 $R3 1
      ${If} $R2 == "$\""
        StrCpy $R3 $R3 "" 1
        StrCpy $R3 $R3 -1
      ${EndIf}

      ; When the previous install dir is unknown, derive it from the registered
      ; uninstaller path instead of appending an empty _?= which makes the old
      ; uninstaller delete nothing.
      ${If} $4 == ""
      ${AndIf} $R3 != ""
        ${GetParent} "$R3" $4
      ${EndIf}

      ; If the registered uninstaller no longer exists, drop the stale keys and
      ; continue installing without uninstalling; ExecWait would otherwise fail
      ; with "unable to uninstall" and hard-block the upgrade.
      ${IfNot} ${FileExists} "$R3"
        DetailPrint "Previous uninstaller not found ($R3); cleaning stale uninstall entries and installing without uninstalling."
        DeleteRegKey SHCTX "${UNINSTKEY}"
        DeleteRegKey SHCTX "${MANUPRODUCTKEY}"
        Goto reinst_uninstall_skipped
      ${EndIf}

      ${IfThen} $UpdateMode = 1 ${|} StrCpy $R1 "$R1 /UPDATE" ${|} ; append /UPDATE
      ${IfThen} $PassiveMode = 1 ${|} StrCpy $R1 "$R1 /P" ${|} ; append /P
      StrCpy $R1 "$R1 _?=$4" ; append uninstall directory
      ExecWait '$R1' $0
    ${EndIf}
'@

    $failureMessageSearch = @'
      ; Other erros? show generic error message and return to select un/reinstall page
      MessageBox MB_ICONEXCLAMATION "$(unableToUninstall)"
      Abort
    ${EndIf}
  reinst_done:
'@
    $failureMessageReplacement = @'
      ; Other erros? show generic error message and return to select un/reinstall page
      ; BUG-20260905-06: actionable guidance instead of the bare unableToUninstall message
      ${If} $LANGUAGE == 2052
        MessageBox MB_ICONEXCLAMATION "无法自动卸载旧版本。$\r$\n$\r$\n请先关闭正在运行的 ${PRODUCTNAME}，点击「上一步」重试；或返回后改选「请勿卸载」直接覆盖安装；也可手动卸载旧版后重新运行本安装包。"
      ${Else}
        MessageBox MB_ICONEXCLAMATION "Unable to uninstall the previous version.$\r$\n$\r$\nClose any running ${PRODUCTNAME}, click Back and retry; or go back, choose not to uninstall and install over it; or uninstall the old version manually and run this installer again."
      ${EndIf}
      Abort
    ${EndIf}

  reinst_uninstall_skipped:
  reinst_done:
'@

    # Player report 2026-10-20: both installers stopped on 「无法停止正在使用
    # d:\yes-bd2 中 Python/Qt 文件的进程」 after a blue PowerShell window, and a
    # restart didn't help. The installer runs without admin rights, but the
    # launcher asks for admin (uac: true), so an old launcher or tool still
    # running from the install folder can't be stopped by it; and security
    # software that blocks PowerShell made the same check fail. Now the check
    # runs hidden; what is left gets one more try with admin rights (one UAC
    # prompt); the message names what is still running; and when PowerShell
    # can't run at all the install carries on (a file that is really in use
    # still gets NSIS's own retry prompt when it is written).
    # Leo 2026-10-20: players must never be asked to touch their security
    # software, and an installer that starts PowerShell with a policy bypass
    # is exactly what such software flags. Only an earlier install can have
    # programs running from the folder, so a first install skips the check and
    # never starts PowerShell.
    $killFirstInstallSearch = @'
Function KillInstallDirExecutables
  ${IfNot} ${FileExists} "$INSTDIR\*.*"
    Return
  ${EndIf}
'@
    $killFirstInstallReplacement = @'
Function KillInstallDirExecutables
  ${IfNot} ${FileExists} "$INSTDIR\${MAINBINARYNAME}.exe"
  ${AndIfNot} ${FileExists} "$INSTDIR\data\*.*"
    Return
  ${EndIf}
'@
    # Player reports 2026-10-19/20: installs to a folder the player picked on
    # D: or F: stopped on 「无法打开要写入的文件 …\yes-bd2.exe」. The installer has
    # no admin rights, and some drives only let administrators write. The
    # folder is now tried when the player leaves the folder page; one that
    # can't be written keeps them there with a message naming the default
    # place, instead of failing halfway through the install.
    $dirWritableSearch = @'
ascii_check_done:
  ; If we reach this point, the directory is valid.
FunctionEnd
'@
    $dirWritableReplacement = @'
ascii_check_done:
  ; The folder must be writable without admin rights: this installer has none.
  StrCpy $R5 0
  ${IfNot} ${FileExists} "$INSTDIR\*.*"
    StrCpy $R5 1
  ${EndIf}
  ClearErrors
  CreateDirectory "$INSTDIR"
  FileOpen $R6 "$INSTDIR\yes-bd2-write-test.tmp" w
  ${If} ${Errors}
    ${If} $R5 == 1
      RMDir "$INSTDIR"
    ${EndIf}
    ${If} $LANGUAGE == 2052
      MessageBox MB_OK|MB_ICONEXCLAMATION "这个位置没有写入权限，装不进去：$\r$\n$INSTDIR$\r$\n$\r$\n请换一个位置，例如默认位置：$\r$\n$LOCALAPPDATA\${PRODUCTNAME}"
    ${Else}
      MessageBox MB_OK|MB_ICONEXCLAMATION "This folder can't be written to:$\r$\n$INSTDIR$\r$\n$\r$\nPlease choose another one, for example the default:$\r$\n$LOCALAPPDATA\${PRODUCTNAME}"
    ${EndIf}
    Abort
  ${EndIf}
  FileClose $R6
  Delete "$INSTDIR\yes-bd2-write-test.tmp"
  ${If} $R5 == 1
    RMDir "$INSTDIR"
  ${EndIf}
FunctionEnd
'@
    $killParamSearch = @'
  FileWrite $R1 "  [string]$$InstallerPath$\r$\n"
'@
    $killParamReplacement = @'
  FileWrite $R1 "  [string]$$InstallerPath,$\r$\n"
  FileWrite $R1 "  [string]$$ReportPath$\r$\n"
'@
    $killReportSearch = @'
  FileWrite $R1 "if ($$remaining.Count -gt 0) { exit 2 }$\r$\n"
'@
    $killReportReplacement = @'
  FileWrite $R1 "if ($$remaining.Count -gt 0) {$\r$\n"
  FileWrite $R1 "  if ($$ReportPath) { (@($$remaining | ForEach-Object { $$_.Name } | Sort-Object -Unique) -join ', ') | Set-Content -LiteralPath $$ReportPath -Encoding ASCII -NoNewline }$\r$\n"
  FileWrite $R1 "  exit 2$\r$\n"
  FileWrite $R1 "}$\r$\n"
'@
    $killRunSearch = @'
  retry_kill_install_dir_executables:
  DetailPrint "Stopping running executables in $INSTDIR"
  ExecWait 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$R0" "$INSTDIR" "$EXEPATH"' $R2
  ${If} $R2 <> 0
    ${If} $LANGUAGE == 2052
      MessageBox MB_ICONEXCLAMATION|MB_RETRYCANCEL "无法停止正在使用 $INSTDIR 中 Python/Qt 文件的进程。$\r$\n请关闭相关应用后点击“重试”。" IDRETRY retry_kill_install_dir_executables
    ${Else}
      MessageBox MB_ICONEXCLAMATION|MB_RETRYCANCEL "Some processes are still using Python/Qt files in $INSTDIR.$\r$\nClose the related app and click Retry." IDRETRY retry_kill_install_dir_executables
    ${EndIf}
    Abort
  ${EndIf}
FunctionEnd
'@
    $killRunReplacement = @'
  StrCpy $R3 "$PLUGINSDIR\kill-install-dir-executables.txt"
  retry_kill_install_dir_executables:
  DetailPrint "Stopping running executables in $INSTDIR"
  Delete "$R3"
  nsExec::ExecToLog 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$R0" "$INSTDIR" "$EXEPATH" "$R3"'
  Pop $R2
  ${If} $R2 == 2
    ; What is left most likely runs as administrator (the launcher asks for
    ; admin) and this installer does not: stop it once more with admin rights.
    DetailPrint "Some are still running; stopping them as administrator"
    ExecShellWait "runas" "powershell.exe" '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "$R0" "$INSTDIR" "$EXEPATH"' SW_HIDE
    Delete "$R3"
    nsExec::ExecToLog 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$R0" "$INSTDIR" "$EXEPATH" "$R3"'
    Pop $R2
  ${EndIf}
  ${If} $R2 == 2
    StrCpy $R4 ""
    ClearErrors
    FileOpen $R1 "$R3" r
    ${IfNot} ${Errors}
      FileRead $R1 $R4
      FileClose $R1
    ${EndIf}
    ${If} $LANGUAGE == 2052
      MessageBox MB_ICONEXCLAMATION|MB_RETRYCANCEL "安装位置 $INSTDIR 里还有程序在运行，关不掉：$R4$\r$\n请按 Ctrl+Shift+Esc 打开任务管理器，在「详细信息」里右键结束它们（结束进程树），再点「重试」。" IDRETRY retry_kill_install_dir_executables
    ${Else}
      MessageBox MB_ICONEXCLAMATION|MB_RETRYCANCEL "Programs in $INSTDIR are still running and could not be stopped: $R4$\r$\nEnd them in Task Manager (Details, right-click, End process tree), then click Retry." IDRETRY retry_kill_install_dir_executables
    ${EndIf}
    Abort
  ${ElseIf} $R2 != 0
    ; PowerShell could not run (blocked by security software, policy, ...):
    ; don't stop the install over the check itself.
    DetailPrint "Could not check for running programs ($R2); continuing."
  ${EndIf}
FunctionEnd
'@

    $patches = @(
        @{ Description = "dangling uninstaller guard"; Search = $uninstallBranchSearch; Replacement = $uninstallBranchReplacement },
        @{ Description = "actionable failure message"; Search = $failureMessageSearch; Replacement = $failureMessageReplacement },
        @{ Description = "install folder must be writable"; Search = $dirWritableSearch; Replacement = $dirWritableReplacement },
        @{ Description = "running-program check: skipped on a first install"; Search = $killFirstInstallSearch; Replacement = $killFirstInstallReplacement },
        @{ Description = "running-program check: report path"; Search = $killParamSearch; Replacement = $killParamReplacement },
        @{ Description = "running-program check: name what is left"; Search = $killReportSearch; Replacement = $killReportReplacement },
        @{ Description = "running-program check: admin retry, hidden, never blocks on PowerShell"; Search = $killRunSearch; Replacement = $killRunReplacement }
    )

    foreach ($patch in $patches) {
        # Normalize line endings on both sides: the .ps1 file may be CRLF while the
        # cloned template is LF, and here-string literals inherit the script's endings.
        $search = $patch.Search -replace "`r`n", "`n"
        $replacement = $patch.Replacement -replace "`r`n", "`n"
        $matchCount = [regex]::Matches($content, [regex]::Escape($search)).Count
        if ($matchCount -ne 1) {
            $firstLine = ($search -split "`n")[0]
            throw "installer.nsi patch '$($patch.Description)' expected exactly 1 match but found $matchCount (content=$($content.Length) chars, search=$($search.Length) chars, firstLineIndex=$($content.IndexOf($firstLine))). The pyappify template changed; update the embedded patch text."
        }
        $content = $content.Replace($search, $replacement)
    }

    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($nsiPath, ($content -replace "`n", "`r`n"), $utf8NoBom)
    Write-Host "Patched installer.nsi template for stale uninstaller tolerance (BUG-20260905-06)."
}

function Assert-UnderWorkspace {
    param(
        [string]$PathToCheck,
        [string]$Workspace
    )

    $resolvedWorkspace = (Resolve-Path -LiteralPath $Workspace).Path
    $parent = Split-Path -Parent $PathToCheck
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $resolvedParent = (Resolve-Path -LiteralPath $parent).Path
    if (-not $resolvedParent.StartsWith($resolvedWorkspace, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to write outside workspace: $PathToCheck"
    }
}

$workspace = (Resolve-Path -LiteralPath ".").Path
$buildPath = Join-Path $workspace $BuildDir
Assert-UnderWorkspace -PathToCheck $buildPath -Workspace $workspace

$configPath = Join-Path $workspace "pyappify.yml"
if (-not (Test-Path -LiteralPath $configPath)) {
    throw "pyappify.yml not found at $configPath"
}

$configText = Get-Content -LiteralPath $configPath -Raw
$appNameMatch = [regex]::Match($configText, '(?m)^\s*name:\s*["'']?([^"''\r\n]+)["'']?\s*$')
if (-not $appNameMatch.Success) {
    throw "Could not read application name from pyappify.yml"
}
$appName = $appNameMatch.Groups[1].Value.Trim()
$requiresUac = [regex]::IsMatch($configText, '(?m)^\s*uac:\s*true\s*$')

Ensure-Pnpm
Ensure-Cargo

if (Test-Path -LiteralPath $buildPath) {
    Remove-Item -LiteralPath $buildPath -Recurse -Force
}

git clone https://github.com/ok-oldking/pyappify.git $buildPath
git -C $buildPath checkout "tags/$Version"

$assetConfigPath = Join-Path $buildPath "src-tauri\assets\pyappify.yml"
Copy-Item -LiteralPath $configPath -Destination $assetConfigPath -Force

$iconsSource = Join-Path $workspace "icons"
if (Test-Path -LiteralPath $iconsSource) {
    $iconsTarget = Join-Path $buildPath "src-tauri\icons"
    if (Test-Path -LiteralPath $iconsTarget) {
        Remove-Item -LiteralPath $iconsTarget -Recurse -Force
    }
    Copy-Item -LiteralPath $iconsSource -Destination $iconsTarget -Recurse -Force
}

$tauriConfPath = Join-Path $buildPath "src-tauri\tauri.conf.json"
$tauriConf = Get-Content -LiteralPath $tauriConfPath -Raw
$tauriConf = $tauriConf.Replace('"pyappify"', '"' + $appName + '"')
$tauriConf = $tauriConf.Replace('"0.0.1"', '"' + $LauncherVersion.TrimStart("v") + '"')
$tauriConfObject = $tauriConf | ConvertFrom-Json
$tauriConfObject.bundle.windows.nsis | Add-Member `
    -MemberType NoteProperty `
    -Name compression `
    -Value $NsisCompression `
    -Force
$tauriConf = $tauriConfObject | ConvertTo-Json -Depth 100
Set-Content -LiteralPath $tauriConfPath -Value $tauriConf -Encoding UTF8

$cargoTomlPath = Join-Path $buildPath "src-tauri\Cargo.toml"
$cargoToml = Get-Content -LiteralPath $cargoTomlPath -Raw
$cargoToml = $cargoToml.Replace('name = "pyappify"', 'name = "' + $appName + '"')
Set-Content -LiteralPath $cargoTomlPath -Value $cargoToml -Encoding UTF8

$packageJsonPath = Join-Path $buildPath "package.json"
$packageJson = Get-Content -LiteralPath $packageJsonPath -Raw | ConvertFrom-Json
if (-not $packageJson.pnpm) {
    $packageJson | Add-Member -MemberType NoteProperty -Name pnpm -Value ([pscustomobject]@{})
}
$onlyBuiltDependencies = @()
if ($packageJson.pnpm.onlyBuiltDependencies) {
    $onlyBuiltDependencies = @($packageJson.pnpm.onlyBuiltDependencies)
}
if ($onlyBuiltDependencies -notcontains "esbuild") {
    $onlyBuiltDependencies += "esbuild"
}
$packageJson.pnpm | Add-Member -MemberType NoteProperty -Name onlyBuiltDependencies -Value @($onlyBuiltDependencies | Sort-Object -Unique) -Force
$packageJson | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $packageJsonPath -Encoding UTF8

if ($requiresUac) {
    $buildRsPath = Join-Path $buildPath "src-tauri\build.rs"
    $buildRs = Get-Content -LiteralPath $buildRsPath -Raw
    $buildRs = $buildRs.Replace("const UAC: bool = false;", "const UAC: bool = true;")
    Set-Content -LiteralPath $buildRsPath -Value $buildRs -Encoding UTF8
}

$viteConfigPath = Join-Path $buildPath "vite.config.ts"
$viteConfig = Get-Content -LiteralPath $viteConfigPath -Raw
if ($viteConfig -notmatch 'base:\s*["'']\./["'']') {
    $viteConfig = $viteConfig -replace 'plugins:\s*\[react\(\)\],', "plugins: [react()],`r`n  base: `"./`","
    Set-Content -LiteralPath $viteConfigPath -Value $viteConfig -Encoding UTF8
}

# The launcher's footer linked to PyAppify's own repository; players read it
# as the tool's page (Leo 10-08), and Leo 10-09 asked to drop it altogether.
# appVersion stays referenced: the launcher is type-checked with noUnusedLocals.
$appTsxPath = Join-Path $buildPath "src\App.tsx"
$appTsx = Get-Content -LiteralPath $appTsxPath -Raw
$footerLink = '<Link href="https://github.com/ok-oldking/pyappify" target="_blank" rel="noopener noreferrer">{t(''appMadeWith'', {name: `PyAppify ${appVersion}`})}</Link>'
if (-not $appTsx.Contains($footerLink)) {
    throw "PyAppify footer link not found in App.tsx; update prepare_pyappify_launcher.ps1."
}
$appTsx = $appTsx.Replace(
    $footerLink,
    '{appVersion && null}'
)
Set-Content -LiteralPath $appTsxPath -Value $appTsx -Encoding UTF8

$appServicePath = Join-Path $buildPath "src-tauri\src\app_service.rs"
$libRsPath = Join-Path $buildPath "src-tauri\src\lib.rs"
$gitRsPath = Join-Path $buildPath "src-tauri\src\git.rs"
$loggerRsPath = Join-Path $buildPath "src-tauri\src\utils\logger.rs"
$pythonEnvRsPath = Join-Path $buildPath "src-tauri\src\python_env.rs"
$i18nPath = Join-Path $buildPath "src\i18n.ts"

# Every patch below must hit exactly once, or the build fails loudly (the old
# hide-window patch searched text v1.2.3 no longer has and silently did nothing).
function Replace-Once([string]$Text, [string]$Search, [string]$Replacement, [string]$What) {
    $count = ([regex]::Matches($Text, [regex]::Escape($Search))).Count
    if ($count -ne 1) {
        throw "Launcher patch '$What' expected exactly 1 match but found $count; update prepare_pyappify_launcher.ps1."
    }
    return $Text.Replace($Search, $Replacement)
}

# git on Windows may check the sources out with CRLF; the searches below are LF.
$appService = (Get-Content -LiteralPath $appServicePath -Raw -Encoding UTF8) -replace "`r`n", "`n"
$libRs = (Get-Content -LiteralPath $libRsPath -Raw -Encoding UTF8) -replace "`r`n", "`n"
$gitRs = (Get-Content -LiteralPath $gitRsPath -Raw -Encoding UTF8) -replace "`r`n", "`n"
$loggerRs = (Get-Content -LiteralPath $loggerRsPath -Raw -Encoding UTF8) -replace "`r`n", "`n"
$pythonEnvRs = (Get-Content -LiteralPath $pythonEnvRsPath -Raw -Encoding UTF8) -replace "`r`n", "`n"
$appTsx = (Get-Content -LiteralPath $appTsxPath -Raw -Encoding UTF8) -replace "`r`n", "`n"
$i18n = (Get-Content -LiteralPath $i18nPath -Raw -Encoding UTF8) -replace "`r`n", "`n"

# Start the installed version when GitHub can't be reached (player report
# 2026-10-10: 「启动应用」 stayed grey). Every open fetched the tags first and
# gave up on a failed fetch, so an install whose network can't reach GitHub
# (the Full setup from a mainland network, or an accelerator turned off later)
# never learned its own version: the start button stayed disabled and auto
# start never ran. A failed fetch now falls back to the tags already on disk.
$gitRs = Replace-Once $gitRs `
    (@'
        remote
            .fetch(
                &["+refs/tags/*:refs/tags/*"],
                Some(&mut fetch_options),
                None,
            )
            .with_context(|| {
                format!(
                    "Failed to fetch tags for repository {}",
                    repo_path_for_task.display()
                )
            })?;
        prune_deleted_local_tags_from_remote(&repo, "origin", &app_name_for_task)?;
'@ -replace "`r`n", "`n") `
    (@'
        match remote.fetch(
            &["+refs/tags/*:refs/tags/*"],
            Some(&mut fetch_options),
            None,
        ) {
            Ok(()) => prune_deleted_local_tags_from_remote(&repo, "origin", &app_name_for_task)?,
            Err(e) => {
                warn!(
                    "Failed to fetch tags for repository {}, using the local tags: {}",
                    repo_path_for_task.display(),
                    e
                );
                emit_info!(
                    app_name_for_task,
                    "Cannot reach the update server; using the installed version."
                );
            }
        }
'@ -replace "`r`n", "`n") `
    "use local tags when the tag fetch fails"

# The install sat at 「Receiving objects: 99.9%」 (player report 2026-10-13).
# The progress line only moved in 0.1 steps and 100.0 - 99.9 is just under
# 0.1 in floating point, so 100% never showed, and the steps after the
# download (unpacking, writing the files) printed nothing. A download that
# stopped getting data also waited forever: libgit2 has no read timeout.
# Now 100% shows, unpacking and writing files show their own progress, and a
# stalled download gives up after a minute with the 「连不上 GitHub」 message.
$gitRs = Replace-Once $gitRs `
    (@'
        .clone();
    let _guard = lock_arc.lock().await;

    let profile = app.get_current_profile_settings();
'@ -replace "`r`n", "`n") `
    (@'
        .clone();
    let _guard = lock_arc.lock().await;

    // A download that stops getting data gives up after a minute instead of
    // waiting forever (libgit2 has no read timeout by default).
    // SAFETY: only sets libgit2's global timeout values.
    if let Err(e) = unsafe { git2::opts::set_server_timeout_in_milliseconds(60_000) } {
        warn!("Could not set the git read timeout: {}", e);
    }
    let profile = app.get_current_profile_settings();
'@ -replace "`r`n", "`n") `
    "give up on a stalled download"
$gitRs = Replace-Once $gitRs `
    (@'
        let app_name_for_progress_clone = app_name_for_messages.clone();
        callbacks.transfer_progress({
            let mut last_percent = -1.0;
            move |progress: Progress| {
'@ -replace "`r`n", "`n") `
    (@'
        let app_name_for_progress_clone = app_name_for_messages.clone();
        callbacks.transfer_progress({
            let mut last_percent = -1.0;
            let mut last_deltas_percent = usize::MAX;
            move |progress: Progress| {
'@ -replace "`r`n", "`n") `
    "track unpacking progress"
$gitRs = Replace-Once $gitRs `
    (@'
                if total_objects > 0 {
                    let current_percent = (received_objects as f64 * 100.0) / total_objects as f64;
                    let rounded_percent = (current_percent * 10.0).round() / 10.0;
                    if (rounded_percent - last_percent).abs() >= 0.1 {
                        emit_update_info!(
'@ -replace "`r`n", "`n") `
    (@'
                if total_objects > 0 {
                    let current_percent = (received_objects as f64 * 100.0) / total_objects as f64;
                    let rounded_percent = (current_percent * 10.0).round() / 10.0;
                    let all_received = received_objects == total_objects;
                    if all_received && progress.total_deltas() > 0 {
                        let deltas_percent =
                            progress.indexed_deltas() * 100 / progress.total_deltas();
                        if deltas_percent != last_deltas_percent {
                            emit_update_info!(
                                app_name_for_progress_clone,
                                "\rDownloaded {}. Unpacking files: {}%... ",
                                format_bytes(received_bytes),
                                deltas_percent
                            );
                            last_deltas_percent = deltas_percent;
                        }
                    } else if (rounded_percent - last_percent).abs() >= 0.1
                        || (all_received && last_percent < 100.0)
                    {
                        emit_update_info!(
'@ -replace "`r`n", "`n") `
    "show 100% and the unpacking step"
$gitRs = Replace-Once $gitRs `
    (@'
        let mut builder = git2::build::RepoBuilder::new();
        builder.fetch_options(fetch_options);
        builder.bare(false);

'@ -replace "`r`n", "`n") `
    (@'
        let mut builder = git2::build::RepoBuilder::new();
        builder.fetch_options(fetch_options);
        builder.bare(false);
        let app_name_for_checkout = app_name_for_messages.clone();
        let mut last_checkout_percent = usize::MAX;
        let mut checkout = CheckoutBuilder::new();
        checkout.progress(move |_path, done, total| {
            if total > 0 {
                let percent = done * 100 / total;
                if percent != last_checkout_percent {
                    emit_update_info!(
                        app_name_for_checkout,
                        "\rWriting files: {}% ({} / {})... ",
                        percent,
                        done,
                        total
                    );
                    last_checkout_percent = percent;
                }
            }
        });
        builder.with_checkout(checkout);

'@ -replace "`r`n", "`n") `
    "show the files being written"
$appService = Replace-Once $appService `
    ("        ensure_repository(&app).await?;`n        let previous_known_version = app.current_version.clone();") `
    ("        if let Err(e) = ensure_repository(&app).await {`n" +
     "            warn!(`n" +
     "                `"Could not update the repository of '{}', continuing with the local copy: {:?}`",`n" +
     "                app.name, e`n" +
     "            );`n" +
     "        }`n" +
     "        let previous_known_version = app.current_version.clone();") `
    "open with the local copy when the fetch fails"

# Download again when an earlier install stopped halfway (player report
# 2026-10-10: install failed with 「Could not open requirements file」). A
# clone that is cut off (launcher closed, PC asleep, network dropped) leaves a
# repo folder that git can open but whose files are missing; the next install
# saw the folder, only fetched, and copied the missing files on to pip. Setup
# now checks the files against the checked-out version and clones again when
# any are missing; if that still fails it says what the player can do.
# A failed download said only 「Failed to fetch updates for …\repo」 (player
# report 2026-10-11) and hid the reason; it now says GitHub could not be
# reached, what to do, and the underlying git error.
$appService = Replace-Once $appService `
    (@'
#[tauri::command]
pub async fn setup_app(app_name: &str, profile_name: &str) -> Result<(), Error> {
'@ -replace "`r`n", "`n") `
    (@'
async fn ensure_repository_for_setup(app: &App) -> Result<(), Error> {
    ensure_repository(app).await.map_err(|e| {
        err!(
            "下载失败，多半是连不上 GitHub：请先开加速器或换个网络，再按一次安装。Download failed, most likely GitHub cannot be reached: turn on an accelerator or try another network, then press install again. ({:#})",
            e
        )
    })
}

fn repo_checkout_complete(repo_path: &Path) -> bool {
    let Ok(repo) = git2::Repository::open(repo_path) else {
        return false;
    };
    let Ok(tree) = repo.head().and_then(|head| head.peel_to_tree()) else {
        return false;
    };
    let missing = match repo.diff_tree_to_workdir(Some(&tree), None) {
        Ok(diff) => diff
            .deltas()
            .any(|delta| delta.status() == git2::Delta::Deleted),
        Err(_) => true,
    };
    !missing
}

#[tauri::command]
pub async fn setup_app(app_name: &str, profile_name: &str) -> Result<(), Error> {
'@ -replace "`r`n", "`n") `
    "check the downloaded files"
$appService = Replace-Once $appService `
    (@'
    ensure_repository(&app).await?;

    let working_dir_path = get_app_working_dir_path(app_name);
'@ -replace "`r`n", "`n") `
    (@'
    ensure_repository_for_setup(&app).await?;
    if !repo_checkout_complete(&repo_path) {
        warn!(
            "Repository for '{}' at {} is missing files (an earlier download stopped halfway). Downloading it again.",
            app_name,
            repo_path.display()
        );
        emit_info!(
            app_name,
            "The last download did not finish; downloading again."
        );
        delete_dir_if_exist(&repo_path).await?;
        ensure_repository_for_setup(&app).await?;
        if !repo_checkout_complete(&repo_path) {
            return Err(err!(
                "下载不完整：请确认能连上 GitHub（可以先开加速器），再按一次安装。The download is incomplete: make sure GitHub can be reached, then press install again."
            ));
        }
    }

    let working_dir_path = get_app_working_dir_path(app_name);
'@ -replace "`r`n", "`n") `
    "download again when the files are missing"

# Update before starting, even when 「启动应用」 is pressed during the update
# check (player report 2026-10-10: auto start ticked, v0.1.11 started although
# v0.1.17 was out, and the update had to be clicked by hand). The auto update
# and the auto start only run once the tags are fetched, but the button is
# live as soon as the window shows the installed version, and start_app marks
# that check done: a press during the fetch started the old version and the
# check (update and auto start alike) was skipped. A start now waits for the
# check, so the newest version is installed first when the update method
# updates by itself (自动更新, the default), then the tool starts; when GitHub
# can't be reached the check uses the local tags (above) and the installed
# version starts.
$appService = Replace-Once $appService `
    'static AUTO_START_CANCELLED: AtomicBool = AtomicBool::new(false);' `
    ('static AUTO_START_CANCELLED: AtomicBool = AtomicBool::new(false);' + "`n" +
     'static STARTUP_CHECK: Lazy<Mutex<()>> = Lazy::new(|| Mutex::new(()));') `
    "startup check lock"
$appService = Replace-Once $appService `
    ("    emit_app().await;`n`n    if update_app_from_disk().await? {") `
    ("    emit_app().await;`n`n    let _startup_check = STARTUP_CHECK.lock().await;`n    if update_app_from_disk().await? {") `
    "hold the startup check from the fetch on"
$appService = Replace-Once $appService `
    ("pub async fn start_app(app_handle: AppHandle, app_name: String) -> Result<(), Error> {`n" +
     "    AUTO_START_CANCELLED.store(true, AtomicOrdering::SeqCst);") `
    ("pub async fn start_app(app_handle: AppHandle, app_name: String) -> Result<(), Error> {`n" +
     "    if STARTUP_CHECK.try_lock().is_err() {`n" +
     "        info!(`"Start of '{}' asked during the update check; starting after it.`", app_name);`n" +
     "    }`n" +
     "    drop(STARTUP_CHECK.lock().await);`n" +
     "    AUTO_START_CANCELLED.store(true, AtomicOrdering::SeqCst);") `
    "start after the update check"

# The launcher sat a minute or two on 「Fetching all tags」 before the tool
# opened (player report 2026-10-17, still on v0.1.30 with v0.1.44 out). Every
# open asked GitHub three times (fetch, tag fetch, tag list), and on Windows
# libgit2 waits 60 s for each connection that never opens and forever for one
# that stops sending: the read timeout set above only works with the
# non-Windows transport. The startup check now asks GitHub once with a short
# time limit first; when it doesn't answer, the installed version starts right
# away. When it answers, one fetch brings the branches and tags, the tag list
# is read from disk, and a fetch still going after 90 s carries on in the
# background while the installed version starts.
$gitRs = Replace-Once $gitRs `
    (@'
#[tauri::command]
pub async fn get_tags_and_current_version(
'@ -replace "`r`n", "`n") `
    (@'
/// Whether the update server answers at all within a few seconds; the git
/// download itself can't be given a time limit on Windows.
pub async fn update_server_reachable(git_url: &str) -> bool {
    let url = format!(
        "{}/info/refs?service=git-upload-pack",
        git_url.trim_end_matches('/')
    );
    let client = match reqwest::Client::builder()
        .connect_timeout(std::time::Duration::from_secs(8))
        .timeout(std::time::Duration::from_secs(12))
        .build()
    {
        Ok(client) => client,
        Err(e) => {
            warn!("Could not build the update server check, fetching anyway: {}", e);
            return true;
        }
    };
    // Any answer counts: only a connection that fails or times out means
    // the git fetch would hang too.
    match client.get(&url).send().await {
        Ok(_) => true,
        Err(e) => {
            warn!("Update server {} did not answer: {}", git_url, e);
            false
        }
    }
}

/// YES-BD2's own relay for networks that can't reach GitHub: a Cloudflare
/// Worker that forwards only the YES-BD2 repositories, read only.
const UPDATE_RELAY: &str = "https://gh.yesbd2.cc.cd";

static CHOSEN_GIT_URL: Lazy<Mutex<Option<(String, String)>>> = Lazy::new(|| Mutex::new(None));

/// The relay address of a GitHub repository, or None for any other address.
pub fn relay_git_url(git_url: &str) -> Option<String> {
    git_url
        .strip_prefix("https://github.com/")
        .map(|rest| format!("{}/{}", UPDATE_RELAY.trim_end_matches('/'), rest))
}

/// Where to update from: GitHub when it answers, else the relay when that
/// answers, else None. An address that answered is kept for the rest of this
/// launcher run, so the startup check and the download use the same one.
pub async fn reachable_git_url(git_url: &str) -> Option<String> {
    let mut chosen = CHOSEN_GIT_URL.lock().await;
    if let Some((asked, answer)) = chosen.as_ref() {
        if asked == git_url {
            return Some(answer.clone());
        }
    }
    let answer = if update_server_reachable(git_url).await {
        git_url.to_string()
    } else {
        let relay = relay_git_url(git_url)?;
        if !update_server_reachable(&relay).await {
            return None;
        }
        info!("GitHub did not answer; updating through the relay {}", relay);
        relay
    };
    *chosen = Some((git_url.to_string(), answer.clone()));
    Some(answer)
}

/// The tags and the installed version from the copy on disk, without asking
/// the update server. Takes no repository lock: an update check past its time
/// limit may still hold it while the installed version starts.
pub async fn get_local_tags_and_current_version(
    repo_path: PathBuf,
) -> Result<(Vec<String>, String)> {
    task::spawn_blocking(move || -> Result<(Vec<String>, String)> {
        let repo = open_repository(&repo_path)?;
        let sorted_tags = get_sorted_tags_by_time(&repo)?;
        let head_oid = repo
            .head()
            .context("Failed to get repo HEAD")?
            .target()
            .context("HEAD has no target OID")?;
        let mut current_version_tag: Option<String> = None;
        for tag_name in &sorted_tags {
            let tag_ref_name = format!("refs/tags/{}", tag_name);
            if let Ok(reference) = repo.find_reference(&tag_ref_name) {
                if let Ok(obj) = reference.peel(ObjectType::Commit) {
                    if obj.id() == head_oid {
                        current_version_tag = Some(tag_name.clone());
                        break;
                    }
                }
            }
        }
        let current_version = current_version_tag.unwrap_or_else(|| head_oid.to_string());
        Ok((sorted_tags, current_version))
    })
    .await
    .context("Reading the local tags panicked or was cancelled")?
}

#[tauri::command]
pub async fn get_tags_and_current_version(
'@ -replace "`r`n", "`n") `
    "read the tags from disk"
$appService = Replace-Once $appService `
    (@'
        if let Err(e) = ensure_repository(&app).await {
            warn!(
                "Could not update the repository of '{}', continuing with the local copy: {:?}",
                app.name, e
            );
        }
        let previous_known_version = app.current_version.clone();
        let (versions, current) = git::get_tags_and_current_version(&app.name, repo_path).await?;
'@ -replace "`r`n", "`n") `
    (@'
        emit_info!(app.name, "Checking for updates...");
        let git_url = app.get_current_profile_settings().git_url.clone();
        if git::reachable_git_url(&git_url).await.is_some() {
            // Fetches the branches and the tags; the tag list below reads them
            // from disk instead of asking GitHub again.
            let app_for_check = app.clone();
            let check = tokio::spawn(async move { ensure_repository(&app_for_check).await });
            match tokio::time::timeout(UPDATE_CHECK_LIMIT, check).await {
                Ok(Ok(Ok(()))) => {}
                Ok(Ok(Err(e))) => {
                    warn!(
                        "Could not update the repository of '{}', continuing with the local copy: {:?}",
                        app.name, e
                    );
                    emit_info!(
                        app.name,
                        "Cannot reach the update server; using the installed version."
                    );
                }
                Ok(Err(e)) => warn!("The update check for '{}' stopped: {:?}", app.name, e),
                Err(_) => {
                    warn!(
                        "The update check for '{}' took over {} s; starting with the local copy while it continues.",
                        app.name,
                        UPDATE_CHECK_LIMIT.as_secs()
                    );
                    emit_info!(
                        app.name,
                        "更新检查太久，先用已安装的版本。The update check is taking too long; using the installed version."
                    );
                }
            }
        } else {
            emit_info!(
                app.name,
                "连不上 GitHub，先用已安装的版本；开加速器后再打开才会更新。Cannot reach GitHub; using the installed version. Turn on an accelerator to get updates."
            );
        }
        let previous_known_version = app.current_version.clone();
        let (versions, current) = git::get_local_tags_and_current_version(repo_path).await?;
'@ -replace "`r`n", "`n") `
    "ask GitHub once with a time limit"
$appService = Replace-Once $appService `
    'static AUTO_START_CANCELLED: AtomicBool = AtomicBool::new(false);' `
    ('static AUTO_START_CANCELLED: AtomicBool = AtomicBool::new(false);' + "`n" +
     '/// How long the startup update check may take before the installed version is used.' + "`n" +
     'const UPDATE_CHECK_LIMIT: Duration = Duration::from_secs(90);') `
    "update check time limit"

# Players whose network can't reach GitHub at all, with no accelerator, could
# neither install nor update (Leo 2026-10-20: 「這種問題怎麼根除 不想讓用戶設定
# 那些有的沒的」). GitHub stays first; when it doesn't answer, installs and
# updates go through YES-BD2's own relay (cn-mirror/worker.js on Cloudflare),
# which forwards only the YES-BD2 repositories and only for reading. git still
# checks every object it downloads against its hash.
$gitRs = Replace-Once $gitRs `
    '    let url = profile.git_url.clone();' `
    ("    let url = reachable_git_url(&profile.git_url)`n" +
     "        .await`n" +
     "        .unwrap_or_else(|| profile.git_url.clone());") `
    "update through the relay when GitHub does not answer"

# With an accelerator on (Clash and the like set the Windows proxy), the
# browser reached GitHub but the launcher still sat on 「正在启动应用 ·
# Attempting to start app」 (player report 2026-10-19, v0.1.44 with v0.2.0
# out). libgit2 on Windows only looks at git config and the https_proxy
# variable, never at the proxy Windows is set to, so it went to GitHub
# directly, and a direct connection that stalls is waited on forever. git now
# goes through the Windows proxy too, the one the browser and the update
# server check above already use.
$gitRs = Replace-Once $gitRs `
    (@'
fn create_proxy_options() -> ProxyOptions<'static> {
    let mut proxy_opts = ProxyOptions::new();
    proxy_opts.auto();
    proxy_opts
}
'@ -replace "`r`n", "`n") `
    (@'
fn create_proxy_options() -> ProxyOptions<'static> {
    let mut proxy_opts = ProxyOptions::new();
    // A proxy given in the environment wins, as it did before (auto reads it).
    let from_env = ["https_proxy", "HTTPS_PROXY"]
        .iter()
        .any(|name| std::env::var(name).map_or(false, |value| !value.trim().is_empty()));
    match if from_env { None } else { windows_proxy_url() } {
        Some(url) => {
            info!("git goes through the Windows proxy {}", url);
            proxy_opts.url(&url);
        }
        None => {
            proxy_opts.auto();
        }
    }
    proxy_opts
}

/// The proxy for https that Windows is set to (Settings > Network > Proxy),
/// when it is turned on.
#[cfg(windows)]
fn windows_proxy_url() -> Option<String> {
    use windows_sys::Win32::System::Registry::{
        RegGetValueW, HKEY_CURRENT_USER, RRF_RT_REG_DWORD, RRF_RT_REG_SZ,
    };
    fn wide(text: &str) -> Vec<u16> {
        text.encode_utf16().chain(std::iter::once(0)).collect()
    }
    let key = wide("Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings");
    let enable_name = wide("ProxyEnable");
    let server_name = wide("ProxyServer");
    let mut enabled: u32 = 0;
    let mut size = std::mem::size_of::<u32>() as u32;
    let status = unsafe {
        RegGetValueW(
            HKEY_CURRENT_USER,
            key.as_ptr(),
            enable_name.as_ptr(),
            RRF_RT_REG_DWORD,
            std::ptr::null_mut(),
            &mut enabled as *mut u32 as *mut core::ffi::c_void,
            &mut size,
        )
    };
    if status != 0 || enabled == 0 {
        return None;
    }
    let mut server = vec![0u16; 2048];
    let mut size = (server.len() * 2) as u32;
    let status = unsafe {
        RegGetValueW(
            HKEY_CURRENT_USER,
            key.as_ptr(),
            server_name.as_ptr(),
            RRF_RT_REG_SZ,
            std::ptr::null_mut(),
            server.as_mut_ptr() as *mut core::ffi::c_void,
            &mut size,
        )
    };
    if status != 0 {
        warn!("The Windows proxy is on but its address could not be read ({})", status);
        return None;
    }
    let length = server.iter().position(|&c| c == 0).unwrap_or(server.len());
    proxy_url_from_setting(&String::from_utf16_lossy(&server[..length]))
}

#[cfg(not(windows))]
fn windows_proxy_url() -> Option<String> {
    None
}

/// Windows writes the proxy as "127.0.0.1:7890" for every protocol, or per
/// protocol as "http=127.0.0.1:7890;https=127.0.0.1:7890;socks=127.0.0.1:7891".
/// libgit2 takes an http proxy URL; a SOCKS-only setting gives None.
fn proxy_url_from_setting(setting: &str) -> Option<String> {
    let entries: Vec<&str> = setting
        .split(';')
        .map(str::trim)
        .filter(|entry| !entry.is_empty())
        .collect();
    let per_protocol = |protocol: &str| {
        entries.iter().find_map(|entry| {
            let (name, server) = entry.split_once('=')?;
            name.trim()
                .eq_ignore_ascii_case(protocol)
                .then(|| server.trim())
        })
    };
    let server = if entries.iter().any(|entry| entry.contains('=')) {
        per_protocol("https").or_else(|| per_protocol("http"))?
    } else {
        *entries.first()?
    };
    let lower = server.to_ascii_lowercase();
    if server.is_empty() || lower.starts_with("socks") {
        None
    } else if lower.starts_with("http://") || lower.starts_with("https://") {
        Some(server.to_string())
    } else {
        Some(format!("http://{}", server))
    }
}
'@ -replace "`r`n", "`n") `
    "git goes through the Windows proxy"

# GitHub refuses the launcher log as an attachment because it had no extension
# (app.2026-10-10, player report 2026-10-10). New logs are app.<date>.txt; the
# launcher never reads or deletes old logs, so app.<date> files just stay.
$loggerRs = Replace-Once $loggerRs `
    '        let file_appender = rolling::daily(&self.log_dir, &self.file_prefix);' `
    ("        let file_appender = rolling::RollingFileAppender::builder()`n" +
     "            .rotation(rolling::Rotation::DAILY)`n" +
     "            .filename_prefix(self.file_prefix.clone())`n" +
     "            .filename_suffix(`"txt`")`n" +
     "            .build(&self.log_dir)?;") `
    "name the launcher log app.<date>.txt"

# Hide the launcher window once the tool is seen running.
$appService = Replace-Once $appService `
    ("            emit_app().await;`n            return Ok(true);") `
    ("            emit_app().await;`n" +
     "            if let Some(window) = get_app_handle().and_then(|handle| handle.get_webview_window(`"main`")) {`n" +
     "                if let Err(e) = window.hide() {`n" +
     "                    warn!(`"Failed to hide main window after app '{}' started: {:?}`", app_name, e);`n" +
     "                }`n" +
     "            }`n" +
     "            return Ok(true);") `
    "hide the launcher once the tool runs"

# The auto start waited 10 s with nothing on screen, so players thought it did
# nothing (Leo 10-09): it now waits 5 s, says 「5 秒後自動啟動」 next to the
# switch with a 取消 button, then 「正在啟動…」 until the tool is up.
$appService = Replace-Once $appService `
    'info!("Scheduling auto-start for ''{}'' in 10 seconds.", app.name);' `
    ('info!("Scheduling auto-start for ''{}'' in 5 seconds.", app.name);' + "`n" + '                emitter::emit("auto_start_scheduled", 5u64);') `
    "announce the auto start"
$appService = Replace-Once $appService `
    'tokio::time::sleep(Duration::from_secs(10)).await;' `
    'tokio::time::sleep(Duration::from_secs(5)).await;' `
    "auto start after 5 s"
$appService = Replace-Once $appService `
    'pub(crate) async fn emit_app() {' `
    ("#[tauri::command]`n" +
     "pub async fn cancel_auto_start() -> Result<(), Error> {`n" +
     "    AUTO_START_CANCELLED.store(true, AtomicOrdering::SeqCst);`n" +
     "    info!(`"Delayed auto-start cancelled by the user.`");`n" +
     "    Ok(())`n" +
     "}`n`n" +
     'pub(crate) async fn emit_app() {') `
    "cancel command"
$libRs = Replace-Once $libRs `
    '    setup_app, start_app, stop_app, update_app_preferences, update_to_version, StartupOverrides,' `
    '    cancel_auto_start, setup_app, start_app, stop_app, update_app_preferences, update_to_version, StartupOverrides,' `
    "import the cancel command"
$libRs = Replace-Once $libRs `
    '                start_app,' `
    ("                start_app,`n                cancel_auto_start,") `
    "register the cancel command"

$appTsx = Replace-Once $appTsx `
    'const [startingAppName, setStartingAppName] = useState<string | null>(null);' `
    ('const [startingAppName, setStartingAppName] = useState<string | null>(null);' + "`n" +
     '    const [autoStartAt, setAutoStartAt] = useState<number | null>(null);' + "`n" +
     '    const [, setAutoStartTick] = useState(0);' + "`n" +
     '    useEffect(() => {' + "`n" +
     '        if (autoStartAt === null) return;' + "`n" +
     '        const timer = window.setInterval(() => setAutoStartTick(tick => tick + 1), 500);' + "`n" +
     '        return () => window.clearInterval(timer);' + "`n" +
     '    }, [autoStartAt]);') `
    "auto start countdown state"
$appTsx = Replace-Once $appTsx `
    'unlistenPromises.push(listen<App>("app", (event) => {' `
    ('unlistenPromises.push(listen<number>("auto_start_scheduled", (event) => {' + "`n" +
     '            setAutoStartAt(Date.now() + event.payload * 1000);' + "`n" +
     '        }));' + "`n" +
     '        unlistenPromises.push(listen<App>("app", (event) => {') `
    "auto start countdown listener"
$autoStartLabel = "{t('Auto Start')}</Typography>}`n" + (" " * 60) + "/>`n" + (" " * 56) + ")}"
$appTsx = Replace-Once $appTsx $autoStartLabel `
    ($autoStartLabel + "`n" +
     (" " * 56) + "{app.installed && !app.running && app.auto_start && autoStartAt !== null && autoStartAt > Date.now() - 30000 && (`n" +
     (" " * 60) + "<Typography variant=`"body2`" color=`"primary`" sx={{fontWeight: 600, ml: 1}}>`n" +
     (" " * 64) + "{autoStartAt > Date.now() ? t('autoStartIn', {n: Math.ceil((autoStartAt - Date.now()) / 1000)}) : t('autoStarting')}`n" +
     (" " * 60) + "</Typography>`n" +
     (" " * 56) + ")}`n" +
     (" " * 56) + "{app.installed && !app.running && app.auto_start && autoStartAt !== null && autoStartAt > Date.now() && (`n" +
     (" " * 60) + "<Button size=`"small`" variant=`"outlined`" color=`"warning`" sx={{ml: 1}} onClick={() => { invoke('cancel_auto_start').catch(() => {}); setAutoStartAt(null); }}>{t('Cancel')}</Button>`n" +
     (" " * 56) + ")}") `
    "auto start countdown and cancel"
foreach ($entry in @(
    @("Auto Start", "Auto-starting in {{n}} s", "Starting..."),
    @("自动启动", "{{n}} 秒后自动启动", "正在启动…"),
    @("自動啟動", "{{n}} 秒後自動啟動", "正在啟動…"),
    @("自動起動", "{{n}} 秒後に自動起動", "起動中…"),
    @("자동 시작", "{{n}}초 후 자동 시작", "시작 중…"),
    @("Inicio Automático", "Inicio automático en {{n}} s", "Iniciando...")
)) {
    $line = '"Auto Start": "' + $entry[0] + '"'
    $i18n = Replace-Once $i18n $line `
        ($line + ",`n            `"autoStartIn`": `"" + $entry[1] + "`",`n            `"autoStarting`": `"" + $entry[2] + "`"") `
        ("auto start text " + $entry[0])
}

# Try the package install again when a download breaks off (player report
# 2026-10-14: PySide6 from the Aliyun mirror stopped at 34.6/72.4 MB with a
# urllib3 read error, and older pip does not resume a broken download). Up
# to 3 tries; pip's cache keeps every package already downloaded, and the
# last try uses the other China mirror when Aliyun or Tsinghua is set. If
# all fail, the message says what the player can do.
# Before the install the pip sources are timed and the fastest one is used
# (player report 2026-10-22: Aliyun gave that player 80-100 kB/s, so the
# ~300 MB of packages looked stuck for an hour).  Only when the launcher's
# setting is one of the listed sources; a source the player typed is kept.
$pythonEnvRs = Replace-Once $pythonEnvRs `
    (@'
#[cfg(target_os = "windows")]
pub async fn install_requirements(
    app_name: &str,
    requirements: &str,
    project_dir: &Path,
    pip_args: &str,
) -> Result<(), Error> {
    let python_exe = get_python_exe(app_name, false);
'@ -replace "`r`n", "`n") `
    (@'
#[cfg(target_os = "windows")]
const PIP_INSTALL_ATTEMPTS: usize = 3;

/// The sources the launcher's settings list (index URL, then where the same
/// source keeps its package files); only these are timed.
#[cfg(target_os = "windows")]
const PIP_SPEED_SOURCES: [(&str, &str, &str); 6] = [
    ("aliyun", "https://mirrors.aliyun.com/pypi/simple/", "https://mirrors.aliyun.com/pypi/packages/"),
    ("tsinghua", "https://pypi.tuna.tsinghua.edu.cn/simple", "https://pypi.tuna.tsinghua.edu.cn/packages/"),
    ("tencent", "https://mirrors.cloud.tencent.com/pypi/simple/", "https://mirrors.cloud.tencent.com/pypi/packages/"),
    ("huawei", "https://repo.huaweicloud.com/repository/pypi/simple/", "https://repo.huaweicloud.com/repository/pypi/packages/"),
    ("ustc", "https://mirrors.ustc.edu.cn/pypi/simple/", "https://mirrors.ustc.edu.cn/pypi/packages/"),
    ("pypi", "https://pypi.org/simple/", "https://files.pythonhosted.org/packages/"),
];
/// One of the largest packages the install downloads (its 76 MB wheel, the
/// one that looked stuck); every source keeps it at the same path, and
/// PyPI never removes a released file.
#[cfg(target_os = "windows")]
const PIP_SPEED_FILE: &str = "93/81/f4605ab2bdbb3daff7cadf7d5265e87c4fe95d01af00ae8e1638b9a4abe9/openvino-2026.2.1-21919-cp312-cp312-win_amd64.whl";
#[cfg(target_os = "windows")]
const PIP_SPEED_READ_SECONDS: u64 = 4;
#[cfg(target_os = "windows")]
const PIP_SPEED_READ_BYTES: u64 = 4 * 1024 * 1024;

fn configured_pip_index_url() -> Option<String> {
    GLOBAL_CONFIG_STATE
        .get()?
        .lock()
        .ok()?
        .get_effective_pip_index_url()
}

fn same_index(a: &str, b: &str) -> bool {
    a.trim_end_matches('/') == b.trim_end_matches('/')
}

/// The other China mirror for the last try when the configured one keeps
/// breaking off downloads; None keeps the configured source.
#[cfg(target_os = "windows")]
fn fallback_pip_index_url() -> Option<String> {
    let configured = configured_pip_index_url()?;
    if configured.contains("aliyun") {
        Some("https://pypi.tuna.tsinghua.edu.cn/simple".to_string())
    } else if configured.contains("tsinghua") {
        Some("https://mirrors.aliyun.com/pypi/simple/".to_string())
    } else {
        None
    }
}

/// Bytes per second read from one source's copy of a large package, or None
/// when the source cannot be reached in time.
#[cfg(target_os = "windows")]
async fn pip_source_speed(client: &Client, packages_url: &str) -> Option<f64> {
    use std::time::{Duration, Instant};
    let started = Instant::now();
    let deadline = started + Duration::from_secs(PIP_SPEED_READ_SECONDS);
    let response = tokio::time::timeout_at(
        deadline.into(),
        client
            .get(format!("{}{}", packages_url, PIP_SPEED_FILE))
            .header("Range", format!("bytes=0-{}", PIP_SPEED_READ_BYTES - 1))
            .send(),
    )
    .await
    .ok()?
    .ok()?;
    if !response.status().is_success() {
        return None;
    }
    let mut stream = response.bytes_stream();
    let mut read: u64 = 0;
    while read < PIP_SPEED_READ_BYTES {
        match tokio::time::timeout_at(deadline.into(), futures_util::StreamExt::next(&mut stream)).await {
            Ok(Some(Ok(chunk))) => read += chunk.len() as u64,
            _ => break,
        }
    }
    let seconds = started.elapsed().as_secs_f64().max(0.001);
    if read == 0 {
        None
    } else {
        Some(read as f64 / seconds)
    }
}

fn speed_text(speed: Option<f64>) -> String {
    match speed {
        Some(bytes) if bytes >= 1024.0 * 1024.0 => format!("{:.1} MB/s", bytes / 1024.0 / 1024.0),
        Some(bytes) => format!("{:.0} kB/s", bytes / 1024.0),
        None => "-".to_string(),
    }
}

/// The fastest and second fastest listed sources, when the launcher's
/// setting is one of them (None: keep the setting).
#[cfg(target_os = "windows")]
async fn fastest_pip_index_urls(app_name: &str) -> (Option<String>, Option<String>) {
    let configured = match configured_pip_index_url() {
        Some(url) => url,
        None => return (None, None),
    };
    if !PIP_SPEED_SOURCES.iter().any(|(_, url, _)| same_index(url, &configured)) {
        return (None, None);
    }
    emit_info!(app_name, "正在测试哪个下载来源最快 / Timing the package sources...");
    let client = match Client::builder().build() {
        Ok(client) => client,
        Err(_) => return (None, None),
    };
    let speeds = futures_util::future::join_all(
        PIP_SPEED_SOURCES
            .iter()
            .map(|(_, _, packages)| pip_source_speed(&client, packages)),
    )
    .await;
    emit_info!(
        app_name,
        "下载来源速度 / Source speeds: {}",
        PIP_SPEED_SOURCES
            .iter()
            .zip(speeds.iter())
            .map(|((name, _, _), speed)| format!("{} {}", name, speed_text(*speed)))
            .collect::<Vec<_>>()
            .join(", ")
    );
    let mut ranked: Vec<(f64, &str)> = PIP_SPEED_SOURCES
        .iter()
        .zip(speeds.iter())
        .filter_map(|((_, url, _), speed)| speed.map(|s| (s, *url)))
        .collect();
    ranked.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap_or(std::cmp::Ordering::Equal));
    let first = ranked.first().map(|(_, url)| url.to_string());
    let second = ranked.get(1).map(|(_, url)| url.to_string());
    if let Some(url) = &first {
        emit_info!(app_name, "用最快的来源下载 / Using the fastest source: {}", url);
    }
    (first, second)
}

#[cfg(target_os = "windows")]
pub async fn install_requirements(
    app_name: &str,
    requirements: &str,
    project_dir: &Path,
    pip_args: &str,
) -> Result<(), Error> {
    let mut last_error = String::new();
    let (fastest, second_fastest) = fastest_pip_index_urls(app_name).await;
    for attempt in 1..=PIP_INSTALL_ATTEMPTS {
        let index_override = if attempt == PIP_INSTALL_ATTEMPTS {
            second_fastest.clone().or_else(fallback_pip_index_url)
        } else {
            fastest.clone()
        };
        if attempt > 1 {
            emit_info!(
                app_name,
                "Package download broke off; trying again ({}/{}){}. Packages already downloaded are kept.",
                attempt,
                PIP_INSTALL_ATTEMPTS,
                index_override
                    .as_deref()
                    .map(|url| format!(" from {}", url))
                    .unwrap_or_default()
            );
        }
        match install_requirements_once(
            app_name,
            requirements,
            project_dir,
            pip_args,
            index_override.as_deref(),
        )
        .await
        {
            Ok(()) => return Ok(()),
            Err(e) => {
                warn!(
                    "pip install for '{}' failed (attempt {}/{}): {}",
                    app_name, attempt, PIP_INSTALL_ATTEMPTS, e
                );
                last_error = e.to_string();
            }
        }
    }
    Err(err!(
        "安装所需套件失败（试了 {} 次，多半是下载中途断线）：请检查网络，或在启动器「设置」把 pip 来源换成别的，再按一次安装，已下载的套件会保留。Installing packages failed {} times, most likely the download broke off: check the network or pick another pip source in Settings, then press install again. ({})",
        PIP_INSTALL_ATTEMPTS,
        PIP_INSTALL_ATTEMPTS,
        last_error
    ))
}

#[cfg(target_os = "windows")]
async fn install_requirements_once(
    app_name: &str,
    requirements: &str,
    project_dir: &Path,
    pip_args: &str,
    index_override: Option<&str>,
) -> Result<(), Error> {
    let python_exe = get_python_exe(app_name, false);
'@ -replace "`r`n", "`n") `
    "retry the package install"
$pythonEnvRs = Replace-Once $pythonEnvRs `
    (@'
        let index_url = config.get_effective_pip_index_url();
'@ -replace "`r`n", "`n") `
    (@'
        let index_url = index_override
            .map(str::to_string)
            .or_else(|| config.get_effective_pip_index_url());
'@ -replace "`r`n", "`n") `
    "use the other mirror on the last try"

# Download Python again, from the other source, when the archive can't be
# unpacked (player report 2026-10-21: 「Extracting archive
# C:\Temp\python-3.12.10-amd64.zip to D:\yes-bd2\data\apps\yes-bd2\python
# failed」; both sources' archives are intact, so the copy on that PC was cut
# off or blocked while being written). The launcher gave up on the first
# extract failure without trying the backup source, and the message left out
# why. Now each try downloads to its own file, checks the size and every
# file's checksum before unpacking, checks python.exe is there afterwards,
# and on any failure tries again from the other source (3 tries); the last
# message gives the real reason.
function Replace-Between([string]$Text, [string]$Start, [string]$End, [string]$Replacement, [string]$What) {
    $startCount = ([regex]::Matches($Text, [regex]::Escape($Start))).Count
    $endCount = ([regex]::Matches($Text, [regex]::Escape($End))).Count
    if ($startCount -ne 1 -or $endCount -ne 1) {
        throw "Launcher patch '$What' expected exactly 1 start and 1 end match but found $startCount and $endCount; update prepare_pyappify_launcher.ps1."
    }
    $startIndex = $Text.IndexOf($Start)
    $endIndex = $Text.IndexOf($End)
    if ($endIndex -lt $startIndex) {
        throw "Launcher patch '$What' found its end before its start; update prepare_pyappify_launcher.ps1."
    }
    return $Text.Substring(0, $startIndex) + $Replacement + $Text.Substring($endIndex)
}

$pythonEnvRs = Replace-Between $pythonEnvRs `
    (@'
    let (primary_url, backup_url) = get_download_urls(&version_to_ensure)?;
'@ -replace "`r`n", "`n") `
    (@'
    if !python_exe_path.exists() {
        error!("CRITICAL:
'@ -replace "`r`n", "`n").TrimEnd("`n") `
    (@'
    let (primary_url, backup_url) = get_download_urls(&version_to_ensure)?;
    let file_name = get_filename_from_url(&primary_url)?;
    let sources = [&primary_url, &backup_url, &primary_url];
    let mut failures: Vec<String> = Vec::new();
    let mut installed = false;
    for (attempt, url) in sources.iter().enumerate() {
        if attempt > 0 {
            emit_info!(
                app_name,
                "Python could not be installed; trying again ({}/{}) from {}",
                attempt + 1,
                sources.len(),
                url
            );
            tokio::time::sleep(std::time::Duration::from_secs(2)).await;
        }
        // Its own file per try: a copy still held open (a scanner, an earlier
        // try) can't stop the next download.
        let archive_path = std::env::temp_dir().join(format!(
            "yes-bd2-{}-{}-{}",
            std::process::id(),
            attempt + 1,
            file_name
        ));
        let result =
            install_python_archive(url, &archive_path, &install_dir, &python_exe_path, app_name)
                .await;
        if archive_path.exists() {
            if let Err(remove_file_err) = fs::remove_file(&archive_path) {
                warn!(
                    "Failed to remove archive file {}: {}",
                    archive_path.display(),
                    remove_file_err
                );
            }
        }
        match result {
            Ok(()) => {
                installed = true;
                break;
            }
            Err(e) => {
                error!(
                    "Installing Python from {} failed (try {}/{}): {:#}",
                    url,
                    attempt + 1,
                    sources.len(),
                    e
                );
                if install_dir.exists() {
                    if let Err(remove_dir_err) = fs::remove_dir_all(&install_dir) {
                        warn!(
                            "Failed to remove extraction directory {}: {}",
                            install_dir.display(),
                            remove_dir_err
                        );
                    }
                }
                let reason = format!("{:#}", e);
                if !failures.contains(&reason) {
                    failures.push(reason);
                }
            }
        }
    }
    if !installed {
        let reasons = failures.join(" | ");
        return Err(anyhow!(
            "安装 Python 失败（换下载来源试了 {} 次）。原因：{}。请再按一次安装；还是不行，请把 data\\logs 里最新的文件发给我们。Installing Python {} failed {} times: {}",
            sources.len(),
            reasons,
            version_to_ensure,
            sources.len(),
            reasons
        ));
    }
    info!(
        "Successfully installed Python {} to {}",
        version_to_ensure,
        install_dir.display()
    );

'@ -replace "`r`n", "`n") `
    "install Python again from the other source when unpacking fails"
$pythonEnvRs = Replace-Once $pythonEnvRs `
    (@'
#[cfg(target_os = "windows")]
fn extract_archive(archive_path: &Path, extract_to_dir: &Path) -> Result<()> {
'@ -replace "`r`n", "`n") `
    (@'
#[cfg(target_os = "windows")]
async fn install_python_archive(
    url: &str,
    archive_path: &Path,
    install_dir: &Path,
    python_exe_path: &Path,
    app_name: &str,
) -> Result<()> {
    download_file(url, archive_path, app_name).await?;
    emit_info!(app_name, "Checking the downloaded Python archive...");
    check_archive(archive_path)?;
    fs::create_dir_all(install_dir).with_context(|| {
        format!("Creating install directory {} failed", install_dir.display())
    })?;
    emit_info!(app_name, "Extracting Python...");
    extract_archive(archive_path, install_dir).with_context(|| {
        format!(
            "Extracting archive {} to {} failed",
            archive_path.display(),
            install_dir.display()
        )
    })?;
    if !python_exe_path.exists() {
        return Err(anyhow!(
            "python.exe is missing from {} right after unpacking (removed or blocked)",
            install_dir.display()
        ));
    }
    Ok(())
}

/// Reads every file in a zip archive once, so a broken or cut-off download
/// is caught (each file's checksum is checked at its end) before anything
/// is unpacked.
#[cfg(target_os = "windows")]
fn check_archive(archive_path: &Path) -> Result<()> {
    if !archive_path.to_string_lossy().ends_with(".zip") {
        return Ok(());
    }
    let file = fs::File::open(archive_path)
        .with_context(|| format!("Failed to open {}", archive_path.display()))?;
    let mut archive = ZipArchive::new(io::BufReader::new(file)).with_context(|| {
        format!(
            "The downloaded archive {} is not a readable zip (broken download)",
            archive_path.display()
        )
    })?;
    for index in 0..archive.len() {
        let mut entry = archive.by_index(index).with_context(|| {
            format!(
                "The downloaded archive {} is broken at file {}",
                archive_path.display(),
                index
            )
        })?;
        let name = entry.name().to_string();
        io::copy(&mut entry, &mut io::sink()).with_context(|| {
            format!(
                "The downloaded archive {} is broken at {}",
                archive_path.display(),
                name
            )
        })?;
    }
    Ok(())
}

#[cfg(target_os = "windows")]
fn extract_archive(archive_path: &Path, extract_to_dir: &Path) -> Result<()> {
'@ -replace "`r`n", "`n") `
    "check the Python archive before unpacking"
$pythonEnvRs = Replace-Once $pythonEnvRs `
    (@'
                last_reported_percent = percent;
            }
        }
    }
    Ok(())
}
'@ -replace "`r`n", "`n") `
    (@'
                last_reported_percent = percent;
            }
        }
    }
    file.flush()
        .with_context(|| format!("Failed to write file {}", dest_path.display()))?;
    if downloaded != total_size {
        return Err(anyhow!(
            "Download from {} stopped at {} of {} bytes",
            url,
            downloaded,
            total_size
        ));
    }
    Ok(())
}
'@ -replace "`r`n", "`n") `
    "check the Python download is complete"

Set-Content -LiteralPath $appServicePath -Value $appService -Encoding UTF8
Set-Content -LiteralPath $pythonEnvRsPath -Value $pythonEnvRs -Encoding UTF8
Set-Content -LiteralPath $libRsPath -Value $libRs -Encoding UTF8
Set-Content -LiteralPath $gitRsPath -Value $gitRs -Encoding UTF8
Set-Content -LiteralPath $loggerRsPath -Value $loggerRs -Encoding UTF8
Set-Content -LiteralPath $appTsxPath -Value $appTsx -Encoding UTF8
Set-Content -LiteralPath $i18nPath -Value $i18n -Encoding UTF8

Update-InstallerNsiTemplate -BuildDirPath $buildPath

pnpm install --dir $buildPath
if ($SkipBuild) {
    Write-Host "PyAppify source prepared without compiling the launcher."
} else {
    pnpm --dir $buildPath exec cargo fmt --manifest-path (Join-Path $buildPath "src-tauri\Cargo.toml")
    pnpm --dir $buildPath tauri build
}
