# MFX Detector Viewer

A near-time detector image analysis tool for viewing and analyzing live PSANA-II detector data from the MFX beamline.

## Features

- **Live Data Streaming**: Connect to PSANA-II data source and view detector images in real-time
- **Multi-projection Analysis**: 
  - 2D detector image display with interactive histogram-based color scaling
  - X and Y projection plots for 1D analysis
  - Region of Interest (ROI) support for focused analysis
- **Reference Traces**: Save and compare multiple reference traces for X and Y projections independently
- **Autoscaling Control**: Toggle continuous autoscaling or manual color range adjustment
- **Detector Boundary Visualization**: Visual outline showing detector array boundaries
- **ADU Filtering**: Optional threshold filtering to remove low-energy noise
- **Flexible Detector Selection**: Choose which detector to view via configurable detector name field
- **Status Logging**: Real-time status messages for monitoring acquisition progress

## Requirements

- Python 3.7+
- PyQt5
- PyQtGraph
- NumPy
- PSANA (for data access at SLAC)

## Setup

Before running the application, you must source the appropriate environment:

```bash
source /sdf/group/lcls/ds/ana/sw/conda2/rel/lcls2_092225/setup_env.sh
```

This sets up all necessary dependencies including PSANA and Python libraries.

## Installation

```bash
pip install PyQt5 pyqtgraph numpy
```

## Usage

Run the application with:

```bash
python MFX_Detector_Viewer.py
```

### Configuration

Before starting acquisition, configure the following settings in the left control panel:

- **Experiment**: PSANA experiment ID (default: `mfx101259025`)
- **Run Number**: Run number to analyze (default: `105`)
- **Detector Name**: Detector to view (default: `epix100_0`)
- **Shots to Accumulate**: Number of events to average per display update (default: `10`)
- **ADU Threshold**: Minimum ADU value for signal (set to `0` to skip filtering)
- **Timeout (s)**: PSANA connection timeout in seconds (default: `30`)

### Controls

#### Image Display
- **Color Scale**: Toggle "Continuous Auto-scale" for automatic color ranging
- **Auto Range**: Reset axis ranges to fit current data
- **Reset Color Scale**: Recalculate color scale based on current image
- **Reset Detector Outline**: Redraw the detector boundary outline

#### Region of Interest (ROI)
- Drag the red ROI rectangle on the image to reposition
- Resize by dragging corners or edges
- Spinbox controls for precise coordinate entry

#### Projection References
- **Reference Button**: Save the current projection as a reference trace
- **Clear Refs Button**: Remove all reference traces for that projection
- References are displayed as dashed colored lines

#### Data Acquisition
- **Start Button**: Begin live data acquisition
- **Stop Button**: End data acquisition

### Window Layout

```
┌─────────────────────────────────────────────┐
│ MFX Detector Viewer                         │
├──────────────┬──────────────────────────────┤
│   Controls   │  Detector Image |  Y Proj    │
│   Panel      │  (with controls)|            │
│              │                 |            │
│  • Settings  ├──────────────────────────────┤
│  • Acq Ctrl  │  X Projection |  Status Box  │
│  • ROI Ctrl  │               |              │
│  • Ref Ctrl  │               |              │
└──────────────┴──────────────────────────────┘
```

## Tips

- Right-click on any plot for axis options and context menu
- Use mouse to pan and zoom plots (scroll wheel or drag)
- Drag histogram bars to manually adjust color range
- Use the red ROI rectangle to define analysis region
- Y axis labels on Y projection are positioned on the right side
- Detector outline helps identify image boundaries even with zero counts

## Status Messages

Real-time feedback appears in the Status Messages box:
- Acquisition start/stop events
- Reference trace operations
- Error messages
- Connection status

## Troubleshooting

**No data appearing**: 
- Verify experiment and run number are correct
- Check detector name matches available detectors
- Ensure PSANA connection is active

**ROI operations fail**: 
- Coordinates are automatically clamped to detector boundaries
- ROI cannot extend beyond detector edges

**Color scaling issues**:
- Use "Reset Color Scale" button to recalculate
- Ensure "Continuous Auto-scale" is enabled for automatic adjustment

## Performance Optimization

- Set ADU threshold to `0` to skip filtering step for faster processing
- Reduce "Shots to Accumulate" for lower latency
- Close unnecessary applications to free system resources
