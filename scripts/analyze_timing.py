# -*- coding: utf-8 -*-
"""
Timing analysis for MFX beamline laser-X-ray synchronisation scans.

Processes psana2 XTC data from timing scans, fits an error-function
(ERF) model to the detector response vs. delay, produces a combined
four-panel diagnostic figure, saves CSV/JSON results, and optionally
posts the figure to the LCLS eLog via Kerberos-authenticated REST.

Typical usage
-------------
Invoked indirectly through :class:`mfx.timing.Timing` or directly::

    python analyze_timing.py \\
        -f S3DF -t output -e mfxls1234 -r 42 -c alvium_dg3
"""

import io
import json
import logging
import os
import sys
import argparse

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from psana import DataSource
from scipy.optimize import curve_fit
from scipy import special
from pathlib import Path


logging.basicConfig()
logging.getLogger().setLevel(logging.INFO)
logger = logging.getLogger(__name__)

COMMISSIONING_EXP = "mfx101609126"


def proxy_jump(
    facility="S3DF",
    exp=None,
    run=None,
    camera="alvium_dg3",
    output_dir=None,
    motor_label=None,
):
    """Submit the analysis job to the psana worker node via SSH.

    Constructs and executes an SSH command that sources the psana
    conda environment and invokes this script with ``-t output`` on
    the remote host.

    Parameters
    ----------
    facility : str, optional
        Target computing facility.  ``"S3DF"`` (default) or
        ``"NERSC"``.
    exp : str, optional
        Experiment identifier (e.g. ``"mfxls1234"``).
    run : str or int, optional
        Run number to analyse.
    camera : str, optional
        Psana detector alias for the timing camera.
        Default: ``"alvium_dg3"``.
    output_dir : str or None, optional
        Root directory for saved outputs.  Defaults to
        ``/sdf/data/lcls/ds/mfx/{exp}/scratch/analyze_timing``.
    motor_label : str or None, optional
        Human-readable label for the scanning motor forwarded to the
        remote invocation via ``-m``.  When *None* the label is
        derived from psana scaninfo on the worker.
    """
    if output_dir is None:
        output_dir = f"/sdf/data/lcls/ds/mfx/{exp}/scratch/analyze_timing"

    motor_arg = f" -m {motor_label}" if motor_label is not None else ""

    if facility.upper() == "NERSC":
        if exp is None:
            raise ValueError("exp must be specified for NERSC.")
        exp = exp[3:-2]
        nersc_script = (
            "/global/common/software/lcls/mfx/scripts/cctbx"
            "/energy_calib_output.sh"
        )
        proc = [
            f"ssh -i ~/.ssh/cctbx -YAC "
            f"cctbx@perlmutter-p1.nersc.gov "
            f"{nersc_script} {facility} {exp} {run}"
        ]
    elif facility.upper() == "S3DF":
        conda_src = (
            "source /sdf/group/lcls/ds/ana/sw/conda2"
            "/manage/bin/psconda.sh"
        )
        script = "/sdf/group/lcls/ds/tools/mfx/scripts/analyze_timing.py"
        run_args = (
            f"-f {facility} -t output -e {exp} -r {run}"
            f" -c {camera} -o {output_dir}{motor_arg}"
        )
        proc = [f"ssh -Yt psana '{conda_src} && python {script} {run_args}'"]
    else:
        logging.error(f"Facility not found: {facility}. Program Exit.")
        sys.exit()

    logging.info(proc)
    os.system(proc[0])


def get_scan_motor(run):
    """Identify the scanned motor from psana2 scan metadata.

    Inspects ``run.scaninfo`` and returns the name of the first
    variable recorded with type ``"raw"`` that is not in the standard
    skip set (``step_value``, ``step_docstring``).

    Parameters
    ----------
    run : psana.Run
        An open psana2 ``Run`` object from ``DataSource.runs()``.

    Returns
    -------
    str
        The psana detector alias of the scanned motor.

    Raises
    ------
    StopIteration
        If no suitable motor entry is found in ``run.scaninfo``.
    """
    tmp = run.scaninfo
    ignore = {"step_value", "step_docstring"}
    mot_name = next(k[0] for k in tmp if k[1] == "raw" and k[0] not in ignore)
    logger.info(f"Scanning motor found as: {mot_name}")
    return mot_name


