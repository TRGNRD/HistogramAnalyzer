
#!/usr/bin/env python3
"""Image Histogram Analyzer — portable EXE tool.

Opens an image, lets the user draw a selection rectangle, and displays
a live histogram (luminance + RGB) for the selected region using
Matplotlib embedded in Tkinter.

Features:
- Free zoom (mouse wheel / Ctrl+wheel) and pan (middle-drag or space-drag)
- Toggle Lum/R/G/B channel visibility with a click on the legend
- Dark theme
"""

import os
import tkinter as tk
from tkinter import filedialog, messagebox

import numpy as np
from PIL import Image, ImageTk

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

try:
    import tkinterdnd2
    from tkinterdnd2 import DND_FILES
    HAS_DND = True
except ImportError:
    HAS_DND = False

# ── Dark theme palette ────────────────────────────────────────────────
BG = "#1e1e2e"
FG = "#cdd6f4"
ACCENT = "#89b4fa"
PANEL_BG = "#181825"
CANVAS_BG = "#11111b"
GRID_COLOR = "#313244"
TEXT_MUTED = "#6c7086"

# Histogram channel colors (luminance, R, G, B)
CH_COLORS = {
    "Lum": "#f5e0dc",
    "R":   "#f38ba8",
    "G":   "#a6e3a1",
    "B":   "#89b4fa",
}

# Zoom limits
ZOOM_MIN = 0.05
ZOOM_MAX = 32.0
ZOOM_STEP = 1.18  # multiplicative factor per wheel tick


