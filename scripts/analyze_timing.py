# -*- coding: utf-8 -*-
"""
analyze_timing
"""
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

def proxy_jump(
        facility: str = "S3DF",
        exp: str = None,
        run: str = None):
    """ Generates the output of the energy scan or series.

    Parameters:
        facility (str):
            Default: "S3DF". Options: "S3DF, NERSC
        exp (str):
            experiment number. Current experiment by default
        run (str):
            The run you'd like to process
    """
    if facility.upper() == "NERSC": #need paths to work on nersc
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
            f"python /sdf/group/lcls/ds/tools/mfx/scripts/analyze_timing.py "
            f"-f {facility} -t output -e {exp} -r {run}'"
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
    ignore = {'step_value', 'step_docstring'}

    mot_name = next( k[0] for k in tmp if k[1] == 'raw' and k[0] not in ignore)
    logger.info(f'Scanning motor found as: {mot_name}')
    return mot_name

def custom_erf(x, a, sigma, mu, b):
            return a * special.erf((x - mu) / (np.sqrt(2) * sigma)) + b

def fit_irfs1(x_data, y_data, run_number, t_stage):
    # Convert to numpy arrays
    x_data = np.asarray(x_data, dtype=float)
    y_data = np.asarray(y_data, dtype=float)

    # Remove NaNs and infs
    mask = np.isfinite(x_data) & np.isfinite(y_data)
    x_data = x_data[mask]
    y_data = y_data[mask]

    # Safety check
    if len(x_data) < 5:
        raise ValueError("Not enough valid points after removing NaNs/Infs")

    # Normalize safely
    ymax = np.max(y_data)
    if ymax != 0:
        y_data = y_data / ymax
    else:
        raise ValueError("y_data max is zero — cannot normalize")

    # Initial guesses
    a_initial = np.max(y_data) - np.min(y_data)
    mu_initial = -1e-12
    sigma_initial = (x_data.max() - x_data.min()) / 100
    b_initial = np.min(y_data)

    p0 = (a_initial, sigma_initial, mu_initial, b_initial)

    # Fit
    popt, pcov = curve_fit(custom_erf, x_data, y_data, p0=p0)

    # Generate fit
    y_fit = custom_erf(x_data, *popt)

    # Sort for plotting
    order = np.argsort(x_data)
    x_sorted = x_data[order]
    y_fit_sorted = y_fit[order]

    # Plot
    plt.figure(figsize=(5, 3))
    plt.scatter(x_data, y_data, s=15, label='Data')
    plt.plot(
        x_sorted,
        y_fit_sorted,
        label=f'Fitted irf, width = {popt[1] * 2.355 * 1e15:.2f} fs'
    )
    plt.xlabel('X')
    plt.ylabel('Y')
    plt.title(f'Sigmoid Fit for run {run_number} scanning {t_stage}')
    plt.legend()
    plt.grid()
    plt.show()

    # Print results
    logger.info("Fitted Parameters:")
    logger.info(f'width = {popt[1] * 2.355}')
    logger.info(f'offset [ps] = {popt[2] * 1e12}')

    return popt, x_data, y_data, y_fit

