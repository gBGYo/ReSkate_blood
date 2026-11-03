"""Desktop controls and live previews for the standalone blood decal generator."""

import argparse
from dataclasses import asdict, replace
import json
import math
import os
from pathlib import Path
import random
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
try:
    from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot, QUrl
    from PySide6.QtGui import QColor, QDesktopServices, QFont, QFontDatabase, QIcon, QImage, QPainter, QPixmap
    from PySide6.QtWidgets import (
        QApplication, QColorDialog, QComboBox, QDoubleSpinBox, QFileDialog,
        QGraphicsScene, QGraphicsView, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
        QMainWindow, QMessageBox, QProgressBar, QPushButton, QScrollArea, QSlider,
        QSplitter, QTabWidget, QVBoxLayout, QWidget,
    )
except ImportError as error:
    raise SystemExit("Run decal_lab.cmd to set up the dedicated uv environment and launch the GUI.") from error

if __package__:
    from . import generate_decals as lab
    from .decal_preview import LatestRenderer, export_variant
else:
    import generate_decals as lab
    from decal_preview import LatestRenderer, export_variant


STYLE = """
QWidget { background: #191c22; color: #e4e7ed; font-family: 'Segoe UI'; font-size: 12px; }
QMainWindow, QScrollArea, QScrollArea > QWidget > QWidget { background: #191c22; }
QLabel#title { font-size: 23px; font-weight: 700; }
QLabel#muted { color: #9aa4b3; }
QLabel#error { color: #ffb3ad; }
QGroupBox { border: 1px solid #343a46; border-radius: 7px; margin-top: 12px; padding: 12px 10px 10px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; }
QPushButton, QComboBox, QDoubleSpinBox, QLineEdit { background: #282e39; border: 1px solid #424b5b; border-radius: 5px; padding: 6px; }
QPushButton:hover { background: #343d4c; border-color: #69778b; }
QPushButton:pressed { background: #424d5f; }
QPushButton:disabled { color: #737d8c; }
QPushButton#export { background: #a93944; border-color: #c6505d; font-weight: 600; }
QPushButton#export:hover { background: #c44854; }
QComboBox::drop-down { border: 0; width: 22px; }
QTabWidget::pane { border: 0; }
QTabBar::tab { background: #222730; padding: 9px 19px; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: #ffffff; border-bottom: 2px solid #d65c68; }
QSlider::groove:horizontal { height: 4px; background: #353d49; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #a94753; }
QSlider::handle:horizontal { background: #ee9ba4; width: 12px; margin: -5px 0; border-radius: 6px; }
QScrollBar:vertical { background: #191c22; width: 9px; margin: 0; }
QScrollBar::handle:vertical { background: #424b59; min-height: 24px; border-radius: 4px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QProgressBar { border: 0; background: #2b303b; max-height: 3px; }
QProgressBar::chunk { background: #c45e69; }
QSplitter::handle { background: #303641; width: 2px; }
QToolTip { background: #303846; color: white; border: 1px solid #67748a; padding: 5px; }
"""


def configure_app(app):
    # The offscreen Qt platform does not discover Windows system fonts itself.
    # Register the same fonts used by the native interface for reliable previews.
    fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    for name in ("segoeui.ttf", "segoeuib.ttf"):
        path = fonts / name
        if path.is_file():
            QFontDatabase.addApplicationFont(str(path))
    app.setFont(QFont("Segoe UI", 9))
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)


