"""
MFX Detector Viewer

A real-time detector image analysis tool for viewing and analyzing live PSANA-II 
detector data from the MFX beamline at SLAC. Provides interactive 2D image display,
1D projections, region of interest analysis, and reference trace capabilities.

"""

import sys
import numpy as np
from PyQt5 import QtWidgets, QtCore, QtGui
import pyqtgraph as pg
from psana import DataSource
from threading import Thread, Event
import queue

def filter_detector_adu(detector_images, adu_threshold=3.0):
    """
    Apply ADU (Analog-to-Digital Unit) threshold filtering to detector images.
    
    Removes low-energy noise by zeroing pixels below the threshold. If threshold 
    is 0, skips filtering entirely for performance optimization.
    
    Parameters
    ----------
    detector_images : ndarray
        2D detector image data
    adu_threshold : float or list, optional
        Threshold value(s). If float, pixels below this value are zeroed.
        If list [min, max], keeps only pixels between min and max (default: 3.0)
    
    Returns
    -------
    ndarray
        Filtered image with low ADU values removed
    """
    # Skip filtering if threshold is 0
    if adu_threshold == 0:
        return detector_images
    
    if isinstance(adu_threshold, list):
        detector_images_adu = detector_images * (detector_images > adu_threshold[0])
        detector_images_adu = detector_images_adu * (detector_images < adu_threshold[1])
    else:
        detector_images_adu = detector_images * (detector_images > adu_threshold)
    return detector_images_adu