class HistogramAnalyzer:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Image Histogram Analyzer")
        self.root.geometry("1280x760")
        self.root.minsize(960, 560)
        self.root.configure(bg=BG)

        # State
        self.original_image: Image.Image | None = None   # full-res PIL image
        self.base_image: Image.Image | None = None      # fit-to-canvas PIL image (zoom=1)
        self.photo_image: ImageTk.PhotoImage | None = None  # current zoomed PhotoImage
        self.file_path: str | None = None

        # Zoom / pan transform: canvas_pos = base_pos * zoom + offset
        self.zoom: float = 1.0
        self.offset_x: float = 0.0
        self.offset_y: float = 0.0

        # Rectangle selection state (in base-image coords, i.e. fit-to-canvas resolution)
        self.rect_start: tuple[float, float] | None = None
        self.rect_current: tuple[float, float] | None = None
        self.rect_id: int | None = None

        # Channel visibility toggles
        self.ch_visible = {"Lum": True, "R": True, "G": True, "B": True}
        self.ch_buttons: dict[str, tk.Frame] = {}

        # Panning state
        self.pan_start: tuple[int, int] | None = None
        self.space_down: bool = False

        # Build UI
        self._build_menu()
        self._build_layout()
        self._bind_events()

    # ── Menu bar ──────────────────────────────────────────────────────
    def _build_menu(self):
        menubar = tk.Menu(self.root, bg=PANEL_BG, fg=FG, activebackground=ACCENT)
        file_menu = tk.Menu(menubar, tearoff=0, bg=PANEL_BG, fg=FG)
        file_menu.add_command(label="Open Image…", command=self.open_image, accelerator="Ctrl+O")
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit, accelerator="Ctrl+Q")
        menubar.add_cascade(label="File", menu=file_menu)

        view_menu = tk.Menu(menubar, tearoff=0, bg=PANEL_BG, fg=FG)
        view_menu.add_command(label="Zoom In", command=lambda: self._zoom_at_center(1.3), accelerator="Ctrl++")
        view_menu.add_command(label="Zoom Out", command=lambda: self._zoom_at_center(1 / 1.3), accelerator="Ctrl+-")
        view_menu.add_command(label="Reset View", command=self.reset_view, accelerator="Ctrl+0")
        menubar.add_cascade(label="View", menu=view_menu)

        help_menu = tk.Menu(menubar, tearoff=0, bg=PANEL_BG, fg=FG)
        help_menu.add_command(label="About", command=self._show_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.root.config(menu=menubar)

    def _show_about(self):
        messagebox.showinfo(
            "About",
            "Image Histogram Analyzer\n"
            "• Left-drag: select region\n"
            "• Mouse wheel: zoom in/out (at cursor)\n"
            "• Middle-drag or Space+drag: pan image\n"
            "• Click a channel chip to show/hide it\n"
            "Channels: Luminance, R, G, B",
            parent=self.root,
        )

    # ── Main layout ───────────────────────────────────────────────────
    def _build_layout(self):
        # Top toolbar
        toolbar = tk.Frame(self.root, bg=PANEL_BG, height=44)
        toolbar.pack(fill=tk.X, side=tk.TOP)
        toolbar.pack_propagate(False)

        self.btn_open = tk.Button(
            toolbar, text="📂 Open Image", command=self.open_image,
            bg=ACCENT, fg="#1e1e2e", activebackground="#74c0fc",
            relief=tk.FLAT, padx=14, pady=4, font=("Segoe UI", 10, "bold"),
        )
        self.btn_open.pack(side=tk.LEFT, padx=(12, 6), pady=8)

        self.btn_clear = tk.Button(
            toolbar, text="✕ Clear Selection", command=self.clear_selection,
            bg=PANEL_BG, fg=FG, activebackground="#313244",
            relief=tk.FLAT, padx=14, pady=4, font=("Segoe UI", 10),
        )
        self.btn_clear.pack(side=tk.LEFT, padx=6, pady=8)

        self.btn_reset = tk.Button(
            toolbar, text="⌂ Reset View", command=self.reset_view,
            bg=PANEL_BG, fg=FG, activebackground="#313244",
            relief=tk.FLAT, padx=14, pady=4, font=("Segoe UI", 10),
        )
        self.btn_reset.pack(side=tk.LEFT, padx=6, pady=8)

        self.lbl_zoom = tk.Label(
            toolbar, text="100%", bg=PANEL_BG, fg=TEXT_MUTED, font=("Segoe UI", 9),
        )
        self.lbl_zoom.pack(side=tk.LEFT, padx=(12, 0))

        self.lbl_status = tk.Label(
            toolbar, text="No image loaded — press Open Image or Ctrl+O",
            bg=PANEL_BG, fg=TEXT_MUTED, font=("Segoe UI", 9),
        )
        self.lbl_status.pack(side=tk.RIGHT, padx=12)

        # Separator line
        sep = tk.Frame(self.root, bg=GRID_COLOR, height=1)
        sep.pack(fill=tk.X)

        # Main split: image left, histogram right
        main = tk.PanedWindow(self.root, orient=tk.HORIZONTAL, bg=BG, sashwidth=4, sashrelief=tk.FLAT)
        main.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        # ── Left: image canvas ──
        left_frame = tk.Frame(main, bg=CANVAS_BG)
        main.add(left_frame, stretch="always")

        self.canvas = tk.Canvas(
            left_frame, bg=CANVAS_BG, highlightthickness=0,
            cursor="crosshair",
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)

        # ── Right: histogram panel ──
        right_frame = tk.Frame(main, bg=PANEL_BG)
        main.add(right_frame, stretch="always")

        # Title
        hist_title = tk.Label(
            right_frame, text="Histogram", bg=PANEL_BG, fg=FG,
            font=("Segoe UI", 12, "bold"), anchor=tk.W,
        )
        hist_title.pack(fill=tk.X, padx=10, pady=(8, 2))

        self.lbl_region = tk.Label(
            right_frame, text="Full image", bg=PANEL_BG, fg=TEXT_MUTED,
            font=("Segoe UI", 9), anchor=tk.W,
        )
        self.lbl_region.pack(fill=tk.X, padx=10, pady=(0, 4))

        # Matplotlib figure
        self.fig = plt.Figure(figsize=(5.2, 4.2), dpi=100, facecolor=PANEL_BG)
        self.ax = self.fig.add_subplot(111)
        self._style_axis()

        self.canvas_hist = FigureCanvasTkAgg(self.fig, master=right_frame)
        self.canvas_hist.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 4))

        # Now safe to draw (canvas_hist exists)
        self._draw_empty_hist()

        # Toolbar for matplotlib (zoom/pan)
        nav_bar = NavigationToolbar2Tk(self.canvas_hist, right_frame)
        nav_bar.update()

        # Channel toggle chips (clickable legend)
        legend_frame = tk.Frame(right_frame, bg=PANEL_BG)
        legend_frame.pack(fill=tk.X, padx=10, pady=(0, 8))
        for ch in ("Lum", "R", "G", "B"):
            btn = self._make_channel_button(legend_frame, ch)
            btn.pack(side=tk.LEFT, padx=(4, 4), pady=4)
            self.ch_buttons[ch] = btn

    def _make_channel_button(self, parent, ch: str) -> tk.Frame:
        """Create a clickable frame that toggles channel visibility."""
        frame = tk.Frame(parent, bg=PANEL_BG, cursor="hand2")
        # Colored dot
        dot = tk.Canvas(frame, width=10, height=10, bg=PANEL_BG, highlightthickness=0)
        dot.create_oval(1, 1, 9, 9, fill=CH_COLORS[ch], outline=CH_COLORS[ch])
        dot.pack(side=tk.LEFT, padx=(4, 3))
        # Label text
        lbl = tk.Label(frame, text=ch, bg=PANEL_BG, fg=FG, font=("Segoe UI", 9, "bold"))
        lbl.pack(side=tk.LEFT)
        # Bind clicks on both dot and label
        for w in (frame, dot, lbl):
            w.bind("<Button-1>", lambda e, c=ch: self._toggle_channel(c))
        return frame

    def _toggle_channel(self, ch: str):
        """Toggle a channel's visibility and redraw the histogram."""
        self.ch_visible[ch] = not self.ch_visible[ch]
        # Update chip appearance
        btn = self.ch_buttons.get(ch)
        if btn is not None:
            for w in btn.winfo_children():
                if isinstance(w, tk.Label):
                    w.config(fg=FG if self.ch_visible[ch] else TEXT_MUTED)
                elif isinstance(w, tk.Canvas):
                    color = CH_COLORS[ch] if self.ch_visible[ch] else GRID_COLOR
                    try:
                        w.itemconfig(1, fill=color, outline=color)
                    except tk.TclError:
                        pass
        # Redraw histogram with current toggles (reuse last selection)
        if self.original_image:
            if self.rect_id is not None and self.rect_start is not None:
                x1, y1, x2, y2 = self._get_rect_coords()
                self.update_histogram((x1, y1, x2, y2))
            else:
                self.update_histogram(None)

    def _style_axis(self):
        self.ax.set_facecolor(CANVAS_BG)
        self.ax.tick_params(colors=TEXT_MUTED, labelsize=8)
        for spine in self.ax.spines.values():
            spine.set_color(GRID_COLOR)
        self.ax.xaxis.label.set_color(TEXT_MUTED)
        self.ax.yaxis.label.set_color(TEXT_MUTED)
        self.ax.title.set_color(FG)

    def _draw_empty_hist(self):
        self.ax.clear()
        self._style_axis()
        self.ax.text(0.5, 0.5, "No image loaded", transform=self.ax.transAxes,
                     ha="center", va="center", color=TEXT_MUTED, fontsize=12)
        self.fig.tight_layout()
        self.canvas_hist.draw_idle()

    # ── Events ────────────────────────────────────────────────────────
    def _bind_events(self):
        self.root.bind("<Control-o>", lambda e: self.open_image())
        self.root.bind("<Control-O>", lambda e: self.open_image())
        self.root.bind("<Control-q>", lambda e: self.root.quit())
        self.root.bind("<Control-Q>", lambda e: self.root.quit())
        self.root.bind("<Control-0>", lambda e: self.reset_view())

        # Image canvas: left-drag = select, middle-drag = pan
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)

        # Middle-click pan
        self.canvas.bind("<ButtonPress-2>", self._on_pan_start)
        self.canvas.bind("<B2-Motion>", self._on_pan_move)
        self.canvas.bind("<ButtonRelease-2>", self._on_pan_end)

        # Space+left-drag pan
        self.root.bind("<space>", self._on_space_down)
        self.root.bind("<KeyRelease-space>", self._on_space_up)

        # Mouse wheel zoom (Windows: <MouseWheel>, Linux: <Button-4/5>)
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<Button-4>", lambda e: self._on_mousewheel(e, delta=1))
        self.canvas.bind("<Button-5>", lambda e: self._on_mousewheel(e, delta=-1))

        self.canvas.bind("<Configure>", self._on_canvas_resize)

        # Drag & Drop (if tkinterdnd2 is available)
        if HAS_DND:
            self.root.bind(DND_FILES, self._on_drop)

    # ── Coordinate transforms ─────────────────────────────────────────
    def _canvas_to_base(self, cx: float, cy: float) -> tuple[float, float]:
        """Convert canvas coords to base-image coords (fit-to-canvas resolution)."""
        bx = (cx - self.offset_x) / self.zoom
        by = (cy - self.offset_y) / self.zoom
        return bx, by

    def _base_to_canvas(self, bx: float, by: float) -> tuple[float, float]:
        """Convert base-image coords to canvas coords."""
        cx = bx * self.zoom + self.offset_x
        cy = by * self.zoom + self.offset_y
        return cx, cy

    # ── Zoom / Pan ────────────────────────────────────────────────────
    def _on_mousewheel(self, event, delta=None):
        if not self.base_image:
            return
        if delta is None:
            # Windows MouseWheel: event.delta is +/- 120 per tick
            delta = 1 if event.delta > 0 else -1
        factor = ZOOM_STEP if delta > 0 else 1.0 / ZOOM_STEP
        self._zoom_at_point(event.x, event.y, factor)

    def _zoom_at_center(self, factor: float):
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        self._zoom_at_point(cw / 2, ch / 2, factor)

    def _zoom_at_point(self, cx: float, cy: float, factor: float):
        """Zoom centered on canvas point (cx, cy)."""
        old_zoom = self.zoom
        new_zoom = max(ZOOM_MIN, min(ZOOM_MAX, old_zoom * factor))
        if abs(new_zoom - old_zoom) < 1e-9:
            return
        # Keep the base point under (cx, cy) fixed:
        #   base = (c - offset) / zoom  =>  offset = c - base * zoom
        bx = (cx - self.offset_x) / old_zoom
        by = (cy - self.offset_y) / old_zoom
        self.zoom = new_zoom
        self.offset_x = cx - bx * new_zoom
        self.offset_y = cy - by * new_zoom
        self._rebuild_zoom_image()
        self._render_canvas()
        self._update_zoom_label()

    def _on_pan_start(self, event):
        if not self.base_image:
            return
        self.pan_start = (event.x, event.y)
        self.canvas.config(cursor="fleur")

    def _on_pan_move(self, event):
        if self.pan_start is None:
            return
        dx = event.x - self.pan_start[0]
        dy = event.y - self.pan_start[1]
        self.offset_x += dx
        self.offset_y += dy
        self.pan_start = (event.x, event.y)
        self._render_canvas()

    def _on_pan_end(self, event):
        self.pan_start = None
        if not self.space_down:
            self.canvas.config(cursor="crosshair")

    def _on_space_down(self, event):
        self.space_down = True
        if self.base_image:
            self.canvas.config(cursor="fleur")

    def _on_space_up(self, event):
        self.space_down = False
        self.pan_start = None
        self.canvas.config(cursor="crosshair")

    def reset_view(self):
        if not self.base_image:
            return
        self.zoom = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0
        self._rebuild_zoom_image()
        self._render_canvas()
        self._update_zoom_label()

    def _update_zoom_label(self):
        pct = int(round(self.zoom * 100))
        self.lbl_zoom.config(text=f"{pct}%")

    # ── Drag & Drop ───────────────────────────────────────────────────
    def _on_drop(self, event):
        """Handle a file dropped onto the window."""
        # event.data contains one or more paths (space-separated on some platforms)
        raw = event.data.strip()
        # On Windows, paths come null-separated; tkinterdnd2 converts to space-separated
        # But paths may contain spaces, so try to parse carefully
        if '\x00' in raw:
            paths = [p for p in raw.split('\x00') if p]
        else:
            # Try to split on double-space or use the whole string as one path
            # tkinterdnd2 on Windows typically gives space-separated list
            paths = raw.split() if ' ' in raw and not raw.startswith('"') else [raw]
        # Filter to valid image files that exist
        valid_exts = {'.png', '.jpg', '.jpeg', '.bmp'}
        for p in paths:
            p = p.strip('"')
            if os.path.isfile(p):
                ext = os.path.splitext(p)[1].lower()
                if ext in valid_exts:
                    self._open_path(p)
                    return
        # If no valid image found, show a message
        messagebox.showwarning(
            "Drag & Drop",
            "Dropped file is not a supported image (PNG, JPG, BMP).",
            parent=self.root,
        )

    def _open_path(self, path: str):
        """Open an image from a known path (used by drag-and-drop)."""
        try:
            img = Image.open(path)
            img.load()
            if img.mode in ("RGBA", "LA") or "transparency" in img.info:
                bg = Image.new("RGB", img.size, (0, 0, 0))
                rgba = img.convert("RGBA")
                bg.paste(rgba, mask=rgba.split()[3])
                img = bg
            elif img.mode != "RGB":
                img = img.convert("RGB")
        except Exception as exc:
            messagebox.showerror("Error", f"Could not open image:\n{exc}", parent=self.root)
            return

        self.original_image = img
        self.file_path = path
        self.root.title(f"Histogram Analyzer — {os.path.basename(path)}")
        self.rect_start = None
        self.rect_current = None
        self.rect_id = None
        self._fit_display()
        self.reset_view()
        self._render_canvas()
        self._set_status(f"Loaded: {os.path.basename(path)}  ({img.width}×{img.height})")
        self.update_histogram(None)

    # ── Image loading ─────────────────────────────────────────────────
    def open_image(self):
        path = filedialog.askopenfilename(
            parent=self.root,
            title="Open Image",
            filetypes=[
                ("Supported images", "*.png *.jpg *.jpeg *.bmp"),
                ("PNG", "*.png"),
                ("JPEG", "*.jpg *.jpeg"),
                ("BMP", "*.bmp"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        try:
            img = Image.open(path)
            img.load()
            if img.mode in ("RGBA", "LA") or "transparency" in img.info:
                bg = Image.new("RGB", img.size, (0, 0, 0))
                rgba = img.convert("RGBA")
                bg.paste(rgba, mask=rgba.split()[3])
                img = bg
            elif img.mode != "RGB":
                img = img.convert("RGB")
        except Exception as exc:
            messagebox.showerror("Error", f"Could not open image:\n{exc}", parent=self.root)
            return

        self.original_image = img
        self.file_path = path
        self.root.title(f"Histogram Analyzer — {os.path.basename(path)}")
        # Clear any previous selection
        self.rect_start = None
        self.rect_current = None
        self.rect_id = None
        self._fit_display()
        self.reset_view()
        self._render_canvas()
        self._set_status(f"Loaded: {os.path.basename(path)}  ({img.width}×{img.height})")
        self.update_histogram(None)

    def _fit_display(self):
        """Scale image to fit the canvas while keeping aspect ratio (zoom=1 baseline)."""
        if not self.original_image:
            return
        cw = max(self.canvas.winfo_width(), 200)
        ch = max(self.canvas.winfo_height(), 200)
        iw, ih = self.original_image.size
        scale = min(cw / iw, ch / ih, 1.0)
        nw, nh = max(1, round(iw * scale)), max(1, round(ih * scale))
        self.display_scale = scale
        self.base_image = self.original_image.resize((nw, nh), Image.Resampling.LANCZOS)

    def _rebuild_zoom_image(self):
        """Resize the base image to the current zoom level and build a PhotoImage."""
        if not self.base_image:
            return
        bw, bh = self.base_image.size
        nw = max(1, round(bw * self.zoom))
        nh = max(1, round(bh * self.zoom))
        # NEAREST keeps true pixel values visible when zoomed in (good for inspection)
        resample = Image.Resampling.NEAREST if self.zoom > 1.0 else Image.Resampling.LANCZOS
        zoomed = self.base_image.resize((nw, nh), resample)
        self.photo_image = ImageTk.PhotoImage(zoomed)

    def _on_canvas_resize(self, _event=None):
        if not self.original_image:
            return
        self._fit_display()
        self._rebuild_zoom_image()
        self._render_canvas()

    def _render_canvas(self):
        if not self.base_image or self.photo_image is None:
            return
        self.canvas.delete("all")
        # Top-left canvas position of the zoomed image
        cx, cy = self._base_to_canvas(0, 0)
        self.canvas.create_image(cx, cy, image=self.photo_image, anchor=tk.NW)
        # Re-draw existing selection rectangle if any
        if self.rect_id is not None and self.rect_start is not None:
            x1, y1, x2, y2 = self._get_rect_coords()
            cx1, cy1 = self._base_to_canvas(x1, y1)
            cx2, cy2 = self._base_to_canvas(x2, y2)
            self.rect_id = self.canvas.create_rectangle(
                cx1, cy1, cx2, cy2, outline=ACCENT, width=2, dash=(6, 3),
            )

    # ── Rectangle selection (in base-image coords) ────────────────────
    def _on_press(self, event):
        if not self.base_image:
            return
        if self.space_down:
            # Space held — treat as pan
            self.pan_start = (event.x, event.y)
            self.canvas.config(cursor="fleur")
            return
        bx, by = self._canvas_to_base(event.x, event.y)
        self.rect_start = (bx, by)
        self.rect_current = (bx, by)
        if self.rect_id is not None:
            self.canvas.delete(self.rect_id)
            self.rect_id = None

    def _on_drag(self, event):
        if self.space_down and self.pan_start is not None:
            # Panning via space+left-drag
            dx = event.x - self.pan_start[0]
            dy = event.y - self.pan_start[1]
            self.offset_x += dx
            self.offset_y += dy
            self.pan_start = (event.x, event.y)
            self._render_canvas()
            return
        if self.rect_start is None:
            return
        bx, by = self._canvas_to_base(event.x, event.y)
        self.rect_current = (bx, by)
        x1, y1, x2, y2 = self._get_rect_coords()
        cx1, cy1 = self._base_to_canvas(x1, y1)
        cx2, cy2 = self._base_to_canvas(x2, y2)
        if self.rect_id is None:
            self.rect_id = self.canvas.create_rectangle(
                cx1, cy1, cx2, cy2, outline=ACCENT, width=2, dash=(6, 3),
            )
        else:
            self.canvas.coords(self.rect_id, cx1, cy1, cx2, cy2)

    def _on_release(self, event):
        if self.space_down:
            self.pan_start = None
            return
        if self.rect_start is None:
            return
        bx, by = self._canvas_to_base(event.x, event.y)
        self.rect_current = (bx, by)
        x1, y1, x2, y2 = self._get_rect_coords()
        w, h = abs(x2 - x1), abs(y2 - y1)
        if w < 2 or h < 2:
            # Too small — treat as click, clear selection
            self.clear_selection()
            return
        self.update_histogram((x1, y1, x2, y2))

    def _get_rect_coords(self):
        """Return rect in base-image coords, clamped to image bounds."""
        sx, sy = self.rect_start
        ex, ey = self.rect_current
        x1, x2 = min(sx, ex), max(sx, ex)
        y1, y2 = min(sy, ey), max(sy, ey)
        iw = self.base_image.width if self.base_image else 0
        ih = self.base_image.height if self.base_image else 0
        x1, x2 = max(0, x1), min(iw, x2)
        y1, y2 = max(0, y1), min(ih, y2)
        return x1, y1, x2, y2

    def clear_selection(self):
        self.rect_start = None
        self.rect_current = None
        if self.rect_id is not None and self.canvas.winfo_exists():
            try:
                self.canvas.delete(self.rect_id)
            except tk.TclError:
                pass
        self.rect_id = None
        if self.original_image:
            self._render_canvas()
            self.update_histogram(None)

    # ── Histogram computation & rendering ─────────────────────────────
    def update_histogram(self, rect_base):
        """Compute and draw histogram. rect_base in base-image coords or None for full image."""
        if not self.original_image:
            return

        if rect_base is None:
            region = self.original_image
            self.lbl_region.config(text="Full image")
        else:
            x1, y1, x2, y2 = rect_base
            scale = self.display_scale
            # Convert to original image coords
            ox1 = max(0, min(self.original_image.width - 1, int(x1 / scale)))
            oy1 = max(0, min(self.original_image.height - 1, int(y1 / scale)))
            ox2 = max(ox1 + 1, min(self.original_image.width, int(x2 / scale)))
            oy2 = max(oy1 + 1, min(self.original_image.height, int(y2 / scale)))
            region = self.original_image.crop((ox1, oy1, ox2, oy2))
            self.lbl_region.config(
                text=f"Selection: {ox2-ox1}×{oy2-oy1} px  (x:{ox1}, y:{oy1})"
            )

        arr = np.asarray(region)
        r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
        # Luminance (ITU-R BT.709)
        lum = (0.2126 * r + 0.7152 * g + 0.0722 * b).astype(np.uint8)

        bins = np.arange(257, dtype=np.float64)
        hist_lum, _ = np.histogram(lum.ravel(), bins=bins)
        hist_r, _ = np.histogram(r.ravel(), bins=bins)
        hist_g, _ = np.histogram(g.ravel(), bins=bins)
        hist_b, _ = np.histogram(b.ravel(), bins=bins)

        # Normalize to 0..1 for overlay (only over visible channels)
        visible_hists = []
        if self.ch_visible["Lum"]:
            visible_hists.append(hist_lum)
        if self.ch_visible["R"]:
            visible_hists.append(hist_r)
        if self.ch_visible["G"]:
            visible_hists.append(hist_g)
        if self.ch_visible["B"]:
            visible_hists.append(hist_b)
        max_count = 1
        if visible_hists:
            max_count = max(h.max() for h in visible_hists)
        x = np.arange(256, dtype=np.float64)

        self.ax.clear()
        self._style_axis()
        self.ax.set_xlim(0, 255)
        self.ax.set_ylim(0, 1.08)
        self.ax.set_xticks([0, 32, 64, 96, 128, 160, 192, 224, 255])
        self.ax.set_xlabel("Pixel value")
        self.ax.set_ylabel("Relative frequency")
        self.ax.grid(True, color=GRID_COLOR, linewidth=0.5, alpha=0.6)

        if self.ch_visible["Lum"]:
            self.ax.fill_between(x, hist_lum / max_count, alpha=0.30, color=CH_COLORS["Lum"])
            self.ax.plot(x, hist_lum / max_count, color=CH_COLORS["Lum"], lw=1.4, label="Luminance")
        if self.ch_visible["R"]:
            self.ax.fill_between(x, hist_r / max_count, alpha=0.22, color=CH_COLORS["R"])
            self.ax.plot(x, hist_r / max_count, color=CH_COLORS["R"], lw=1.1, label="Red")
        if self.ch_visible["G"]:
            self.ax.fill_between(x, hist_g / max_count, alpha=0.22, color=CH_COLORS["G"])
            self.ax.plot(x, hist_g / max_count, color=CH_COLORS["G"], lw=1.1, label="Green")
        if self.ch_visible["B"]:
            self.ax.fill_between(x, hist_b / max_count, alpha=0.22, color=CH_COLORS["B"])
            self.ax.plot(x, hist_b / max_count, color=CH_COLORS["B"], lw=1.1, label="Blue")

        if not visible_hists:
            self.ax.text(0.5, 0.5, "All channels hidden", transform=self.ax.transAxes,
                         ha="center", va="center", color=TEXT_MUTED, fontsize=11)

        self.fig.tight_layout()
        self.canvas_hist.draw_idle()

    # ── Status bar helper ─────────────────────────────────────────────
    def _set_status(self, text: str):
        self.lbl_status.config(text=text)


def main():
    if HAS_DND:
        root = tkinterdnd2.Tk()
    else:
        root = tk.Tk()
    app = HistogramAnalyzer(root)
    root.mainloop()


if __name__ == "__main__":
    main()