def custom_erf(x, a, sigma, mu, b):
    """Evaluate a scaled and shifted error function.

    .. math::

        f(x) = a \\cdot \\operatorname{erf}\\!
               \\left(\\frac{x - \\mu}{\\sqrt{2}\\,\\sigma}\\right) + b

    Parameters
    ----------
    x : array-like
        Independent variable.
    a : float
        Amplitude (half the total step height).
    sigma : float
        Width parameter (standard deviation of the underlying
        Gaussian derivative).
    mu : float
        Centre / inflection point.
    b : float
        Vertical offset.

    Returns
    -------
    numpy.ndarray
        ERF evaluated at each point in *x*.
    """
    return a * special.erf((x - mu) / (np.sqrt(2) * sigma)) + b


def fit_irfs1(
    x_data,
    y_data,
    run_number=None,
    t_stage=None,
    save_path=None,
    ax=None,
    show=True,
):
    """Fit an error-function model to a timing-scan signal.

    Cleans, normalises, and fits the instrument-response-function
    (IRF) edge to the data using ``scipy.optimize.curve_fit``.
    Optionally draws the result into a supplied ``Axes`` object (for
    embedding in a larger figure) or into a new standalone figure.

    Parameters
    ----------
    x_data : array-like
        Motor position values (timing axis).
    y_data : array-like
        Corresponding signal values (unnormalised).
    run_number : int or str, optional
        Run number included in the plot title.
    t_stage : str, optional
        Motor label used as the x-axis label and in the plot title.
        Falls back to ``"Position"`` when *None*.
    save_path : str or pathlib.Path or None, optional
        File path at which to save the standalone figure.  Only used
        when *ax* is *None*.
    ax : matplotlib.axes.Axes or None, optional
        Axes into which the fit is drawn.  When *None* (default) a
        new figure is created and the caller is *not* responsible for
        it.  When an ``Axes`` is supplied the caller owns the figure.
    show : bool, optional
        Call ``plt.show()`` after plotting.  Only applies when *ax*
        is *None*.  Default: ``True``.

    Returns
    -------
    popt : numpy.ndarray
        Optimal ERF parameters ``[a, sigma, mu, b]``.
    x_data : numpy.ndarray
        Cleaned and sorted input positions.
    y_norm : numpy.ndarray
        Normalised (0–1) signal values aligned with *x_data*.
    y_fit : numpy.ndarray
        ERF model evaluated at each point in *x_data*.

    Raises
    ------
    ValueError
        If fewer than 8 finite data points remain after cleaning, or
        if the data has no dynamic range.
    RuntimeError
        If ``curve_fit`` fails to converge within 20 000 iterations.
    """

    def _erf(x, a, sigma, mu, b):
        return a * special.erf((x - mu) / (np.sqrt(2) * sigma)) + b

    # Convert & clean
    x_data = np.asarray(x_data, dtype=float)
    y_data = np.asarray(y_data, dtype=float)

    mask = np.isfinite(x_data) & np.isfinite(y_data)
    x_data = x_data[mask]
    y_data = y_data[mask]

    if len(x_data) < 8:
        raise ValueError("Not enough valid data points.")

    # Sort ascending
    order = np.argsort(x_data)
    x_data = x_data[order]
    y_data = y_data[order]

    # Light smoothing to suppress noise
    from scipy.ndimage import gaussian_filter1d

    y_smooth = gaussian_filter1d(y_data, sigma=2)

    # Robust normalisation (avoids spike sensitivity)
    y_min = np.percentile(y_smooth, 5)
    y_max = np.percentile(y_smooth, 95)
    if y_max - y_min == 0:
        raise ValueError("Data has no dynamic range.")
    y_norm = (y_data - y_min) / (y_max - y_min)

    # Initial parameter estimates
    dydx = np.gradient(y_smooth, x_data)
    mu_initial = x_data[np.argmax(np.abs(dydx))]
    x_span = x_data.max() - x_data.min()
    p0 = [0.5, x_span / 20, mu_initial, 0.5]
    bounds = (
        [-2, x_span / 1000, x_data.min(), -1],
        [2, x_span, x_data.max(), 2],
    )

    try:
        popt, _ = curve_fit(
            _erf,
            x_data,
            y_norm,
            p0=p0,
            bounds=bounds,
            maxfev=20000,
        )
    except RuntimeError:
        raise RuntimeError("Fit failed to converge.")

    y_fit = _erf(x_data, *popt)
    fwhm = abs(popt[1]) * 2.355

    # Plot
    own_figure = ax is None
    _fig = None
    if own_figure:
        _fig, ax = plt.subplots(figsize=(5, 3))

    xlabel = t_stage if t_stage is not None else "Position"
    ax.scatter(x_data, y_norm, s=15, label="Data")
    ax.plot(
        x_data,
        y_fit,
        label=f"Fitted IRF, FWHM = {fwhm:.4f} fs or units",
    )
    ax.set_xlabel(xlabel)
    ax.set_ylabel("Normalised Signal")

    title = "Sigmoid Fit"
    if run_number is not None:
        title += f" | Run {run_number}"
    if t_stage is not None:
        title += f" | {t_stage}"
    ax.set_title(title)
    ax.legend()
    ax.grid()

    if own_figure:
        plt.tight_layout()
        if save_path is not None:
            plt.savefig(save_path, dpi=150, bbox_inches="tight")
            logger.info(f"Fit plot saved to {save_path}")
        if show:
            try:
                plt.show()
            except Exception as exc:
                logger.warning(f"Could not display plot: {exc}")
        else:
            plt.close(_fig)

    print("\nFitted Parameters:")
    print(f"FWHM [fs]  = {fwhm:.2f}")
    print(f"Center     = {popt[2]:.4f}")
    print(f"Amplitude  = {popt[0]:.3f}")

    return popt, x_data, y_norm, y_fit


