import sys
from ui.page_fileChecking import VideoIntegrityCheckerUI
from PyQt6.QtWidgets import QApplication

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = VideoIntegrityCheckerUI()
    window.show()
    sys.exit(app.exec())
