// Windows desktop host. Only same-origin requests from this window receive the session key.
using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Windows.Forms;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

[assembly: System.Reflection.AssemblyProduct("RCBridge")]
[assembly: System.Reflection.AssemblyDescription("RCBridge_Mon3trBot")]
class Workstation : Form {
    readonly WebView2 view = new WebView2();
    readonly string root = AppDomain.CurrentDomain.BaseDirectory;
    readonly string key = Guid.NewGuid().ToString("N") + Guid.NewGuid().ToString("N");
    Process service; string origin; bool closing;
    public Workstation() {
        Text="RCBridge"; Icon=Icon.ExtractAssociatedIcon(Application.ExecutablePath);Width=1180;Height=820;MinimumSize=new Size(740,550);
        StartPosition=FormStartPosition.CenterScreen;view.Dock=DockStyle.Fill;Controls.Add(view);Shown+=async(s,e)=>await Open();
        FormClosed+=(s,e)=>{closing=true;if(service!=null && !service.HasExited)service.StandardInput.Close();};
    }
    async Task Open() {
        try {
            var info=new ProcessStartInfo(Path.Combine(root,@"python\python.exe"),"-I -X utf8 -B \""+Path.Combine(root,@"app\desktop\desktop_service.py")+"\"");
            info.UseShellExecute=false; info.CreateNoWindow=true; info.RedirectStandardOutput=true;info.RedirectStandardError=true;info.RedirectStandardInput=true;
            info.WorkingDirectory=root;
            info.EnvironmentVariables["RCBRIDGE_SESSION"]=key;
            service=new Process {StartInfo=info};service.Start();service.BeginErrorReadLine();
            string line;
            do {line=await service.StandardOutput.ReadLineAsync();if(line==null)throw new Exception("控制服务未就绪。请检查端口占用、本机配置及运行目录。 ");}while(!line.StartsWith("RCBRIDGE_READY "));
            var port=int.Parse(line.Substring(15));origin="http://127.0.0.1:"+port;
            var data=Environment.GetEnvironmentVariable("RCBRIDGE_HOME")??Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),@"RCBridge");
            await view.EnsureCoreWebView2Async(await CoreWebView2Environment.CreateAsync(null,Path.Combine(data,"WebView2")));
            var web=view.CoreWebView2;web.Settings.AreDevToolsEnabled=false;web.Settings.IsStatusBarEnabled=false;web.Settings.AreDefaultContextMenusEnabled=false;
            web.AddWebResourceRequestedFilter("*",CoreWebView2WebResourceContext.All);
            web.WebResourceRequested+=(s,e)=>{Uri uri;if(Uri.TryCreate(e.Request.Uri,UriKind.Absolute,out uri)&&uri.GetLeftPart(UriPartial.Authority)==origin)e.Request.Headers.SetHeader("X-RCBridge-Session",key);};
            web.NavigationStarting+=(s,e)=>{Uri uri;if(!Uri.TryCreate(e.Uri,UriKind.Absolute,out uri)||uri.GetLeftPart(UriPartial.Authority)!=origin)e.Cancel=true;};
            web.NewWindowRequested+=(s,e)=>{e.Handled=true;};web.Navigate(origin+"/");
            service.EnableRaisingEvents=true; service.Exited+=(s,e)=>{if(!closing && IsHandleCreated)BeginInvoke((Action)(()=>{if(!closing){MessageBox.Show("桥接控制服务已退出，请重新打开桌面端。",Text);Close();}}));};
        }catch(Exception e){if(!closing){MessageBox.Show(e.Message,"RCBridge · 启动失败",MessageBoxButtons.OK,MessageBoxIcon.Error);Close();}}
    }
    [STAThread]static void Main(string[] args){
        if(args.Length==2 && args[0]=="--profile")
            Environment.SetEnvironmentVariable("RCBRIDGE_HOME",Path.GetFullPath(args[1]));
        Application.EnableVisualStyles();Application.SetCompatibleTextRenderingDefault(false);Application.Run(new Workstation());
    }
}