def _post_to_elog(exp, fig, run_number, t_stage, popt):
    """Post the combined timing-analysis figure to the LCLS eLog.

    Authentication is performed via Kerberos; a valid token must exist
    before calling this function (obtain one with ``kinit``).

    Parameters
    ----------
    exp : str
        Experiment name used to construct the eLog endpoint URL.
    fig : matplotlib.figure.Figure
        Combined timing-analysis figure to attach to the eLog entry.
    run_number : str or int
        Run number being analysed.
    t_stage : str
        Display label for the scanned timing motor.
    popt : array-like
        Fitted ERF parameters ``[a, sigma, mu, b]``.
    """
    try:
        from krtc import KerberosTicket
        import requests
    except ImportError as exc:
        logger.warning(
            "Could not import package for eLog posting "
            f"({exc}). Skipping."
        )
        return

    buf = io.BytesIO()
    fig.savefig(buf, format="jpeg", dpi=150, bbox_inches="tight")
    buf.seek(0)

    fwhm = abs(popt[1]) * 2.355
    log_text = (
        f"Timing analysis\n"
        f"Run: {run_number}\n"
        f"Scan motor: {t_stage}\n"
        f"FWHM: {fwhm:.4f} (fit units)\n"
        f"Center: {popt[2]:.4f}"
    )

    ws_url = (
        "https://pswww.slac.stanford.edu"
        f"/ws-kerb/lgbk/lgbk/{exp}/ws/new_elog_entry"
    )
    try:
        ticket = KerberosTicket("HTTP@pswww.slac.stanford.edu")
        krbheaders = ticket.getAuthHeaders()
    except Exception as exc:
        logger.warning(
            f"Kerberos authentication failed ({exc}). "
            "Is your token valid? Run 'kinit' first."
        )
        return

    try:
        r = requests.post(
            ws_url,
            data={"log_text": log_text, "log_tags": "timing"},
            files=[("files", ("analyze_timing.jpg", buf, "image/jpeg"))],
            headers=krbheaders,
        )
        r.raise_for_status()
        result = r.json()
        if result.get("success"):
            logger.info("Timing analysis plot posted to eLog successfully.")
        else:
            logger.warning(f"eLog post returned an error: {result}")
    except Exception as exc:
        logger.warning(f"Failed to post to eLog ({exc})")


