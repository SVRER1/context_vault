import sys
import ctypes
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
from desktop.app import ContextVaultApp

def main():
                                                                            
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ContextVault.Workspace.1.0")
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setApplicationName('Context Vault')
    app.setOrganizationName('ContextVault')

                            
    icon_path = Path(__file__).resolve().parent.parent / "assets" / "icon.png"
    if icon_path.exists():
        app_icon = QIcon(str(icon_path))
        app.setWindowIcon(app_icon)

    window = ContextVaultApp()
    if icon_path.exists():
        window.setWindowIcon(QIcon(str(icon_path)))

    window.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
