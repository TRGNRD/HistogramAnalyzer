
# Image Histogram Analyzer

Portable Windows EXE tool for analyzing image histograms with region selection, zoom/pan, and per-channel toggles.

## Features

- **Histogram analysis** — Luminance (ITU-R BT.709), Red, Green, Blue channels
- **Region selection** — Draw a rectangle to analyze only that area
- **Free zoom & pan** — Mouse wheel zoom (5%–3200%), middle-drag or Space+drag to pan
- **Channel toggles** — Click Lum/R/G/B chips to show/hide individual channels
- **Drag & drop** — Drop an image file directly onto the window
- **Dark theme** — Catppuccin Mocha palette
- **Portable** — Single EXE, no installation needed

## Usage

1. Run `HistogramAnalyzer.exe` (double-click)
2. Open an image via **File → Open Image…**, **Ctrl+O**, or **drag & drop**
3. Draw a selection rectangle with left mouse button to analyze a region
4. Zoom with mouse wheel, pan with middle-drag or Space+left-drag
5. Click channel chips (Lum/R/G/B) to toggle visibility

### Supported formats

PNG, JPG/JPEG, BMP

## Controls

| Action | Input |
|--------|-------|
| Select region | Left-drag |
| Zoom in/out | Mouse wheel (at cursor) |
| Pan image | Middle-drag or Space + left-drag |
| Reset view | Ctrl+0 or "Reset View" button |
| Clear selection | Click without dragging, or "Clear Selection" button |
| Toggle channel | Click Lum/R/G/B chip |
| Open image | Ctrl+O or drag & drop |
| Exit | Ctrl+Q |

## Building from source

Requires Python 3.10+, Pillow, matplotlib, numpy, pyinstaller, tkinterdnd2:

```bash
pip install Pillow matplotlib numpy pyinstaller tkinterdnd2
pyinstaller --noconfirm --clean --onefile --windowed --name HistogramAnalyzer histo_analyzer.py
```

The EXE will be in `dist/HistogramAnalyzer.exe`.

## Tech stack

- Python 3.14
- Tkinter (GUI)
- Matplotlib (histogram rendering, embedded via TkAgg)
- Pillow (image loading/manipulation)
- NumPy (histogram computation)
- tkinterdnd2 (drag & drop)
- PyInstaller (portable EXE packaging)