def output(
    facility="S3DF",
    exp=None,
    run=None,
    camera="alvium_dg3",
    output_dir=None,
    post_to_elog=True,
    motor_label=None,
):
    """Process a timing scan run and generate diagnostic outputs.

    Reads psana2 XTC data, builds a 2×2 combined figure (raw QADC
    scatter, raw camera scatter, binned scatter, ERF fit), saves
    per-signal CSV files, fit-parameter JSON files, and the combined
    PNG.  Optionally posts the figure to the LCLS eLog.

    Combined figure panel layout::

        [0,0] Raw QADC Ch1 scatter  |  [0,1] Raw camera scatter
        ─────────────────────────────────────────────────────────
        [1,0] Binned scatter        |  [1,1] ERF fit

    Only the combined figure is shown interactively.  Additional
    signals (e.g. QADC) are processed and saved but not displayed.

    Parameters
    ----------
    facility : str, optional
        Computing facility where the script is running.
        ``"S3DF"`` (default) or ``"NERSC"``.
    exp : str or None, optional
        Experiment identifier.  Falls back to
        :data:`COMMISSIONING_EXP` with a warning when *None*.
    run : str or int
        Run number to analyse.  Required; raises :exc:`ValueError`
        when *None*.
    camera : str, optional
        Psana detector alias for the timing camera.
        Default: ``"alvium_dg3"``.
    output_dir : str or None, optional
        Root directory for saved outputs.  Defaults to
        ``/sdf/data/lcls/ds/mfx/{exp}/scratch/analyze_timing``.
    post_to_elog : bool, optional
        Post the combined figure to the LCLS eLog after fitting.
        Requires a valid Kerberos token (``kinit``).
        Default: ``True``.
    motor_label : str or None, optional
        Human-readable label used in all plot titles and axis labels.
        When *None* (default) the psana motor name from
        ``run.scaninfo`` is used directly.

    Raises
    ------
    ValueError
        If *run* is *None*.
    """
    if exp is None:
        logger.warning(
            "No experiment specified. Falling back to commissioning "
            f"experiment: {COMMISSIONING_EXP}. "
            "Pass exp= explicitly if this is not intended."
        )
        exp = COMMISSIONING_EXP

    if run is None:
        raise ValueError("run must be specified.")

    qadc0_low, qadc0_high = 10, 50
    qadc1_low, qadc1_high = 74, 130

    experiment = exp
    run_numbers = [run]

    # Build and create output directory
    if output_dir is None:
        output_dir = f"/sdf/data/lcls/ds/mfx/{exp}/scratch/analyze_timing"
    run_dir = Path(output_dir) / exp / f"run{int(run):03d}"
    save_outputs = True
    try:
        run_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Output directory: {run_dir}")
    except OSError as exc:
        logger.warning(
            f"Could not create output directory {run_dir}: {exc}. "
            "Outputs will not be saved."
        )
        save_outputs = False

    for run_number in run_numbers:
        logger.info(
            f"Processing run {run_number} "
            f"for experiment {experiment}..."
        )
        ds = DataSource(
            exp=experiment,
            run=int(run_number),
            xdetectors=["jungfrau"],
        )

        for run in ds.runs():
            diode_0 = run.Detector("qadc_ch0")
            diode_1 = run.Detector("qadc_ch1")
            dg3_cam = run.Detector(camera)

            t_stage = get_scan_motor(run)
            # display_label drives all plot text; t_stage is the
            # psana key used for detector access and type checks.
            display_label = motor_label if motor_label is not None else t_stage
            tmptmp = run.Detector(t_stage)
            ipm = run.Detector("MfxDg2BmMon")

            qadc0_cropped = []
            qadc1_cropped = []
            time_mot = []
            x_ray_diode_sum = []
            dg3_sum = []

            for _, evt in enumerate(run.events()):
                # Collect stage position, IPM, and camera for every
                # event, independent of QADC availability.
                time_mot.append(tmptmp(evt))
                x_ray_diode_sum.append(ipm.raw.totalIntensityJoules(evt))

                try:
                    img = dg3_cam.raw.value(evt)
                    img_sum = np.sum(img) if img is not None else np.nan
                except Exception:
                    img_sum = np.nan
                dg3_sum.append(img_sum)

                # QADC: append NaN when absent to keep lists aligned
                diode_val_0 = diode_0.raw.value(evt)
                diode_val_1 = diode_1.raw.value(evt)
                if diode_val_0 is not None and diode_val_1 is not None:
                    tmp0 = np.sum(np.abs(diode_val_0[qadc0_low:qadc0_high]))
                    tmp1 = np.sum(np.abs(diode_val_1[qadc1_low:qadc1_high]))
                else:
                    tmp0 = np.nan
                    tmp1 = np.nan
                qadc0_cropped.append(tmp0)
                qadc1_cropped.append(tmp1)

            qadc0_cropped = np.array(qadc0_cropped)
            qadc1_cropped = np.array(qadc1_cropped)

            qadc_available = bool(np.any(np.isfinite(qadc0_cropped)))
            if not qadc_available:
                logger.warning(
                    "No QADC data found in this run. "
                    "QADC plots and fit will be skipped."
                )

            data = {
                "t_position": time_mot,
                "qadc0_sum": qadc0_cropped,
                "qadc1_sum": qadc1_cropped,
                "x_ray_diode_sum": x_ray_diode_sum,
                "dg3_sum": dg3_sum,
            }

            df = pd.DataFrame(data)
            df["normalized_laser"] = df["qadc1_sum"]
            df["normalized_laser_dg3"] = df["dg3_sum"]

            # Build the combined 2×2 figure.  The original three
            # separate plot windows are merged into one display.
            fig_combined, axes = plt.subplots(2, 2, figsize=(12, 8))
            ax_raw_qadc, ax_raw_cam = axes[0]
            ax_binned, ax_fit = axes[1]

            # Panel 1 (top-left): Raw QADC Ch1 scatter
            if qadc_available:
                ax_raw_qadc.scatter(
                    df["t_position"],
                    df["normalized_laser"],
                    s=0.1,
                )
            else:
                ax_raw_qadc.text(
                    0.5,
                    0.5,
                    "QADC not available",
                    ha="center",
                    va="center",
                    transform=ax_raw_qadc.transAxes,
                    fontsize=12,
                )
            ax_raw_qadc.set_title(
                f"QADC Ch1 | Run {run_number} | {display_label}"
            )
            ax_raw_qadc.set_xlabel(display_label)
            ax_raw_qadc.set_ylabel("QADC Ch1 signal (arb. units)")

            # Panel 2 (top-right): Raw camera scatter
            ax_raw_cam.scatter(
                df["t_position"],
                df["normalized_laser_dg3"],
                s=0.1,
            )
            ax_raw_cam.set_title(
                f"Camera: {camera} | Run {run_number} | {display_label}"
            )
            ax_raw_cam.set_xlabel(display_label)
            ax_raw_cam.set_ylabel("Camera image sum (arb. units)")

            # Per-signal pipeline: outlier removal → bin → fit
            signals_to_process = [(camera, "normalized_laser_dg3")]
            if qadc_available:
                signals_to_process.append(("qadc", "normalized_laser"))

            for i_sig, (sig_label, sig_col) in enumerate(signals_to_process):
                logger.info(f"Processing signal: {sig_label} ({sig_col})")

                # Outlier removal using IQR
                q1 = df[sig_col].quantile(0.25)
                q3 = df[sig_col].quantile(0.75)
                iqr = q3 - q1
                df_clean = df[
                    (df[sig_col] >= q1 - 1.5 * iqr)
                    & (df[sig_col] <= q3 + 1.5 * iqr)
                ].copy()

                if save_outputs:
                    csv_path = run_dir / f"data_{sig_label}.csv"
                    df_clean.to_csv(csv_path, index=False)
                    logger.info(f"Cleaned data saved to {csv_path}")

                # Bin into 100 equal-width intervals
                n_bins = 100
                if t_stage in ("lxt_ttc", "mfx_lxt_fast1", "mfx_lxt_fast2"):
                    df_clean["t_bin"] = pd.cut(
                        df_clean["t_position"].astype(float),
                        bins=n_bins,
                    )
                else:
                    df_clean["t_bin"] = pd.cut(
                        df_clean["t_position"], bins=n_bins
                    )

                binned = df_clean.groupby("t_bin").agg(
                    {"t_position": "mean", sig_col: "mean"}
                )

                if i_sig == 0:
                    # Panel 3 (bottom-left): Binned scatter
                    ax_binned.scatter(
                        binned["t_position"],
                        binned[sig_col],
                        color="royalblue",
                        s=40,
                    )
                    ax_binned.set_xlabel(display_label)
                    ax_binned.set_ylabel(sig_col)
                    ax_binned.set_title(
                        "Binned Scatter (Outliers Removed) "
                        f"| {sig_label} | Run {run_number}"
                    )
                    ax_binned.grid(True)

                    # Panel 4 (bottom-right): ERF fit
                    popt, _, _, _ = fit_irfs1(
                        binned["t_position"],
                        binned[sig_col],
                        run_number,
                        display_label,
                        save_path=None,
                        ax=ax_fit,
                    )

                    if save_outputs:
                        fit_params = {
                            "run": run_number,
                            "signal": sig_label,
                            "t_stage": t_stage,
                            "FWHM": float(abs(popt[1]) * 2.355),
                            "center": float(popt[2]),
                            "amplitude": float(popt[0]),
                        }
                        json_path = run_dir / f"fit_params_{sig_label}.json"
                        with open(json_path, "w") as fh:
                            json.dump(fit_params, fh, indent=2)
                        logger.info(f"Fit parameters saved to {json_path}")

                    # Finalise and display the combined figure
                    fig_combined.suptitle(
                        f"Timing Analysis | Run {run_number}"
                        f" | {display_label}",
                        fontsize=13,
                    )
                    fig_combined.tight_layout()

                    if save_outputs:
                        combined_path = (
                            run_dir
                            / f"combined_timing_run"
                            f"{int(run_number):03d}.png"
                        )
                        fig_combined.savefig(
                            combined_path, dpi=150, bbox_inches="tight"
                        )
                        logger.info(
                            "Combined timing plot saved to "
                            f"{combined_path}"
                        )

                    if post_to_elog:
                        logger.info("Posting timing analysis to eLog...")
                        _post_to_elog(
                            exp,
                            fig_combined,
                            run_number,
                            display_label,
                            popt,
                        )

                    try:
                        plt.show()
                    except Exception as exc:
                        logger.warning(f"Could not display plot: {exc}")
                    plt.close(fig_combined)

                else:
                    # Additional signals: save outputs, do not display
                    fig_extra, ax_extra = plt.subplots(figsize=(6, 4))
                    ax_extra.scatter(
                        binned["t_position"],
                        binned[sig_col],
                        color="royalblue",
                        s=40,
                    )
                    ax_extra.set_xlabel(display_label)
                    ax_extra.set_ylabel(sig_col)
                    ax_extra.set_title(
                        "Binned Scatter (Outliers Removed) "
                        f"| {sig_label} | Run {run_number}"
                    )
                    ax_extra.grid(True)
                    fig_extra.tight_layout()
                    if save_outputs:
                        extra_path = (
                            run_dir
                            / f"scatter_binned_{sig_label}.png"
                        )
                        fig_extra.savefig(
                            extra_path, dpi=150, bbox_inches="tight"
                        )
                        logger.info(
                            "Binned scatter plot saved to "
                            f"{extra_path}"
                        )
                    plt.close(fig_extra)

                    popt2, _, _, _ = fit_irfs1(
                        binned["t_position"],
                        binned[sig_col],
                        run_number,
                        display_label,
                        save_path=(
                            run_dir / f"fit_{sig_label}.png"
                            if save_outputs else None
                        ),
                        ax=None,
                        show=False,
                    )

                    if save_outputs:
                        fit_params2 = {
                            "run": run_number,
                            "signal": sig_label,
                            "t_stage": t_stage,
                            "FWHM": float(abs(popt2[1]) * 2.355),
                            "center": float(popt2[2]),
                            "amplitude": float(popt2[0]),
                        }
                        json_path2 = run_dir / f"fit_params_{sig_label}.json"
                        with open(json_path2, "w") as fh:
                            json.dump(fit_params2, fh, indent=2)
                        logger.info(f"Fit parameters saved to {json_path2}")