class NumberControl(QWidget):
    changed = Signal()

    def __init__(self, title, low, high, decimals=2, step=0.1, logarithmic=False, hint=""):
        super().__init__()
        self.low, self.high, self.logarithmic = low, high, logarithmic
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 5)
        row = QHBoxLayout()
        label = QLabel(title)
        label.setWordWrap(True)
        row.addWidget(label, 1)
        self.spin = QDoubleSpinBox()
        self.spin.setDecimals(decimals)
        self.spin.setRange(low, high)
        self.spin.setSingleStep(step)
        self.spin.setKeyboardTracking(False)
        self.spin.setFixedWidth(104)
        row.addWidget(self.spin)
        layout.addLayout(row)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 1000)
        layout.addWidget(self.slider)
        self.setToolTip(hint)
        self.slider.valueChanged.connect(self._slide)
        self.spin.valueChanged.connect(self._typed)

    def _position(self, value):
        if self.logarithmic:
            return round(1000 * math.log(value / self.low) / math.log(self.high / self.low))
        return round(1000 * (value - self.low) / (self.high - self.low))

    def _slide(self, position):
        value = self.low * (self.high / self.low)**(position / 1000) if self.logarithmic else self.low + (self.high - self.low) * position / 1000
        self.spin.setValue(value)

    def _typed(self, value):
        self.slider.blockSignals(True)
        self.slider.setValue(self._position(value))
        self.slider.blockSignals(False)
        self.changed.emit()

    def set_value(self, value):
        self.spin.blockSignals(True)
        self.spin.setValue(value)
        self.spin.blockSignals(False)
        self.slider.blockSignals(True)
        self.slider.setValue(self._position(self.spin.value()))
        self.slider.blockSignals(False)

    def value(self):
        return self.spin.value()


class ColorControl(QWidget):
    changed = Signal()

    def __init__(self, title):
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 4, 0, 4)
        row.addWidget(QLabel(title), 1)
        self.swatch = QPushButton()
        self.swatch.setFixedSize(34, 30)
        self.swatch.clicked.connect(self.choose)
        row.addWidget(self.swatch)
        self.text = QLineEdit()
        self.text.setFixedWidth(104)
        self.text.setMaxLength(7)
        self.text.editingFinished.connect(self._typed)
        row.addWidget(self.text)
        self.rgb = (65, 3, 7)
        self.set_value(self.rgb)

    def set_value(self, rgb):
        self.rgb = tuple(rgb)
        value = "#" + "".join(f"{channel:02x}" for channel in rgb)
        self.text.setText(value)
        self.swatch.setStyleSheet(f"background: {value}; border: 1px solid #8993a4;")

    def _typed(self):
        value = QColor(self.text.text())
        if not value.isValid() or len(self.text.text()) != 7:
            self.set_value(self.rgb)
            return
        self.set_value((value.red(), value.green(), value.blue()))
        self.changed.emit()

    def choose(self):
        value = QColorDialog.getColor(QColor(*self.rgb), self, "Blood color")
        if value.isValid():
            self.set_value((value.red(), value.green(), value.blue()))
            self.changed.emit()

    def value(self):
        return self.rgb


class PreviewView(QGraphicsView):
    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.item = self.scene().addPixmap(QPixmap())
        self.setBackgroundBrush(QColor("#101217"))
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.fitted = True

    def show_image(self, image):
        rgba = image.convert("RGBA")
        qimage = QImage(rgba.tobytes(), rgba.width, rgba.height, rgba.width * 4, QImage.Format.Format_RGBA8888).copy()
        self.item.setPixmap(QPixmap.fromImage(qimage))
        self.scene().setSceneRect(self.item.boundingRect())
        if self.fitted:
            self.fit()

    def fit(self):
        self.fitted = True
        if not self.item.pixmap().isNull():
            self.fitInView(self.item, Qt.AspectRatioMode.KeepAspectRatio)

    def actual_size(self):
        self.fitted = False
        self.resetTransform()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.fitted:
            self.fit()

    def wheelEvent(self, event):
        self.fitted = False
        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        scale = self.transform().m11() * factor
        if 0.08 <= scale <= 24:
            self.scale(factor, factor)
        event.accept()


class Bridge(QObject):
    rendered = Signal(int, object, object)
    exported = Signal(object, object)


