# VideoSplitter Pro

A powerful, user-friendly desktop application for splitting videos into segments with precision control and advanced features like scene detection and auto-splitting.

## Features

### 🎬 **Core Functionality**
- **Frame-accurate video splitting** - Split videos at exact timestamps
- **Visual timeline navigation** - Seek through videos with frame-by-frame precision
- **Multiple export formats** - Support for MP4, AVI, MOV, MKV, WMV, FLV, and WebM
- **Keyboard shortcuts** - Efficient workflow with spacebar for play/pause and arrow keys for navigation

### 🔧 **Advanced Features**
- **Auto-split functionality** - Automatically split long segments into smaller chunks
- **Scene detection** - AI-powered scene change detection for automatic split points
- **Customizable thresholds** - Adjust sensitivity for scene detection
- **Project saving/loading** - Save and restore your work with `.vsproj` files

### 🎨 **User Experience**
- **Dark theme interface** - Easy on the eyes during long editing sessions
- **Aspect ratio preservation** - Maintains correct video proportions in preview
- **Real-time preview** - See exactly where you're splitting
- **Progress tracking** - Monitor export progress with visual indicators

## Installation

### Prerequisites
- **Python 3.7+**
- **FFmpeg** (must be installed and available in system PATH)

### Dependencies
```bash
pip install PyQt5
```

### Running the Application
```bash
python video_splitter.py
```

## Usage

### Basic Video Splitting
1. **Load a video** - Click "Select Video" to choose your video file
2. **Navigate timeline** - Use the slider or frame navigation buttons
3. **Add split points** - Click "Add Split Point" at desired locations
4. **Export segments** - Choose output directory and export

### Auto-Split Feature
- Enable "Auto Split Segments Longer Than Max Duration"
- Set maximum and minimum segment durations
- The app will automatically split long segments while respecting your duration constraints

### Scene Detection
1. Go to the "Settings" tab
2. Adjust detection threshold (higher = fewer scene changes detected)
3. Click "Detect Scenes" to automatically find scene transitions
4. Review and edit detected split points as needed

### Keyboard Shortcuts
- **Spacebar**: Play/Pause
- **Left/Right Arrow**: Previous/Next frame
- **Up/Down Arrow**: ±10 seconds
- **S**: Add split point at current position

## Project Files

Save your work as `.vsproj` files to preserve:
- Video file reference
- All split points
- Auto-split settings
- Scene detection threshold
- Export preferences

## Technical Details

### Supported Video Formats
- MP4, AVI, MOV, MKV, WMV, FLV, WebM
- All codecs supported by FFmpeg

### Output
- Segments are exported as high-quality MP4 files
- Uses FFmpeg's stream copy for fast, lossless splitting
- Maintains original video quality

## Troubleshooting

### Common Issues
- **FFmpeg not found**: Ensure FFmpeg is installed and in your system PATH
- **Video won't load**: Check file format compatibility and file integrity
- **Export fails**: Verify sufficient disk space and write permissions

### Performance Tips
- For large videos, consider using scene detection first, then manual refinement
- Lower scene detection threshold for more sensitive detection
- Close other applications during export for better performance

## License

This project is provided as-is for educational and personal use.

## Support

For issues and feature requests, please ensure:
1. FFmpeg is properly installed
2. You're using supported video formats
3. You have sufficient system resources

---

**VideoSplitter Pro** - Making video segmentation simple and precise! 🎥✂️
