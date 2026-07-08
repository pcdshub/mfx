# -*- coding: utf-8 -*-
"""
analyze_timing_v2
"""

import io
import json
import logging
import os
import sys
import argparse
import pickle
import h5py
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from psana import DataSource
from scipy.optimize import curve_fit
from scipy import special
from pathlib import Path
from tqdm import tqdm


logging.basicConfig()
logging.getLogger().setLevel(logging.INFO)
logger = logging.getLogger(__name__)

COMMISSIONING_EXP = "mfx101609126"


def proxy_jump(
    facility: str = "S3DF",
    exp: str = None,
    run: str = None,
    camera: str = "alvium_dg3",
    output_dir: str = None,
):
    """Generates the output of the energy scan or series.

    Parameters:
        facility (str):
            Default: "S3DF". Options: "S3DF, NERSC
        exp (str):
            experiment number. Current experiment by default
        run (str):
            The run you'd like to process
        camera (str):
            Detector name for the camera. Default: 'alvium_dg3'
        output_dir (str):
            Base output directory. Default: /sdf/data/lcls/ds/mfx/{exp}/scratch/analyze_timing
    """
    if output_dir is None:
        output_dir = f"/sdf/data/lcls/ds/mfx/{exp}/scratch/analyze_timing"

    if facility.upper() == "NERSC":  # need paths to work on nersc
        exp = exp[3:-2]
        proc = [
            f"ssh -i ~/.ssh/cctbx -YAC cctbx@perlmutter-p1.nersc.gov "
            f"/global/common/software/lcls/mfx/scripts/cctbx/energy_calib_output.sh "
            f"{facility} {exp} {run}"
        ]
    elif facility.upper() == "S3DF":
        proc = [
            f"ssh -Yt psana '"
            f"source /sdf/group/lcls/ds/ana/sw/conda2/manage/bin/psconda.sh && "
            f"python /sdf/group/lcls/ds/tools/mfx/scripts/analyze_timing_v2.py "
            f"-f {facility} -t output -e {exp} -r {run} -c {camera} -o {output_dir}'"
        ]
    else:
        logging.error(f"Facility not found: {facility}. Program Exit.")
        sys.exit()

    logging.info(proc)
    os.system(proc[0])


def get_scan_motor(run):
    # want to pick up the scanned motor automatically
    # wants the psana run object
    tmp = run.scaninfo
    ignore = {"step_value", "step_docstring"}

    mot_name = next(k[0] for k in tmp if k[1] == "raw" and k[0] not in ignore)
    logger.info(f"Scanning motor found as: {mot_name}")
    return mot_name


def custom_erf(x, a, sigma, mu, b):
    return a * special.erf((x - mu) / (np.sqrt(2) * sigma)) + b


# def fit_irfs1(x_data, y_data, run_number, t_stage):
#     # Convert to numpy arrays
#     x_data = np.asarray(x_data, dtype=float)
#     y_data = np.asarray(y_data, dtype=float)

#     # Remove NaNs and infs
#     mask = np.isfinite(x_data) & np.isfinite(y_data)
#     x_data = x_data[mask]
#     y_data = y_data[mask]

#     # Safety check
#     if len(x_data) < 5:
#         raise ValueError("Not enough valid points after removing NaNs/Infs")

#     # Normalize safely
#     ymax = np.max(y_data)
#     if ymax != 0:
#         y_data = y_data / ymax
#     else:
#         raise ValueError("y_data max is zero — cannot normalize")

#     # Initial guesses
#     a_initial = np.max(y_data) - np.min(y_data)
#     mu_initial = -1e-12
#     sigma_initial = (x_data.max() - x_data.min()) / 100
#     b_initial = np.min(y_data)

#     p0 = (a_initial, sigma_initial, mu_initial, b_initial)

#     # Fit
#     popt, pcov = curve_fit(custom_erf, x_data, y_data, p0=p0)

#     # Generate fit
#     y_fit = custom_erf(x_data, *popt)

#     # Sort for plotting
#     order = np.argsort(x_data)
#     x_sorted = x_data[order]
#     y_fit_sorted = y_fit[order]

