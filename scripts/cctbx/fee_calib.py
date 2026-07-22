from __future__ import absolute_import, division, print_function
# LIBTBX_SET_DISPATCHER_NAME cctbx.xfel.fee_calib

from dials.util.options import OptionParser
from libtbx.phil import parse
import sys
import io
import psana
import numpy as np
from scipy.signal import savgol_filter
from scipy.stats import linregress
import matplotlib.pyplot as plt
from scipy.optimize import curve_fit

# Define the PHIL scope
phil_scope = parse("""
calibration {
    exp = None
        .type = str
        .help = Experiment name
    run_start = None
        .type = int
        .help = First run number
    energy_start = None
        .type = float
        .help = Starting photon energy in eV
    energy_step = None
        .type = float
        .help = Energy step size between runs in eV
    n_runs = None
        .type = int
        .help = Number of runs to process
    detector = 'feespec'
        .type = str
        .help = Detector name
    events_per_run = 1000
        .type = int
        .help = Maximum events to process per run
    fit_window = 300
        .type = int
        .help = Points around maximum for Gaussian peak fit
    savgol_window = 51
        .type = int
        .help = Window size for Savitzky-Golay filter
    savgol_order = 3
        .type = int
        .help = Polynomial order for Savitzky-Golay filter
    plot = True
        .type = bool
        .help = Generate diagnostic plots
    post_to_elog = True
        .type = bool
        .help = Post the calibration plot to the eLog (requires Kerberos token via kinit)  # noqa: E501
}
""")


def process_run(exp, run_num, detector_name, max_events):
    """Process a single run and return the accumulated spectrum.

    Parameters
    ----------
    exp : str
        Experiment name.
    run_num : int
        Run number to process.
    detector_name : str
        Name of the FEE spectrometer detector.
    max_events : int
        Maximum number of good events to accumulate.

    Returns
    -------
    data : numpy.ndarray or None
        Accumulated horizontal projection spectrum, or None if no
        valid events were found.
    total_events : int
        Number of good events accumulated.
    """
    try:
        ds = psana.DataSource(f"exp={exp}:run={run_num}:smd")
    except Exception:
        # psana2
        ds = psana.DataSource(
            exp=exp,
            run=run_num,
            detectors=[f"{detector_name}"],
            max_events=max_events,
        )
    try:
        detector = psana.Detector(detector_name)
    except Exception:
        # psana2
        detector = None

    data = None
    total_events = 0
    total_attempts = 0

    for run in ds.runs():
        try:
            # psana2
            detector = run.Detector(detector_name)
        except Exception:
            pass
        for evt in run.events():
            total_attempts += 1
            try:
                is_psana1 = True
                spectrum = detector.get(evt)
                dta = spectrum.hproj().astype(float)
                if not spectrum:
                    continue
            except Exception:
                # psana2
                is_psana1 = False
                spectrum = detector.raw.hproj(evt)
                if spectrum is None:
                    continue
                dta = spectrum.astype(float)

            if data is None:
                data = dta
            else:
                data += dta
            total_events += 1

            if is_psana1:
                if total_events >= max_events:
                    break

    print(
        f"  Processed {total_attempts} total events "
        f"to get {total_events} good events"
    )
    return data, total_events


def gaussian(x, amplitude, mean, sigma):
    """Evaluate a Gaussian function.

    Parameters
    ----------
    x : numpy.ndarray
        Independent variable.
    amplitude : float
        Peak amplitude.
    mean : float
        Centre position.
    sigma : float
        Standard deviation.

    Returns
    -------
    numpy.ndarray
        Gaussian evaluated at each point in *x*.
    """
    return amplitude * np.exp(-((x - mean) ** 2) / (2 * sigma**2))


