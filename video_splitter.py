import sys
import os
import subprocess
import threading
from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, 
                             QWidget, QPushButton, QLabel, QSlider, QListWidget, 
                             QFileDialog, QMessageBox, QProgressBar, QSpinBox,
                             QGroupBox, QGridLayout, QCheckBox, QListWidgetItem, QTabWidget, QSizePolicy)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal, QEvent
from PyQt5.QtGui import QPixmap, QFont
import tempfile
import json
import re

class VideoProcessor(QThread):
    progress = pyqtSignal(int)
    finished = pyqtSignal(str)
    error = pyqtSignal(str)
    
    def __init__(self, video_path, splits, output_dir):
        super().__init__()
        self.video_path = video_path
        self.splits = splits
        self.output_dir = output_dir
    
    def run(self):
        try:
            base_name = os.path.splitext(os.path.basename(self.video_path))[0]
            
            for i, (start, end) in enumerate(self.splits):
                output_path = os.path.join(self.output_dir, f"{base_name}_part_{i+1:03d}.mp4")
                duration = end - start
                
                cmd = [
                    'ffmpeg', '-y', '-i', self.video_path,
                    '-ss', str(start), '-t', str(duration),
                    '-c', 'copy', output_path
                ]
                
                process = subprocess.run(cmd, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
                if process.returncode != 0:
                    self.error.emit(f"Error processing segment {i+1}: {process.stderr}")
                    return
                
                progress = int((i + 1) / len(self.splits) * 100)
                self.progress.emit(progress)
            
            self.finished.emit(f"Successfully created {len(self.splits)} video segments")
        except Exception as e:
            self.error.emit(f"Processing error: {str(e)}")

class SceneDetector(QThread):
    scene_detected = pyqtSignal(float)
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, video_path, threshold):
        super().__init__()
        self.video_path = video_path
        self.threshold = threshold

    def run(self):
        try:
            # Use the scenedetect filter from ffmpeg. Scene change detected when average difference between frames exceeds threshold.
            cmd = [
                'ffmpeg', '-i', self.video_path,
                '-filter:v', f"select='gt(scene,{self.threshold})',showinfo",
                '-f', 'null', '-'
            ]
            
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
            
            # Read stderr line by line to get progress and scene detections
            for line in iter(process.stderr.readline, ''):
                if "Parsed_showinfo_" in line:
                    # Example line: [Parsed_showinfo_0 @ 0000021319717540] n:  126 pts:    5292 pos:  1605333 bytes t:0.046927 s
                    # This line format is from the showinfo filter, not scene change detection
                    pass # We are interested in lines from scene detect filter
                elif "scene_change_score" in line:
                    # Example line from scenedetect: [Parsed_select_0 @ 0x...] n:126 pts:5292 t:0.046927 scene_change_score: 0.123456
                    # Look for lines that indicate scene changes based on the score.
                    # ffmpeg's scenedetect filter will output a 'scene_score' if a scene change is detected.
                    # The exact output format can vary, but typically it would be a line like this:
                    # [Parsed_select_0 @ 0x...] n:126 pts:5292 t:0.046927 scene_change_score: 0.123456

                    # Extract time from line
                    try:
                        # Use regex to find the time 't:X.XXX'
                        match = re.search(r't:([\d.]+)', line)
                        if match:
                            scene_time = float(match.group(1))
                            self.scene_detected.emit(scene_time)
                    except ValueError:
                        continue # Skip if time cannot be parsed

            process.stderr.close()
            process.wait()

            if process.returncode != 0:
                self.error.emit(f"Scene detection error: {process.stderr.read()}")
                return

            self.finished.emit()
        except Exception as e:
            self.error.emit(f"Scene detection process error: {str(e)}")