#     # Plot
#     plt.figure(figsize=(5, 3))
#     plt.scatter(x_data, y_data, s=15, label='Data')
#     plt.plot(
#         x_sorted,
#         y_fit_sorted,
#         label=f'Fitted irf, width = {popt[1] * 2.355 * 1e15:.2f} fs'
#     )
#     plt.xlabel('X')
#     plt.ylabel('Y')
#     plt.title(f'Sigmoid Fit for run {run_number} scanning {t_stage}')
#     plt.legend()
#     plt.grid()
#     plt.show()

#     # Print results
#     logger.info("Fitted Parameters:")
#     logger.info(f'width = {popt[1] * 2.355}')
#     logger.info(f'offset [ps] = {popt[2] * 1e12}')

#     return popt, x_data, y_data, y_fit


def fit_irfs1(
    x_data, y_data, run_number=None, t_stage=None, save_path=None, ax=None, show=True
):
    def custom_erf(x, a, sigma, mu, b):
        return a * special.erf((x - mu) / (np.sqrt(2) * sigma)) + b

    # --- Convert & clean ---
    x_data = np.asarray(x_data, dtype=float)
    y_data = np.asarray(y_data, dtype=float)

    mask = np.isfinite(x_data) & np.isfinite(y_data)
    x_data = x_data[mask]
    y_data = y_data[mask]

    if len(x_data) < 8:
        raise ValueError("Not enough valid data points.")

    # --- Sort ---
    order = np.argsort(x_data)
    x_data = x_data[order]
    y_data = y_data[order]

    # --- Light smoothing to suppress noise (optional but helps a lot) ---
    from scipy.ndimage import gaussian_filter1d

    y_smooth = gaussian_filter1d(y_data, sigma=2)

    # --- Normalize robustly (avoid max spikes) ---
    y_min = np.percentile(y_smooth, 5)
    y_max = np.percentile(y_smooth, 95)

    if y_max - y_min == 0:
        raise ValueError("Data has no dynamic range.")

    y_norm = (y_data - y_min) / (y_max - y_min)

    # --- Automatic edge detection for mu guess ---
    dydx = np.gradient(y_smooth, x_data)
    mu_initial = x_data[np.argmax(np.abs(dydx))]

    # --- Better sigma guess ---
    x_span = x_data.max() - x_data.min()
    sigma_initial = x_span / 20

    # --- Amplitude & offset ---
    a_initial = 0.5
    b_initial = 0.5

    p0 = [a_initial, sigma_initial, mu_initial, b_initial]

    # --- Bounds (critical for stability) ---
    bounds = (
        [-2, x_span / 1000, x_data.min(), -1],  # lower
        [2, x_span, x_data.max(), 2],  # upper
    )

    try:
        popt, pcov = curve_fit(
            custom_erf, x_data, y_norm, p0=p0, bounds=bounds, maxfev=20000
        )
    except RuntimeError:
        raise RuntimeError("Fit failed to converge.")

    y_fit = custom_erf(x_data, *popt)

    # --- Plot ---
    own_figure = ax is None
    _fig = None
    if own_figure:
        _fig, ax = plt.subplots(figsize=(5, 3))

    ax.scatter(x_data, y_norm, s=15, label="Data")
    ax.plot(
        x_data,
        y_fit,
        label=f"Fitted IRF, FWHM = {abs(popt[1]) * 2.355:.4f} fs or units",
    )
    ax.set_xlabel(t_stage if t_stage is not None else "Position")
    ax.set_ylabel("Normalized Signal")

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
            except Exception as e:
                logger.warning(f"Could not display plot: {e}")
        else:
            plt.close(_fig)

    print("\nFitted Parameters:")
    print(f"FWHM [fs]  = {abs(popt[1]) * 2.355:.2f}")
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
        Experiment name (used to construct the eLog endpoint URL).
    fig : matplotlib.figure.Figure
        Combined timing-analysis figure to attach to the eLog entry.
    run_number : str or int
        Run number being analysed.
    t_stage : str
        Name of the scanned timing motor.
    popt : array-like
        Fitted ERF parameters ``[a, sigma, mu, b]``.
    """
    try:
        from krtc import KerberosTicket
        import requests
    except ImportError as e:
        logger.warning(f"Could not import package for eLog posting ({e}). Skipping.")
        return

    buf = io.BytesIO()
    fig.savefig(buf, format="jpeg", dpi=150, bbox_inches="tight")
    buf.seek(0)

    log_text = (
        f"Timing analysis\n"
        f"Run: {run_number}\n"
        f"Scan motor: {t_stage}\n"
        f"FWHM: {abs(popt[1]) * 2.355:.4f} (fit units)\n"
        f"Center: {popt[2]:.4f}"
    )

    ws_url = (
        f"https://pswww.slac.stanford.edu/ws-kerb/lgbk/lgbk/{exp}/ws/new_elog_entry"
    )
    try:
        krbheaders = KerberosTicket("HTTP@pswww.slac.stanford.edu").getAuthHeaders()
    except Exception as e:
        logger.warning(
            f"Kerberos authentication failed ({e}). "
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
    except Exception as e:
        logger.warning(f"Failed to post to eLog ({e})")


def output(
    facility: str = "S3DF",
    exp: str = None,
    run: str = None,
    camera: str = "alvium_dg3",
    output_dir: str = None,
    post_to_elog: bool = True,
):
    """Generates the output of the timing scan.

    Parameters:
        facility (str):
            Default: "S3DF". Options: "S3DF, NERSC
        exp (str):
            experiment number. Current experiment by default
        run (str):
            The run you'd like to process
        camera (str):
            Detector name for the camera. Default: 'alvium_dg3'
        output_dir (str):
            Base output directory. Default: /sdf/data/lcls/ds/mfx/{exp}/scratch/analyze_timing
        post_to_elog (bool):
            Automatically post the combined timing figure to the eLog
            (requires a valid Kerberos token via ``kinit``). Default: True
    """
    if exp is None:
        logger.warning(
            f"No experiment specified. Falling back to commissioning experiment: "
            f"{COMMISSIONING_EXP}. Pass exp= explicitly if this is not intended."
        )
        exp = COMMISSIONING_EXP

    if run is None:
        raise ValueError("run must be specified.")

    qadc0_low = 10
    qadc0_high = 50
    qadc1_low = 74
    qadc1_high = 130

    experiment = exp
    run_numbers = [run]

    # --- Build and create output directory ---
    if output_dir is None:
        output_dir = f"/sdf/data/lcls/ds/mfx/{exp}/scratch/analyze_timing"
    run_dir = Path(output_dir) / exp / f"run{int(run):03d}"
    save_outputs = True
    try:
        run_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Output directory: {run_dir}")
    except OSError as e:
        logger.warning(
            f"Could not create output directory {run_dir}: {e}. Outputs will not be saved."
        )
        save_outputs = False

    for run_number in run_numbers:
        logger.info(f"Processing run {run_number} for experiment {experiment}...")
        ds = DataSource(exp=experiment, run=int(run_number), xdetectors=["jungfrau"])

        for run in ds.runs():
            diode_0 = run.Detector("qadc_ch0")
            diode_1 = run.Detector("qadc_ch1")
            dg3_cam = run.Detector(camera)

            t_stage = get_scan_motor(run)
            tmptmp = run.Detector(t_stage)
            ipm = run.Detector("MfxDg2BmMon")

            evts = 0
            qadc0_cropped = []
            qadc1_cropped = []
            time_mot = []
            x_ray_diode_sum = []
            dg3_sum = []

            for i_evt, evt in enumerate(run.events()):
                evts += 1

                # Always collect stage position, IPM, and camera — independent of QADC
                time_mot.append(tmptmp(evt))
                x_ray_diode_sum.append(ipm.raw.totalIntensityJoules(evt))

                try:
                    img = dg3_cam.raw.value(evt)
                    img_sum = np.sum(img) if img is not None else np.nan
                except Exception:
                    img_sum = np.nan
                dg3_sum.append(img_sum)

                # QADC — append nan when absent so all lists stay aligned
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

            # Determine whether usable QADC data exists
            qadc_available = bool(np.any(np.isfinite(qadc0_cropped)))
            if not qadc_available:
                logger.warning(
                    "No QADC data found in this run. QADC plots and fit will be skipped."
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

            # ---------------------------------------------------------------
            # Combined multipanel figure — the original three plot windows
            # are merged into a single 2×2 display:
            #
            #   [0,0] Raw QADC Ch1 scatter   [0,1] Raw camera scatter
            #   [1,0] Binned scatter          [1,1] ERF fit
            #
            # Only the combined figure is shown.  The ERF fit panel (bottom-
            # right) is also posted to the eLog when post_to_elog=True.
            # ---------------------------------------------------------------
            fig_combined, axes = plt.subplots(2, 2, figsize=(12, 8))
            ax_raw_qadc, ax_raw_cam = axes[0]
            ax_binned, ax_fit = axes[1]

            # --- Panel 1 (top-left): Raw QADC Ch1 scatter ---
            if qadc_available:
                ax_raw_qadc.scatter(df["t_position"], df["normalized_laser"], s=0.1)
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
            ax_raw_qadc.set_title(f"QADC Ch1 | Run {run_number} | {t_stage}")
            ax_raw_qadc.set_xlabel(t_stage)
            ax_raw_qadc.set_ylabel("QADC Ch1 signal (arb. units)")

            # --- Panel 2 (top-right): Raw camera scatter ---
            ax_raw_cam.scatter(df["t_position"], df["normalized_laser_dg3"], s=0.1)
            ax_raw_cam.set_title(f"Camera: {camera} | Run {run_number} | {t_stage}")
            ax_raw_cam.set_xlabel(t_stage)
            ax_raw_cam.set_ylabel("Camera image sum (arb. units)")

            # --- Per-signal pipeline: outlier removal → bin → fit → save ---
            signals_to_process = [(camera, "normalized_laser_dg3")]
            if qadc_available:
                signals_to_process.append(("qadc", "normalized_laser"))

            for i_sig, (sig_label, sig_col) in enumerate(signals_to_process):
                logger.info(f"Processing signal: {sig_label} ({sig_col})")

                # Outlier removal using IQR
                Q1 = df[sig_col].quantile(0.25)
                Q3 = df[sig_col].quantile(0.75)
                IQR = Q3 - Q1
                df_clean = df[
                    (df[sig_col] >= Q1 - 1.5 * IQR) & (df[sig_col] <= Q3 + 1.5 * IQR)
                ].copy()

                if save_outputs:
                    csv_path = run_dir / f"data_{sig_label}.csv"
                    df_clean.to_csv(csv_path, index=False)
                    logger.info(f"Cleaned data saved to {csv_path}")

                # Bin
                n_bins = 100
                if t_stage in ("lxt_ttc", "mfx_lxt_fast1", "mfx_lxt_fast2"):
                    df_clean["t_bin"] = pd.cut(
                        df_clean["t_position"].astype(float), bins=n_bins
                    )
                else:
                    df_clean["t_bin"] = pd.cut(df_clean["t_position"], bins=n_bins)

                binned = df_clean.groupby("t_bin").agg(
                    {"t_position": "mean", sig_col: "mean"}
                )

                if i_sig == 0:
                    # --- Panel 3 (bottom-left): Binned scatter for first signal ---
                    ax_binned.scatter(
                        binned["t_position"], binned[sig_col], color="royalblue", s=40
                    )
                    ax_binned.set_xlabel(t_stage)
                    ax_binned.set_ylabel(sig_col)
                    ax_binned.set_title(
                        f"Binned Scatter (Outliers Removed) | {sig_label} | Run {run_number}"
                    )
                    ax_binned.grid(True)

                    # --- Panel 4 (bottom-right): ERF fit for first signal ---
                    popt, _, _, _ = fit_irfs1(
                        binned["t_position"],
                        binned[sig_col],
                        run_number,
                        t_stage,
                        save_path=None,  # combined figure saved below
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
                        with open(json_path, "w") as f:
                            json.dump(fit_params, f, indent=2)
                        logger.info(f"Fit parameters saved to {json_path}")

                    # Finalise combined figure
                    fig_combined.suptitle(
                        f"Timing Analysis | Run {run_number} | {t_stage}", fontsize=13
                    )
                    fig_combined.tight_layout()

                    if save_outputs:
                        combined_path = (
                            run_dir / f"combined_timing_run{int(run_number):03d}.png"
                        )
                        fig_combined.savefig(
                            combined_path, dpi=150, bbox_inches="tight"
                        )
                        logger.info(f"Combined timing plot saved to {combined_path}")

                    if post_to_elog:
                        logger.info("Posting timing analysis to eLog...")
                        _post_to_elog(exp, fig_combined, run_number, t_stage, popt)

                    try:
                        plt.show()
                    except Exception as e:
                        logger.warning(f"Could not display plot: {e}")
                    plt.close(fig_combined)

                else:
                    # Additional signals (e.g., QADC): save outputs but do not display
                    fig_extra, ax_extra = plt.subplots(figsize=(6, 4))
                    ax_extra.scatter(
                        binned["t_position"], binned[sig_col], color="royalblue", s=40
                    )
                    ax_extra.set_xlabel(t_stage)
                    ax_extra.set_ylabel(sig_col)
                    ax_extra.set_title(
                        f"Binned Scatter (Outliers Removed) | {sig_label} | Run {run_number}"
                    )
                    ax_extra.grid(True)
                    fig_extra.tight_layout()
                    if save_outputs:
                        fig_extra.savefig(
                            run_dir / f"scatter_binned_{sig_label}.png",
                            dpi=150,
                            bbox_inches="tight",
                        )
                        logger.info(
                            f"Binned scatter plot saved to "
                            f"{run_dir / f'scatter_binned_{sig_label}.png'}"
                        )
                    plt.close(fig_extra)

                    popt2, _, _, _ = fit_irfs1(
                        binned["t_position"],
                        binned[sig_col],
                        run_number,
                        t_stage,
                        save_path=(run_dir / f"fit_{sig_label}.png")
                        if save_outputs
                        else None,
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
                        with open(json_path2, "w") as f:
                            json.dump(fit_params2, f, indent=2)
                        logger.info(f"Fit parameters saved to {json_path2}")


def parse_args(args):
    """Parse command line parameters

    Args:
      args ([str]): command line parameters as list of strings

    Returns:
      :obj:`argparse.Namespace`: command line parameters namespace
    """
    parser = argparse.ArgumentParser(description="startup script for cctbx on iana.")
    parser.add_argument(
        "--facility",
        "-f",
        dest="facility",
        default=None,
        help="Enter -f to specify facility",
    )
    parser.add_argument(
        "--type",
        "-t",
        dest="run_type",
        default=None,
        help="Enter -t to specify which step proxy or output",
    )
    parser.add_argument(
        "--experiment",
        "-e",
        dest="experiment",
        default=None,
        help="Enter -e to specify experiment number",
    )
    parser.add_argument(
        "--run",
        "-r",
        dest="run",
        default=None,
        help="Enter -r for the run you'd like to process.",
    )
    parser.add_argument(
        "--camera",
        "-c",
        dest="camera",
        default="alvium_dg3",
        help="Detector name for the camera. Default: alvium_dg3",
    )
    parser.add_argument(
        "--output",
        "-o",
        dest="output",
        default=None,
        help="Base output directory. Default: /sdf/data/lcls/ds/mfx/{exp}/scratch/analyze_timing",
    )
    parser.add_argument(
        "--post-to-elog",
        "-p",
        dest="post_to_elog",
        action="store_true",
        default=True,
        help=(
            "Post the combined timing figure to the eLog after the fit "
            "(requires a valid Kerberos token via kinit). Default: enabled."
        ),
    )
    parser.add_argument(
        "--no-post-to-elog",
        dest="post_to_elog",
        action="store_false",
        help="Disable automatic eLog posting.",
    )
    return parser.parse_args(args)


def main(args):
    """
    Main entry point allowing external calls
    Entry point for console_scripts
    Args:
      args ([str]): command line parameter list
    """
    args = parse_args(args)

    output_dir = args.output
    if output_dir is None:
        output_dir = f"/sdf/data/lcls/ds/mfx/{args.experiment}/scratch/analyze_timing"

    if args.run_type == "proxy":
        proxy_jump(args.facility, args.experiment, args.run, args.camera, output_dir)
    elif args.run_type == "output":
        output(
            args.facility,
            args.experiment,
            args.run,
            args.camera,
            output_dir,
            args.post_to_elog,
        )


def run():
    """Entry point for console_scripts"""
    main(sys.argv[1:])


if __name__ == "__main__":
    run()