def find_peak_position(spectrum, fit_window, sg_window, poly_order):
    """Find the peak position in a spectrum using a Gaussian fit.

    A Savitzky-Golay filter is applied first to locate an approximate
    peak, then a Gaussian is fitted within a window around that peak
    to obtain a sub-pixel position estimate.

    Parameters
    ----------
    spectrum : numpy.ndarray
        1-D intensity spectrum.
    fit_window : int
        Number of pixels around the rough peak to include in the fit.
    sg_window : int
        Window length for the Savitzky-Golay filter (must be odd).
    poly_order : int
        Polynomial order for the Savitzky-Golay filter.

    Returns
    -------
    peak_pos : float
        Sub-pixel peak position (Gaussian mean, or smoothed argmax on
        fit failure).
    smoothed : numpy.ndarray
        Savitzky-Golay smoothed spectrum.
    fit_y : numpy.ndarray or None
        Gaussian fit evaluated over the fit window, or None if the
        fit failed.
    fit_range : tuple of int
        ``(left, right)`` pixel indices of the fit window.
    """
    smoothed = savgol_filter(spectrum, sg_window, poly_order)
    rough_peak = np.argmax(smoothed)

    left = max(0, rough_peak - fit_window // 2)
    right = min(len(spectrum), rough_peak + fit_window // 2)
    x = np.arange(left, right)
    y = spectrum[left:right]

    p0 = [
        np.max(y),  # amplitude
        rough_peak,  # mean
        fit_window / 6,  # sigma (window_size/6 is a reasonable guess)
    ]

    try:
        popt, _ = curve_fit(gaussian, x, y, p0=p0)
        peak_pos = popt[1]
        fit_y = gaussian(x, *popt)
        return peak_pos, smoothed, fit_y, (left, right)
    except Exception as e:
        print(
            f"  Warning: Gaussian fit failed ({e}), "
            "falling back to smoothed maximum"
        )
        return float(rough_peak), smoothed, None, (left, right)


def calibrate_energy_scale(peak_positions, energies):
    """Fit a linear energy calibration to a set of peak positions.

    Parameters
    ----------
    peak_positions : array-like of float
        Pixel positions of spectral peaks, one per calibration run.
    energies : array-like of float
        Known photon energies (eV) corresponding to each peak.

    Returns
    -------
    slope : float
        eV per pixel (dispersion).
    intercept : float
        Energy at pixel 0 (eV).
    r_value : float
        Pearson correlation coefficient of the fit.
    """
    slope, intercept, r_value, _, _ = linregress(peak_positions, energies)
    return slope, intercept, r_value


def post_to_elog(exp, fig, ev_per_pixel, intercept, r_value,
                 run_start, n_runs):
    """Post the calibration figure and results to the LCLS eLog.

    Authentication is performed via Kerberos; a valid token must exist
    before calling this function (obtain one with ``kinit``).

    Parameters
    ----------
    exp : str
        Experiment name (used to construct the eLog endpoint URL).
    fig : matplotlib.figure.Figure
        Calibration figure to attach to the eLog entry.
    ev_per_pixel : float
        Calibrated dispersion in eV per pixel.
    intercept : float
        Energy at pixel 0 in eV.
    r_value : float
        Pearson correlation coefficient of the linear fit.
    run_start : int
        First run number included in the calibration.
    n_runs : int
        Total number of runs included in the calibration.
    """
    try:
        from krtc import KerberosTicket
        import requests
    except ImportError as e:
        print(
            f"  Warning: could not import package for eLog "
            f"posting ({e}). Skipping."
        )
        return

    buf = io.BytesIO()
    fig.savefig(buf, format="jpeg", dpi=600, bbox_inches="tight")
    buf.seek(0)

    log_text = (
        f"FEE spectrometer energy calibration\n"
        f"Runs: {run_start} \u2013 {run_start + n_runs - 1}\n"
        f"eV/pixel: {ev_per_pixel:.5f}\n"
        f"Intercept: {intercept:.2f} eV\n"
        f"R\u00b2: {r_value**2:.4f}"
    )

    ws_url = (
        "https://pswww.slac.stanford.edu"
        f"/ws-kerb/lgbk/lgbk/{exp}/ws/new_elog_entry"
    )
    try:
        krbheaders = KerberosTicket(
            "HTTP@pswww.slac.stanford.edu"
        ).getAuthHeaders()
    except Exception as e:
        print(
            f"  Warning: Kerberos authentication failed ({e}). "
            "Is your token valid? Run 'kinit' first."
        )
        return

    try:
        r = requests.post(
            ws_url,
            data={"log_text": log_text, "log_tags": "energy"},
            files=[("files", ("fee_calib.jpg", buf, "image/jpeg"))],
            headers=krbheaders,
        )
        r.raise_for_status()
        result = r.json()
        if result.get("success"):
            print("  Calibration plot posted to eLog successfully.")
        else:
            print(f"  eLog post returned an error: {result}")
    except Exception as e:
        print(f"  Warning: failed to post to eLog ({e})")


def run(args):
    """Run the FEE spectrometer energy calibration pipeline.

    Processes a sequence of psana runs taken at known photon energies,
    finds the spectral peak in each run, performs a linear regression
    to determine the eV-per-pixel dispersion, and optionally plots the
    results and posts them to the eLog.

    Parameters
    ----------
    args : list of str
        Command-line arguments in PHIL format, e.g.
        ``["calibration.exp=mfxdaq13", "calibration.run_start=100"]``.
    """
    parser = OptionParser(phil=phil_scope)
    params, options = parser.parse_args(args=args, show_diff_phil=True)

    required = ["exp", "run_start", "energy_start", "energy_step", "n_runs"]
    for param in required:
        if getattr(params.calibration, param) is None:
            raise ValueError(f"Parameter {param} must be specified")

    peak_positions = []
    energies = []
    all_spectra = []
    all_smoothed = []
    all_fits = []
    all_fit_ranges = []

    for i in range(params.calibration.n_runs):
        run_num = params.calibration.run_start + i
        energy = (
            params.calibration.energy_start
            + i * params.calibration.energy_step
        )

        print(f"Processing run {run_num} at {energy} eV...")

        spectrum, n_events = process_run(
            params.calibration.exp,
            run_num,
            params.calibration.detector,
            params.calibration.events_per_run,
        )

        if spectrum is not None and n_events > 0:
            norm_spectrum = spectrum / n_events
            result = find_peak_position(
                norm_spectrum,
                params.calibration.fit_window,
                params.calibration.savgol_window,
                params.calibration.savgol_order,
            )
            peak_pos, smoothed, fit, fit_range = result

            all_spectra.append(norm_spectrum)
            all_smoothed.append(smoothed)
            all_fits.append(fit)
            all_fit_ranges.append(fit_range)
            peak_positions.append(peak_pos)
            energies.append(energy)
            print(f"  Peak found at position {peak_pos:.1f}")
        else:
            print(f"  No valid data for run {run_num}")

    ev_per_pixel, intercept, r_value = calibrate_energy_scale(
        peak_positions, energies
    )

    if params.calibration.plot or params.calibration.post_to_elog:
        x_min = 0
        x_max = len(all_spectra[0])

        fig = plt.figure(figsize=(7.5, 5))

        # Plot 1: calibration curve
        ax1 = fig.add_subplot(211)
        ax1.scatter(peak_positions, energies)
        x_fit = np.array([x_min, x_max])
        y_fit = ev_per_pixel * x_fit + intercept
        ax1.plot(x_fit, y_fit, "r-")
        ax1.set_ylabel("Set energy (eV)")
        ax1.set_title("Linear fit")
        ax1.grid(True)
        ax1.set_xlim(x_min, x_max)

        # Plot 2: spectra and peaks
        ax2 = fig.add_subplot(212)
        colors = plt.cm.rainbow(np.linspace(0, 1, len(all_spectra)))

        for i, (
            spectrum,
            smoothed,
            fit,
            fit_range,
            peak_pos,
            energy,
            color,
        ) in enumerate(
            zip(
                all_spectra,
                all_smoothed,
                all_fits,
                all_fit_ranges,
                peak_positions,
                energies,
                colors,
            )
        ):
            run_num = params.calibration.run_start + i

            ax2.plot(spectrum, "--", color=color, alpha=0.3)
            ax2.plot(smoothed, color=color, alpha=0.5)

            if fit is not None:
                x_fit = np.arange(fit_range[0], fit_range[1])
                ax2.plot(x_fit, fit, "-", color=color, linewidth=2)

            ax2.plot(
                peak_pos,
                spectrum[int(round(peak_pos))],
                "o",
                color=color,
            )
            y_text = spectrum[int(round(peak_pos))] * 0.8
            ax2.text(peak_pos, y_text, run_num, ha="center", va="top")

        ax2.set_xlabel("Pixel")
        ax2.set_ylabel("Intensity (normalized)")
        ax2.grid(True)
        ax2.set_xlim(x_min, x_max)

        plt.tight_layout()

        if params.calibration.post_to_elog:
            print("\nPosting calibration plot to eLog...")
            post_to_elog(
                params.calibration.exp,
                fig,
                ev_per_pixel,
                intercept,
                r_value,
                params.calibration.run_start,
                params.calibration.n_runs,
            )

        if params.calibration.plot:
            plt.show()

    print("\nCalibration Results:")
    print(f"eV per pixel: {ev_per_pixel:.5f}")
    print(f"Intercept: {intercept:.2f} eV")
    print(f"R-squared: {r_value**2:.4f}")


if __name__ == "__main__":
    run(sys.argv[1:])