class AspectRatioWidget(QWidget):
    def __init__(self, content_widget, aspect_ratio=16/9, parent=None):
        super().__init__(parent)
        self.content_widget = content_widget
        self.aspect_ratio = aspect_ratio
        self.main_layout = QVBoxLayout(self)
        self.main_layout.addWidget(self.content_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def heightForWidth(self, width):
        if self.aspect_ratio == 0: return self.content_widget.height()
        return int(width / self.aspect_ratio)

    def sizeHint(self):
        return self.minimumSizeHint()

    def resizeEvent(self, event):
        size = event.size()
        new_height = self.heightForWidth(size.width())
        if new_height > size.height():
            new_width = self.widthForHeight(size.height())
            self.content_widget.setFixedSize(new_width, size.height())
        else:
            self.content_widget.setFixedSize(size.width(), new_height)
        super().resizeEvent(event)

    def widthForHeight(self, height):
        if self.aspect_ratio == 0: return self.content_widget.width()
        return int(height * self.aspect_ratio)

class VideoSplitter(QMainWindow):
    def __init__(self):
        super().__init__()
        self.video_path = None
        self.video_duration = 0.0
        self.current_time = 0.0
        self.splits = []
        self.temp_dir = tempfile.mkdtemp()
        self.fps = 30  # Default FPS
        self.video_width = 0 # Initialize video width
        self.video_height = 0 # Initialize video height
        
        # New attributes for auto-split
        self.auto_split_enabled = False
        self.max_segment_duration = 28.5 # Default max segment duration
        self.min_segment_duration = 9.9 # Default min segment duration
        
        # New attributes for scene detection
        self.scene_detection_threshold = 0.4 # Default scene detection threshold
        self.scene_detector = None # To hold the scene detection thread

        self.init_ui()
        
    def init_ui(self):
        self.setWindowTitle("Video Splitter")
        self.showMaximized()
        
        # Install event filter for keyboard shortcuts
        self.installEventFilter(self)
        
        # Apply dark mode stylesheet
        self.setStyleSheet("""
            QWidget {
                background-color: #2b2b2b; /* Dark background */
                color: #ffffff; /* White text */
                font-family: "Segoe UI", sans-serif;
            }
            QMainWindow {
                background-color: #2b2b2b;
            }
            QGroupBox {
                background-color: #3c3c3c; /* Slightly lighter dark for groups */
                border: 1px solid #5a5a5a;
                border-radius: 5px;
                margin-top: 1ex; /* Give space for the title */
                font-size: 10pt;
                font-weight: bold;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top center; /* Position at top center */
                padding: 0 3px;
                background-color: #3c3c3c;
                color: #87ceeb; /* Sky Blue for titles */
            }
            QLabel {
                color: #ffffff;
            }
            QPushButton {
                background-color: #4682b4; /* Steel Blue */
                color: #ffffff;
                border: none;
                padding: 8px 16px;
                border-radius: 5px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #5b9bd5; /* Lighter Steel Blue on hover */
            }
            QPushButton:pressed {
                background-color: #3a6d9b; /* Darker Steel Blue on pressed */
            }
            QPushButton:disabled {
                background-color: #5a5a5a;
                color: #cccccc;
            }
            QSlider::groove:horizontal {
                border: 1px solid #5a5a5a;
                height: 8px; /* the groove height */
                background: #3c3c3c;
                margin: 2px 0;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #87ceeb; /* Sky Blue handle */
                border: 1px solid #87ceeb;
                width: 18px;
                margin: -5px 0; /* handle is 18x18 when groove is 8px */
                border-radius: 9px;
            }
            QSlider::sub-page:horizontal {
                background: #4682b4; /* Steel Blue for filled part */
                border: 1px solid #4682b4;
                height: 8px;
                border-radius: 4px;
            }
            QListWidget {
                background-color: #3c3c3c;
                border: 1px solid #5a5a5a;
                border-radius: 5px;
                color: #ffffff;
                alternate-background-color: #444444;
            }
            QListWidget::item {
                padding: 5px;
            }
            QListWidget::item:selected {
                background-color: #4682b4; /* Steel Blue for selected item */
                color: #ffffff;
            }
            QProgressBar {
                border: 1px solid #5a5a5a;
                border-radius: 5px;
                text-align: center;
                background-color: #3c3c3c;
                color: #ffffff;
            }
            QProgressBar::chunk {
                background-color: #4682b4; /* Steel Blue for progress */
                width: 20px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
            }
            QCheckBox::indicator:unchecked {
                background-color: #5a5a5a;
                border: 1px solid #888888;
                border-radius: 3px;
            }
            QCheckBox::indicator:checked {
                background-color: #4682b4; /* Steel Blue for checked */
                border: 1px solid #4682b4;
                border-radius: 3px;
                image: url(data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAcAAAAHCAYAAACzXPxXAAAAAXNSR0IArs4c6QAAADFJREFUGFcBwAEGAACjKx5OAAAAAElFTkSuQmCC); /* A tiny white checkmark if you have one */
            }
            QTabWidget::pane {
                border: 1px solid #5a5a5a;
                background-color: #3c3c3c;
                border-radius: 5px;
            }
            QTabBar::tab {
                background: #3c3c3c;
                border: 1px solid #5a5a5a;
                border-bottom-color: #3c3c3c; /* same as pane color */
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                min-width: 8ex;
                padding: 5px;
                color: #ffffff;
            }
            QTabBar::tab:selected {
                background: #4682b4; /* Steel Blue for selected tab */
                border-color: #4682b4;
                border-bottom-color: #4682b4; /* selected tab has same border color as pane */
            }
            QTabBar::tab:hover {
                background: #5b9bd5; /* Lighter Steel Blue on hover */
            }
        """)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)

        # --- Video & Splits Tab --- #
        video_splits_tab = QWidget()
        video_splits_layout = QVBoxLayout(video_splits_tab)
        self.tab_widget.addTab(video_splits_tab, "Video & Splits")

        # File selection
        file_group = QGroupBox("Video File")
        file_layout = QHBoxLayout(file_group)
        
        self.file_label = QLabel("No file selected")
        self.file_button = QPushButton("Select Video")
        self.file_button.clicked.connect(self.select_file)
        
        file_layout.addWidget(self.file_label)
        file_layout.addWidget(self.file_button)
        video_splits_layout.addWidget(file_group)
        
        # Video preview
        preview_group = QGroupBox("Preview")
        preview_layout = QVBoxLayout(preview_group)
        
        self.preview_label = QLabel("No video loaded")
        self.preview_label.setStyleSheet("border: 1px solid #5a5a5a; background-color: black;")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setScaledContents(True)
        
        self.aspect_ratio_widget = AspectRatioWidget(self.preview_label) # Wrap label in aspect ratio widget
        preview_layout.addWidget(self.aspect_ratio_widget)
        
        # Time display
        time_layout = QHBoxLayout()
        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setFont(QFont("Arial", 12, QFont.Bold))
        time_layout.addWidget(self.time_label)
        time_layout.addStretch()
        preview_layout.addLayout(time_layout)
        
        video_splits_layout.addWidget(preview_group, 1) # Add stretch factor to make it adjustable
        
        # Timeline controls
        timeline_group = QGroupBox("Timeline")
        timeline_layout = QVBoxLayout(timeline_group)
        
        self.timeline_slider = QSlider(Qt.Horizontal)
        self.timeline_slider.setEnabled(False)
        self.timeline_slider.valueChanged.connect(self.on_timeline_change)
        timeline_layout.addWidget(self.timeline_slider)
        
        # Frame navigation
        frame_layout = QHBoxLayout()
        self.frame_back_10 = QPushButton("<<10s")
        self.frame_back_1 = QPushButton("<1s")
        self.frame_forward_1 = QPushButton("1s>")
        self.frame_forward_10 = QPushButton("10s>>")
        
        self.frame_next_frame = QPushButton("Next Frame")
        self.frame_prev_frame = QPushButton("Prev Frame")
        
        self.frame_back_10.clicked.connect(lambda: self.seek_relative(-10))
        self.frame_back_1.clicked.connect(lambda: self.seek_relative(-1))
        self.frame_forward_1.clicked.connect(lambda: self.seek_relative(1))
        self.frame_forward_10.clicked.connect(lambda: self.seek_relative(10))
        
        self.frame_next_frame.clicked.connect(self.seek_next_frame)
        self.frame_prev_frame.clicked.connect(self.seek_prev_frame)
        
        frame_layout.addWidget(self.frame_back_10)
        frame_layout.addWidget(self.frame_back_1)
        frame_layout.addStretch()
        frame_layout.addWidget(self.frame_prev_frame)
        frame_layout.addWidget(self.frame_next_frame)
        frame_layout.addWidget(self.frame_forward_1)
        frame_layout.addWidget(self.frame_forward_10)
        
        timeline_layout.addLayout(frame_layout)
        video_splits_layout.addWidget(timeline_group)
        
        # Split controls
        split_group = QGroupBox("Split Points")
        split_layout = QGridLayout(split_group)
        
        self.add_split_button = QPushButton("Add Split Point")
        self.add_split_button.clicked.connect(self.add_split)
        self.add_split_button.setEnabled(False)
        
        self.clear_splits_button = QPushButton("Clear All Splits")
        self.clear_splits_button.clicked.connect(self.clear_splits)
        
        self.splits_list = QListWidget()
        self.splits_list.itemDoubleClicked.connect(self.jump_to_split)
        
        split_layout.addWidget(self.add_split_button, 0, 0)
        split_layout.addWidget(self.clear_splits_button, 0, 1)
        split_layout.addWidget(QLabel("Split Points (double-click to jump):"), 1, 0, 1, 2)
        split_layout.addWidget(self.splits_list, 2, 0, 1, 2)
        split_layout.setRowStretch(2, 1)
        
        video_splits_layout.addWidget(split_group)

        # --- Settings Tab --- #
        settings_tab = QWidget()
        settings_layout = QVBoxLayout(settings_tab)
        self.tab_widget.addTab(settings_tab, "Settings")
        
        # Auto Split controls
        auto_split_group = QGroupBox("Auto Split Options")
        auto_split_layout = QVBoxLayout(auto_split_group)

        self.auto_split_checkbox = QCheckBox("Auto Split Segments Longer Than Max Duration")
        self.auto_split_checkbox.setChecked(False)
        self.auto_split_checkbox.stateChanged.connect(self.toggle_auto_split_controls)
        auto_split_layout.addWidget(self.auto_split_checkbox)

        max_duration_layout = QHBoxLayout()
        max_duration_label_prefix = QLabel("Max Segment Duration (seconds):")
        self.max_segment_duration_label = QLabel(f"{self.max_segment_duration:.1f}")
        self.max_segment_duration_label.setFixedWidth(50)

        self.max_segment_duration_slider = QSlider(Qt.Horizontal)
        self.max_segment_duration_slider.setMinimum(100) # 10.0 seconds
        self.max_segment_duration_slider.setMaximum(3000) # 300.0 seconds
        self.max_segment_duration_slider.setValue(int(self.max_segment_duration * 100)) # Default 28.5 seconds
        self.max_segment_duration_slider.setEnabled(False) # Initially disabled
        self.max_segment_duration_label.setEnabled(False) # Initially disabled
        self.max_segment_duration_slider.valueChanged.connect(self.update_max_segment_duration_label)

        max_duration_layout.addWidget(max_duration_label_prefix)
        max_duration_layout.addWidget(self.max_segment_duration_slider)
        max_duration_layout.addWidget(self.max_segment_duration_label)
        auto_split_layout.addLayout(max_duration_layout)
        
        min_duration_layout = QHBoxLayout()
        min_duration_label_prefix = QLabel("Min Segment Duration (seconds):")
        self.min_segment_duration_label = QLabel(f"{self.min_segment_duration:.1f}")
        self.min_segment_duration_label.setFixedWidth(50)

        self.min_segment_duration_slider = QSlider(Qt.Horizontal)
        self.min_segment_duration_slider.setMinimum(10) # 1.0 seconds
        self.min_segment_duration_slider.setMaximum(2900) # Max 29.0 seconds, just below max_duration default
        self.min_segment_duration_slider.setValue(int(self.min_segment_duration * 100))
        self.min_segment_duration_slider.setEnabled(False)
        self.min_segment_duration_label.setEnabled(False)
        self.min_segment_duration_slider.valueChanged.connect(self.update_min_segment_duration_label)

        min_duration_layout.addWidget(min_duration_label_prefix)
        min_duration_layout.addWidget(self.min_segment_duration_slider)
        min_duration_layout.addWidget(self.min_segment_duration_label)
        auto_split_layout.addLayout(min_duration_layout)
        
        settings_layout.addWidget(auto_split_group)
        
        # Scene Detection controls
        scene_detection_group = QGroupBox("Scene Detection Options")
        scene_detection_layout = QVBoxLayout(scene_detection_group)

        self.detect_scenes_button = QPushButton("Detect Scenes (might take a while)")
        self.detect_scenes_button.clicked.connect(self.detect_scenes)
        self.detect_scenes_button.setEnabled(False) # Enable after video loaded
        scene_detection_layout.addWidget(self.detect_scenes_button)

        threshold_layout = QHBoxLayout()
        threshold_label_prefix = QLabel("Detection Threshold:")
        self.scene_threshold_label = QLabel(f"{self.scene_detection_threshold:.1f}")
        self.scene_threshold_label.setFixedWidth(50)

        self.scene_threshold_slider = QSlider(Qt.Horizontal)
        self.scene_threshold_slider.setMinimum(10) # 0.1
        self.scene_threshold_slider.setMaximum(100) # 1.0
        self.scene_threshold_slider.setValue(int(self.scene_detection_threshold * 100))
        self.scene_threshold_slider.valueChanged.connect(self.update_scene_threshold_label)
        
        threshold_layout.addWidget(threshold_label_prefix)
        threshold_layout.addWidget(self.scene_threshold_slider)
        threshold_layout.addWidget(self.scene_threshold_label)
        scene_detection_layout.addLayout(threshold_layout)
        
        settings_layout.addWidget(scene_detection_group)
        settings_layout.addStretch(1)

        # --- Project Controls --- #
        project_group = QGroupBox("Project")
        project_layout = QHBoxLayout(project_group)

        self.save_project_button = QPushButton("Save Project")
        self.save_project_button.clicked.connect(self.save_project)
        self.save_project_button.setEnabled(False) # Disable until video is loaded

        self.load_project_button = QPushButton("Load Project")
        self.load_project_button.clicked.connect(self.load_project)

        project_layout.addWidget(self.save_project_button)
        project_layout.addWidget(self.load_project_button)
        main_layout.addWidget(project_group)

        # --- Export Controls (always visible) --- #
        export_group = QGroupBox("Export")
        export_layout = QHBoxLayout(export_group)
        
        self.export_button = QPushButton("Export Video Segments")
        self.export_button.clicked.connect(self.export_segments)
        self.export_button.setEnabled(False)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        
        export_layout.addWidget(self.export_button)
        export_layout.addWidget(self.progress_bar)
        
        main_layout.addWidget(export_group)
        
    def select_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Video File", "", 
            "Video Files (*.mp4 *.avi *.mov *.mkv *.wmv *.flv *.webm);;All Files (*)"
        )
        
        if file_path:
            self.load_video(file_path)
    
    def load_video(self, file_path):
        self.video_path = file_path
        self.file_label.setText(os.path.basename(file_path))
        
        # Clear existing splits when a new video is loaded
        self.clear_splits()
        
        # Get video info using ffprobe
        try:
            cmd = [
                'ffprobe', '-v', 'quiet', '-print_format', 'json', 
                '-show_format', '-show_streams', file_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
            video_info = json.loads(result.stdout)
            
            # Find video stream
            video_stream = None
            for stream in video_info['streams']:
                if stream['codec_type'] == 'video':
                    video_stream = stream
                    break
            
            if video_stream:
                self.video_duration = float(video_info['format']['duration'])
                self.fps = eval(video_stream.get('r_frame_rate', '30/1'))
                self.video_width = video_stream.get('width', 0)
                self.video_height = video_stream.get('height', 0)
                
                if self.video_height > 0:
                    self.aspect_ratio_widget.aspect_ratio = self.video_width / self.video_height
                else:
                    self.aspect_ratio_widget.aspect_ratio = 16/9 # Default to 16:9 if height is zero

                # Setup timeline
                self.timeline_slider.setMaximum(int(self.video_duration * 1000))
                self.timeline_slider.setEnabled(True)
                self.add_split_button.setEnabled(True)
                
                # Ensure layout is updated before loading first frame
                self.aspect_ratio_widget.updateGeometry()
                self.aspect_ratio_widget.parentWidget().updateGeometry()
                QApplication.processEvents() # Process events to ensure layout calculation

                # Load first frame
                self.seek_to_time(0)
                self.aspect_ratio_widget.resize(self.aspect_ratio_widget.size()) # Trigger resize for proper scaling
                
                # Enable save project button after successful video load
                self.save_project_button.setEnabled(True)
                
                # Enable scene detection button after successful video load
                self.detect_scenes_button.setEnabled(True)
                
            else:
                QMessageBox.warning(self, "Error", "No video stream found in file")
                
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load video: {str(e)}")
    
    def seek_to_time(self, time_seconds):
        if not self.video_path:
            return
            
        self.current_time = max(0.0, min(time_seconds, self.video_duration))
        
        # Extract frame at current time
        frame_path = os.path.join(self.temp_dir, "current_frame.jpg")
        cmd = [
            'ffmpeg', '-y', '-ss', str(self.current_time), '-i', self.video_path,
            '-vframes', '1', '-q:v', '2', frame_path
        ]
        
        try:
            subprocess.run(cmd, capture_output=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
            
            # Load and display frame
            pixmap = QPixmap(frame_path)
            if not pixmap.isNull():
                self.preview_label.setPixmap(pixmap)
            
            # Update time display
            current_str = self.format_time(self.current_time)
            total_str = self.format_time(self.video_duration)
            self.time_label.setText(f"{current_str} / {total_str}")
            
            # Update slider (without triggering signal)
            self.timeline_slider.blockSignals(True)
            self.timeline_slider.setValue(int(self.current_time * 1000))
            self.timeline_slider.blockSignals(False)
            
        except subprocess.CalledProcessError:
            pass  # Failed to extract frame, continue anyway
    
    def on_timeline_change(self, value):
        self.seek_to_time(value / 1000.0)
    
    def seek_relative(self, seconds):
        new_time = self.current_time + seconds
        self.seek_to_time(new_time)
    
    def seek_next_frame(self):
        if self.video_path and self.fps > 0:
            frame_duration = 1.0 / self.fps
            new_time = self.current_time + frame_duration
            self.seek_to_time(new_time)

    def seek_prev_frame(self):
        if self.video_path and self.fps > 0:
            frame_duration = 1.0 / self.fps
            new_time = self.current_time - frame_duration
            self.seek_to_time(new_time)

    def format_time(self, seconds):
        total_milliseconds = int(seconds * 1000)
        mins = total_milliseconds // 60000
        secs = (total_milliseconds % 60000) // 1000
        msecs = total_milliseconds % 1000
        return f"{mins:02d}:{secs:02d}.{msecs:03d}"
    
    def add_split(self):
        if self.current_time not in self.splits:
            self.splits.append(self.current_time)
            self.splits.sort()
            self.update_splits_list()
            
            if len(self.splits) >= 1:
                self.export_button.setEnabled(True)
    
    def clear_splits(self):
        self.splits.clear()
        self.update_splits_list()
        self.export_button.setEnabled(False)
    
    def update_splits_list(self):
        self.splits_list.clear()
        for i, split_time in enumerate(self.splits):
            time_str = self.format_time(split_time)
            
            # Create a widget for each item to hold label and button
            item_widget = QWidget()
            item_layout = QHBoxLayout(item_widget)
            
            label = QLabel(f"Split {i+1}: {time_str}")
            remove_button = QPushButton("x")
            remove_button.setFixedSize(20, 20) # Make button small
            
            # Connect button to remove_split method with the current index
            remove_button.clicked.connect(lambda checked, index=i: self.remove_split(index))
            
            item_layout.addWidget(label)
            item_layout.addStretch()
            item_layout.addWidget(remove_button)
            item_layout.setContentsMargins(0, 0, 0, 0) # Remove margins for compact look
            
            list_item = QListWidgetItem(self.splits_list)
            list_item.setSizeHint(item_widget.sizeHint())
            self.splits_list.addItem(list_item)
            self.splits_list.setItemWidget(list_item, item_widget)
    
    def remove_split(self, index):
        if 0 <= index < len(self.splits):
            del self.splits[index]
            self.splits.sort() # Re-sort to maintain order if needed, though not strictly necessary after deletion
            self.update_splits_list()
            # Disable export button if no splits remain
            if not self.splits:
                self.export_button.setEnabled(False)
    
    def jump_to_split(self, item):
        row = self.splits_list.row(item)
        if 0 <= row < len(self.splits):
            self.seek_to_time(self.splits[row])
    
    def toggle_auto_split_controls(self, state):
        self.auto_split_enabled = bool(state)
        self.max_segment_duration_slider.setEnabled(self.auto_split_enabled)
        self.max_segment_duration_label.setEnabled(self.auto_split_enabled)
        self.min_segment_duration_slider.setEnabled(self.auto_split_enabled)
        self.min_segment_duration_label.setEnabled(self.auto_split_enabled)
    
    def update_max_segment_duration_label(self, value):
        self.max_segment_duration = value / 100.0
        self.max_segment_duration_label.setText(f"{self.max_segment_duration:.1f}")
        # Ensure max is not less than min
        if self.max_segment_duration < self.min_segment_duration:
            self.min_segment_duration = self.max_segment_duration
            self.min_segment_duration_slider.setValue(int(self.min_segment_duration * 100))

    def update_min_segment_duration_label(self, value):
        self.min_segment_duration = value / 100.0
        self.min_segment_duration_label.setText(f"{self.min_segment_duration:.1f}")
        # Ensure min is not greater than max
        if self.min_segment_duration > self.max_segment_duration:
            self.max_segment_duration = self.min_segment_duration
            self.max_segment_duration_slider.setValue(int(self.max_segment_duration * 100))

    def update_scene_threshold_label(self, value):
        self.scene_detection_threshold = value / 100.0
        self.scene_threshold_label.setText(f"{self.scene_detection_threshold:.1f}")

    def detect_scenes(self):
        if not self.video_path:
            QMessageBox.warning(self, "Warning", "No video loaded to detect scenes.")
            return
        
        self.detect_scenes_button.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0) # Scene detection doesn't have granular progress, so reset
        self.progress_bar.setFormat("Detecting scenes...")

        if self.scene_detector and self.scene_detector.isRunning():
            self.scene_detector.terminate()
            self.scene_detector.wait()

        self.scene_detector = SceneDetector(self.video_path, self.scene_detection_threshold)
        self.scene_detector.scene_detected.connect(self.add_split_from_detection)
        self.scene_detector.finished.connect(self.on_scene_detection_finished)
        self.scene_detector.error.connect(self.on_scene_detection_error)
        self.scene_detector.start()

    def add_split_from_detection(self, time_seconds):
        # Add detected scene change as a split point, avoiding duplicates
        if time_seconds not in self.splits:
            self.splits.append(time_seconds)
            self.splits.sort()
            self.update_splits_list()
            # Enable export button if at least one split is added via detection
            if len(self.splits) >= 1:
                self.export_button.setEnabled(True)

    def on_scene_detection_finished(self):
        self.progress_bar.setVisible(False)
        self.progress_bar.setFormat("%p%") # Reset format
        self.detect_scenes_button.setEnabled(True)
        QMessageBox.information(self, "Scene Detection", "Scene detection completed.")
    
    def on_scene_detection_error(self, error_message):
        self.progress_bar.setVisible(False)
        self.progress_bar.setFormat("%p%") # Reset format
        self.detect_scenes_button.setEnabled(True)
        QMessageBox.critical(self, "Scene Detection Error", error_message)

    def _apply_auto_split(self, segments, max_duration, min_duration):
        if max_duration <= 0 or min_duration <= 0 or min_duration > max_duration:
            QMessageBox.warning(self, "Warning", "Invalid auto-split duration settings. Please ensure Min Duration > 0, Max Duration > 0, and Min Duration <= Max Duration.")
            return segments

        new_segments = []
        for start, end in segments:
            duration = end - start
            if duration <= max_duration:
                new_segments.append((start, end))
                continue

            # If duration > max_duration, we need to split
            # Calculate initial number of splits based on max_duration
            num_splits_candidate = int(duration / max_duration)
            remainder_duration = duration % max_duration

            optimal_num_segments = -1
            if remainder_duration == 0: # Perfectly divisible
                optimal_num_segments = num_splits_candidate
            elif remainder_duration >= min_duration: # Last segment is valid
                optimal_num_segments = num_splits_candidate + 1
            else: # Last segment is too short, need to re-distribute
                # Find the smallest number of segments 'n' such that duration/n is within [min_duration, max_duration]
                # Iterate from num_splits_candidate upwards to ensure max_duration is respected as much as possible
                found_optimal = False
                for n in range(num_splits_candidate, int(duration / min_duration) + 2): # Add +2 for safety margin
                    if n == 0: continue
                    avg_segment_duration = duration / n
                    if min_duration <= avg_segment_duration <= max_duration:
                        optimal_num_segments = n
                        found_optimal = True
                        break
                
                if not found_optimal: # Fallback if no ideal split found (should not happen with valid min/max)
                    # This fallback should ideally maintain validity, prioritizing max_duration
                    # if min_duration constraint can't be met, user should be warned.
                    # For now, it will simply take the current num_splits_candidate and add 1 if there's a remainder.
                    QMessageBox.warning(self, "Warning", f"Could not find an ideal auto-split for a segment. Splitting by max duration.")
                    optimal_num_segments = num_splits_candidate + (1 if remainder_duration > 0 else 0)

            segment_length = duration / optimal_num_segments
            current_segment_start = start
            for i in range(optimal_num_segments):
                split_start = current_segment_start
                # For the last segment, ensure it goes exactly to the original end
                split_end = end if (i == optimal_num_segments - 1) else (current_segment_start + segment_length)
                new_segments.append((split_start, split_end))
                current_segment_start = split_end

        return new_segments

    def export_segments(self):
        if not self.splits:
            QMessageBox.warning(self, "Warning", "No split points defined")
            return
        
        output_dir = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if not output_dir:
            return
        
        # Create segments list
        segments = []
        split_points = [0] + self.splits + [self.video_duration]
        
        for i in range(len(split_points) - 1):
            start = split_points[i]
            end = split_points[i + 1]
            if end > start:  # Only add valid segments
                segments.append((start, end))
        
        if not segments:
            QMessageBox.warning(self, "Warning", "No valid segments to export")
            return

        if self.auto_split_enabled:
            max_duration = self.max_segment_duration
            min_duration = self.min_segment_duration
            
            # Validate min/max duration before applying auto-split
            if max_duration <= 0 or min_duration <= 0 or min_duration > max_duration:
                QMessageBox.warning(self, "Warning", "Invalid auto-split duration settings. Please ensure Min Duration > 0, Max Duration > 0, and Min Duration <= Max Duration.")
                return # Stop export if settings are invalid

            segments = self._apply_auto_split(segments, max_duration, min_duration)
        
        # Start processing
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.export_button.setEnabled(False)
        
        self.processor = VideoProcessor(self.video_path, segments, output_dir)
        self.processor.progress.connect(self.progress_bar.setValue)
        self.processor.finished.connect(self.on_export_finished)
        self.processor.error.connect(self.on_export_error)
        self.processor.start()
    
    def on_export_finished(self, message):
        self.progress_bar.setVisible(False)
        self.export_button.setEnabled(True)
        QMessageBox.information(self, "Success", message)
    
    def on_export_error(self, error_message):
        self.progress_bar.setVisible(False)
        self.export_button.setEnabled(True)
        QMessageBox.critical(self, "Error", error_message)
    
    def save_project(self):
        if not self.video_path:
            QMessageBox.warning(self, "Warning", "No video loaded to save project.")
            return

        file_path, _ = QFileDialog.getSaveFileName(self, "Save Project File", "", "Video Splitter Project (*.vsproj);;All Files (*)")
        if not file_path:
            return

        project_data = {
            "video_path": self.video_path,
            "splits": self.splits,
            "auto_split_enabled": self.auto_split_enabled,
            "max_segment_duration": self.max_segment_duration,
            "min_segment_duration": self.min_segment_duration,
            "scene_detection_threshold": self.scene_detection_threshold
        }

        try:
            with open(file_path, 'w') as f:
                json.dump(project_data, f, indent=4)
            QMessageBox.information(self, "Save Project", "Project saved successfully!")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save project: {str(e)}")

    def load_project(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Load Project File", "", "Video Splitter Project (*.vsproj);;All Files (*)")
        if not file_path:
            return

        try:
            with open(file_path, 'r') as f:
                project_data = json.load(f)

            video_path = project_data.get("video_path")
            splits = project_data.get("splits", [])
            auto_split_enabled = project_data.get("auto_split_enabled", False)
            max_segment_duration = project_data.get("max_segment_duration", 28.5)
            min_segment_duration = project_data.get("min_segment_duration", 9.9)
            scene_detection_threshold = project_data.get("scene_detection_threshold", 0.4)

            if not video_path or not os.path.exists(video_path):
                QMessageBox.warning(self, "Load Project", f"Video file not found: {video_path}. Please re-select the video.")
                # We can still load other settings even if video is missing
                self.video_path = None
                self.file_label.setText("No file selected")
                self.timeline_slider.setEnabled(False)
                self.add_split_button.setEnabled(False)
                self.export_button.setEnabled(False)
                self.preview_label.clear()
                self.time_label.setText("00:00 / 00:00")
                self.save_project_button.setEnabled(False)
            else:
                self.load_video(video_path) # This will reset splits, so we need to re-add them after
                QApplication.processEvents() # Ensure video load is processed before adding splits

            self.splits = sorted([float(s) for s in splits]) # Ensure splits are floats and sorted
            self.update_splits_list()
            if self.splits:
                self.export_button.setEnabled(True)

            self.auto_split_checkbox.setChecked(auto_split_enabled)
            self.max_segment_duration = max_segment_duration
            self.min_segment_duration = min_segment_duration
            self.max_segment_duration_slider.setValue(int(max_segment_duration * 100))
            self.min_segment_duration_slider.setValue(int(min_segment_duration * 100))
            self.update_max_segment_duration_label(int(max_segment_duration * 100)) # Force update labels
            self.update_min_segment_duration_label(int(min_segment_duration * 100))
            
            self.scene_detection_threshold = scene_detection_threshold
            self.scene_threshold_slider.setValue(int(scene_detection_threshold * 100))
            self.update_scene_threshold_label(int(scene_detection_threshold * 100)) # Force update label

            QMessageBox.information(self, "Load Project", "Project loaded successfully!")

        except json.JSONDecodeError:
            QMessageBox.critical(self, "Error", "Invalid project file format.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load project: {str(e)}")
    
    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress:
            key = event.key()
            if key == Qt.Key_Space:
                self.seek_to_time(self.current_time + (1.0 / self.fps))
                return True
            elif key == Qt.Key_S:
                self.add_split()
                return True
            elif key == Qt.Key_Left:
                self.seek_prev_frame()
                return True
            elif key == Qt.Key_Right:
                self.seek_next_frame()
                return True
            elif key == Qt.Key_Down:
                self.seek_relative(-10)
                return True
            elif key == Qt.Key_Up:
                self.seek_relative(10)
                return True
        return super().eventFilter(obj, event)

    def closeEvent(self, event):
        # Cleanup temp directory
        try:
            import shutil
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        except:
            pass
        event.accept()

def main():
    app = QApplication(sys.argv)
    
    # Check if ffmpeg is available
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        QMessageBox.critical(None, "Error", 
                           "FFmpeg not found. Please install FFmpeg and ensure it's in your PATH.")
        sys.exit(1)
    
    window = VideoSplitter()
    window.show()
    
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
