"""Build a new portable x64 distribution from public sources, not the live bridge tree."""
import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parent
HERE=ROOT/'desktop'
SDK_SHA='9d07275f53894ab4d5e2e0e996227193e7187dec276d9b624dccbce029216b46'
DEPS='certifi charset_normalizer comtypes idna mouseinfo PIL pyautogui pygetwindow pymsgbox pyperclip pyrect pyscreeze pytweening requests uiautomation urllib3 websockets'.split()
CORE='astrbot_ctl bridge_core config exit_reason main message_source ob_client ob_protocol people senders state uia_sender web_panel werc_adapter wx_msg_parser'.split()

def read_version():
    version = (ROOT/'bridge/VERSION').read_text('utf8').strip()
    if not re.fullmatch(r'(0|[1-9][0-9]{0,4})(\.(0|[1-9][0-9]{0,4})){2}', version) or any(
        int(part) > 65534 for part in version.split('.')
    ):
        raise ValueError('bridge/VERSION must be MAJOR.MINOR.PATCH (0–65534 per component)')
    return version


def build(out):
    version = read_version()
    out.mkdir(parents=True,exist_ok=False)
    base=Path(sys.base_prefix); py=out/'python'; py.mkdir()
    import sysconfig
    site=Path(sysconfig.get_path('purelib'))
    for f in ['python.exe','python3.dll','python313.dll','vcruntime140.dll','vcruntime140_1.dll','LICENSE.txt']:
        shutil.copy2(base/f,py/f)
    skip=shutil.ignore_patterns('__pycache__','*.pyc','test','tests','site-packages','ensurepip','idlelib','turtledemo')
    shutil.copytree(base/'DLLs',py/'DLLs',ignore=shutil.ignore_patterns('*test*'))
    shutil.copytree(base/'Lib',py/'Lib',ignore=skip)
    dest=py/'Lib/site-packages';dest.mkdir()
    for name in DEPS:
        shutil.copytree(site/name,dest/name,ignore=skip)
        dist={'PIL':'pillow'}.get(name,name)
        for meta in site.glob(dist+'-*.dist-info'):shutil.copytree(meta,dest/meta.name)
    core=out/'app/bridge';core.mkdir(parents=True)
    for name in [n+'.py' for n in CORE]+['LICENSE','VERSION','config.example.json']:
        shutil.copy2(ROOT/'bridge'/name,core/name)
    app=out/'app'/HERE.name;app.mkdir();shutil.copy2(HERE/'desktop_service.py',app);shutil.copytree(HERE/'ui',app/'ui');(app/'assets').mkdir();shutil.copy2(HERE/'assets/icon.png',app/'assets')
    wheels=ROOT/'toolchain/rcbridge-sdk';wheel=wheels/'pywebview-6.2.1-py3-none-any.whl'
    if not wheel.exists():subprocess.run([sys.executable,'-m','pip','download','--no-deps','--dest',str(wheels),'pywebview==6.2.1'],check=True)
    if hashlib.sha256(wheel.read_bytes()).hexdigest()!=SDK_SHA:raise ValueError('WebView2 packaging wheel hash mismatch')
    with zipfile.ZipFile(wheel) as z:
        for name in ['Microsoft.Web.WebView2.WinForms.dll','Microsoft.Web.WebView2.Core.dll','runtimes/win-x64/native/WebView2Loader.dll']:
            (out/Path(name).name).write_bytes(z.read('webview/lib/'+name))
        for name in z.namelist():
            if '/licenses/' in name and not name.endswith('/'):(out/('WebView-'+Path(name).name)).write_bytes(z.read(name))
    csc=Path('C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe')
    with tempfile.TemporaryDirectory() as temp:
        metadata = Path(temp)/'Version.cs'
        metadata.write_text(
            f'[assembly: System.Reflection.AssemblyVersion("{version}.0")]\n'
            f'[assembly: System.Reflection.AssemblyFileVersion("{version}.0")]\n'
            f'[assembly: System.Reflection.AssemblyInformationalVersion("{version}")]\n',
            encoding='ascii',
        )
        subprocess.run([str(csc),'/nologo','/target:winexe','/platform:x64','/utf8output','/win32icon:'+str(HERE/'assets/icon.ico'),'/out:'+str(out/'RCBridge.exe'),'/reference:System.Windows.Forms.dll','/reference:System.Drawing.dll',*['/reference:'+str(f) for f in out.glob('Microsoft.Web.*.dll')],str(HERE/'Workstation.cs'),str(metadata)],check=True)
    if (ROOT/'README.md').exists():shutil.copy2(ROOT/'README.md',out/'使用说明.md')
    shutil.copy2(ROOT/'CHANGELOG.md',out/'CHANGELOG.md')
    return out

if __name__=='__main__':
    print(build(Path(sys.argv[1]).resolve() if len(sys.argv)>1 else ROOT/'build'/f'RCBridge-{read_version()}-win-x64'))
