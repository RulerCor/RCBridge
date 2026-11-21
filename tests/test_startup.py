"""Check the Windows logon command without touching the real startup registry."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch

from desktop import desktop_service as desktop


class LogonStartupTest(unittest.TestCase):
    def test_register_and_remove_only_this_profile(self):
        with TemporaryDirectory(prefix='RCBridge startup ') as folder:
            home = Path(folder) / 'local profile'
            exe = Path(folder) / 'production app' / 'RCBridge.exe'
            exe.parent.mkdir()
            exe.touch()
            startup = desktop.LogonStartup(home, exe)
            self.assertNotEqual(startup.name, desktop.LogonStartup(home.with_name('another profile'), exe).name)
            self.assertEqual(startup.command, f'"{exe}" --profile "{home}"')
            key = MagicMock()
            with (
                patch.object(desktop.winreg, 'OpenKey', return_value=key) as opening,
                patch.object(desktop.winreg, 'CreateKeyEx', return_value=key) as creating,
                patch.object(desktop.winreg, 'QueryValueEx', side_effect=FileNotFoundError) as query,
                patch.object(desktop.winreg, 'SetValueEx') as write,
                patch.object(desktop.winreg, 'DeleteValue') as delete,
            ):
                self.assertFalse(startup.enabled())
                startup.set_enabled(True)
                creating.assert_called_once_with(desktop.winreg.HKEY_CURRENT_USER, desktop.RUN_KEY, 0, desktop.winreg.KEY_SET_VALUE)
                write.assert_called_once_with(key.__enter__(), startup.name, 0, desktop.winreg.REG_SZ, startup.command)
                query.side_effect = None
                query.return_value = (startup.command, desktop.winreg.REG_SZ)
                self.assertTrue(startup.enabled())
                startup.set_enabled(False)
                opening.assert_called_with(desktop.winreg.HKEY_CURRENT_USER, desktop.RUN_KEY, 0, desktop.winreg.KEY_SET_VALUE)
                delete.assert_called_once_with(key.__enter__(), startup.name)

    def test_no_registration_without_the_desktop_executable(self):
        with TemporaryDirectory() as folder:
            startup = desktop.LogonStartup(Path(folder) / 'profile', Path(folder) / 'missing.exe')
            with patch.object(desktop.winreg, 'CreateKeyEx') as create, self.assertRaises(ValueError):
                startup.set_enabled(True)
            create.assert_not_called()