def parse_args(args):
    """Parse command-line arguments for analyze_timing.

    Parameters
    ----------
    args : list of str
        Argument tokens (typically ``sys.argv[1:]``).

    Returns
    -------
    argparse.Namespace
        Parsed namespace with attributes *facility*, *run_type*,
        *experiment*, *run*, *camera*, *output*, *motor*, and
        *post_to_elog*.
    """
    parser = argparse.ArgumentParser(description="MFX timing analysis script.")
    parser.add_argument(
        "--facility",
        "-f",
        dest="facility",
        default=None,
        help="Computing facility: S3DF (default) or NERSC.",
    )
    parser.add_argument(
        "--type",
        "-t",
        dest="run_type",
        default=None,
        help="Execution mode: 'proxy' or 'output'.",
    )
    parser.add_argument(
        "--experiment",
        "-e",
        dest="experiment",
        default=None,
        help="Experiment identifier, e.g. mfxls1234.",
    )
    parser.add_argument(
        "--run",
        "-r",
        dest="run",
        default=None,
        help="Run number to process.",
    )
    parser.add_argument(
        "--camera",
        "-c",
        dest="camera",
        default="alvium_dg3",
        help="Psana detector alias for the camera. Default: alvium_dg3.",
    )
    parser.add_argument(
        "--output",
        "-o",
        dest="output",
        default=None,
        help="Base output directory. "
        "Default: /sdf/data/lcls/ds/mfx/{exp}/scratch/"
        "analyze_timing.",
    )
    parser.add_argument(
        "--motor",
        "-m",
        dest="motor",
        default=None,
        help="Display label for the scanning motor. "
        "Overrides the psana scaninfo name in plot text. "
        "The psana key used for data access is unaffected.",
    )
    parser.add_argument(
        "--post-to-elog",
        "-p",
        dest="post_to_elog",
        action="store_true",
        default=True,
        help="Post the combined timing figure to the eLog after "
        "fitting (requires kinit). Default: enabled.",
    )
    parser.add_argument(
        "--no-post-to-elog",
        dest="post_to_elog",
        action="store_false",
        help="Disable automatic eLog posting.",
    )
    return parser.parse_args(args)


def main(args):
    """Entry point for direct invocation and ``console_scripts``.

    Parses *args*, resolves the output directory, then dispatches to
    :func:`proxy_jump` or :func:`output` depending on ``--type``.

    Parameters
    ----------
    args : list of str
        Raw command-line tokens passed to :func:`parse_args`.
    """
    args = parse_args(args)

    output_dir = args.output
    if output_dir is None:
        output_dir = (
            f"/sdf/data/lcls/ds/mfx/{args.experiment}"
            "/scratch/analyze_timing"
        )

    if args.run_type == "proxy":
        proxy_jump(
            args.facility,
            args.experiment,
            args.run,
            args.camera,
            output_dir,
            args.motor,
        )
    elif args.run_type == "output":
        output(
            args.facility,
            args.experiment,
            args.run,
            args.camera,
            output_dir,
            args.post_to_elog,
            args.motor,
        )


def run():
    """Entry point for ``console_scripts``."""
    main(sys.argv[1:])


if __name__ == "__main__":
    run()
