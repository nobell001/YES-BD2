param(
    [string]$Version = "v1.2.3",
    # The version our patched launcher reports. Installed launchers replace
    # themselves only with a higher one (ok's update_pyappify), so bump this
    # whenever the launcher patches below change.
    [string]$LauncherVersion = "1.2.5",
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

    $patches = @(
        @{ Description = "dangling uninstaller guard"; Search = $uninstallBranchSearch; Replacement = $uninstallBranchReplacement },
        @{ Description = "actionable failure message"; Search = $failureMessageSearch; Replacement = $failureMessageReplacement }
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

Set-Content -LiteralPath $appServicePath -Value $appService -Encoding UTF8
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
