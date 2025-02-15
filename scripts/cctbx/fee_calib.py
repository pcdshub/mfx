from __future__ import absolute_import, division, print_function
# LIBTBX_SET_DISPATCHER_NAME cctbx.xfel.fee_calib

from dials.util.options import OptionParser
from libtbx.phil import parse
import sys
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
    detector = 'FEE-SPEC0'
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
}
""")

def process_run(exp, run_num, detector_name, max_events):
    """Process a single run and return accumulated spectrum"""
    ds = psana.DataSource(f'exp={exp}:run={run_num}:smd')
    detector = psana.Detector(detector_name)

    data = None
    total_events = 0
    total_attempts = 0

    for run in ds.runs():
        for nevt, evt in enumerate(run.events()):
            total_attempts += 1
            spectrum = detector.get(evt)
            if not spectrum:
                continue

            dta = spectrum.hproj().astype(float)
            if data is None:
                data = dta
            else:
                data += dta
            total_events += 1

            if total_events >= max_events:
                break

    print(f"  Processed {total_attempts} total events to get {total_events} good events")
    return data, total_events


def gaussian(x, amplitude, mean, sigma):
    """Gaussian function for fitting"""
    return amplitude * np.exp(-(x - mean)**2 / (2 * sigma**2))

def find_peak_position(spectrum, fit_window, sg_window, poly_order):
    """Find peak position using smoothed spectrum and Gaussian fit"""
    # First get approximate peak using smoothing
    smoothed = savgol_filter(spectrum, sg_window, poly_order)
    rough_peak = np.argmax(smoothed)

    # Define region around peak for fitting
    left = max(0, rough_peak - fit_window//2)
    right = min(len(spectrum), rough_peak + fit_window//2)
    x = np.arange(left, right)
    y = spectrum[left:right]

    # Initial parameter guesses
    p0 = [
        np.max(y),  # amplitude
        rough_peak,  # mean
        fit_window/6  # sigma (window_size/6 is a reasonable guess)
    ]

    try:
        # Fit Gaussian
        popt, _ = curve_fit(gaussian, x, y, p0=p0)
        peak_pos = popt[1]  # mean of Gaussian
        amplitude = popt[0]
        sigma = popt[2]
        fit_y = gaussian(x, *popt)
        return peak_pos, smoothed, fit_y, (left, right)
    except Exception as e:
        print(f"  Warning: Gaussian fit failed ({str(e)}), falling back to smoothed maximum")
        return float(rough_peak), smoothed, None, (left, right)

def calibrate_energy_scale(peak_positions, energies):
    """Perform linear regression to get eV per pixel"""
    slope, intercept, r_value, p_value, std_err = linregress(peak_positions, energies)
    return slope, intercept, r_value

def run(args):
    # Process command line
    parser = OptionParser(phil=phil_scope)
    params, options = parser.parse_args(args=args, show_diff_phil=True)
    
    # Validate required parameters
    required = ['exp', 'run_start', 'energy_start', 'energy_step', 'n_runs']
    for param in required:
        if getattr(params.calibration, param) is None:
            raise ValueError(f"Parameter {param} must be specified")

    # Initialize lists for peak positions and corresponding energies
    peak_positions = []
    energies = []
    
    # Store spectra and smoothed spectra for plotting
    all_spectra = []
    all_smoothed = []
    all_fits = []
    all_fit_ranges = []

    # Process each run
    for i in range(params.calibration.n_runs):
        run_num = params.calibration.run_start + i
        energy = params.calibration.energy_start + i * params.calibration.energy_step

        print(f"Processing run {run_num} at {energy} eV...")

        spectrum, n_events = process_run(
            params.calibration.exp,
            run_num,
            params.calibration.detector,
            params.calibration.events_per_run
        )

        if spectrum is not None and n_events > 0:
            # Normalize spectrum for plotting
            norm_spectrum = spectrum / n_events
            result = find_peak_position(
                norm_spectrum,
                params.calibration.fit_window,
                params.calibration.savgol_window,
                params.calibration.savgol_order
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


    # Perform calibration
    ev_per_pixel, intercept, r_value = calibrate_energy_scale(peak_positions, energies)

    # Plotting
    if params.calibration.plot:
        # Determine x-axis range from the first spectrum
        x_min = 0
        x_max = len(all_spectra[0])

        # Create figure with two subplots
        fig = plt.figure(figsize=(7.5,5))

        # Plot 1: Calibration curve
        ax1 = fig.add_subplot(211)
        ax1.scatter(peak_positions, energies)
        x_fit = np.array([x_min, x_max])
        y_fit = ev_per_pixel * x_fit + intercept
        ax1.plot(x_fit, y_fit, 'r-')
        ax1.set_ylabel('Set energy (eV)')
        ax1.set_title('Linear fit')
        ax1.grid(True)
        ax1.set_xlim(x_min, x_max)

        # Plot 2: Spectra and peaks
        ax2 = fig.add_subplot(212)
        colors = plt.cm.rainbow(np.linspace(0, 1, len(all_spectra)))

        for i, (spectrum, smoothed, fit, fit_range, peak_pos, energy, color) in enumerate(
            zip(all_spectra, all_smoothed, all_fits, all_fit_ranges,
                peak_positions, energies, colors)):

            run_num = params.calibration.run_start + i

            # Plot raw spectrum
            ax2.plot(spectrum, '--', color=color, alpha=0.3)

            # Plot smoothed spectrum
            ax2.plot(smoothed, color=color, alpha=0.5)

            # Plot Gaussian fit if available
            if fit is not None:
                x_fit = np.arange(fit_range[0], fit_range[1])
                ax2.plot(x_fit, fit, '-', color=color, linewidth=2)

            # Mark peak
            ax2.plot(peak_pos, spectrum[int(round(peak_pos))], 'o', color=color)

            # Add run number under peak
            y_text = spectrum[int(round(peak_pos))] * 0.8  # Position text below peak
            ax2.text(peak_pos, y_text, run_num,
                    ha='center', va='top')

        ax2.set_xlabel('Pixel')
        ax2.set_ylabel('Intensity (normalized)')
        ax2.grid(True)
        ax2.set_xlim(x_min, x_max)



        plt.tight_layout()
        plt.show()

    print("\nCalibration Results:")
    print(f"eV per pixel: {ev_per_pixel:.5f}")
    print(f"Intercept: {intercept:.2f} eV")
    print(f"R-squared: {r_value**2:.4f}")


if __name__ == '__main__':
    run(sys.argv[1:])
