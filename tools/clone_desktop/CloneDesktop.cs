// 桌面分身 (child session) viewer for bd2-auto.
//
// Opens this Windows user's child session: a second, independent desktop with
// its own mouse and keyboard, shown here in a window (1920x1080, scaled to
// fit). The game and the tool run inside it, so they never touch the real
// cursor. Minimising keeps it on the taskbar like any window (Leo, 2026-10-03);
// the session and its display keep running (setup.ps1 sets RemoteDesktop_SuppressWhenMinimized). Closing
// the window ends the clone: it signs out, which closes the game and the tool
// inside (Leo, 2026-10-03; BetterGI does the same). It asks 直接關掉 or
// 搬回桌面, which then opens the game on the user's own desktop.
//
// Sign-in: Windows' own sign-in box asks for the account password (a PIN
// cannot sign in to the clone). Ticking its 「記住」 box keeps the password in
// Windows Credential Manager (encrypted for this Windows user, target
// bd2-auto/clone-desktop), and later opens sign in with it (Leo chose this,
// 2026-10-03). A saved password that stops working is deleted. Nothing is
// written anywhere else.
//
// Adapted from ChildStream (https://github.com/mattxslv/childstream,
// src/ChildStream.cs, commit d41693e), MIT License, Copyright (c) 2026
// mattxslv. See LICENSE-childstream.txt in this folder.
//
// Build and one-time setup: tools/clone_desktop/setup.ps1.
//   CloneDesktop.exe              open the clone desktop
//   CloneDesktop.exe -user NAME   pre-fill NAME in Windows' sign-in box
//   CloneDesktop.exe -move URI    on close, offer 搬回桌面: end the clone, then
//                                 open URI (the game) on the user's desktop
//   CloneDesktop.exe -launch EXE -args ARGS -cwd DIR
//                                 after sign-in, start EXE inside the clone
//                                 once (skipped when it already runs there);
//                                 the result goes to launch-result.txt
//   CloneDesktop.exe -check       exit code 0 when child sessions are enabled
//   CloneDesktop.exe -enable      enable child sessions (needs Administrator)
//   CloneDesktop.exe -disable     disable child sessions (needs Administrator)
// Everything is logged to %LOCALAPPDATA%\bd2-auto\clone-desktop\viewer.log.
//
// C# 5 only: it is compiled by the csc.exe that ships with .NET Framework 4.

using System;
using System.Drawing;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Forms;

