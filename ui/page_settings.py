"""Settings page: currently just FFmpeg binary location, per OS."""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel, QLineEdit,
    QPushButton, QFileDialog, QTabWidget
)
from PyQt6.QtCore import Qt

from utils.platform_utils import get_platform_name, find_ffmpeg_in_path
from utils.settings import get_ffmpeg_override, set_ffmpeg_override


class SettingsPage(QWidget):
    """Settings page, opened from the main window's Settings menu action."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Settings')
        self.setMinimumSize(560, 360)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        ffmpeg_group = QGroupBox('FFMPEG')
        ffmpeg_layout = QVBoxLayout(ffmpeg_group)

        tabs = QTabWidget()
        tabs.addTab(self._build_windows_tab(), 'Windows')
        tabs.addTab(self._build_unsupported_tab('macOS'), 'macOS')
        tabs.addTab(self._build_unsupported_tab('Linux'), 'Linux')

        # Open the tab matching the current OS by default
        platform_name = get_platform_name()
        tab_index = {'windows': 0, 'macos': 1, 'linux': 2}.get(platform_name, 0)
        tabs.setCurrentIndex(tab_index)

        ffmpeg_layout.addWidget(tabs)
        layout.addWidget(ffmpeg_group)
        layout.addStretch()

    def _build_windows_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        layout.addWidget(QLabel('Detected on PATH:'))
        detected_path = find_ffmpeg_in_path('ffmpeg.exe')
        self.detected_path_label = QLabel(detected_path or 'Not found in PATH')
        self.detected_path_label.setStyleSheet(
            "color: #1a7f37; font-weight: bold;" if detected_path else "color: #b42318; font-weight: bold;"
        )
        self.detected_path_label.setWordWrap(True)
        layout.addWidget(self.detected_path_label)

        layout.addSpacing(12)
        layout.addWidget(QLabel('Manual override (leave empty to use the path above or the bundled binary):'))

        override_row = QHBoxLayout()
        self.override_input = QLineEdit()
        self.override_input.setPlaceholderText(r'C:\path\to\ffmpeg.exe')
        self.override_input.setText(get_ffmpeg_override() or '')
        self.override_input.editingFinished.connect(self._save_override)
        override_row.addWidget(self.override_input)

        browse_button = QPushButton('Browse...')
        browse_button.clicked.connect(self._browse_for_ffmpeg)
        override_row.addWidget(browse_button)
        layout.addLayout(override_row)

        clear_button = QPushButton('Clear Override')
        clear_button.clicked.connect(self._clear_override)
        layout.addWidget(clear_button)

        self.status_label = QLabel('')
        layout.addWidget(self.status_label)

        layout.addStretch()
        return tab

    def _build_unsupported_tab(self, platform_label: str) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        label = QLabel(f'{platform_label} FFmpeg detection/override is not implemented yet.')
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addWidget(label)
        layout.addStretch()
        return tab

    def _browse_for_ffmpeg(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, 'Select ffmpeg executable', '', 'ffmpeg.exe;;All Files (*)'
        )
        if file_path:
            self.override_input.setText(file_path)
            self._save_override()

    def _save_override(self):
        path = self.override_input.text().strip()
        set_ffmpeg_override(path)
        self.status_label.setText(f'Saved: using {path}' if path else 'Override cleared.')

    def _clear_override(self):
        self.override_input.clear()
        set_ffmpeg_override(None)
        self.status_label.setText('Override cleared.')
