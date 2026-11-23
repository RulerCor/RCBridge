// Windows desktop host. Only same-origin requests from this window receive the session key.
using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Windows.Forms;
using System.Threading.Tasks;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

[assembly: System.Reflection.AssemblyProduct("RCBridge")]
[assembly: System.Reflection.AssemblyDescription("RCBridge_Mon3trBot")]
class Workstation : Form {
    readonly WebView2 view = new WebView2();
    readonly string root = AppDomain.CurrentDomain.BaseDirectory;
    readonly string key = Guid.NewGuid().ToString("N") + Guid.NewGuid().ToString("N");
    readonly NotifyIcon tray;
    readonly ContextMenuStrip trayMenu;
    Process service; string origin; bool closing, exitRequested;
    public Workstation() {
        Text="RCBridge"; Icon=Icon.ExtractAssociatedIcon(Application.ExecutablePath);Width=1180;Height=820;MinimumSize=new Size(740,550);
        StartPosition=FormStartPosition.CenterScreen;view.Dock=DockStyle.Fill;Controls.Add(view);Shown+=async(s,e)=>await Open();
        trayMenu = new ContextMenuStrip();
        trayMenu.Items.Add("显示主窗口", null, (s, e) => RestoreWindow());
        trayMenu.Items.Add("退出程序", null, (s, e) => ExitProgram());
        tray = new NotifyIcon { Icon = Icon, Text = "RCBridge", ContextMenuStrip = trayMenu };
        tray.MouseDoubleClick += (s, e) => { if (e.Button == MouseButtons.Left) RestoreWindow(); };
    }

    protected override void OnFormClosing(FormClosingEventArgs e) {
        if (e.CloseReason == CloseReason.UserClosing && !exitRequested) {
            var choice = PromptClose();
            if (choice != DialogResult.Yes) {
                e.Cancel = true;
                if (choice == DialogResult.No) {
                    tray.Visible = true;
                    Hide();
                }
            }
        }
        base.OnFormClosing(e);
        if (!e.Cancel) closing = true;
    }

    protected override void OnFormClosed(FormClosedEventArgs e) {
        tray.Visible = false;
        tray.Dispose();
        trayMenu.Dispose();
        if (service != null && !service.HasExited) service.StandardInput.Close();
        base.OnFormClosed(e);
    }

    DialogResult PromptClose() {
        using (var dialog = new Form {
            Text = "关闭 RCBridge", Icon = Icon, FormBorderStyle = FormBorderStyle.FixedDialog,
            ShowInTaskbar = false, MinimizeBox = false, MaximizeBox = false,
            StartPosition = FormStartPosition.CenterParent, AutoScaleMode = AutoScaleMode.Dpi,
            ClientSize = new Size(416, 126),
        }) {
            var hint = new Label {
                Text = "收进托盘后，桥接继续运行；退出程序会停止桥接。",
                TextAlign = ContentAlignment.MiddleLeft,
                Location = new Point(16, 14), Size = new Size(384, 52),
            };
            var minimize = new Button { Text = "最小化到托盘", DialogResult = DialogResult.No,
                Bounds = new Rectangle(98, 82, 112, 28), TabIndex = 1 };
            var exit = new Button { Text = "退出程序", DialogResult = DialogResult.Yes,
                Bounds = new Rectangle(218, 82, 92, 28), TabIndex = 2 };
            var cancel = new Button { Text = "取消", DialogResult = DialogResult.Cancel,
                Bounds = new Rectangle(318, 82, 82, 28), TabIndex = 0 };
            dialog.Controls.AddRange(new Control[] { hint, minimize, exit, cancel });
            dialog.CancelButton = cancel;
            dialog.ActiveControl = cancel;
            return dialog.ShowDialog(this);
        }
    }

    void RestoreWindow() {
        Show();
        if (WindowState == FormWindowState.Minimized) WindowState = FormWindowState.Normal;
        tray.Visible = false;
        Activate();
    }

    void ExitProgram() {
        exitRequested = true;
        Close();
    }

    void FailAndExit(string message, string title) {
        if (closing) return;
        RestoreWindow();
        MessageBox.Show(this, message, title, MessageBoxButtons.OK, MessageBoxIcon.Error);
        ExitProgram();
    }

    async Task Open() {
        try {
            var info=new ProcessStartInfo(Path.Combine(root,@"python\python.exe"),"-I -X utf8 -B \""+Path.Combine(root,@"app\desktop\desktop_service.py")+"\"");
            info.UseShellExecute=false; info.CreateNoWindow=true; info.RedirectStandardOutput=true;info.RedirectStandardError=true;info.RedirectStandardInput=true;
            info.WorkingDirectory=root;
            info.EnvironmentVariables["RCBRIDGE_SESSION"]=key;
            var worker=new Process {StartInfo=info};
            worker.Start();
            service=worker;
            service.BeginErrorReadLine();
            string line;
            do {line=await service.StandardOutput.ReadLineAsync();if(line==null)throw new Exception("控制服务未就绪。请检查端口占用、本机配置及运行目录。 ");}while(!line.StartsWith("RCBRIDGE_READY "));
            if (closing) return;
            var port=int.Parse(line.Substring(15));origin="http://127.0.0.1:"+port;
            var data=Environment.GetEnvironmentVariable("RCBRIDGE_HOME")??Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),@"RCBridge");
            var environment = await CoreWebView2Environment.CreateAsync(null,Path.Combine(data,"WebView2"));
            if (closing) return;
            await view.EnsureCoreWebView2Async(environment);
            if (closing) return;
            var web=view.CoreWebView2;web.Settings.AreDevToolsEnabled=false;web.Settings.IsStatusBarEnabled=false;web.Settings.AreDefaultContextMenusEnabled=false;
            web.AddWebResourceRequestedFilter("*",CoreWebView2WebResourceContext.All);
            web.WebResourceRequested+=(s,e)=>{Uri uri;if(Uri.TryCreate(e.Request.Uri,UriKind.Absolute,out uri)&&uri.GetLeftPart(UriPartial.Authority)==origin)e.Request.Headers.SetHeader("X-RCBridge-Session",key);};
            web.NavigationStarting+=(s,e)=>{Uri uri;if(!Uri.TryCreate(e.Uri,UriKind.Absolute,out uri)||uri.GetLeftPart(UriPartial.Authority)!=origin)e.Cancel=true;};
            web.NewWindowRequested+=(s,e)=>{e.Handled=true;};web.Navigate(origin+"/");
            service.Exited += (s, e) => {
                if (!closing && IsHandleCreated) BeginInvoke((Action)(() => FailAndExit("桥接控制服务已退出，请重新打开桌面端。", Text)));
            };
            service.EnableRaisingEvents = true;
        } catch (Exception e) {
            FailAndExit(e.Message, "RCBridge · 启动失败");
        }
    }
    [STAThread]static void Main(string[] args){
        if(args.Length==2 && args[0]=="--profile")
            Environment.SetEnvironmentVariable("RCBRIDGE_HOME",Path.GetFullPath(args[1]));
        Application.EnableVisualStyles();Application.SetCompatibleTextRenderingDefault(false);Application.Run(new Workstation());
    }
}