class PSANALiveAnalysis(QtWidgets.QMainWindow):
    """
    Main application window for MFX Detector Viewer.
    
    Provides a PyQt5-based GUI for real-time visualization and analysis of 
    PSANA-II detector data. Features include live 2D image display, 1D projections,
    interactive ROI selection, reference trace management, and flexible detector
    configuration.
    
    Attributes
    ----------
    update_signal : QtCore.pyqtSignal
        Signal emitted to trigger GUI updates from worker thread
    status_signal : QtCore.pyqtSignal
        Signal to append messages to status message box
    accumulated_images : list
        Buffer of images awaiting accumulation
    current_image : ndarray
        Current accumulated/displayed detector image
    reference_x_projections : list
        Stored X projection reference curves
    reference_y_projections : list
        Stored Y projection reference curves
    running : threading.Event
        Flag to control acquisition thread
    data_queue : queue.Queue
        Thread-safe queue for image data from acquisition thread
    """
    
    # Signals for thread-safe GUI updates
    update_signal = QtCore.pyqtSignal()
    status_signal = QtCore.pyqtSignal(str)
    
    def __init__(self):
        """Initialize the application and UI components."""
        super().__init__()
        
        # Data storage
        self.accumulated_images = []
        self.current_image = None
        self.reference_x_projections = []
        self.reference_y_projections = []
        
        # Threading
        self.running = Event()
        self.data_queue = queue.Queue(maxsize=100)
        self.worker_thread = None
        self.event_counter = 0
        
        # Track if we've set initial levels
        self._image_levels_set = False
        
        # Track if boundary has been drawn
        self._boundary_drawn = False
        self.boundary_rect = None
        
        # Initialize UI
        self.init_ui()
        
        # Connect signals
        self.update_signal.connect(self.update_plots) # Note: This signal is defined but not emitted. Updates happen via the timer.
        self.status_signal.connect(self.update_status)
        
        # Start update timer
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.check_queue)
        self.timer.start(100)  # 100ms updates
        
    def init_ui(self):
        """
        Initialize the user interface.
        
        Creates the main window layout with control panel on the left and 
        visualization panels on the right. Sets window title and geometry.
        """
        self.setWindowTitle("MFX Detector Viewer")
        self.setGeometry(100, 100, 1600, 1000)
        
        # Central widget
        central_widget = QtWidgets.QWidget()
        self.setCentralWidget(central_widget)
        
        # Main layout
        main_layout = QtWidgets.QHBoxLayout(central_widget)
        
        # Left panel - Controls
        control_panel = self.create_control_panel()
        main_layout.addWidget(control_panel)
        
        # Right panel - Plots
        plot_panel = self.create_plot_panel()
        main_layout.addWidget(plot_panel, stretch=1)
    
    def create_control_panel(self):
        """
        Create the left control panel with acquisition and analysis settings.
        
        Builds UI elements for configuring:
        - Experiment and run selection
        - Detector identification
        - Accumulation parameters
        - ADU filtering threshold
        - ROI coordinates
        - Reference trace management
        
        Returns
        -------
        QtWidgets.QWidget
            Configured control panel widget
        """
        panel = QtWidgets.QWidget()
        panel.setMaximumWidth(350)
        layout = QtWidgets.QVBoxLayout(panel)
        
        # Title
        title = QtWidgets.QLabel("MFX Detector Viewer")
        title.setStyleSheet("""
            font-size: 16px; 
            font-weight: bold;
            color: rgb(247, 130, 40);
            text-shadow: -1px -1px 0 #000, 1px -1px 0 #000, -1px 1px 0 #000, 1px 1px 0 #000;
        """)
        layout.addWidget(title)
        
        # Acquisition Settings
        acq_group = QtWidgets.QGroupBox("Acquisition Settings")
        acq_layout = QtWidgets.QFormLayout()
        
        self.experiment_edit = QtWidgets.QLineEdit("mfx101259025")
        acq_layout.addRow("Experiment:", self.experiment_edit)
        
        self.run_number_spin = QtWidgets.QSpinBox()
        self.run_number_spin.setRange(0, 100000)
        self.run_number_spin.setValue(105)
        acq_layout.addRow("Run Number:", self.run_number_spin)
        
        self.detector_name_edit = QtWidgets.QLineEdit("epix100_0")
        acq_layout.addRow("Detector Name:", self.detector_name_edit)
        
        self.accumulation_spin = QtWidgets.QSpinBox()
        self.accumulation_spin.setRange(1, 1000)
        self.accumulation_spin.setValue(10)
        acq_layout.addRow("Shots to Accumulate:", self.accumulation_spin)
        
        self.adu_threshold_spin = QtWidgets.QDoubleSpinBox()
        self.adu_threshold_spin.setRange(0, 1000)
        self.adu_threshold_spin.setValue(3.0)
        self.adu_threshold_spin.setDecimals(1)
        acq_layout.addRow("ADU Threshold:", self.adu_threshold_spin)
        
        self.timeout_spin = QtWidgets.QSpinBox()
        self.timeout_spin.setRange(1, 300)
        self.timeout_spin.setValue(30)
        acq_layout.addRow("Timeout (s):", self.timeout_spin)
        
        acq_group.setLayout(acq_layout)
        layout.addWidget(acq_group)
        
        # Control Buttons
        button_layout = QtWidgets.QHBoxLayout()
        self.start_button = QtWidgets.QPushButton("Start")
        self.start_button.clicked.connect(self.start_acquisition)
        self.stop_button = QtWidgets.QPushButton("Stop")
        self.stop_button.clicked.connect(self.stop_acquisition)
        self.stop_button.setEnabled(False)
        button_layout.addWidget(self.start_button)
        button_layout.addWidget(self.stop_button)
        layout.addLayout(button_layout)
        
        # Initialize color scale controls that will be added to image widget
        self.auto_color_scale_check = QtWidgets.QCheckBox("Continuous Auto-scale")
        self.auto_color_scale_check.setChecked(False)
        self.auto_color_scale_check.setToolTip(
            "When checked: Automatically rescale color range on each new image\n"
            "When unchecked: Use histogram widget to manually adjust color range"
        )
        self.auto_color_scale_check.stateChanged.connect(self.update_autoscale_indicator)
        self.update_autoscale_indicator()  # Set initial color
        
        # ROI Settings
        roi_group = QtWidgets.QGroupBox("ROI Settings")
        roi_layout = QtWidgets.QFormLayout()
        
        self.roi_x0_spin = QtWidgets.QSpinBox()
        self.roi_x0_spin.setRange(0, 760)
        self.roi_x0_spin.setValue(100)
        self.roi_x0_spin.valueChanged.connect(self.update_roi_from_spinbox)
        roi_layout.addRow("X Start:", self.roi_x0_spin)
        
        self.roi_x1_spin = QtWidgets.QSpinBox()
        self.roi_x1_spin.setRange(0, 760)
        self.roi_x1_spin.setValue(300)
        self.roi_x1_spin.valueChanged.connect(self.update_roi_from_spinbox)
        roi_layout.addRow("X End:", self.roi_x1_spin)
        
        self.roi_y0_spin = QtWidgets.QSpinBox()
        self.roi_y0_spin.setRange(0, 760)
        self.roi_y0_spin.setValue(100)
        self.roi_y0_spin.valueChanged.connect(self.update_roi_from_spinbox)
        roi_layout.addRow("Y Start:", self.roi_y0_spin)
        
        self.roi_y1_spin = QtWidgets.QSpinBox()
        self.roi_y1_spin.setRange(0, 760)
        self.roi_y1_spin.setValue(300)
        self.roi_y1_spin.valueChanged.connect(self.update_roi_from_spinbox)
        roi_layout.addRow("Y End:", self.roi_y1_spin)
        
        roi_group.setLayout(roi_layout)
        layout.addWidget(roi_group)
        
        # Reference Buttons
        ref_layout = QtWidgets.QVBoxLayout()
        self.reference_button = QtWidgets.QPushButton("Reference Current")
        self.reference_button.clicked.connect(self.reference_current)
        self.clear_ref_button = QtWidgets.QPushButton("Clear References")
        self.clear_ref_button.clicked.connect(self.clear_references)
        ref_layout.addWidget(self.reference_button)
        ref_layout.addWidget(self.clear_ref_button)
        layout.addLayout(ref_layout)
        
        # Instructions
        instructions = QtWidgets.QLabel(
            "Tips:\n"
            "• Right-click plots for axis options\n"
            "• Use mouse to pan/zoom plots\n"
            "• Drag histogram bars to adjust color\n"
            "• Drag/resize red ROI on image"
        )
        instructions.setWordWrap(True)
        instructions.setStyleSheet("QLabel { background-color: #f0f0f0; padding: 10px; }")
        layout.addWidget(instructions)
        
        # Add stretch to push everything to top
        layout.addStretch()
        
        return panel
        
    def create_plot_panel(self):
        """
        Create the right visualization panel with detector image and projection plots.
        
        Builds the main analysis interface with:
        - 2D detector image display with histogram color adjustment
        - Y projection plot (transposed coordinates with right-axis labels)
        - X projection plot (full width) below image
        - Status message box for logging
        - ROI rectangle for region selection
        - Detector boundary outline
        
        Returns
        -------
        QtWidgets.QWidget
            Configured plot panel widget
        """
        panel = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setSpacing(20)
        
        # Configure PyQtGraph globally
        pg.setConfigOptions(
            antialias=True, 
            imageAxisOrder='row-major'
        )
        
        # Top row: Image and Y projection
        top_layout = QtWidgets.QHBoxLayout()
        
        # Image plot with controls
        image_container = QtWidgets.QVBoxLayout()
        
        # Image scaling controls (Color Scale)
        color_scale_layout = QtWidgets.QHBoxLayout()
        color_scale_layout.addWidget(QtWidgets.QLabel("Color Scale:"))
        color_scale_layout.addWidget(self.auto_color_scale_check)
        color_scale_layout.addStretch()
        image_container.addLayout(color_scale_layout)
        
        # Image control buttons
        image_controls = QtWidgets.QHBoxLayout()
        img_auto_btn = QtWidgets.QPushButton("Auto Range")
        img_auto_btn.setToolTip("Auto-range both X and Y axes")
        img_auto_btn.clicked.connect(lambda: self.image_plot.autoRange())
        
        img_auto_x_btn = QtWidgets.QPushButton("Auto X")
        img_auto_x_btn.setToolTip("Auto-range X axis only")
        img_auto_x_btn.clicked.connect(lambda: self.image_plot.getViewBox().enableAutoRange(axis=pg.ViewBox.XAxis))
        
        img_auto_y_btn = QtWidgets.QPushButton("Auto Y")
        img_auto_y_btn.setToolTip("Auto-range Y axis only")
        img_auto_y_btn.clicked.connect(lambda: self.image_plot.getViewBox().enableAutoRange(axis=pg.ViewBox.YAxis))
        
        img_reset_color_btn = QtWidgets.QPushButton("Reset Color Scale")
        img_reset_color_btn.setToolTip("Reset color scale to current image range")
        img_reset_color_btn.clicked.connect(self.reset_color_scale)
        
        img_reset_boundary_btn = QtWidgets.QPushButton("Reset Detector Outline")
        img_reset_boundary_btn.setToolTip("Reset the detector boundary outline")
        img_reset_boundary_btn.clicked.connect(self.reset_detector_outline)
        
        image_controls.addWidget(img_auto_btn)
        image_controls.addWidget(img_auto_x_btn)
        image_controls.addWidget(img_auto_y_btn)
        image_controls.addWidget(img_reset_color_btn)
        image_controls.addWidget(img_reset_boundary_btn)
        image_controls.addStretch()
        
        self.image_widget = pg.GraphicsLayoutWidget()
        self.image_plot = self.image_widget.addPlot(title="Detector Image")
        self.image_plot.setAspectLocked(True)
        self.image_plot.setLabel('bottom', 'X Pixel')
        self.image_plot.setLabel('left', 'Y Pixel')
        
        self.image_item = pg.ImageItem()
        self.image_plot.addItem(self.image_item)
        
        colormap = pg.colormap.get('viridis')
        self.image_item.setColorMap(colormap)
        
        self.hist = pg.HistogramLUTItem()
        self.hist.setImageItem(self.image_item)
        self.image_widget.addItem(self.hist)
        
        self.roi_rect = pg.ROI([100, 100], [200, 200], pen=pg.mkPen('r', width=2), movable=True, resizable=True)
        self.roi_rect.addScaleHandle([1, 1], [0, 0])
        self.roi_rect.addScaleHandle([0, 0], [1, 1])
        self.image_plot.addItem(self.roi_rect)
        self.roi_rect.sigRegionChanged.connect(self.update_roi_from_drag)
        
        image_container.addLayout(image_controls)
        image_container.addWidget(self.image_widget)
        
        top_layout.addLayout(image_container, stretch=3)
        
        # Y projection plot
        y_proj_container = QtWidgets.QVBoxLayout()
        y_proj_controls = QtWidgets.QHBoxLayout()
        y_auto_btn = QtWidgets.QPushButton("Auto Range")
        y_auto_btn.clicked.connect(lambda: self.y_proj_widget.autoRange())
        y_ref_btn = QtWidgets.QPushButton("Reference")
        y_ref_btn.clicked.connect(self.reference_y_projection)
        y_clear_ref_btn = QtWidgets.QPushButton("Clear Refs")
        y_clear_ref_btn.clicked.connect(self.clear_y_references)
        y_proj_controls.addWidget(y_auto_btn)
        y_proj_controls.addWidget(y_ref_btn)
        y_proj_controls.addWidget(y_clear_ref_btn)
        y_proj_controls.addStretch()

        self.y_proj_widget = pg.PlotWidget(title="Y Projection")
        self.y_proj_widget.setLabel('bottom', 'Intensity')
        self.y_proj_widget.setLabel('right', 'Y Pixel', angle=180)
        self.y_proj_widget.getAxis('right').setStyle(showValues=True)
        self.y_proj_widget.getAxis('left').setStyle(showValues=False)
        self.y_proj_widget.showGrid(x=True, y=True, alpha=0.3)
        self.y_proj_widget.addLegend()

        self.y_proj_curve = self.y_proj_widget.plot(
            pen=pg.mkPen('c', width=2), 
            name='Current'
        )
        self.y_proj_refs = []
        
        y_proj_container.addLayout(y_proj_controls)
        y_proj_container.addWidget(self.y_proj_widget)
        top_layout.addLayout(y_proj_container, stretch=1)
        
        layout.addLayout(top_layout, stretch=3)
        
        # Bottom row: X projection and Status message box
        bottom_layout = QtWidgets.QHBoxLayout()
        
        # X projection plot (full width)
        x_proj_container = QtWidgets.QVBoxLayout()
        x_proj_controls = QtWidgets.QHBoxLayout()
        x_auto_btn = QtWidgets.QPushButton("Auto Range")
        x_auto_btn.clicked.connect(lambda: self.x_proj_widget.autoRange())
        x_ref_btn = QtWidgets.QPushButton("Reference")
        x_ref_btn.clicked.connect(self.reference_x_projection)
        x_clear_ref_btn = QtWidgets.QPushButton("Clear Refs")
        x_clear_ref_btn.clicked.connect(self.clear_x_references)
        x_proj_controls.addWidget(x_auto_btn)
        x_proj_controls.addWidget(x_ref_btn)
        x_proj_controls.addWidget(x_clear_ref_btn)
        x_proj_controls.addStretch()

        self.x_proj_widget = pg.PlotWidget(title="X Projection")
        self.x_proj_widget.setLabel('bottom', 'X Pixel')
        self.x_proj_widget.setLabel('left', 'Intensity')
        self.x_proj_widget.showGrid(x=True, y=True, alpha=0.3)
        self.x_proj_widget.addLegend()

        self.x_proj_curve = self.x_proj_widget.plot(
            pen=pg.mkPen('m', width=2),
            name='Current'
        )
        self.x_proj_refs = []
        
        x_proj_container.addLayout(x_proj_controls)
        x_proj_container.addWidget(self.x_proj_widget)
        bottom_layout.addLayout(x_proj_container, stretch=3)
        
        # Status message box (bottom right)
        status_container = QtWidgets.QVBoxLayout()
        status_label = QtWidgets.QLabel("Status Messages")
        status_label.setStyleSheet("font-weight: bold;")
        status_container.addWidget(status_label)
        
        self.status_message_box = QtWidgets.QTextEdit()
        self.status_message_box.setReadOnly(True)
        self.status_message_box.setMaximumHeight(150)
        self.status_message_box.setMaximumWidth(300)
        status_container.addWidget(self.status_message_box)
        status_container.addStretch()
        
        bottom_layout.addLayout(status_container, stretch=1)
        layout.addLayout(bottom_layout, stretch=1)
        
        return panel

    # --- Plotting and ROI Methods ---

    def update_plots(self):
        """
        Update all visualization plots with current image data.
        
        Main entry point for graphical updates. Calls specialized update methods
        for image display and projection plots. Called via timer at ~10 Hz rate.
        """
        if self.current_image is None:
            return
        
        self.update_image_plot()
        self.update_projection_plots()

    def update_image_plot(self):
        """
        Update the 2D detector image display.
        
        Refreshes image data, applies color scaling (auto or manual), draws
        detector boundary on first update, and manages axis ranges. Uses
        1st to 99th percentile for color scaling.
        """
        h, w = self.current_image.shape
        self.image_item.setImage(self.current_image, autoLevels=False)
        
        if self.auto_color_scale_check.isChecked():
            vmin, vmax = np.percentile(
                self.current_image, 
                [1, 99]
            )
            self.image_item.setLevels([vmin, vmax])
        elif not self._image_levels_set:
            vmin, vmax = np.percentile(
                self.current_image, 
                [1, 99]
            )
            self.image_item.setLevels([vmin, vmax])
            self._image_levels_set = True

        self.image_plot.setTitle(f"Detector Image (Events: {self.event_counter})")
        
        if not hasattr(self, '_image_range_set'):
            self.image_plot.setRange(xRange=[0, w], yRange=[0, h], padding=0)
            self._image_range_set = True
        
        # Draw boundary rectangle once on first image
        if not self._boundary_drawn:
            self.draw_detector_outline(w, h)

    def draw_detector_outline(self, w, h):
        """
        Draw the detector boundary outline.
        
        Creates a white dashed rectangle showing the detector image array boundaries.
        
        Parameters
        ----------
        w : int
            Detector image width in pixels
        h : int
            Detector image height in pixels
        """
        # Create boundary as a simple rectangle using PlotCurveItem
        pen = pg.mkPen('white', width=2, style=QtCore.Qt.DashLine)
        
        # Create the four corners of the rectangle
        x_coords = [0, w, w, 0, 0]
        y_coords = [0, 0, h, h, 0]
        
        self.boundary_rect = pg.PlotCurveItem(x_coords, y_coords, pen=pen, clickable=False)
        self.boundary_rect.setZValue(-1)  # Keep it behind other items
        self.image_plot.addItem(self.boundary_rect)
        self._boundary_drawn = True
    
    def reset_detector_outline(self):
        """
        Reset the detector boundary outline.
        
        Removes the current outline and redraws it based on current image dimensions.
        Emits status message upon completion.
        """
        if self.boundary_rect is not None:
            self.image_plot.removeItem(self.boundary_rect)
            self.boundary_rect = None
        
        if self.current_image is not None:
            h, w = self.current_image.shape
            self.draw_detector_outline(w, h)
            self.status_signal.emit("Detector outline reset")


    def update_projection_plots(self):
        """
        Update X and Y projection plots based on ROI selection.
        
        Calculates and plots 1D projections of the current image within the
        user-defined ROI. Coordinates are automatically clamped to detector bounds.
        X projection is averaged over Y, Y projection averaged over X.
        """
        x0 = int(self.roi_x0_spin.value())
        x1 = int(self.roi_x1_spin.value())
        y0 = int(self.roi_y0_spin.value())
        y1 = int(self.roi_y1_spin.value())
        
        h, w = self.current_image.shape
        x0, x1 = max(0, min(x0, x1)), min(w, max(x0, x1))
        y0, y1 = max(0, min(y0, y1)), min(h, max(y0, y1))
        
        if x1 <= x0 or y1 <= y0:
            self.x_proj_curve.setData([], [])
            self.y_proj_curve.setData([], [])
            return
        
        roi = self.current_image[y0:y1, x0:x1]
        
        # X projection
        x_proj = np.mean(roi, axis=0)
        x_vals = np.arange(x0, x1)
        self.x_proj_curve.setData(x_vals, x_proj)
        
        # Y projection (plotted horizontally)
        y_proj = np.mean(roi, axis=1)
        y_vals = np.arange(y0, y1)
        self.y_proj_curve.setData(y_proj, y_vals) # Data is (intensity, pixel_coord)

    def update_autoscale_indicator(self):
        """
        Update the autoscale checkbox label color.
        
        Sets checkbox text color to green when autoscaling is enabled,
        red when disabled. Provides visual feedback of autoscale state.
        """
        if self.auto_color_scale_check.isChecked():
            self.auto_color_scale_check.setStyleSheet("QCheckBox { color: green; font-weight: bold; }")
        else:
            self.auto_color_scale_check.setStyleSheet("QCheckBox { color: red; font-weight: bold; }")

    def update_roi_from_spinbox(self):
        """
        Update ROI rectangle when spinbox values change.
        
        Synchronizes the ROI rectangle on the image with coordinate values
        from the control panel spinboxes. Prevents recursive updates using signals.
        """
        # Block signals to prevent a feedback loop
        self.roi_rect.sigRegionChanged.disconnect(self.update_roi_from_drag)
        
        x0 = self.roi_x0_spin.value()
        y0 = self.roi_y0_spin.value()
        w = self.roi_x1_spin.value() - x0
        h = self.roi_y1_spin.value() - y0
        
        self.roi_rect.setPos([x0, y0], finish=False)
        self.roi_rect.setSize([w, h], finish=False)
        
        # Re-enable signals
        self.roi_rect.sigRegionChanged.connect(self.update_roi_from_drag)
        self.update_projection_plots() # Update projections on spinbox change
    
    def update_roi_from_drag(self):
        """
        Update spinboxes when ROI is dragged or resized on the image.
        
        Synchronizes control panel coordinate spinboxes with ROI rectangle position
        and size. Prevents recursive updates using signal blocking.
        """
        pos = self.roi_rect.pos()
        size = self.roi_rect.size()
        
        x0 = int(pos.x())
        y0 = int(pos.y())
        x1 = int(pos.x() + size.x())
        y1 = int(pos.y() + size.y())

        # Block signals to prevent a feedback loop
        for spin in [self.roi_x0_spin, self.roi_x1_spin, self.roi_y0_spin, self.roi_y1_spin]:
            spin.blockSignals(True)
        
        self.roi_x0_spin.setValue(x0)
        self.roi_y0_spin.setValue(y0)
        self.roi_x1_spin.setValue(x1)
        self.roi_y1_spin.setValue(y1)
        
        for spin in [self.roi_x0_spin, self.roi_x1_spin, self.roi_y0_spin, self.roi_y1_spin]:
            spin.blockSignals(False)

        if self.current_image is not None:
             self.update_projection_plots() # Update projections on drag
    
    def reset_color_scale(self):
        """
        Reset color scale to match current image dynamic range.
        
        Recalculates color levels using 1st to 99th percentile of current image.
        Updates both image display and histogram widget.
        """
        if self.current_image is not None:
            vmin, vmax = np.percentile(
                self.current_image, 
                [1, 99]
            )
            self.image_item.setLevels([vmin, vmax])
            self.hist.setLevels(vmin, vmax)

    # --- Acquisition and Threading Methods ---

    def start_acquisition(self):
        """
        Start data acquisition from PSANA.
        
        Launches worker thread to retrieve detector images from the data source.
        Updates UI to reflect acquisition state. Clears buffers to avoid stale data.
        """
        if self.running.is_set():
            return
            
        self.running.set()
        self.event_counter = 0
        self.accumulated_images.clear()
        
        # Clear the queue in case of stale data
        while not self.data_queue.empty():
            self.data_queue.get()

        self.worker_thread = Thread(target=self.acquisition_loop, daemon=True)
        self.worker_thread.start()
        
        self.status_signal.emit(
            f"Status: Running (Exp: {self.experiment_edit.text()}, "
            f"Run: {self.run_number_spin.value()})"
        )
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
    
    def stop_acquisition(self):
        """
        Stop data acquisition and worker thread.
        
        Signals worker thread to exit gracefully and updates UI accordingly.
        """
        self.running.clear()
        if self.worker_thread and self.worker_thread.is_alive():
            self.worker_thread.join(timeout=2.0)
        
        self.status_signal.emit("Status: Stopped")
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
    
    def acquisition_loop(self):
        """
        Background worker thread for PSANA data acquisition.
        
        Connects to PSANA data source, retrieves detector images, applies ADU filtering,
        and queues images for main GUI thread. Runs continuously until stopped.
        Handles connection errors gracefully and updates UI via signals.
        """
        import os
        os.environ['PS_SMD_MAX_RETRIES'] = str(self.timeout_spin.value())
        
        try:
            ds = DataSource(
                exp=self.experiment_edit.text(),
                run=self.run_number_spin.value(),
                live=True
            )
            
            myrun = next(ds.runs())
            detector_name = self.detector_name_edit.text()
            detector = myrun.Detector(detector_name)
            
            for evt in myrun.events():
                if not self.running.is_set():
                    break
                
                raw_data = detector.raw.image(evt)
                
                if raw_data is not None:
                    # Perform filtering in the worker thread to offload CPU
                    filtered_image = filter_detector_adu(
                        raw_data, 
                        adu_threshold=self.adu_threshold_spin.value()
                    )
                    try:
                        self.data_queue.put(filtered_image, timeout=1.0)
                        self.event_counter += 1
                    except queue.Full:
                        # If queue is full, GUI is lagging, so just drop the frame
                        continue
        
        except Exception as e:
            self.status_signal.emit(f"Status: Error - {str(e)}")
            # Safely re-enable UI controls from the worker thread
            QtCore.QMetaObject.invokeMethod(self.start_button, "setEnabled", QtCore.Qt.QueuedConnection, QtCore.Q_ARG(bool, True))
            QtCore.QMetaObject.invokeMethod(self.stop_button, "setEnabled", QtCore.Qt.QueuedConnection, QtCore.Q_ARG(bool, False))
        finally:
            self.running.clear()
            
    def check_queue(self):
        """
        Check acquisition queue for new images and accumulate.
        
        Called periodically by main GUI timer (~10 Hz). Retrieves images from
        worker thread queue, accumulates them, and triggers plot updates when
        sufficient images have been accumulated. Called via QTimer timeout signal.
        """
        new_images = []
        while not self.data_queue.empty():
            try:
                new_images.append(self.data_queue.get_nowait())
            except queue.Empty:
                break
        
        if not new_images:
            return

        self.accumulated_images.extend(new_images)
        shots_to_accumulate = self.accumulation_spin.value()
        
        if len(self.accumulated_images) >= shots_to_accumulate:
            # Take exactly the number of shots needed for one update
            images_to_process = self.accumulated_images[:shots_to_accumulate]
            self.accumulated_images = self.accumulated_images[shots_to_accumulate:]
            
            self.current_image = np.mean(images_to_process, axis=0)
            
            # This single call updates all plots
            self.update_plots()

    # --- Reference and Status Methods ---
    
    def reference_x_projection(self):
        """
        Save current X projection as a reference trace.
        
        Captures the mean projection along Y axis for the current ROI and stores
        as a colored dashed line. Multiple references can be saved with cycling colors.
        Coordinates are clamped to detector boundaries.
        """
        if self.current_image is None:
            return
        
        x0 = int(self.roi_x0_spin.value())
        x1 = int(self.roi_x1_spin.value())
        y0 = int(self.roi_y0_spin.value())
        y1 = int(self.roi_y1_spin.value())
        
        h, w = self.current_image.shape
        # Clamp ROI to detector bounds
        x0, x1 = max(0, min(x0, x1)), min(w, max(x0, x1))
        y0, y1 = max(0, min(y0, y1)), min(h, max(y0, y1))
        
        roi = self.current_image[y0:y1, x0:x1]
        
        if roi.size > 0:
            # Define reference colors - use bright, contrasting colors
            ref_colors = ['yellow', 'lime', 'red', 'cyan', 'orange', 'white']
            ref_index = len(self.x_proj_refs) % len(ref_colors)
            ref_color = ref_colors[ref_index]
            
            # X projection reference
            x_proj = np.mean(roi, axis=0)
            x_vals = np.arange(x0, x1)
            ref_curve_x = self.x_proj_widget.plot(
                x_vals, x_proj,
                pen=pg.mkPen(ref_color, width=2, style=QtCore.Qt.DashLine),
                name=f'Ref {len(self.x_proj_refs)+1}'
            )
            self.x_proj_refs.append(ref_curve_x)
            self.status_signal.emit(f"X Projection: Reference added. {len(self.x_proj_refs)} refs.")
    
    def reference_y_projection(self):
        """
        Save current Y projection as a reference trace.
        
        Captures the mean projection along X axis for the current ROI and stores
        as a colored dashed line. Multiple references can be saved with cycling colors.
        Coordinates are clamped to detector boundaries.
        """
        if self.current_image is None:
            return
        
        x0 = int(self.roi_x0_spin.value())
        x1 = int(self.roi_x1_spin.value())
        y0 = int(self.roi_y0_spin.value())
        y1 = int(self.roi_y1_spin.value())
        
        h, w = self.current_image.shape
        # Clamp ROI to detector bounds
        x0, x1 = max(0, min(x0, x1)), min(w, max(x0, x1))
        y0, y1 = max(0, min(y0, y1)), min(h, max(y0, y1))
        
        roi = self.current_image[y0:y1, x0:x1]
        
        if roi.size > 0:
            # Define reference colors - use bright, contrasting colors
            ref_colors = ['yellow', 'lime', 'red', 'cyan', 'orange', 'white']
            ref_index = len(self.y_proj_refs) % len(ref_colors)
            ref_color = ref_colors[ref_index]
            
            # Y projection reference
            y_proj = np.mean(roi, axis=1)
            y_vals = np.arange(y0, y1)
            ref_curve_y = self.y_proj_widget.plot(
                y_proj, y_vals,
                pen=pg.mkPen(ref_color, width=2, style=QtCore.Qt.DashLine),
                name=f'Ref {len(self.y_proj_refs)+1}'
            )
            self.y_proj_refs.append(ref_curve_y)
            self.status_signal.emit(f"Y Projection: Reference added. {len(self.y_proj_refs)} refs.")
    
    def reference_current(self):
        """
        Save current projections as reference traces for both X and Y.
        
        Convenience method that calls both reference_x_projection() and
        reference_y_projection() for simultaneous X and Y reference capture.
        """
        self.reference_x_projection()
        self.reference_y_projection()
    
    def clear_x_references(self):
        """
        Clear all reference traces from the X projection plot.
        
        Removes all stored reference curves and emits status message.
        """
        for ref_curve in self.x_proj_refs:
            self.x_proj_widget.removeItem(ref_curve)
        
        self.x_proj_refs.clear()
        self.status_signal.emit("X Projection: References cleared")
    
    def clear_y_references(self):
        """
        Clear all reference traces from the Y projection plot.
        
        Removes all stored reference curves and emits status message.
        """
        for ref_curve in self.y_proj_refs:
            self.y_proj_widget.removeItem(ref_curve)
        
        self.y_proj_refs.clear()
        self.status_signal.emit("Y Projection: References cleared")
    
    def clear_references(self):
        """
        Clear all reference traces from both X and Y projection plots.
        
        Convenience method that calls both clear_x_references() and
        clear_y_references() to remove all saved references at once.
        """
        self.clear_x_references()
        self.clear_y_references()
    
    def update_status(self, message):
        """
        Update the status message box with timestamped message.
        
        Appends message to status box with current time. Maintains rolling buffer
        of last 20 messages to prevent excessive memory growth. Thread-safe via signal.
        
        Parameters
        ----------
        message : str
            Status message text to display
        """
        # Append message to the text box with a timestamp
        current_text = self.status_message_box.toPlainText()
        timestamp = QtCore.QDateTime.currentDateTime().toString("hh:mm:ss")
        new_message = f"[{timestamp}] {message}"
        
        # Keep only the last 20 messages to avoid excessive growth
        lines = current_text.split('\n') if current_text else []
        lines.append(new_message)
        if len(lines) > 20:
            lines = lines[-20:]
        
        self.status_message_box.setPlainText('\n'.join(lines))
        # Scroll to bottom
        self.status_message_box.verticalScrollBar().setValue(
            self.status_message_box.verticalScrollBar().maximum()
        )
    
    def closeEvent(self, event):
        """
        Handle window close event to safely stop threads and cleanup.
        
        Stops acquisition thread and timer before allowing window to close.
        Ensures no background threads continue after application exit.
        """
        self.stop_acquisition()
        self.timer.stop()
        event.accept()

def main():
    """
    Main entry point for MFX Detector Viewer application.
    
    Creates QApplication, initializes main window, and starts event loop.
    """
    app = QtWidgets.QApplication(sys.argv)
    app.setStyle('Fusion')
    window = PSANALiveAnalysis()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()