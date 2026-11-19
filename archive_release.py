"""Build, test and archive one Windows release from the current Git commit."""
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from build_desktop import ROOT, build, read_version


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def archive():
    version = read_version()
    tag = f'v{version}'
    releases = ROOT / 'archives' / 'releases'
    target = releases / tag
    if target.exists() or git('tag', '--list', tag):
        raise SystemExit(f'{tag} already has an archive or Git tag; bump bridge/VERSION')
    if git('status', '--porcelain', '--untracked-files=all'):
        raise SystemExit('Commit changes before archiving a release')
    commit = git('rev-parse', 'HEAD')
    name = f'RCBridge-{version}-win-x64'
    python = [sys.executable, '-X', 'utf8']
    subprocess.run([*python, '-m', 'unittest', 'discover', '-s', 'tests'], cwd=ROOT, check=True)

    releases.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=f'.{tag}-', dir=releases) as work:
        stage = Path(work)
        bundle = build(stage / name)
        subprocess.run([*python, 'tests/offline_roundtrip.py', str(bundle)], cwd=ROOT, check=True)
        record = stage / 'release'
        record.mkdir()
        zip_path = Path(shutil.make_archive(str(record / name), 'zip', stage, name))
        with zip_path.open('rb') as file:
            digest = hashlib.file_digest(file, 'sha256').hexdigest()
        (record / 'SHA256SUMS.txt').write_text(f'{digest}  {zip_path.name}\n', encoding='ascii')
        (record / 'BUILD.txt').write_text(
            f'version={version}\ncommit={commit}\npython={sys.version.split()[0]}\n', encoding='ascii'
        )
        if git('rev-parse', 'HEAD') != commit or git('status', '--porcelain', '--untracked-files=all'):
            raise SystemExit('Source changed during packaging; archive not saved')
        record.rename(target)
    print(f'Archived: {target}\nTag the verified commit: git tag -a {tag} {commit} -m "RCBridge {version}"')


if __name__ == '__main__':
    archive()