class DecalWindow(QMainWindow):
    def __init__(self, recipe=None):
        super().__init__()
        self.setWindowTitle("Blood Decal Lab")
        self.setWindowIcon(QIcon(str(ROOT / "icon.png")))
        self.resize(1360, 880)
        self.setMinimumSize(960, 640)
        self.recipe = recipe or lab.preset("splash")
        self.saved = {kind: lab.preset(kind) for kind in lab.KINDS}
        self.controls = {}
        self.groups = {}
        self.result = None
        self.revision = 0
        self.loading = False
        self.exporting = False
        self.closed = False
        self.last_export = None
        self.bridge = Bridge(self)
        self.bridge.rendered.connect(self._rendered)
        self.bridge.exported.connect(self._exported)
        self.renderer = LatestRenderer(self.bridge.rendered.emit)
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(140)
        self.debounce.timeout.connect(self._request)
        self._build()
        self.set_recipe(self.recipe)

    def _build(self):
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(20, 16, 20, 14)
        top = QHBoxLayout()
        title = QLabel("BLOOD  /  DECAL LAB")
        title.setObjectName("title")
        top.addWidget(title)
        top.addStretch()
        for name, action in (("Load recipe", self.load_recipe), ("Save recipe", self.save_recipe)):
            button = QPushButton(name)
            button.clicked.connect(action)
            top.addWidget(button)
        self.export_button = QPushButton("Export textures...")
        self.export_button.setObjectName("export")
        self.export_button.clicked.connect(self.export_dialog)
        top.addWidget(self.export_button)
        outer.addLayout(top)
        subtitle = QLabel("Shape the liquid. Tune the material. Export editable textures.")
        subtitle.setObjectName("muted")
        outer.addWidget(subtitle)
        split = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(split, 1)
        sidebar = QWidget()
        sidebar.setMinimumWidth(325)
        sidebar.setMaximumWidth(480)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(0, 12, 14, 0)
        self.kind = QComboBox()
        for kind in lab.KINDS:
            self.kind.addItem(kind.title(), kind)
        self.kind.currentIndexChanged.connect(self._kind_changed)
        side.addWidget(self.kind)
        seed_row = QHBoxLayout()
        seed_row.addWidget(QLabel("Seed"))
        self.seed = QDoubleSpinBox()
        self.seed.setDecimals(0)
        self.seed.setRange(0, 2**32 - 1)
        self.seed.setKeyboardTracking(False)
        self.seed.valueChanged.connect(self._changed)
        seed_row.addWidget(self.seed, 1)
        shuffle = QPushButton("New seed")
        shuffle.clicked.connect(lambda: self.seed.setValue(random.randrange(2**32)))
        seed_row.addWidget(shuffle)
        side.addLayout(seed_row)
        tabs = QTabWidget()
        side.addWidget(tabs, 1)
        self.pages = {}
        for name in ("Shape", "Material"):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(0, 5, 9, 5)
            self.pages[name] = layout
            scroll.setWidget(page)
            tabs.addTab(scroll, name)
        self._parameters()
        for layout in self.pages.values():
            layout.addStretch()
        reset = QPushButton("Reset this family")
        reset.clicked.connect(lambda: self.set_recipe(replace(lab.preset(self.recipe.kind), seed=int(self.seed.value()), size=self.recipe.size)))
        side.addWidget(reset)
        split.addWidget(sidebar)

        workspace = QWidget()
        work = QVBoxLayout(workspace)
        work.setContentsMargins(14, 12, 0, 0)
        toolbar = QHBoxLayout()
        self.map_view = QComboBox()
        self.map_view.addItems(["Color", "Opacity", "Thickness", "Roughness", "Normals"])
        self.map_view.currentTextChanged.connect(self._display)
        toolbar.addWidget(self.map_view)
        self.background = QComboBox()
        self.background.addItems(["Light + dark", "Light", "Dark", "Checker"])
        self.background.currentTextChanged.connect(self._display)
        toolbar.addWidget(self.background)
        toolbar.addStretch()
        self.quality = QComboBox()
        self.quality.addItems(["Fast preview (256)", "Full resolution"])
        self.quality.setToolTip("Fast preview keeps the seed and parcel count, with fewer simulation steps and at most 256 pixels. Export always uses the full simulation and chosen texture resolution.")
        self.quality.currentIndexChanged.connect(self._changed)
        toolbar.addWidget(self.quality)
        self.view = PreviewView()
        for name, action in (("Fit", self.view.fit), ("1:1", self.view.actual_size)):
            button = QPushButton(name)
            button.clicked.connect(action)
            toolbar.addWidget(button)
        work.addLayout(toolbar)
        work.addWidget(self.view, 1)
        self.details = QLabel("First preview is generating...")
        self.details.setObjectName("muted")
        self.details.setWordWrap(True)
        work.addWidget(self.details)
        footer = QHBoxLayout()
        hint = QLabel("Wheel to zoom  /  Drag to pan  /  Color preview is unlit")
        hint.setObjectName("muted")
        footer.addWidget(hint, 1)
        self.folder_button = QPushButton("Open last export")
        self.folder_button.setEnabled(False)
        self.folder_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_export))))
        footer.addWidget(self.folder_button)
        work.addLayout(footer)
        split.addWidget(workspace)
        split.setSizes([350, 970])
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        outer.addWidget(self.progress)
        self.status = QLabel("Preparing preview...")
        self.status.setWordWrap(True)
        outer.addWidget(self.status)

    def _group(self, title, page="Shape"):
        box = QGroupBox(title)
        layout = QVBoxLayout(box)
        layout.setSpacing(2)
        self.pages[page].addWidget(box)
        self.groups[title] = box
        return layout

    def _number(self, layout, name, title, low, high, decimals=2, step=0.1, log=False, hint=""):
        control = NumberControl(title, low, high, decimals, step, log, hint)
        control.changed.connect(self._changed)
        self.controls[name] = control
        layout.addWidget(control)

    def _parameters(self):
        splatter = self._group("Fine splatter")
        self._number(splatter, "fine_splatter", "Amount", 0, 1, 2, 0.05,
                     hint="Fine streaks and droplets around the main deposit. 0 is off; 1 adds the most detail. The central shape stays fixed.")
        self._number(splatter, "splatter_length_mm", "Streak length (mm)", 0, 30, 1, 0.5,
                     hint="Length of the small tapered streaks. Set to 0 for droplets only. Higher viscosity shortens the streaks.")
        self._number(splatter, "splatter_spread_mm", "Scatter distance (mm)", 0, 60, 1, 1,
                     hint="How far the small fragments land from the edge of the main deposit. 0 keeps them at the rim.")
        liquid = self._group("Liquid")
        self._number(liquid, "volume_ml", "Volume (ml)", 0.001, 100, 3, 0.1, True)
        self._number(liquid, "speed_m_s", "Speed (m/s)", 0.01, 15, 2, 0.1, True)
        self._number(liquid, "viscosity_mpas", "Viscosity (mPa s)", 0.5, 100, 2, 0.5, True, "Higher viscosity limits spreading and reduces smear transfer.")
        self._number(liquid, "surface_tension_mnm", "Surface tension (mN/m)", 10, 150, 1, 1)
        self._number(liquid, "density_kg_m3", "Density (kg/m3)", 500, 2000, 0, 10)
        surface = self._group("Surface & direction")
        self._number(surface, "surface_roughness", "Surface irregularity", 0, 1, 2, 0.05, hint="Physical substrate irregularity, separate from the material's reflective roughness.")
        self._number(surface, "direction_deg", "Direction (degrees)", -360, 360, 1, 5)
        self._number(surface, "angle_deg", "Impact angle (degrees)", 0, 75, 1, 5, hint="0 is a perpendicular impact.")
        self._number(surface, "contact_angle_deg", "Pool wetting angle", 2, 80, 1, 1, hint="A smaller contact angle makes a wider, shallower pool.")
        drag = self._group("Drag path")
        self._number(drag, "drag_length_mm", "Length (mm)", 1, 1500, 1, 5, True)
        self._number(drag, "drag_width_mm", "Width (mm)", 1, 500, 1, 2, True)
        self._number(drag, "drag_curve", "Bend", -0.5, 0.5, 3, 0.025)
        output = self._group("Canvas & detail")
        self._number(output, "canvas_mm", "Canvas width (mm)", 10, 2000, 1, 10, True)
        resolution = QHBoxLayout()
        resolution.addWidget(QLabel("Texture resolution"), 1)
        self.resolution = QComboBox()
        self.resolution.addItems(["256", "512", "1024", "2048"])
        self.resolution.currentTextChanged.connect(self._changed)
        resolution.addWidget(self.resolution)
        output.addLayout(resolution)
        self._number(output, "parcels", "Fluid parcels", 1000, 100000, 0, 1000, True, "Higher counts reduce sampling artifacts and take longer to simulate.")
        color = self._group("Pigment", "Material")
        for name, title in (("deep_rgb", "Dense liquid"), ("thin_rgb", "Thin liquid")):
            control = ColorControl(title)
            control.changed.connect(self._changed)
            self.controls[name] = control
            color.addWidget(control)
        self._number(color, "absorption_mm", "Opacity depth (mm)", 0.001, 1, 3, 0.005, True, "Smaller values make thin liquid more opaque.")
        material = self._group("Reflective roughness", "Material")
        self._number(material, "wet_roughness", "Thick liquid", 0, 1, 2, 0.05)
        self._number(material, "dry_roughness", "Thin liquid", 0, 1, 2, 0.05)
        note = QLabel("0 = smooth, 1 = rough. Select Roughness above the preview to inspect this map.")
        note.setWordWrap(True)
        note.setObjectName("muted")
        material.addWidget(note)

    def set_recipe(self, recipe):
        recipe.validate()
        self.loading = True
        self.recipe = recipe
        self.saved[recipe.kind] = recipe
        self.kind.setCurrentIndex(lab.KINDS.index(recipe.kind))
        self.seed.setValue(recipe.seed)
        size = str(recipe.size)
        if self.resolution.findText(size) < 0:
            self.resolution.addItem(size)
        self.resolution.setCurrentText(size)
        for name, control in self.controls.items():
            control.set_value(getattr(recipe, name))
        self.loading = False
        self._visibility()
        self._changed()

    def _visibility(self):
        kind = self.recipe.kind
        self.groups["Drag path"].setVisible(kind == "smear")
        self.controls["angle_deg"].setVisible(kind in ("splash", "drops"))
        self.controls["contact_angle_deg"].setVisible(kind == "pool")
        for name in ("speed_m_s", "parcels"):
            self.controls[name].setVisible(kind != "pool")
        self.controls["viscosity_mpas"].setVisible(kind != "pool" or self.recipe.fine_splatter > 0)
        for name in ("surface_tension_mnm", "density_kg_m3"):
            self.controls[name].setVisible(kind != "smear")

    def _read(self):
        changes = {name: control.value() for name, control in self.controls.items()}
        changes["parcels"] = int(changes["parcels"])
        return replace(self.recipe, **changes, seed=int(self.seed.value()), size=int(self.resolution.currentText())).validate()

    def _preview_recipe(self):
        return replace(self.recipe, size=min(256, self.recipe.size)) if self.quality.currentIndex() == 0 else self.recipe

    def _kind_changed(self):
        if not self.loading:
            self.saved[self.recipe.kind] = self._read()
            self.set_recipe(self.saved[self.kind.currentData()])

    def _changed(self, *_):
        if self.loading:
            return
        self.recipe = self._read()
        self.saved[self.recipe.kind] = self.recipe
        self._visibility()
        self.revision = self.renderer.invalidate(self._preview_recipe(), draft=self.quality.currentIndex() == 0)
        self.status.setText("Updating preview...")
        self.progress.show()
        self.debounce.start()

    def _request(self):
        self.revision = self.renderer.request(self._preview_recipe(), draft=self.quality.currentIndex() == 0)

    @Slot(int, object, object)
    def _rendered(self, revision, result, error):
        if revision != self.revision:
            return
        self.progress.hide()
        if error:
            self.status.setText("Could not generate: " + error)
            return
        self.result = result
        self._display()
        stats = result.stats
        self.details.setText(f"{result.recipe.size} x {result.recipe.size} preview  |  {self.recipe.canvas_mm:g} mm canvas  |  "
                             f"{stats['deposited_ml']:.3f} ml deposited  |  {stats['carried_away_ml']:.3f} ml carried away")
        message = f"Ready in {result.seconds:.2f}s" + (" · material updated; shape reused" if result.reused_shape else "")
        if stats["outside_canvas_ml"] > self.recipe.volume_ml * 0.001 or stats["edge_ml"] > self.recipe.volume_ml * 0.0001:
            message += " · Mark reaches the border. Increase Canvas width to avoid clipping."
        if not self.exporting:
            self.status.setText(message)

    def _display(self, *_):
        if self.result is None:
            return
        name = self.map_view.currentText()
        self.background.setEnabled(name == "Color")
        if name == "Thickness":
            height = self.result.height
            image = lab.Image.fromarray(lab.np.round(height / max(float(height.max()), 1e-9) * 255).astype(lab.np.uint8))
        elif name == "Color":
            rgba = self.result.maps["color.png"]
            background = self.background.currentText()
            if background == "Light + dark":
                image = lab.Image.new("RGB", (rgba.width * 2, rgba.height))
                image.paste(lab.preview(rgba), (0, 0))
                image.paste(lab.preview(rgba, dark=True), (rgba.width, 0))
            elif background == "Checker":
                yy, xx = lab.np.indices((rgba.height, rgba.width))
                values = 110 + ((xx // 16 + yy // 16) % 2) * 35
                image = lab.Image.fromarray(lab.np.repeat(values[..., None], 3, axis=2).astype(lab.np.uint8)).convert("RGBA")
                image.alpha_composite(rgba)
            else:
                image = lab.preview(rgba, dark=background == "Dark")
        else:
            filename = {"Opacity": "opacity.png", "Roughness": "roughness.png", "Normals": "normal.png"}[name]
            image = self.result.maps[filename]
        self.view.show_image(image)

    def load_recipe(self):
        name, _ = QFileDialog.getOpenFileName(self, "Load a recipe", str(ROOT / "build/decal_lab"), "Recipe (*.json)")
        if name:
            try:
                self.set_recipe(lab.load_recipe(Path(name)))
            except (OSError, ValueError, TypeError) as error:
                QMessageBox.warning(self, "Cannot load recipe", str(error))

    def save_recipe(self):
        recipe = self._read()
        name, _ = QFileDialog.getSaveFileName(self, "Save recipe", str(ROOT / "build" / f"{recipe.kind}_{recipe.seed}.json"), "Recipe (*.json)")
        if name:
            try:
                Path(name).write_text(json.dumps(asdict(recipe), indent=2) + "\n", encoding="utf-8")
                self.status.setText(f"Recipe saved: {name}")
            except OSError as error:
                QMessageBox.warning(self, "Cannot save recipe", str(error))

    def export_dialog(self):
        parent = QFileDialog.getExistingDirectory(self, "Choose a parent folder for a new texture set", str(ROOT / "build"))
        if parent:
            self.start_export(Path(parent))

    def start_export(self, parent):
        if self.exporting:
            return
        recipe, cached = self._read(), self.result
        self.exporting = True
        self.export_button.setEnabled(False)
        self.export_button.setText("Exporting...")
        self.status.setText(f"Exporting {recipe.kind}, seed {recipe.seed}, at {recipe.size} x {recipe.size}...")
        # Export is a snapshot. Further slider changes cannot alter its recipe.
        def task():
            try:
                result = export_variant(recipe, parent, cached)
            except Exception as error:
                if not self.closed:
                    self.bridge.exported.emit(None, str(error))
            else:
                if not self.closed:
                    self.bridge.exported.emit(result, None)
        self.export_thread = threading.Thread(target=task, name="decal-export", daemon=False)
        self.export_thread.start()

    @Slot(object, object)
    def _exported(self, path, error):
        self.exporting = False
        self.export_button.setEnabled(True)
        self.export_button.setText("Export textures...")
        if error:
            self.status.setText("Export failed: " + error)
        else:
            self.last_export = path
            self.folder_button.setEnabled(True)
            self.status.setText(f"Textures and recipe saved: {path}")

    def closeEvent(self, event):
        self.closed = True
        self.debounce.stop()
        self.renderer.close()
        # An already requested export finishes in its non-daemon thread.
        event.accept()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="Open a saved recipe")
    args = parser.parse_args(argv)
    try:
        recipe = lab.load_recipe(args.config) if args.config else None
    except (OSError, ValueError, TypeError) as error:
        parser.error(str(error))
    app = QApplication.instance() or QApplication(sys.argv[:1])
    configure_app(app)
    window = DecalWindow(recipe)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
