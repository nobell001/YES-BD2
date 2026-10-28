import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD_WORKFLOW = ROOT / ".github" / "workflows" / "build.yml"
TEST_WORKFLOW = ROOT / ".github" / "workflows" / "test.yml"
PYAPPIFY_CONFIG = ROOT / "pyappify.yml"
RUN_CHECKS_SCRIPT = ROOT / "scripts" / "run_checks.ps1"


class BuildWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = BUILD_WORKFLOW.read_text(encoding="utf-8")
        cls.test_workflow = TEST_WORKFLOW.read_text(encoding="utf-8")
        cls.pyappify_config = PYAPPIFY_CONFIG.read_text(encoding="utf-8")
        cls.run_checks_script = RUN_CHECKS_SCRIPT.read_text(encoding="utf-8")

    def test_hot_switch_defaults_to_fast_and_accepts_compact(self):
        self.assertIn("REQUESTED_MODE: ${{ vars.PACKAGE_BUILD_MODE }}", self.workflow)
        self.assertIn('$mode = "fast"', self.workflow)
        self.assertIn('@("fast", "compact")', self.workflow)
        self.assertIn('if ($mode -eq "fast") { "zlib" } else { "lzma" }', self.workflow)

    def test_fast_and_compact_jobs_are_both_present(self):
        self.assertIn("  package-fast:", self.workflow)
        self.assertIn("  package-compact:", self.workflow)
        self.assertIn("  release-compact:", self.workflow)
        self.assertIn("needs.prepare.outputs.package_mode == 'fast'", self.workflow)
        self.assertIn("needs.prepare.outputs.package_mode == 'compact'", self.workflow)

    def test_one_full_installer_for_every_region(self):
        # Leo 2026-10-08: the China/Global split only chose the update source;
        # every install now updates from GitHub, so one installer is built.
        self.assertIn("          - profile: Full", self.workflow)
        self.assertIn("yes-bd2-win32-Full-setup.exe", self.workflow)
        self.assertNotIn("China", self.workflow)
        self.assertNotIn("Global", self.workflow)
        self.assertEqual(1, self.pyappify_config.count("  - name: "))

    def test_launcher_reuse_is_guarded_by_launcher_inputs(self):
        self.assertIn("Find reusable launcher", self.workflow)
        self.assertIn("scripts/prepare_pyappify_launcher.ps1", self.workflow)
        self.assertIn("yes-bd2-win32.zip", self.workflow)
        self.assertIn("restore_pyappify_launcher.ps1", self.workflow)

    def test_required_workflow_scripts_are_packaged(self):
        scripts = (
            "check_commit_attribution.py",
            "check_dependency_exports.ps1",
            "prepare_pyappify_launcher.ps1",
            "prepare_release_notes.ps1",
            "refresh_dependencies.ps1",
            "restore_pyappify_launcher.ps1",
            "run_checks.ps1",
            "select_pyappify_profile.ps1",
        )
        for script in scripts:
            with self.subTest(script=script):
                self.assertTrue((ROOT / "scripts" / script).is_file())

    def test_run_checks_separates_focused_final_and_release_gates(self):
        self.assertIn(
            '[ValidateSet("Focused", "Final", "Release")]',
            self.run_checks_script,
        )
        self.assertIn('if ($Mode -eq "Focused")', self.run_checks_script)
        self.assertIn(
            '@("-m", "unittest", "discover", "-s", "tests", "-q")',
            self.run_checks_script,
        )
        self.assertIn('if ($Mode -eq "Release")', self.run_checks_script)
        self.assertIn('"check_dependency_exports.ps1"', self.run_checks_script)
        self.assertIn(
            '@("pip", "check", "--python", $pythonExecutable)',
            self.run_checks_script,
        )
        self.assertIn('"ok-bd2-ruff-cache"', self.run_checks_script)
        self.assertIn('"ok-bd2-pycache"', self.run_checks_script)
        self.assertNotIn("exit 0", self.run_checks_script)

    def test_test_workflow_checks_complete_commit_attribution(self):
        self.assertIn("          fetch-depth: 0", self.test_workflow)
        self.assertIn(
            "run: python scripts/check_commit_attribution.py",
            self.test_workflow,
        )

    def test_launcher_script_supports_both_compression_modes(self):
        script = (ROOT / "scripts" / "prepare_pyappify_launcher.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn('[ValidateSet("zlib", "lzma")]', script)
        self.assertIn("[switch]$SkipBuild", script)
        self.assertIn("-Name compression", script)

    def test_launcher_version_is_consistently_pinned(self):
        script = (ROOT / "scripts" / "prepare_pyappify_launcher.ps1").read_text(
            encoding="utf-8"
        )

        for old_version in ("v1.1.6", "v1.1.7", "v1.1.9"):
            self.assertNotIn(old_version, self.workflow)
            self.assertNotIn(old_version, script)
        self.assertEqual(6, self.workflow.count("v1.2.3"))
        self.assertIn('[string]$Version = "v1.2.3"', script)

    def test_launcher_times_the_pip_sources_and_uses_the_fastest(self):
        # A player 2026-10-22: Aliyun gave 80-100 kB/s and the install looked
        # stuck for an hour.
        script = (ROOT / "scripts" / "prepare_pyappify_launcher.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("async fn fastest_pip_index_urls", script)
        self.assertIn("let (fastest, second_fastest) = fastest_pip_index_urls(app_name).await;", script)
        # The probe file is the wheel this install really downloads.
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("openvino==2026.2.1 ", requirements)
        self.assertIn("openvino-2026.2.1-21919-cp312-cp312-win_amd64.whl", script)
        for index in (
            "https://mirrors.aliyun.com/pypi/simple/",
            "https://pypi.tuna.tsinghua.edu.cn/simple",
            "https://mirrors.cloud.tencent.com/pypi/simple/",
            "https://repo.huaweicloud.com/repository/pypi/simple/",
            "https://mirrors.ustc.edu.cn/pypi/simple/",
            "https://pypi.org/simple/",
        ):
            self.assertIn(f'"{index}"', script)

    def test_launcher_uses_project_icon(self):
        self.assertIn('icon: "icons/icon.png"', self.pyappify_config)
        self.assertTrue((ROOT / "icons" / "icon.png").is_file())

    def test_launcher_links_point_to_yes_bd2(self):
        # Leo 10-09: the launcher footer link is dropped altogether; the app
        # name's link still goes to YES-BD2.
        script = (ROOT / "scripts" / "prepare_pyappify_launcher.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'website: "https://github.com/nobell001/YES-BD2"', self.pyappify_config
        )
        self.assertIn("'{appVersion && null}'", script)
        self.assertNotIn('<Link href=', script.split("$footerLink,", 1)[1])

    def test_launcher_start_waits_for_the_update_check(self):
        # Player report 10-10: 「启动应用」 pressed while the launcher was still
        # fetching started v0.1.11 and skipped the update to v0.1.17.
        script = (ROOT / "scripts" / "prepare_pyappify_launcher.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("let _startup_check = STARTUP_CHECK.lock().await;", script)
        self.assertIn("drop(STARTUP_CHECK.lock().await);", script)

    def test_launcher_asks_github_once_with_a_time_limit(self):
        # Player report 10-17: 「Fetching all tags」 for a minute or two on
        # every open when GitHub can't be reached (libgit2 on Windows waits
        # 60 s per connection and never gives up on a stalled one).
        script = (ROOT / "scripts" / "prepare_pyappify_launcher.ps1").read_text(
            encoding="utf-8"
        )
        # The check now also tries the relay (10-20), still through the same
        # short-limit probe.
        self.assertIn("let answer = if update_server_reachable(git_url).await {", script)
        self.assertIn("tokio::time::timeout(UPDATE_CHECK_LIMIT, check)", script)
        self.assertIn(
            "git::get_local_tags_and_current_version(repo_path).await?", script
        )

    def test_installer_running_program_check_never_blocks_on_powershell(self):
        # Player report 10-20: a first install stopped on 「无法停止正在使用
        # … Python/Qt 文件的进程」. Only programs really left running may stop
        # the install, after one try with admin rights.
        script = (ROOT / "scripts" / "prepare_pyappify_launcher.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("nsExec::ExecToLog 'powershell.exe -NoProfile", script)
        self.assertIn('ExecShellWait "runas" "powershell.exe"', script)
        self.assertIn("  ${ElseIf} $R2 != 0", script)
        self.assertIn('-Encoding ASCII -NoNewline', script)
        # A first install never starts PowerShell (Leo 10-20: players must
        # not be asked to touch their security software).
        self.assertIn('${AndIfNot} ${FileExists} "$INSTDIR\\data\\*.*"', script)
        # A folder the installer can't write to is caught on the folder page.
        self.assertIn('FileOpen $R6 "$INSTDIR\\yes-bd2-write-test.tmp" w', script)
        pyappify = (ROOT / "pyappify.yml").read_text(encoding="utf-8")
        self.assertIn("show_add_defender: false", pyappify)

    def test_launcher_python_install_retries_a_broken_archive(self):
        # Player report 10-21: 「Extracting archive …python-3.12.10-amd64.zip
        # … failed」 with no reason and no try from the other source.
        script = (ROOT / "scripts" / "prepare_pyappify_launcher.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("let sources = [&primary_url, &backup_url, &primary_url];", script)
        self.assertIn("check_archive(archive_path)?;", script)
        self.assertIn("if downloaded != total_size {", script)
        self.assertIn("python.exe is missing from {} right after unpacking", script)
        self.assertIn("安装 Python 失败（换下载来源试了 {} 次）。原因：{}", script)

    def test_launcher_git_uses_the_windows_proxy(self):
        # Player report 10-19: with Clash on, the browser reached GitHub but
        # the launcher hung on 「Attempting to start app」: libgit2 on Windows
        # never reads the proxy Windows is set to.
        script = (ROOT / "scripts" / "prepare_pyappify_launcher.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("match if from_env { None } else { windows_proxy_url() } {", script)
        self.assertIn('wide("ProxyEnable")', script)
        self.assertIn("fn proxy_url_from_setting(setting: &str) -> Option<String> {", script)

    def test_launcher_updates_through_the_relay_when_github_is_unreachable(self):
        # Leo 10-20: players who can't reach GitHub shouldn't have to set
        # anything up. GitHub first, then YES-BD2's own relay.
        script = (ROOT / "scripts" / "prepare_pyappify_launcher.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("pub async fn reachable_git_url(git_url: &str) -> Option<String> {", script)
        self.assertIn("if git::reachable_git_url(&git_url).await.is_some() {", script)
        self.assertIn("    let url = reachable_git_url(&profile.git_url)`n", script)

    def test_launcher_log_ends_in_txt(self):
        # GitHub refused the extensionless app.2026-10-10 as an attachment.
        script = (ROOT / "scripts" / "prepare_pyappify_launcher.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn('.filename_suffix(`"txt`")', script)

    def test_workflows_validate_uv_lock_and_exports(self):
        action = "astral-sh/setup-uv@08807647e7069bb48b6ef5acd8ec9567f424441b"
        for workflow in (self.workflow, self.test_workflow):
            with self.subTest(workflow=workflow[:20]):
                self.assertIn(action, workflow)
                self.assertIn('version: "0.11.21"', workflow)
                self.assertIn(r".\scripts\check_dependency_exports.ps1", workflow)

    def test_build_tests_do_not_receive_release_credentials(self):
        run_tests = self.workflow.split("      - name: Run tests", 1)[1].split(
            "      - name: Inline ok-script for update repository", 1
        )[0]
        for variable in (
            "GITHUB_TOKEN",
            "GH_TOKEN",
            "CNB_GH",
            "OK_GH",
            "SIGNPATH_API_TOKEN",
            "MirrorChyanUploadToken",
            "ACTIONS_RUNTIME_TOKEN",
            "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
        ):
            with self.subTest(variable=variable):
                self.assertIn(f'{variable}: ""', run_tests)
                self.assertIn(f'"{variable}"', run_tests)

    def test_build_tests_run_before_inlining_dependencies(self):
        run_tests = self.workflow.index("      - name: Run tests")
        inline_dependencies = self.workflow.index(
            "      - name: Inline ok-script for update repository"
        )
        validate_inline = self.workflow.index(
            "      - name: Validate inlined update repository"
        )

        self.assertLess(run_tests, inline_dependencies)
        self.assertLess(inline_dependencies, validate_inline)
        self.assertIn(
            'Test-Path -LiteralPath "ok" -PathType Container',
            self.workflow,
        )
        self.assertIn(
            "requirements.txt still contains ok-script after inlining.",
            self.workflow,
        )

    def _release_notes(self, tags_and_titles, release_tag, start_tag=""):
        """Run prepare_release_notes.ps1 in a throwaway repository whose
        commits carry the given titles and tags (None = untagged)."""
        script = ROOT / "scripts" / "prepare_release_notes.ps1"
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            env = {key: value for key, value in os.environ.items() if key != "GH_TOKEN"}

            def git(*args):
                subprocess.run(
                    ["git", *args], cwd=repo, env=env, check=True,
                    capture_output=True, text=True, encoding="utf-8",
                )

            git("init", "--quiet")
            git("config", "user.name", "test")
            git("config", "user.email", "test@example.com")
            for index, (title, tag) in enumerate(tags_and_titles):
                (repo / "file.txt").write_text(str(index), encoding="utf-8")
                git("add", "file.txt")
                git("commit", "--quiet", "-m", title)
                if tag:
                    git("tag", "-a", tag, "-m", tag)
            pwsh = shutil.which("pwsh")
            if pwsh is None:
                # The release runs this script on GitHub under PowerShell 7;
                # Windows' built-in PowerShell 5.1 reads git's UTF-8 titles
                # differently, so it is no stand-in.
                self.fail(
                    "PowerShell 7 (pwsh) is not installed; install it with "
                    "`winget install Microsoft.PowerShell` to run this test."
                )
            result = subprocess.run(
                [
                    pwsh, "-NoProfile", "-File", str(script),
                    "-StartTag", start_tag,
                    "-EndTag", release_tag,
                    "-Changelog", "",
                    "-ReleaseTag", release_tag,
                    "-OutputPath", "release-notes.md",
                ],
                cwd=repo, env=env, capture_output=True, text=True,
                encoding="utf-8", errors="replace", check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            return (repo / "release-notes.md").read_text(encoding="utf-8-sig")

    def test_release_notes_for_the_first_release(self):
        notes = self._release_notes([("YES-BD2", "v0.1.1")], "v0.1.1")

        self.assertIn("## YES-BD2 v0.1.1", notes)
        self.assertIn("第一个公开版本", notes)
        self.assertIn("releases/download/v0.1.1/yes-bd2-win32-Full-setup.exe", notes)

    def test_release_notes_list_the_changes_since_the_previous_tag(self):
        notes = self._release_notes(
            [
                ("YES-BD2", "v0.1.1"),
                ("修好跑商", None),
                ("魔獸戰加快", "v0.1.2"),
            ],
            "v0.1.2",
        )

        self.assertIn("### 更新内容 v0.1.1 -> v0.1.2", notes)
        self.assertIn("- 修好跑商", notes)
        self.assertIn("- 魔獸戰加快", notes)
        self.assertNotIn("- YES-BD2", notes)

    def test_release_notes_leave_out_maintenance_and_split_joined_notes(self):
        maintenance = "开发和测试调整，不影响工具使用"
        notes = self._release_notes(
            [
                ("YES-BD2", "v0.1.1"),
                (maintenance, None),
                (maintenance, None),
                ("修好跑商；魔兽追踪者角色名单新增：乙", "v0.1.2"),
            ],
            "v0.1.2",
        )

        self.assertNotIn(maintenance, notes)
        self.assertIn("- 修好跑商\n- 魔兽追踪者角色名单新增：乙", notes)


if __name__ == "__main__":
    unittest.main()