def output(
        facility: str = "S3DF",
        exp: str = None,
        run: str = None):
    """ Generates the output of the timing scan.

    Parameters:
        facility (str):
            Default: "S3DF". Options: "S3DF, NERSC
        exp (str):
            experiment number. Current experiment by default
        run (str):
            The run you'd like to process
    """
    qadc0_low = 10
    qadc0_high = 50
    qadc1_low = 93
    qadc1_high = 104

    # diode_0 = run.Detector('qadc_ch0')
    # diode_1 = run.Detector('qadc_ch1')

    # plt.plot(diode_0[qadc0_low:qadc0_high],label='qadc0')
    # plt.plot(diode_1[qadc1_low:qadc1_high],label='qadc1')
    # plt.legend()

    # Load all QADC data from XTC and save in a df
    experiment = exp
    run_numbers = [run]

    all_counts=[]
    evts=0
    qadc0_cropped = []
    qadc1_cropped = []
    time_mot = []
    x_ray_diode_sum = []
    x = []

    # Load QADC and timing info from XTC file and plot as funciton of time
    for run_number in run_numbers:
        logger.info(f'Processing run {run_number} for experiment {experiment}...')
        ds = DataSource(exp=experiment, run=int(run_number), xdetectors=['jungfrau'])
        for run in ds.runs():
            diode_0 = run.Detector('qadc_ch0')
            diode_1 = run.Detector('qadc_ch1')

            t_stage = get_scan_motor(run) #'lxt', 'lxt_ttc", 'mfx_lxt_fast1' ect..

            evts=0
            for i_evt, evt in enumerate(run.events()):
                evts+=1
                diode_val_0 = diode_0.raw.value(evt)
                diode_val_1 = diode_1.raw.value(evt)
                if diode_val_0 is not None and diode_val_1 is not None:
                    tmp0 = np.sum(np.abs(diode_val_0[qadc0_low:qadc0_high]))
                    tmp1 = np.sum(np.abs(diode_val_1[qadc1_low:qadc1_high]))

                    qadc0_cropped.append(tmp0)
                    qadc1_cropped.append(tmp1)

                    # tmptmp = run.Detector('mfx_lxt_fast1')
                    # tmptmp = run.Detector('lxt')
                    # tmptmp = run.Detector('lxt_fast')
                    # tmptmp = run.Detector('lxt_ttc_set')

                    tmptmp = run.Detector(t_stage)
                    time_mot.append(tmptmp(evt))
                    # x.append(time_mot)
                    ipm= run.Detector('MfxDg2BmMon')
                    x_ray_diode_sum.append(ipm.raw.totalIntensityJoules(evt))
                    # timing = run.Detector('timing')

    qadc0_cropped = np.array(qadc0_cropped)
    qadc1_cropped = np.array(qadc1_cropped)

    # Calculate the sums for each event
    qadc0_sum_per_event = qadc0_cropped
    qadc1_sum_per_event = qadc1_cropped


    data = {
        # 't_position': t_position.squeeze(),
        't_position': time_mot,
        'qadc0_sum': qadc0_sum_per_event,
        'qadc1_sum': qadc1_sum_per_event,
        'x_ray_diode_sum': x_ray_diode_sum
        #'tt': tt
    }

    df = pd.DataFrame(data)

    df['normalized_laser'] = df['qadc1_sum'] # / df['qadc0_sum']
    df['normalized_laser_x_ray'] = df['normalized_laser']/df['x_ray_diode_sum']

    fig, axes = plt.subplots(1, 2, figsize=(10, 4), sharex=True)

    # Left plot
    axes[0].scatter(df['t_position'], df['normalized_laser'], s=0.1)
    axes[0].set_title(f'Run: {run_number}, scanning: {t_stage}')
    axes[0].set_xlabel('time (ps?)')
    axes[0].set_ylabel('normalized laser')

    # Right plot
    axes[1].scatter(df['t_position'], df['normalized_laser_x_ray'], s=0.1)
    axes[1].set_title('Normalized laser × X-ray')
    axes[1].set_xlabel('time (ps?)')

    plt.tight_layout()
    plt.show()

    # Remove outliers and bin data
    diode_repsonse = 'normalized_laser' # could use normalized_laser_x_ray if X-ray normalization look sensible
    # --- Remove outliers using IQR on normalized_laser ---
    Q1 = df['normalized_laser'].quantile(0.25)
    Q3 = df['normalized_laser'].quantile(0.75)
    IQR = Q3 - Q1

    # Keep only points within 1.5 * IQR
    df_clean = df[(df['normalized_laser'] >= Q1 - 1.5 * IQR) &
                (df['normalized_laser'] <= Q3 + 1.5 * IQR)]

    # --- Bin and plot ---
    n_bins = 100
    if t_stage == 'lxt_ttc' or t_stage == 'mfx_lxt_fast1' or t_stage == 'mfx_lxt_fast2':
        df_clean['t_bin'] = pd.cut(df_clean['t_position'].astype(float), bins=n_bins)
    else:
        df_clean['t_bin'] = pd.cut(df_clean['t_position'], bins=n_bins)

    binned = df_clean.groupby('t_bin').agg({
        't_position': 'mean',
        'normalized_laser': 'mean'
    })

    plt.scatter(binned['t_position'], binned['normalized_laser'], color='royalblue', s=40)
    plt.xlabel('t_position')
    plt.ylabel('normalized_laser')
    plt.title('Binned Scatter (Outliers Removed)')
    plt.grid(True)
    plt.show()

    # Now fit
    fit_irfs1(binned['t_position'], binned['normalized_laser'], run_number, t_stage)

def parse_args(args):
    """Parse command line parameters

    Args:
      args ([str]): command line parameters as list of strings

    Returns:
      :obj:`argparse.Namespace`: command line parameters namespace
    """
    parser = argparse.ArgumentParser(
        description="startup script for cctbx on iana."
    )
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
        help="Enter -r for the run you'd like to process."
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
    if args.run_type == "proxy":
        proxy_jump(args.facility, args.experiment, args.run)
    elif args.run_type == "output":
        output(args.facility, args.experiment, args.run)

def run():
    """Entry point for console_scripts"""
    main(sys.argv[1:])

if __name__ == "__main__":
    run()