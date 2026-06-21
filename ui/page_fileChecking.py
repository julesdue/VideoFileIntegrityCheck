import sys
import os
import subprocess
from typing import Optional
from PyQt6.QtWidgets import (
    QApplication, QWidget, QMainWindow, QVBoxLayout, QPushButton, QTextEdit, QLabel, QFileDialog, QListWidget, QHBoxLayout, QListWidgetItem, QMenu, QCheckBox, QScrollArea, QMessageBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QPoint, QTimer
from PyQt6.QtGui import QIcon, QPixmap, QKeySequence, QShortcut, QAction
from scripts.checkFile import check_video_file, get_available_check_methods
from utils.platform_utils import get_ffmpeg_paths, verify_ffmpeg_installation, is_valid_file_path, get_invalid_path_reason
from ui.page_settings import SettingsPage

# Keywords that mark a raw FFmpeg log line as an issue worth surfacing, and the
# subset of those that indicate an ERROR rather than a WARNING. Kept as the single
# source of truth so legacy-method log scanning and structured-error severity
# (VideoIntegrityError.severity in ['critical', 'major']) can't drift apart.
ISSUE_KEYWORDS = ['error', 'invalid frame', 'unable', 'corrupt', 'failed']
ERROR_KEYWORDS = ['corrupt', 'failed', 'unable', 'critical']


def classify_log_line_severity(line: str) -> Optional[str]:
    """Return 'ERROR', 'WARNING', or None for a raw FFmpeg log line."""
    lowered = line.lower()
    if not any(keyword in lowered for keyword in ISSUE_KEYWORDS):
        return None
    return 'ERROR' if any(keyword in lowered for keyword in ERROR_KEYWORDS) else 'WARNING'


class FFmpegCheckThread(QThread):
    log_signal = pyqtSignal(str)
    error_signal = pyqtSignal(str)
    issue_signal = pyqtSignal(str, str)  # severity, message for summary
    file_progress_signal = pyqtSignal(str, str)  # file_path, status ("start", "done")
    method_progress_signal = pyqtSignal(str, str)  # method_name, status ("start", "done")

    def __init__(self, files, check_methods):
        super().__init__()
        self.files = files
        self.check_methods = check_methods
        # Use cross-platform FFmpeg path detection
        self.ffmpeg_path, self.ffprobe_path = get_ffmpeg_paths()
        self.collected_log = []
        self.errors_found = set()
        self.detailed_errors = []
        self.method_issues = {}  # Track which methods have issues
        self.statistics = {}
        self.stop_requested = False  # Flag for graceful stopping

    def request_stop(self):
        """Request the thread to stop gracefully"""
        self.stop_requested = True

    def run(self):
        # Reset method issues tracking for new run
        self.method_issues = {}
        
        # First validate all files
        valid_files = []
        invalid_files = []
        
        for file in self.files:
            if is_valid_file_path(file):
                valid_files.append(file)
            else:
                reason = get_invalid_path_reason(file)
                invalid_files.append((file, reason))
                
        # Report invalid files
        for file, reason in invalid_files:
            self.log_signal.emit(f'❌ SKIPPED: {file}')
            self.log_signal.emit(f'   Reason: {reason}')
            self.error_signal.emit(f'Invalid file path: {file} - {reason}')
            
        for file in valid_files:
            # Check for stop request
            if self.stop_requested:
                self.log_signal.emit('🛑 Processing stopped by user request.')
                break
            
            # Signal that we're starting this file
            self.file_progress_signal.emit(file, "start")
            # Add clear section separator for the file
            separator = "=" * 80
            self.log_signal.emit(f"\n{separator}")
            self.log_signal.emit(f"CHECKING FILE: {file}")
            self.log_signal.emit(f"{separator}\n")
            self.log_signal.emit(f'Checking: {file}')

            # Run selected check methods
            for method, enabled in self.check_methods.items():
                if not enabled:
                    continue
                
                # Check for stop request before each method
                if self.stop_requested:
                    self.log_signal.emit('🛑 Processing stopped by user request.')
                    # Signal that we're done with current file (interrupted)
                    self.file_progress_signal.emit(file, "done")
                    return
                    
                # Add clear section separator for the method
                separator = "=" * 60
                self.log_signal.emit(f"\n{separator}")
                self.log_signal.emit(f"STARTING {method.upper()} CHECK")
                self.log_signal.emit(f"{separator}\n")
                self.log_signal.emit(f'  Running {method} check...')
                self.method_progress_signal.emit(method, "start")
                
                def emit_log(line):
                    self.log_signal.emit(f'    {line}')
                    self.collected_log.append(line)
                    severity = classify_log_line_severity(line)
                    if severity is not None:
                        err = line.strip()
                        if err not in self.errors_found:
                            self.errors_found.add(err)
                            self.error_signal.emit(err)
                            issue_msg = f'[{method}] {err}'
                            self.issue_signal.emit(severity, issue_msg)
                            self.method_issues.setdefault(method, []).append(issue_msg)

                try:
                    # Use the enhanced check_video_file function
                    result = check_video_file(file, self.ffmpeg_path, method,
                                            ffprobe_path=self.ffprobe_path, log_callback=emit_log)
                    
                    # Handle both old and new return formats
                    if len(result) == 4:
                        returncode, log_content, detailed_errors, stats = result
                        self.detailed_errors.extend(detailed_errors)
                        
                        # Process detailed errors for summary with enhanced messages
                        for error in detailed_errors:
                            display_severity = 'ERROR' if error.severity in ['critical', 'major'] else 'WARNING'
                            issue_msg = f'[{method}] {error.get_detailed_message()}'
                            self.issue_signal.emit(display_severity, issue_msg)
                            self.method_issues.setdefault(method, []).append(issue_msg)
                        
                        if stats:
                            self.statistics[f'{method}_{file}'] = stats
                    else:
                        returncode, log_content = result[:2]
                    
                    if returncode == 0:
                        self.log_signal.emit(f'  ✓ OK: {method} check passed')
                        self.collected_log.append(f'OK: {method} check passed for {file}')
                        # Add RESULT line for successful check
                        self.log_signal.emit(f'RESULT: {method.upper()} CHECK: No issues found')
                    elif returncode == -1:
                        self.log_signal.emit(f'  ✗ EXCEPTION: {method} check failed')
                        self.collected_log.append(f'EXCEPTION: {method} check failed for {file}')
                        # Add RESULT line for failed check
                        self.log_signal.emit(f'RESULT: {method.upper()} CHECK: EXCEPTION occurred')
                        self.method_issues.setdefault(method, []).append(f"EXCEPTION: {method} check failed for {file}")
                    else:
                        self.log_signal.emit(f'  ⚠ ERROR: {method} check failed (code: {returncode})')
                        self.collected_log.append(f'ERROR: {method} check failed for {file}')
                        # Add RESULT line for failed check
                        self.log_signal.emit(f'RESULT: {method.upper()} CHECK: Issues detected')
                        self.method_issues.setdefault(method, []).append(f"ERROR: {method} check failed (code: {returncode}) for {file}")

                except Exception as e:
                    self.log_signal.emit(f'  ✗ EXCEPTION: {method} check crashed: {str(e)}')
                    self.collected_log.append(f'EXCEPTION: {method} check crashed for {file}: {str(e)}')
                    # Add RESULT line for crashed check
                    self.log_signal.emit(f'RESULT: {method.upper()} CHECK: EXCEPTION occurred')
                    self.method_issues.setdefault(method, []).append(f"EXCEPTION: {method} check crashed: {str(e)}")
                    
                # Add separator at the end of the method
                separator = "-" * 60
                self.log_signal.emit(f"{separator}")
                self.log_signal.emit(f"FINISHED {method.upper()} CHECK")
                self.log_signal.emit(f"{separator}\n")
                self.method_progress_signal.emit(method, "done")
                    
            # Signal that we're done with this file
            self.file_progress_signal.emit(file, "done")
            
        # Emit summary with results for each method
        summary = f"\n=== ANALYSIS SUMMARY ==="
        
        # Track method results
        method_results = {}
        
        # Initialize all enabled methods as "NO ISSUES FOUND"
        for method, enabled in self.check_methods.items():
            if enabled:
                method_results[method] = "NO ISSUES FOUND"
        
        # Update method results based on tracked issues
        for method, issues in self.method_issues.items():
            has_exceptions = any("EXCEPTION" in issue for issue in issues)
            if has_exceptions:
                method_results[method] = "EXCEPTION"
            else:
                method_results[method] = "ISSUES DETECTED"
                
        # Add method results to summary
        for method, result in method_results.items():
            summary += f"\n{method.upper()}: {result}"
            
        # Add detailed error counts if any
        if self.detailed_errors:
            summary += f"\n\nTotal Issues Found: {len(self.detailed_errors)}"
            
            # Group by severity
            severity_counts = {}
            for error in self.detailed_errors:
                sev = error.severity
                severity_counts[sev] = severity_counts.get(sev, 0) + 1
                
            for sev, count in severity_counts.items():
                summary += f"\n {sev.upper()}: {count}"
        else:
            summary += f"\n\nNo issues found in any checks."
                
        self.log_signal.emit(summary)
        self.collected_log.append(summary)

class VideoIntegrityCheckerUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Video File Integrity Checker - Enhanced')
        self.setGeometry(100, 100, 1200, 600)  # Increased size for more options
        self.setAcceptDrops(True)
        self.files = []
        self.settings_page = None  # Lazily created on first "Settings" menu click
        
        # Get available check methods
        available_methods = get_available_check_methods()
        self.check_methods = {method: True for method in available_methods.keys()}
        
        self.init_ui()
        self.check_thread = None  # Fixed thread attribute name
        self.issue_count = {'warnings': 0, 'errors': 0}  # Track issue counts
        
        # Add keyboard shortcut for stop operation
        self.stop_shortcut = QShortcut(QKeySequence('Escape'), self)
        self.stop_shortcut.activated.connect(self.stop_check)
        
        # Initialize spinning animation variables
        self.spin_states = ["◐", "◓", "◑", "◒"]
        self.spin_index = 0
        self.spin_timer = QTimer()
        self.spin_timer.timeout.connect(self.update_spin_animation)
        self.active_spinners = set()

    def init_ui(self):
        self._init_menu_bar()

        # Create main horizontal layout with three columns
        main_layout = QHBoxLayout()

        # First column: Drag and drop area
        first_column = QVBoxLayout()
        self.label = QLabel('Drag and drop video files here:')
        first_column.addWidget(self.label)
        
        self.file_list = QListWidget()
        self.file_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.file_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.file_list.customContextMenuRequested.connect(self.show_file_list_context_menu)
        first_column.addWidget(self.file_list)
        
        self.import_button = QPushButton('Import Files')
        self.import_button.clicked.connect(self.import_files)
        first_column.addWidget(self.import_button)
        
        main_layout.addLayout(first_column)
        
        # Second column: Options with scroll area
        second_column = QVBoxLayout()
        
        # Add label for check methods
        options_label = QLabel('File check options:')
        second_column.addWidget(options_label)
        
        # Create scroll area for options
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        # Create widget to hold the scrollable content
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        
        # Get available methods and create checkboxes dynamically
        available_methods = get_available_check_methods()
        self.method_checkboxes = {}
        self.method_indicators = {}
        
        # Enhanced detailed descriptions to display below checkboxes
        method_descriptions = {
            'basic': 'Performs a fundamental integrity check by processing the entire video through FFmpeg without re-encoding. Detects major corruption, unreadable streams, and basic structural problems. Fast and reliable for initial validation.',
            'frame_crc': 'Validates every single frame using CRC32 checksums. Detects frame-level corruption, encoding artifacts, and data integrity issues that might not be visible during normal playback. More thorough than basic check.',
            'frame_md5': 'Calculates MD5 hash for every frame to verify pixel-perfect integrity. Detects subtle frame corruption, encoding errors, and ensures frames are bit-for-bit accurate. Most thorough frame validation method.',
            'stream_analysis': 'Performs deep analysis of video/audio streams with maximum probe duration and buffer sizes. Detects stream structure issues, codec problems, metadata inconsistencies, and timing irregularities.',
            'sync_check': 'Analyzes audio and video synchronization by examining keyframes and timing relationships. Detects A/V sync drift, timing issues, dropped frames, and playback synchronization problems.',
            'file_validation': 'Examines file at binary level - validates file headers, container format signatures (MP4/AVI/MKV), structural integrity, and detects corruption patterns. Very fast and catches fundamental file problems.',
            'quality_analysis': 'Analyzes video/audio quality issues including black screen detection, frozen/stuck frames, audio silence periods, and audio clipping/distortion. Identifies content quality problems that affect viewing experience.',
            'metadata_validation': 'Validates stream metadata consistency, timestamp accuracy (PTS/DTS), duration matching between audio/video, codec parameters, and container-level metadata integrity.'
        }
        
        for method, description in available_methods.items():
            # Create a horizontal layout for the checkbox and indicator
            method_layout = QHBoxLayout()
            
            # Create checkbox
            checkbox = QCheckBox(method.replace('_', ' ').title())
            checkbox.setChecked(True)  # Check all boxes by default
            checkbox.stateChanged.connect(lambda state, m=method: self.update_check_method(m, state))
            method_layout.addWidget(checkbox)
            self.method_checkboxes[method] = checkbox
            
            # Create spinning indicator label
            indicator = QLabel("○")  # Circle character as simple indicator
            indicator.setStyleSheet("color: #666666; font-size: 14px; margin-left: 5px;")
            indicator.setVisible(False)  # Hidden by default
            method_layout.addWidget(indicator)
            self.method_indicators[method] = indicator
            
            # Add the layout to the scroll layout
            scroll_layout.addLayout(method_layout)
            
            # Add description label below checkbox
            desc_label = QLabel(method_descriptions.get(method, description))
            desc_label.setWordWrap(True)
            desc_label.setStyleSheet("color: #666666; font-size: 10px; margin-left: 20px; margin-bottom: 8px;")
            scroll_layout.addWidget(desc_label)
        
        # Add stretch to push content to top within scroll area
        scroll_layout.addStretch()
        
        # Set the scroll widget to the scroll area
        scroll_area.setWidget(scroll_widget)
        second_column.addWidget(scroll_area)
        
        # Add buttons below scroll area
        self.check_button = QPushButton('Check Files')
        self.check_button.clicked.connect(self.start_check)
        second_column.addWidget(self.check_button)
        
        self.stop_button = QPushButton('Stop Processing')
        self.stop_button.clicked.connect(self.stop_check)
        self.stop_button.setEnabled(False)  # Disabled initially
        self.stop_button.setStyleSheet("QPushButton { background-color: #ff4444; color: white; }")
        self.stop_button.setToolTip('Stop the current checking operation (or press Escape key)')
        second_column.addWidget(self.stop_button)
        
        main_layout.addLayout(second_column)
        
        # Third column: Log output, summary, and export button
        third_column = QVBoxLayout()
        self.log_field = QTextEdit()
        self.log_field.setReadOnly(True)
        third_column.addWidget(QLabel('Log Output:'))
        third_column.addWidget(self.log_field)
        
        # Add summary section for warnings and errors
        self.summary_field = QTextEdit()
        self.summary_field.setReadOnly(True)
        self.summary_field.setMaximumHeight(150)  # Limit height to preserve space
        self.summary_label = QLabel('Issues Summary (Warnings & Errors):')
        third_column.addWidget(self.summary_label)
        third_column.addWidget(self.summary_field)
        
        # Add separate export buttons
        export_layout = QHBoxLayout()
        
        self.export_full_log_button = QPushButton('Export Full Log')
        self.export_full_log_button.clicked.connect(self.export_full_log)
        export_layout.addWidget(self.export_full_log_button)
        
        self.export_summary_button = QPushButton('Export Summary')
        self.export_summary_button.clicked.connect(self.export_summary)
        export_layout.addWidget(self.export_summary_button)
        
        third_column.addLayout(export_layout)
        
        main_layout.addLayout(third_column)
        
        # Set column widths (equal width for all columns)
        main_layout.setStretch(0, 1)  # First column
        main_layout.setStretch(1, 1)  # Second column
        main_layout.setStretch(2, 1)  # Third column
        
        # Make the file list take up all available space in the first column
        first_column.setStretchFactor(self.file_list, 1)

        central_widget = QWidget()
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)

        # Verify FFmpeg installation on startup
        self.verify_ffmpeg_on_startup()

    def _init_menu_bar(self):
        menu_bar = self.menuBar()
        settings_menu = menu_bar.addMenu('Settings')

        open_settings_action = QAction('Open Settings...', self)
        open_settings_action.triggered.connect(self.open_settings)
        settings_menu.addAction(open_settings_action)

    def open_settings(self):
        if self.settings_page is None:
            self.settings_page = SettingsPage()
        self.settings_page.show()
        self.settings_page.raise_()
        self.settings_page.activateWindow()

    def verify_ffmpeg_on_startup(self):
        """Verify FFmpeg installation and show platform info"""
        success, message = verify_ffmpeg_installation()
        if success:
            ffmpeg_path, ffprobe_path = get_ffmpeg_paths()
            from utils.platform_utils import get_platform_name
            platform_name = get_platform_name()
            self.log_field.append(f"✓ {message}")
            self.log_field.append(f"Platform: {platform_name}")
            self.log_field.append(f"FFmpeg: {ffmpeg_path}")
            self.log_field.append(f"FFprobe: {ffprobe_path}")
        else:
            self.log_field.append(f"⚠ WARNING: {message}")
            self.log_field.append("Some check methods may not work properly.")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        invalid_files = []
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            if file_path and file_path not in self.files:
                # Validate file path
                if not is_valid_file_path(file_path):
                    reason = get_invalid_path_reason(file_path)
                    invalid_files.append(f"{file_path}: {reason}")
                    continue
                    
                self.files.append(file_path)
                self.file_list.addItem(file_path)
                
        # Show error message for invalid files
        if invalid_files:
            error_msg = "The following files contain unusual characters and cannot be processed:\n\n" + "\n".join(invalid_files)
            error_msg += "\n\nThese files have been skipped."
            QMessageBox.warning(self, "Invalid File Paths", error_msg)

    def show_file_list_context_menu(self, pos: QPoint):
        menu = QMenu(self)
        remove_action = menu.addAction('Remove Selected')
        action = menu.exec(self.file_list.mapToGlobal(pos))
        if action == remove_action:
            self.remove_selected_files()

    def remove_selected_files(self):
        selected_items = self.file_list.selectedItems()
        for item in selected_items:
            row = self.file_list.row(item)
            self.file_list.takeItem(row)
            if item.text() in self.files:
                self.files.remove(item.text())

    def update_check_method(self, method, state):
        # Update the check method state based on checkbox state
        self.check_methods[method] = (state == 2)  # Qt.Checked = 2

    def import_files(self):
        # Open file dialog to select video files
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            'Select Video Files',
            '',
            'Video Files (*.mp4 *.avi *.mkv *.mov *.wmv *.flv *.webm *.m4v);;All Files (*)'
        )
        
        invalid_files = []
        for file_path in file_paths:
            if file_path and file_path not in self.files:
                # Validate file path
                if not is_valid_file_path(file_path):
                    reason = get_invalid_path_reason(file_path)
                    invalid_files.append(f"{file_path}: {reason}")
                    continue
                    
                self.files.append(file_path)
                self.file_list.addItem(file_path)
                
        # Show error message for invalid files
        if invalid_files:
            error_msg = "The following files contain unusual characters and cannot be processed:\n\n" + "\n".join(invalid_files)
            error_msg += "\n\nThese files have been skipped."
            QMessageBox.warning(self, "Invalid File Paths", error_msg)

    def start_check(self):
        if not self.files:
            self.log_field.append('No files to check.')
            return
        self.log_field.clear()
        self.summary_field.clear()  # Clear previous summary
        self.issue_count = {'warnings': 0, 'errors': 0}  # Reset counters
        
        # Enable stop button, disable start button
        self.check_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        
        self.check_thread = FFmpegCheckThread(self.files, self.check_methods)
        self.check_thread.log_signal.connect(self.log_field.append)
        self.check_thread.issue_signal.connect(self.add_issue_to_summary)
        self.check_thread.file_progress_signal.connect(self.update_file_progress)
        self.check_thread.method_progress_signal.connect(self.update_method_progress)
        self.check_thread.finished.connect(self.on_check_finished)
        self.check_thread.start()

    def stop_check(self):
        """Stop the ongoing check operation"""
        if not (self.check_thread and self.check_thread.isRunning()):
            return  # No operation to stop
            
        self.log_field.append('\n🛑 Stopping operation... Please wait for current operation to complete.')
        
        # First try graceful stop
        self.check_thread.request_stop()
        
        # Give it some time to stop gracefully
        if not self.check_thread.wait(3000):  # Wait 3 seconds
            self.log_field.append('⚠️ Force stopping operation...')
            self.check_thread.terminate()
            self.check_thread.wait(2000)  # Wait 2 more seconds
        
        self.log_field.append('✅ Operation stopped by user.')
        self.on_check_finished()  # Reset UI state

    def add_issue_to_summary(self, severity: str, message: str):
        """Add an issue to the summary list with appropriate formatting"""
        # Create formatted item with severity icon
        if severity == 'ERROR':
            icon = '🔴'
            self.issue_count['errors'] += 1
        else:  # WARNING
            icon = '⚠️'
            self.issue_count['warnings'] += 1
            
        formatted_message = f'{icon} {severity}: {message}'
        self.summary_field.append(formatted_message)
        
        # Auto-scroll to latest issue (QTextEdit automatically scrolls to bottom with append)
        
        # Update summary label with counts
        total_issues = self.issue_count['errors'] + self.issue_count['warnings']
        summary_text = f'Issues Summary ({total_issues} total: {self.issue_count["errors"]} errors, {self.issue_count["warnings"]} warnings):'
        self.summary_label.setText(summary_text)

    def update_file_progress(self, file_path, status):
        """Update visual indicator for currently processing file"""
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            if item is None:
                continue
                
            item_text = item.text()
            
            # Remove any existing indicators
            if item_text.startswith('🔄 ') or item_text.startswith('✅ '):
                item_text = item_text[2:]  # Remove the first 2 characters (emoji + space)
            
            # Check if this is the current file
            if item_text == file_path:
                if status == "start":
                    item.setText(f'🔄 {file_path}')  # Processing indicator
                elif status == "done":
                    item.setText(f'✅ {file_path}')  # Completed indicator
            else:
                # Reset text for other files (remove indicators)
                item.setText(item_text)


    def update_method_progress(self, method_name, status):
        """Update visual indicator for currently processing method"""
        if method_name in self.method_indicators:
            indicator = self.method_indicators[method_name]
            if status == "start":
                indicator.setText(self.spin_states[0])  # Set initial spin character
                indicator.setVisible(True)
                self.active_spinners.add(method_name)
                # Start animation timer if not already running
                if not self.spin_timer.isActive():
                    self.spin_timer.start(100)  # Update every 100ms
            elif status == "done":
                indicator.setVisible(False)
                self.active_spinners.discard(method_name)
                # Stop animation timer if no active spinners
                if not self.active_spinners and self.spin_timer.isActive():
                    self.spin_timer.stop()

    def update_spin_animation(self):
        """Update the spinning animation for active indicators"""
        self.spin_index = (self.spin_index + 1) % len(self.spin_states)
        spin_char = self.spin_states[self.spin_index]
        
        for method_name in self.active_spinners:
            if method_name in self.method_indicators:
                self.method_indicators[method_name].setText(spin_char)

    def on_check_finished(self):
        if self.check_thread:
            self.collected_log = self.check_thread.collected_log
        else:
            self.collected_log = []
            
        # Stop spin animation timer and hide all indicators
        if self.spin_timer.isActive():
            self.spin_timer.stop()
        self.active_spinners.clear()
        for indicator in self.method_indicators.values():
            indicator.setVisible(False)
            
        # Reset button states
        self.check_button.setEnabled(True)
        self.stop_button.setEnabled(False)

    def export_full_log(self):
        """Export the complete log output"""
        log_content = self.log_field.toPlainText()
        if not log_content.strip():
            self.log_field.append('No log to export.')
            return
        file_path, _ = QFileDialog.getSaveFileName(self, 'Save Full Log', '', 'Text Files (*.txt);;All Files (*)')
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(log_content)
                self.log_field.append(f'Full log exported to {file_path}')
            except Exception as e:
                self.log_field.append(f'Failed to export full log: {e}')

    def export_summary(self):
        """Export only the issues summary"""
        summary_content = self.summary_field.toPlainText()
        if not summary_content.strip():
            self.log_field.append('No summary to export.')
            return
        file_path, _ = QFileDialog.getSaveFileName(self, 'Save Summary', '', 'Text Files (*.txt);;All Files (*)')
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(summary_content)
                self.log_field.append(f'Summary exported to {file_path}')
            except Exception as e:
                self.log_field.append(f'Failed to export summary: {e}')

    def export_log(self):
        """Legacy method - now redirects to full log export"""
        self.export_full_log()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = VideoIntegrityCheckerUI()
    window.show()
    sys.exit(app.exec())
