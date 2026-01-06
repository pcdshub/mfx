"""
junk_plot.py
-------------
Lightweight camera viewer for EPICS PV-based cameras.

Usage as script:
    python junk_plot.py MFX:GIGE:02

Usage as module:
    import junk_plot
    junk_plot.live_view("MFX:GIGE:02", n_frames=200)
"""

import sys
import numpy as np
import matplotlib.pyplot as plt
from epics import caget


# ----------------------------------------------------------------------
# EPICS utility functions
# ----------------------------------------------------------------------

def get_image(PV):
    """Fetch image and reshape into 2D array."""
    arr = caget(PV + ":IMAGE1:ArrayData")
    nx = caget(PV + ":IMAGE1:ArraySize0_RBV")
    ny = caget(PV + ":IMAGE1:ArraySize1_RBV")

    if arr is None or nx is None or ny is None:
        raise RuntimeError(f"Failed to read camera PV: {PV}")

    return np.reshape(arr, (ny, nx))


def require_zero(PV, suffix, expected):
    """Helper for checks."""
    val = caget(PV + suffix)
    if val != expected:
        raise RuntimeError(f"[!] {PV}{suffix} must be {expected} (got {val})")


def check_color_mode(PV):
    """Ensure camera color mode is MONO (0)."""
    require_zero(PV, ":IMAGE1:ColorMode_RBV", 0)


def check_data_stream(PV):
    """Ensure NDArray stream is enabled."""
    require_zero(PV, ":IMAGE1:EnableCallbacks_RBV", 1)


def check_camviewer_config(PV):
    """Ensure ROI and Process plugins are disabled."""
    require_zero(PV, ":IMAGE1:ArrayCallbacks_RBV", 1)

    # Plugins that should be off:
    off_suffixes = [
        ":Proc1:EnableCallbacks_RBV",
        ":ROI1:EnableCallbacks_RBV",
    ]

    for suf in off_suffixes:
        val = caget(PV + suf)
        if val != 0:
            raise RuntimeError(
                f"[!] {PV}{suf} must be 0 for raw image display (got {val})"
            )
import numpy as np
from scipy.optimize import curve_fit

def gaussian2D(coords, amplitude, xo, yo, sigma_x, sigma_y, offset):
    x, y = coords
    xo = float(xo)
    yo = float(yo)

    g = offset + amplitude * np.exp(
        -(((x - xo)**2) / (2*sigma_x**2)
        + ((y - yo)**2) / (2*sigma_y**2))
    )
    return g.ravel()



# ----------------------------------------------------------------------
# Live viewer
# ----------------------------------------------------------------------

def live_view(PV, n_frames=200):
    """
    Simple live camera viewer.

    Parameters
    ----------
    PV : str
        Base PV name (e.g. 'MFX:GIGE:02')
    n_frames : int
        Number of frames to display
    """
    print(f"[+] Using camera PV: {PV}")
    print("[+] Checking EPICS configuration...")

    check_color_mode(PV)
    check_data_stream(PV)
    check_camviewer_config(PV)

    print("[+] Configuration OK. Starting viewer...")

    plt.ion()
    fig, ax = plt.subplots()
    im = None

    im = None
    cbar = None
    for ii in range(n_frames):
        try:
            frame = get_image(PV)
        except Exception as exc:
            print("[ERROR] Failed to read frame:", exc)
            break

        # ---------------------------------------------
        # 2D Gaussian fit (same for first and later frames)
        # ---------------------------------------------

        ny, nx = frame.shape
        x = np.arange(nx)
        y = np.arange(ny)
        X, Y = np.meshgrid(x, y)

        # Initial guesses
        amplitude0 = np.max(frame) - np.min(frame)
        offset0 = np.min(frame)
        xo0 = nx / 2
        yo0 = ny / 2
        sigma_x0 = nx / 6
        sigma_y0 = ny / 6

        p0 = [amplitude0, xo0, yo0, sigma_x0, sigma_y0, offset0]

        # Fit
        try:
            popt, pcov = curve_fit(
                gaussian2D,
                (X, Y),
                frame.ravel(),
                p0=p0,
                maxfev=8000
            )

            amplitude, xo, yo, sigma_x, sigma_y, offset = popt

            print(
                f"[Frame {ii}] Fit: center=({xo:.1f}, {yo:.1f}), "
                f"sigma=({sigma_x:.2f}, {sigma_y:.2f}), amp={amplitude:.1f}"
            )

        except Exception as exc:
            print("[WARNING] Gaussian fit failed for frame", ii, exc)

        # ---------------------------------------------
        # Your plotting / updating code
        # ---------------------------------------------
        if im is None:
            mean = np.mean(frame)
            std = np.std(frame)

            im = ax.imshow(frame, vmin=0, vmax=1)
            ax.set_title(f"Frame {ii}", fontsize=12)

            cbar = fig.colorbar(im, ax=ax)
            cbar.set_label("Intensity", fontsize=10)

            plt.pause(0.01)

        else:
            mean = np.mean(frame)
            std = np.std(frame)

            im.set_data(frame)
            im.set_clim(0, 1)

            if cbar is not None:
                cbar.update_normal(im)

            ax.set_title(f"Frame {ii}")
            fig.canvas.draw_idle()
            plt.pause(0.0001)

    plt.ioff()
    plt.show()
    print("[+] Viewer finished.")



# ----------------------------------------------------------------------
# Script entry point
# ----------------------------------------------------------------------

def main():
    """Command-line entry point."""
    if len(sys.argv) < 2:
        print("Usage: python junk_plot.py <PV>")
        sys.exit(1)

    PV = sys.argv[1]
    live_view(PV)


if __name__ == "__main__":
    main()