[ComImport, Guid("302D8188-0052-4807-806A-362B628F9AC5"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMsRdpExtendedSettings
{
    void put_Property([MarshalAs(UnmanagedType.BStr)] string name, ref object value);
    void get_Property([MarshalAs(UnmanagedType.BStr)] string name, out object value);
}

// Events of the RDP control (DIID_IMsTscAxEvents), only the ones logged here.
[ComImport, Guid("336D5562-EFA8-482E-8CB3-C5C0FC7A7DB6"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
public interface IMsTscAxEvents
{
    [DispId(1)] void OnConnecting();
    [DispId(2)] void OnConnected();
    [DispId(3)] void OnLoginComplete();
    [DispId(4)] void OnDisconnected(int discReason);
    [DispId(10)] void OnFatalError(int errorCode);
    [DispId(11)] void OnWarning(int warningCode);
    [DispId(22)] void OnLogonError(int lError);
}

[ClassInterface(ClassInterfaceType.None)]
public class RdpEvents : IMsTscAxEvents
{
    public int DisconnectReason = -1;
    public DateTime LoginTime = DateTime.MinValue;
    public void OnConnecting() { Program.Log("event: connecting"); }
    public void OnConnected() { Program.Log("event: connected"); }
    public void OnLoginComplete() { LoginTime = DateTime.Now; Program.Log("event: login complete"); }
    public void OnDisconnected(int discReason) { DisconnectReason = discReason; Program.Log("event: disconnected, reason " + discReason); }
    public void OnFatalError(int errorCode) { Program.Log("event: fatal error " + errorCode); }
    public void OnWarning(int warningCode) { Program.Log("event: warning " + warningCode); }
    public void OnLogonError(int lError) { Program.Log("event: logon error " + lError); }
}

// Microsoft RDP Client Control (MsTscAx).
public class RdpBox : AxHost
{
    public readonly RdpEvents Sink = new RdpEvents();
    ConnectionPointCookie cookie;

    public RdpBox() : base("8B918B82-7985-4C24-89DF-C33AD2BBFBCD") { }
    public object Ocx { get { return GetOcx(); } }

    protected override void CreateSink()
    {
        try { cookie = new ConnectionPointCookie(GetOcx(), Sink, typeof(IMsTscAxEvents)); }
        catch (Exception ex) { Program.Log("event sink failed: " + ex.Message); }
    }

    protected override void DetachSink()
    {
        try { if (cookie != null) cookie.Disconnect(); }
        catch { }
        cookie = null;
    }
}

static class Program
{
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    struct CredUiInfo
    {
        public int cbSize;
        public IntPtr hwndParent;
        public string pszMessageText;
        public string pszCaptionText;
        public IntPtr hbmBanner;
    }

    [DllImport("credui.dll", CharSet = CharSet.Unicode)]
    static extern int CredUIPromptForWindowsCredentials(ref CredUiInfo info, int authError, ref uint authPackage,
        IntPtr inBuffer, uint inBufferSize, out IntPtr outBuffer, out uint outBufferSize, ref bool save, int flags);
    [DllImport("credui.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern bool CredPackAuthenticationBuffer(int flags, string userName, string password, IntPtr packed, ref int packedSize);
    [DllImport("credui.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern bool CredUnPackAuthenticationBuffer(int flags, IntPtr buffer, uint bufferSize, StringBuilder userName,
        ref int userNameSize, StringBuilder domain, ref int domainSize, StringBuilder password, ref int passwordSize);

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    struct Credential
    {
        public int Flags;
        public int Type;
        public string TargetName;
        public string Comment;
        public long LastWritten;
        public int CredentialBlobSize;
        public IntPtr CredentialBlob;
        public int Persist;
        public int AttributeCount;
        public IntPtr Attributes;
        public string TargetAlias;
        public string UserName;
    }

    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern bool CredWrite(ref Credential credential, int flags);
    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern bool CredRead(string target, int type, int flags, out IntPtr credential);
    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern bool CredDelete(string target, int type, int flags);
    [DllImport("advapi32.dll")]
    static extern void CredFree(IntPtr buffer);

    const int CreduiwinGeneric = 0x1, CreduiwinCheckbox = 0x2, CredPackGenericCredentials = 0x4;
    const int CredTypeGeneric = 1, CredPersistLocalMachine = 2;
    const string SavedTarget = "bd2-auto/clone-desktop";

    [DllImport("wtsapi32.dll", SetLastError = true)]
    static extern bool WTSEnableChildSessions(bool enable);
    [DllImport("wtsapi32.dll")]
    static extern bool WTSIsChildSessionsEnabled(out bool enabled);
    [DllImport("wtsapi32.dll")]
    static extern bool WTSGetChildSessionId(out uint sessionId);

    const string Title = "桌面分身";
    // The tool's 1080p reference size; the window scales it to fit.  The tool
    // in the clone puts the game in fullscreen, which fills exactly this (a
    // window with its title bar did not fit and the taskbar covered it).
    const int DesktopWidth = 1920, DesktopHeight = 1080;
    // A wrong password must not lock the account: a logon that has never
    // worked is not retried, and reconnects stop after a few failures.
    const int MaxReconnects = 3;

    static readonly string dataDir = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "bd2-auto", "clone-desktop");
    static readonly string logPath = Path.Combine(dataDir, "viewer.log");
    // Read by the tool outside: "started", "running PID" or "failed WHY".
    static readonly string launchResultPath = Path.Combine(dataDir, "launch-result.txt");
    // Left by the tool in the clone when its run is done and 做完关闭分身 is on
    // (Leo 2026-11-08): end the clone as 「直接關掉」 or 「搬回桌面」 does.
    // Same name as END_REQUEST in clone_desktop.py.
    static readonly string endRequestPath = Path.Combine(dataDir, "end-request.txt");

    internal static void Log(string message)
    {
        try { File.AppendAllText(logPath, DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss.fff") + " " + message + Environment.NewLine); }
        catch { }
    }

    static bool Enabled()
    {
        bool enabled;
        return WTSIsChildSessionsEnabled(out enabled) && enabled;
    }

    // The port the Remote Desktop listener uses (BetterGI reads it the same way).
    static int RdpPort()
    {
        try
        {
            using (var key = Microsoft.Win32.Registry.LocalMachine.OpenSubKey(@"SYSTEM\CurrentControlSet\Control\Terminal Server\WinStations\RDP-Tcp"))
            {
                object value = key == null ? null : key.GetValue("PortNumber");
                if (value is int && (int)value > 0) return (int)value;
            }
        }
        catch (Exception ex) { Log("rdp port: " + ex.Message); }
        return 3389;
    }

    // The account the clone signs in to: a Microsoft account signs in as
    // MicrosoftAccount\<email>, a local one as MACHINE\user.
    static string DefaultAccount()
    {
        try
        {
            using (var key = Microsoft.Win32.Registry.CurrentUser.OpenSubKey(@"Software\Microsoft\IdentityCRL\UserExtendedProperties"))
            {
                if (key != null)
                    foreach (string name in key.GetSubKeyNames())
                        if (name.Contains("@")) return "MicrosoftAccount\\" + name;
            }
        }
        catch { }
        return Environment.MachineName + "\\" + Environment.UserName;
    }

    static bool ReadSaved(out string account, out string password)
    {
        account = password = null;
        IntPtr pointer;
        if (!CredRead(SavedTarget, CredTypeGeneric, 0, out pointer)) return false;
        try
        {
            var credential = (Credential)Marshal.PtrToStructure(pointer, typeof(Credential));
            if (credential.CredentialBlobSize <= 0 || string.IsNullOrEmpty(credential.UserName)) return false;
            account = credential.UserName;
            password = Marshal.PtrToStringUni(credential.CredentialBlob, credential.CredentialBlobSize / 2);
            return true;
        }
        finally { CredFree(pointer); }
    }

    static void Save(string account, string password)
    {
        IntPtr blob = Marshal.StringToCoTaskMemUni(password);
        try
        {
            var credential = new Credential
            {
                Type = CredTypeGeneric,
                TargetName = SavedTarget,
                Comment = "bd2-auto 桌面分身的登入密碼",
                CredentialBlobSize = password.Length * 2,
                CredentialBlob = blob,
                Persist = CredPersistLocalMachine,
                UserName = account,
            };
            Log(CredWrite(ref credential, 0) ? "password saved in Credential Manager" : "saving password failed, error " + Marshal.GetLastWin32Error());
        }
        finally { Marshal.ZeroFreeCoTaskMemUnicode(blob); }
    }

    internal static void ForgetSaved()
    {
        if (CredDelete(SavedTarget, CredTypeGeneric, 0)) Log("saved password deleted");
    }

    // Windows' own sign-in box, plain user name and password (no PIN tile),
    // with a 「記住」 box. False when cancelled.
    static bool PromptCredentials(IntPtr parent, ref string account, out string password, out bool save)
    {
        password = null;
        save = false;
        var info = new CredUiInfo
        {
            hwndParent = parent,
            pszCaptionText = Title,
            pszMessageText = "輸入這台電腦 Windows 帳號的密碼（Microsoft 帳號就是微軟密碼，不是 PIN）。\n勾「記住」的話，下次開分身就不用再打。",
        };
        info.cbSize = Marshal.SizeOf(typeof(CredUiInfo));
        int inSize = 0;
        IntPtr inBuffer = IntPtr.Zero;
        CredPackAuthenticationBuffer(CredPackGenericCredentials, account, "", IntPtr.Zero, ref inSize);
        if (inSize > 0)
        {
            inBuffer = Marshal.AllocCoTaskMem(inSize);
            if (!CredPackAuthenticationBuffer(CredPackGenericCredentials, account, "", inBuffer, ref inSize))
            {
                Marshal.FreeCoTaskMem(inBuffer);
                inBuffer = IntPtr.Zero;
                inSize = 0;
            }
        }
        uint package = 0;
        IntPtr outBuffer;
        uint outSize;
        bool saveBox = true;
        int result = CredUIPromptForWindowsCredentials(ref info, 0, ref package, inBuffer, (uint)inSize,
            out outBuffer, out outSize, ref saveBox, CreduiwinGeneric | CreduiwinCheckbox);
        if (inBuffer != IntPtr.Zero) Marshal.FreeCoTaskMem(inBuffer);
        if (result != 0)
        {
            Log("sign-in box closed, result " + result);  // 1223 = cancelled
            return false;
        }
        try
        {
            var user = new StringBuilder(1024);
            var domain = new StringBuilder(1024);
            var secret = new StringBuilder(1024);
            int userSize = user.Capacity, domainSize = domain.Capacity, secretSize = secret.Capacity;
            if (!CredUnPackAuthenticationBuffer(0, outBuffer, outSize, user, ref userSize, domain, ref domainSize, secret, ref secretSize))
            {
                Log("sign-in box: unpack failed, error " + Marshal.GetLastWin32Error());
                return false;
            }
            if (user.Length > 0)
                account = domain.Length > 0 ? domain + "\\" + user : user.ToString();
            password = secret.ToString();
            save = saveBox;
            if (password.Length == 0)
            {
                // Windows never lets an account without a password sign in to the clone.
                Log("sign-in box: empty password");
                MessageBox.Show(
                    "分身要用 Windows 帳號的密碼登入，這次沒有打密碼。\n" +
                    "如果這個帳號本來就沒有設密碼，要先到「設定 > 帳戶 > 登入選項 > 密碼」加一個，才能用桌面分身。",
                    Title, MessageBoxButtons.OK, MessageBoxIcon.Warning);
            }
            return password.Length > 0;
        }
        finally
        {
            Marshal.Copy(new byte[outSize], 0, outBuffer, (int)outSize);
            Marshal.FreeCoTaskMem(outBuffer);
        }
    }

    static void SignOutChild(bool wait = false)
    {
        uint id;
        if (!WTSGetChildSessionId(out id) || id == 0 || id == uint.MaxValue)
        {
            Log("sign out: no child session");
            return;
        }
        Log("signing out child session " + id);
        var info = new System.Diagnostics.ProcessStartInfo("logoff", id.ToString()) { UseShellExecute = false, CreateNoWindow = true };
        using (var logoff = System.Diagnostics.Process.Start(info))
            if (wait && logoff != null) logoff.WaitForExit(15000);
    }

    // 搬回桌面: the game in the clone is gone after sign-out; open it again on
    // the user's desktop through Explorer, so it starts as a normal user even
    // when this viewer runs as Administrator.
    static void OpenOnDesktop(string uri)
    {
        System.Threading.Thread.Sleep(3000);
        Log("opening on the desktop: " + uri);
        System.Diagnostics.Process.Start("explorer.exe", "\"" + uri + "\"");
    }

    // X asks how to end the clone: 直接關掉 or 搬回桌面 (Leo, 2026-10-03).
    static string AskClose(Form owner, bool canMove)
    {
        string result = "cancel";
        using (var box = new Form
        {
            Text = Title, FormBorderStyle = FormBorderStyle.FixedDialog, StartPosition = FormStartPosition.CenterParent,
            MinimizeBox = false, MaximizeBox = false, ShowInTaskbar = false, ClientSize = new Size(440, 130),
        })
        {
            box.Controls.Add(new Label
            {
                Text = "要關掉桌面分身嗎？分身裡的遊戲和工具會一起關掉。\n" +
                       (canMove ? "「搬回桌面」會接著在你的桌面打開遊戲。" : ""),
                Location = new Point(16, 14), Size = new Size(410, 56),
            });
            int x = 16;
            Action<string, string> add = (label, value) =>
            {
                var button = new Button { Text = label, Location = new Point(x, 84), Size = new Size(130, 30) };
                button.Click += delegate { result = value; box.Close(); };
                box.Controls.Add(button);
                x += 140;
            };
            add("直接關掉", "end");
            if (canMove) add("搬回桌面", "move");
            add("取消", "cancel");
            box.ShowDialog(owner);
        }
        Log("close asked: " + result);
        return result;
    }

    static bool IsElevated()
    {
        using (var identity = System.Security.Principal.WindowsIdentity.GetCurrent())
            return new System.Security.Principal.WindowsPrincipal(identity).IsInRole(
                System.Security.Principal.WindowsBuiltInRole.Administrator);
    }

    static void WriteLaunchResult(string text)
    {
        Log("launch: " + text);
        try { File.WriteAllText(launchResultPath, text, new UTF8Encoding(false)); }
        catch (Exception ex) { Log("launch result not written: " + ex.Message); }
    }

    // Starts EXE on the clone desktop as this same user, with no password,
    // through a one-off Task Scheduler task (BetterGI does the same in
    // Service/ChildSession/ChildSessionProcessLauncher.cs).
    static string LaunchInClone(string exe, string arguments, string directory)
    {
        uint id;
        if (!WTSGetChildSessionId(out id) || id == 0 || id == uint.MaxValue)
            return "failed 找不到桌面分身";
        foreach (var process in System.Diagnostics.Process.GetProcessesByName(Path.GetFileNameWithoutExtension(exe)))
        {
            using (process)
            {
                try { if (process.SessionId == (int)id) return "running " + process.Id; }
                catch { }
            }
        }
        Type type = Type.GetTypeFromProgID("Schedule.Service");
        if (type == null) return "failed 這台電腦沒有工作排程器";
        string taskName = "bd2-auto-clone-desktop-launch-" + Guid.NewGuid().ToString("N");
        string user;
        using (var identity = System.Security.Principal.WindowsIdentity.GetCurrent())
            user = identity.Name;
        dynamic scheduler = Activator.CreateInstance(type);
        scheduler.Connect();
        dynamic folder = scheduler.GetFolder("\\");
        dynamic task = scheduler.NewTask(0);
        task.RegistrationInfo.Author = "bd2-auto";
        task.RegistrationInfo.Description = "桌面分身：在分身裡打開工具（開完就刪）";
        task.Settings.Enabled = true;
        task.Settings.Hidden = true;
        task.Settings.AllowDemandStart = true;
        task.Settings.DisallowStartIfOnBatteries = false;
        task.Settings.StopIfGoingOnBatteries = false;
        task.Settings.ExecutionTimeLimit = "PT0S";
        // Task Scheduler starts programs below normal priority unless told otherwise.
        task.Settings.Priority = 4;
        task.Principal.UserId = user;
        task.Principal.LogonType = 3;  // TASK_LOGON_INTERACTIVE_TOKEN
        // The tool needs Administrator to start the game, and "Run as
        // administrator" does not work inside the clone, so an elevated viewer
        // starts it elevated (TASK_RUNLEVEL_HIGHEST).
        task.Principal.RunLevel = IsElevated() ? 1 : 0;
        dynamic action = task.Actions.Create(0);  // TASK_ACTION_EXEC
        action.Path = exe;
        action.Arguments = arguments ?? "";
        if (!string.IsNullOrEmpty(directory)) action.WorkingDirectory = directory;
        bool registered = false;
        try
        {
            dynamic registeredTask = folder.RegisterTaskDefinition(taskName, task, 2, user, null, 3, null);  // TASK_CREATE
            registered = true;
            registeredTask.RunEx(null, 4, (int)id, null);  // TASK_RUN_USE_SESSION_ID
            return "started";
        }
        finally
        {
            if (registered)
            {
                try { folder.DeleteTask(taskName, 0); }
                catch (Exception ex) { Log("launch task not deleted: " + ex.Message); }
            }
        }
    }

    // Windows starts the user's startup programs on the clone at sign-in (it
    // ignores a Remote Desktop start program for a child session, live
    // 2026-10-03).  Close them in that session only, from the moment of
    // sign-in, for 2 minutes: Windows tells us each process start, so nothing
    // polls (Leo picked this over changing a Windows setting and found
    // frequent polling too much).  The list (Run keys and Startup folders) is
    // written by the tool.
    static readonly string StartupListFile = Path.Combine(dataDir, "startup-programs.txt");
    static readonly string StartupTaskListFile = Path.Combine(dataDir, "startup-tasks.txt");
    static int sweepGeneration;

    static void StartStartupSweep(uint session)
    {
        var programs = new System.Collections.Generic.HashSet<string>(StringComparer.OrdinalIgnoreCase);
        try
        {
            foreach (string line in File.ReadAllLines(StartupListFile))
                if (line.Trim().Length > 0) programs.Add(line.Trim());
        }
        catch (Exception ex) { Log("startup sweep: no list (" + ex.Message + ")"); return; }
        // Started by Task Scheduler at sign-in (e.g. Google Play Games Notifier,
        // which only shows error SE102 on the clone): their parent is svchost.
        var taskPrograms = new System.Collections.Generic.HashSet<string>(StringComparer.OrdinalIgnoreCase);
        try
        {
            foreach (string line in File.ReadAllLines(StartupTaskListFile))
                if (line.Trim().Length > 0) taskPrograms.Add(line.Trim());
        }
        catch { }
        if (programs.Count == 0 && taskPrograms.Count == 0) return;
        int generation = System.Threading.Interlocked.Increment(ref sweepGeneration);
        // Only what the sign-in started: a browser the game's launcher opens
        // (e.g. a Google login) is also on the list but must stay.  Children
        // of a closed one go too (Discord's updater starts Discord itself).
        var closed = new System.Collections.Generic.HashSet<int>();
        Func<int, int> parentOf = delegate (int pid)
        {
            try
            {
                using (var searcher = new System.Management.ManagementObjectSearcher(
                    "SELECT ParentProcessId FROM Win32_Process WHERE ProcessId=" + pid))
                    foreach (System.Management.ManagementObject row in searcher.Get())
                        return Convert.ToInt32(row["ParentProcessId"]);
            }
            catch { }
            return -1;
        };
        Func<int, string> commandLineOf = delegate (int pid)
        {
            try
            {
                using (var searcher = new System.Management.ManagementObjectSearcher(
                    "SELECT CommandLine FROM Win32_Process WHERE ProcessId=" + pid))
                    foreach (System.Management.ManagementObject row in searcher.Get())
                        return Convert.ToString(row["CommandLine"]) ?? "";
            }
            catch { }
            return "";
        };
        Func<int, bool, bool> startedBySignIn =delegate (int parent, bool fromTask)
        {
            if (parent <= 0) return false;
            lock (closed) if (closed.Contains(parent)) return true;
            try
            {
                using (var p = System.Diagnostics.Process.GetProcessById(parent))
                {
                    string name = p.ProcessName.ToLowerInvariant();
                    if (name == "explorer" || name == "userinit") return true;
                    return fromTask && (name == "svchost" || name == "taskhostw");
                }
            }
            catch { return false; }
        };
        Action<int, int> check = delegate (int pid, int parent)
        {
            try
            {
                using (var process = System.Diagnostics.Process.GetProcessById(pid))
                {
                    if (process.SessionId != (int)session) return;
                    bool child;
                    lock (closed) child = closed.Contains(parent);
                    string path = process.MainModule.FileName;
                    bool fromTask = taskPrograms.Contains(path);
                    if (!child && !programs.Contains(path) && !fromTask) return;
                    if (parent < 0) parent = parentOf(pid);
                    if (!startedBySignIn(parent, fromTask)) return;
                    // The game's own start (Play Games' bootstrapper with a
                    // googleplaygames:// link) is the same exe as its sign-in task.
                    if (fromTask && commandLineOf(pid).Contains("://")) return;
                    lock (closed) closed.Add(pid);
                    Log("startup sweep: closing " + Path.GetFileName(path) + " in session " + session);
                    var kill = new System.Diagnostics.ProcessStartInfo("taskkill", "/T /F /PID " + pid)
                    { UseShellExecute = false, CreateNoWindow = true };
                    System.Diagnostics.Process.Start(kill);
                }
            }
            catch { }
        };
        var thread = new System.Threading.Thread(delegate ()
        {
            // Win32_ProcessStartTrace is instant but needs admin; a column list
            // there is rejected ("Invalid parameter", live 2026-10-04), so SELECT *.
            // Without admin, Win32_Process creation events (polled each second).
            System.Management.ManagementEventWatcher watcher = null;
            try
            {
                watcher = new System.Management.ManagementEventWatcher(
                    new System.Management.WqlEventQuery("SELECT * FROM Win32_ProcessStartTrace"));
                watcher.EventArrived += delegate (object sender, System.Management.EventArrivedEventArgs e)
                {
                    try
                    {
                        if (Convert.ToInt32(e.NewEvent["SessionID"]) == (int)session)
                            check(Convert.ToInt32(e.NewEvent["ProcessID"]),
                                  Convert.ToInt32(e.NewEvent["ParentProcessID"]));
                    }
                    catch { }
                };
                watcher.Start();
            }
            catch (Exception ex)
            {
                if (watcher != null) { try { watcher.Dispose(); } catch { } }
                watcher = null;
                Log("startup sweep: start trace unavailable (" + ex.Message + "), polling creations");
                try
                {
                    watcher = new System.Management.ManagementEventWatcher(
                        new System.Management.WqlEventQuery(
                            "SELECT * FROM __InstanceCreationEvent WITHIN 1 WHERE TargetInstance ISA 'Win32_Process'"));
                    watcher.EventArrived += delegate (object sender, System.Management.EventArrivedEventArgs e)
                    {
                        try
                        {
                            var target = (System.Management.ManagementBaseObject)e.NewEvent["TargetInstance"];
                            if (Convert.ToInt32(target["SessionId"]) == (int)session)
                                check(Convert.ToInt32(target["ProcessId"]),
                                      Convert.ToInt32(target["ParentProcessId"]));
                        }
                        catch { }
                    };
                    watcher.Start();
                }
                catch (Exception ex2)
                {
                    watcher = null;
                    Log("startup sweep: no process-start events (" + ex2.Message + ")");
                }
            }
            // Whatever started before the watcher was listening.
            foreach (var process in System.Diagnostics.Process.GetProcesses())
            {
                int pid = process.Id;
                process.Dispose();
                check(pid, -1);
            }
            DateTime start = DateTime.Now;
            while (generation == sweepGeneration && (DateTime.Now - start).TotalSeconds < 300)
                System.Threading.Thread.Sleep(1000);
            if (watcher != null)
            {
                try { watcher.Stop(); watcher.Dispose(); } catch { }
            }
            Log("startup sweep: done");
        });
        thread.IsBackground = true;
        thread.Start();
    }

    static void LaunchOnce(string exe, string arguments, string directory, NotifyIcon tray)
    {
        string result;
        try { result = LaunchInClone(exe, arguments, directory); }
        catch (Exception ex) { result = "failed " + ex.Message; }
        WriteLaunchResult(result);
        if (result.StartsWith("failed") && tray != null)
            tray.ShowBalloonTip(8000, Title, "沒辦法在分身裡自動打開工具，請在分身裡自己打開。", ToolTipIcon.Warning);
    }

    // Disconnect codes that mean the clone could not be reached at all, so no
    // sign-in was tried and the password is not the problem: 260 / 1288 name
    // lookup, 264 timeout, 516 connect failed, 520 host not found, 772 / 1028 /
    // 2308 connection dropped. Same list as CONNECT_FAILURES in clone_desktop.py.
    // A player got 516 with Windows' text about remote access being off and the
    // PC being off (B站 2026-10-14), and the old message only talked about the
    // password.
    static readonly int[] ConnectFailures = { 260, 264, 516, 520, 772, 1028, 1288, 2308 };

    internal static bool IsConnectFailure(int reason)
    {
        return Array.IndexOf(ConnectFailures, reason) >= 0;
    }

    // The clone is a Remote Desktop session of this PC to itself, so it needs
    // Windows' 「遠端桌面服務」 (TermService). Optimisers and trimmed Windows
    // builds stop, disable or remove it. Started here when it is only stopped
    // (the viewer runs as Administrator; this lets no other PC in, Remote
    // Desktop itself stays off). Returns what to tell the player, or null.
    static string CheckRemoteDesktopService()
    {
        try
        {
            using (var service = new System.Management.ManagementObject("Win32_Service.Name='TermService'"))
            {
                service.Get();
                string mode = Convert.ToString(service["StartMode"]);
                string state = Convert.ToString(service["State"]);
                Log("remote desktop service: " + mode + ", " + state);
                if (mode == "Disabled")
                    return "Windows 的「遠端桌面服務」被停用了，分身要靠它開第二個桌面。\n" +
                           "請回到工具按「在桌面分身跑」，再按「幫我打開」。";
                if (state != "Running")
                {
                    object code = service.InvokeMethod("StartService", null);
                    Log("start remote desktop service => " + code);
                    for (int i = 0; i < 20; i++)
                    {
                        System.Threading.Thread.Sleep(500);
                        service.Get();
                        if (Convert.ToString(service["State"]) == "Running") break;
                    }
                    Log("remote desktop service now " + service["State"]);
                }
            }
        }
        catch (System.Management.ManagementException ex)
        {
            Log("remote desktop service: " + ex.ErrorCode + " " + ex.Message);
            if (ex.ErrorCode == System.Management.ManagementStatus.NotFound)
                return "這台電腦沒有 Windows 的「遠端桌面服務」，不能用桌面分身。\n" +
                       "常見於精簡版 Windows，或用過系統優化／精簡工具。請改用一般模式。";
        }
        catch (Exception ex) { Log("remote desktop service check failed: " + ex.Message); }
        return null;
    }

    // Windows' own words for the last disconnect, for the log and the
    // first-logon error message.
    static string Describe(dynamic ocx, int reason)
    {
        if (reason < 0) return "（沒有收到原因）";
        uint extended = 0;
        try { extended = (uint)(int)ocx.ExtendedDisconnectReason; } catch { }
        try
        {
            string text = ocx.GetErrorDescription((uint)reason, extended);
            return text + "（代碼 " + reason + "／" + extended + "）";
        }
        catch (Exception ex) { return "代碼 " + reason + "／" + extended + "（" + ex.Message + "）"; }
    }

    [STAThread]
    static int Main(string[] args)
    {
        Directory.CreateDirectory(dataDir);
        string command = args.Length > 0 ? args[0] : "";
        if (command == "-check")
        {
            bool enabled = Enabled();
            Log("check: child sessions enabled = " + enabled);
            return enabled ? 0 : 1;
        }
        if (command == "-enable" || command == "-disable")
        {
            bool want = command == "-enable";
            bool ok = WTSEnableChildSessions(want);
            int error = Marshal.GetLastWin32Error();
            bool enabled = Enabled();
            Log("WTSEnableChildSessions(" + want + ") => " + ok + " (error " + error + "), enabled now = " + enabled);
            return enabled == want ? 0 : 1;
        }
        string account = null, launchExe = null, launchArgs = "", launchDir = null, moveUri = null;
        for (int i = 0; i < args.Length; i += 2)
        {
            if (i + 1 >= args.Length)
            {
                MessageBox.Show("參數少了值：" + args[i], Title);
                return 2;
            }
            if (args[i] == "-user") account = args[i + 1];
            else if (args[i] == "-launch") launchExe = args[i + 1];
            else if (args[i] == "-args") launchArgs = args[i + 1];
            else if (args[i] == "-cwd") launchDir = args[i + 1];
            else if (args[i] == "-move") moveUri = args[i + 1];
            else
            {
                MessageBox.Show("不認得的參數：" + args[i], Title);
                return 2;
            }
        }

        bool firstInstance;
        using (var single = new System.Threading.Mutex(true, "Local\\bd2-auto-clone-desktop", out firstInstance))
        {
            if (!firstInstance)
            {
                // The clone is already signed in: start the tool there if it is not running.
                // From the tool's start button the task just goes on there, so
                // no message (Leo 2026-10-07); opened by hand, say where it is.
                if (launchExe != null) LaunchOnce(launchExe, launchArgs, launchDir, null);
                else MessageBox.Show("桌面分身已經開著了（看右下角的圖示）。", Title);
                return 1;
            }
            return Run(account, launchExe, launchArgs, launchDir, moveUri);
        }
    }

    static int Run(string account, string launchExe, string launchArgs, string launchDir, string moveUri)
    {
        if (!Enabled())
        {
            MessageBox.Show("桌面分身還沒開啟。\n請先執行一次 tools\\clone_desktop\\setup.ps1。", Title);
            return 1;
        }
        Application.EnableVisualStyles();
        string serviceProblem = CheckRemoteDesktopService();
        if (serviceProblem != null)
        {
            if (launchExe != null) WriteLaunchResult("failed 遠端桌面服務不能用");
            MessageBox.Show(serviceProblem, Title, MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return 1;
        }
        string password;
        bool fromSaved = false, saveAfterLogin = false;
        string savedAccount;
        if (ReadSaved(out savedAccount, out password))
        {
            fromSaved = true;
            if (account == null) account = savedAccount;
        }
        else
        {
            if (account == null) account = DefaultAccount();
            if (!PromptCredentials(IntPtr.Zero, ref account, out password, out saveAfterLogin))
            {
                if (launchExe != null) WriteLaunchResult("failed 沒有輸入密碼");
                return 1;
            }
        }
        Log("viewer start, user " + account + (fromSaved ? " (saved password)" : ""));
        var form = new Form { Text = Title + "（連線中）", Width = 1360, Height = 820 };
        Icon icon = SystemIcons.Application;
        try { icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); } catch { }
        form.Icon = icon;
        form.Show();
        form.Activate();
        var tray = new NotifyIcon { Icon = icon, Visible = true, Text = Title };

        var rdp = new RdpBox { Dock = DockStyle.Fill };
        form.Controls.Add(rdp);
        rdp.CreateControl();
        dynamic ocx = rdp.Ocx;

        bool closingForReal = false;
        bool wantReconnect = true;
        bool everConnected = false;
        bool launchPending = launchExe != null;
        DateTime connectedSince = DateTime.MaxValue;
        int failedReconnects = 0;
        int last = -1;
        DateTime lastAttempt = DateTime.Now;
        var timer = new Timer { Interval = 2000 };

        Action connect = delegate
        {
            lastAttempt = DateTime.Now;
            try
            {
                ocx.Server = "localhost";
                ocx.UserName = account;
                ocx.AdvancedSettings2.ClearTextPassword = password;
                try { ocx.AdvancedSettings2.RDPPort = RdpPort(); } catch { }
                ocx.DesktopWidth = DesktopWidth;
                ocx.DesktopHeight = DesktopHeight;
                try { ocx.AdvancedSettings2.SmartSizing = true; } catch { }
                // Reconnecting must not pull the keyboard away from what the user is doing.
                try { ocx.AdvancedSettings2.GrabFocusOnConnect = false; } catch { }
                try { ocx.ColorDepth = 32; } catch { }
                // Alt+Tab and other Windows keys go into the clone while its window has focus (as BetterGI).
                try { ocx.SecuredSettings2.KeyboardHookMode = 1; } catch { }
                try { ocx.AdvancedSettings7.EnableCredSspSupport = true; } catch { }
                object yes = true;
                ((IMsRdpExtendedSettings)rdp.Ocx).put_Property("ConnectToChildSession", ref yes);
                Log("connecting");
                ocx.Connect();
            }
            catch (Exception ex) { Log("connect failed: " + ex.Message); }
        };

        Action show = delegate { form.Show(); form.WindowState = FormWindowState.Normal; form.Activate(); };
        var menu = new ContextMenuStrip();
        menu.Items.Add("顯示", null, delegate { show(); });
        menu.Items.Add("重新連線", null, delegate
        {
            Log("manual reconnect");
            failedReconnects = 0;
            wantReconnect = true;
            lastAttempt = DateTime.MinValue;
            try { if ((int)ocx.Connected != 0) ocx.Disconnect(); } catch { }
        });
        menu.Items.Add("結束分身（遊戲和工具一起關）", null, delegate { form.Close(); });
        tray.ContextMenuStrip = menu;
        tray.DoubleClick += delegate { show(); };

        form.FormClosing += (sender, e) =>
        {
            // Closing always ends the clone, so nothing is left running in it (Leo, 2026-10-03).
            if (!closingForReal)
            {
                string answer = e.CloseReason == CloseReason.UserClosing ? AskClose(form, moveUri != null) : "end";
                if (answer == "cancel") { e.Cancel = true; return; }
                try
                {
                    SignOutChild(answer == "move");
                    if (answer == "move") OpenOnDesktop(moveUri);
                }
                catch (Exception ex) { Log("close failed: " + ex.Message); }
            }
            wantReconnect = false;
            timer.Stop();
            tray.Visible = false;
            if (launchPending) { launchPending = false; WriteLaunchResult("failed 分身視窗在登入前關掉了"); }
            Log("viewer closing (" + e.CloseReason + ")");
        };

        timer.Tick += delegate
        {
            try
            {
                if (!closingForReal && File.Exists(endRequestPath))
                {
                    // "end" = 直接關掉, "move" = 搬回桌面 (Leo 2026-11-08), as the X asks.
                    string asked = "end";
                    try { asked = File.ReadAllText(endRequestPath).Trim(); } catch { }
                    try { File.Delete(endRequestPath); } catch { }
                    bool move = asked == "move" && moveUri != null;
                    Log("end asked by the tool in the clone: " + asked);
                    closingForReal = true;
                    try
                    {
                        SignOutChild(move);
                        if (move) OpenOnDesktop(moveUri);
                    }
                    catch (Exception ex) { Log("close failed: " + ex.Message); }
                    form.Close();
                    return;
                }
                int state = (int)ocx.Connected;  // 0 disconnected, 1 connected, 2 connecting
                if (state != last)
                {
                    string extra = "";
                    if (state == 0)
                        extra = " " + Describe(ocx, rdp.Sink.DisconnectReason);
                    if (state == 1)
                    {
                        uint id;
                        if (WTSGetChildSessionId(out id)) extra = " child_session=" + id;
                    }
                    Log("state " + last + " -> " + state + extra);
                    last = state;
                    form.Text = Title + (state == 1 ? "（縮到最小也會繼續跑）" : state == 2 ? "（連線中）" : "（沒有連線）");
                }
                if (state == 1)
                {
                    failedReconnects = 0;
                    // Connected means Windows accepted the sign-in (network level authentication).
                    everConnected = true;
                    if (saveAfterLogin)
                    {
                        // Only a password that worked is kept.
                        saveAfterLogin = false;
                        Save(account, password);
                    }
                    if (connectedSince == DateTime.MaxValue)
                    {
                        connectedSince = DateTime.Now;
                        uint sweepSession;
                        if (WTSGetChildSessionId(out sweepSession)) StartStartupSweep(sweepSession);
                    }
                    // Give the clone's desktop a few seconds after sign-in before starting the tool.
                    DateTime login = rdp.Sink.LoginTime;
                    if (launchPending && ((login != DateTime.MinValue && (DateTime.Now - login).TotalSeconds >= 3)
                                          || (DateTime.Now - connectedSince).TotalSeconds >= 20))
                    {
                        launchPending = false;
                        LaunchOnce(launchExe, launchArgs, launchDir, tray);
                    }
                }
                else connectedSince = DateTime.MaxValue;
                if (state != 0 || !wantReconnect || (DateTime.Now - lastAttempt).TotalSeconds < 5) return;
                if (!everConnected)
                {
                    wantReconnect = false;
                    int reason = rdp.Sink.DisconnectReason;
                    string why = Describe(ocx, reason);
                    Log("first logon failed, not retrying: " + why);
                    if (IsConnectFailure(reason))
                    {
                        // Never reached the sign-in: keep a saved password.
                        if (launchPending) { launchPending = false; WriteLaunchResult("failed noconnect " + reason); }
                        MessageBox.Show(
                            "連不上桌面分身（不是密碼的問題）。\n\nWindows 的說明：" + why +
                            "\n\n請依序試：" +
                            "\n1. 關掉這個視窗和工具，重新打開工具再按一次「在桌面分身跑」。" +
                            "\n2. 重新開機後再試（剛設定完，常要重新開機才生效）。" +
                            "\n3. 用過系統優化／精簡工具，或裝過 RDP Wrapper 的電腦，Windows 的「遠端桌面服務」可能被改掉，分身會開不了。" +
                            "\n\n還是不行的話，請把這個資料夾裡的 viewer.log 傳給我們：\n" + dataDir,
                            Title, MessageBoxButtons.OK, MessageBoxIcon.Warning);
                        closingForReal = true;
                        form.Close();
                        return;
                    }
                    if (fromSaved) ForgetSaved();
                    if (launchPending) { launchPending = false; WriteLaunchResult("failed 沒有登入分身"); }
                    MessageBox.Show(
                        "登入桌面分身失敗。\n\nWindows 的說明：" + why +
                        "\n\n常見原因：登入框裡要打 Windows 帳號的密碼（用 Microsoft 帳號的是微軟密碼），不是 PIN；" +
                        "\n或這個帳號設成只能用 Windows Hello 登入，可以到「設定 > 帳戶 > 登入選項」關掉「只允許 Windows Hello 登入」。" +
                        (fromSaved ? "\n記住的密碼已經不能用（可能改過密碼），已經刪掉，下次會再問一次。" : "") +
                        "\n改好之後再打開一次桌面分身。",
                        Title, MessageBoxButtons.OK, MessageBoxIcon.Warning);
                    closingForReal = true;
                    form.Close();
                    return;
                }
                if (failedReconnects >= MaxReconnects)
                {
                    wantReconnect = false;
                    Log("giving up after " + failedReconnects + " reconnects");
                    tray.ShowBalloonTip(5000, Title, "分身連不回去了。右鍵這個圖示按「重新連線」，不行的話把這個視窗關掉再打開。", ToolTipIcon.Warning);
                    return;
                }
                failedReconnects++;
                Log("reconnect " + failedReconnects);
                connect();
            }
            catch (Exception ex) { Log("poll failed: " + ex.Message); }
        };
        // One left from before must not end the new clone at once.
        try { File.Delete(endRequestPath); } catch { }
        timer.Start();

        connect();
        Application.Run(form);
        tray.Visible = false;
        Log("viewer exit");
        return 0;
    }
}
