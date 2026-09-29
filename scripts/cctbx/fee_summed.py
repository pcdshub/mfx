import io
import sys
import argparse

import psana
import numpy as np
from matplotlib import pyplot as plt
from scipy.signal import savgol_filter


def process_runs(exp, runs):
    """Accumulate FEE spectrometer data across one or more runs.

    Parameters
    ----------
    exp : str
        Experiment name.
    runs : list of int
        Run numbers to process.

    Returns
    -------
    data : numpy.ndarray
        Normalised, accumulated horizontal projection spectrum.
    events : list of int
        Per-event FEE presence flags (1 present, 0 absent).
    maxes : list of float
        Per-event maximum intensity values for good events.
    total : int
        Total number of good events accumulated.
    """
    data = None
    events = []
    maxes = []
    total = 0

    for r in runs:
        ds = psana.DataSource(exp=exp, run=r, detectors=["feespec"])
        for run in ds.runs():
            d = run.Detector("feespec")
            for evt in run.events():
                f = d.raw.hproj(evt)
                if f is not None:
                    events.append(1)
                else:
                    events.append(0)
                    continue
                dta = f.astype(float)
                maxes.append(np.max(dta))
                if data is None:
                    data = dta
                else:
                    data += dta
                total += 1
        print(
            f"run {r}  max x pos {np.argmax(data)}  "
            f"max value {np.max(data)}"
        )

    print(f"Total good events: {total}")
    data /= total
    data /= np.max(data)
    return data, events, maxes, total


def plot_spectrum(exp, runs, data):
    """Plot the normalised FEE spectrum with smoothed overlay and gradient.

    Parameters
    ----------
    exp : str
        Experiment name, used in the plot title.
    runs : list of int
        Run numbers, used in the legend label.
    data : numpy.ndarray
        Normalised accumulated spectrum.

    Returns
    -------
    fig : matplotlib.figure.Figure
        The spectrum figure.
    edge_pixel : int
        Pixel position of the gradient minimum (absorption edge).
    """
    smoothed = savgol_filter(data, 51, 3)
    grad = np.gradient(smoothed)
    edge_pixel = int(np.argmin(grad))
    grad = (grad - np.min(grad)) / (np.max(grad) - np.min(grad))

    x = range(len(data))
    # To label the x-axis as energy, replace the line above with:
    # x = np.array(range(len(data))) * 0.07512 + 9625.1

    fig, ax = plt.subplots()
    ax.plot(x, data, "-")
    ax.plot(x, smoothed, "-")
    ax.plot(x, grad, "-")
    ax.axvline(edge_pixel, color="k", linestyle="--", label="_nolegend_")
    ax.text(
        edge_pixel,
        ax.get_ylim()[1],
        f" edge: {edge_pixel} px",
        va="top",
        fontsize=8,
    )
    ax.legend(
        [
            f"{min(runs)}-{max(runs)}",
            "Smoothed",
            "Gradient",
        ]
    )
    ax.set_title(f"FEE spec for {exp} runs")
    ax.set_xlabel("Pixel")
    # ax.set_xlabel("Energy (eV)")
    ax.set_ylabel("Mean counts")
    return fig, edge_pixel


def plot_presence(events):
    """Plot FEE detector presence as a function of event number.

    Parameters
    ----------
    events : list of int
        Per-event FEE presence flags (1 present, 0 absent).
    """
    fig, ax = plt.subplots()
    ax.plot(range(len(events)), events, "-")
    ax.set_title("FEE presence over time")
    ax.set_xlabel("Event number")
    ax.set_ylabel("FEE present (1 yes, 0 no)")
    return fig


def plot_histogram(maxes):
    """Plot a histogram of per-event maximum intensity values.

    Parameters
    ----------
    maxes : list of float
        Per-event maximum intensity values.

    Returns
    -------
    matplotlib.figure.Figure
        The histogram figure.
    """
    fig, ax = plt.subplots()
    ax.hist(maxes, bins=100)
    ax.set_xlabel("Max intensity")
    ax.set_ylabel("Count")
    ax.set_title("Per-event max intensity distribution")
    return fig


def post_to_elog(exp, fig, runs, total, edge_pixel):
    """Post the FEE spectrum figure to the LCLS eLog.

    Authentication is performed via Kerberos; a valid token must exist
    before calling this function (obtain one with ``kinit``).

    Parameters
    ----------
    exp : str
        Experiment name (used to construct the eLog endpoint URL).
    fig : matplotlib.figure.Figure
        Spectrum figure to attach to the eLog entry.
    runs : list of int
        Run numbers included in the plot.
    total : int
        Total number of good events accumulated.
    edge_pixel : int
        Pixel position of the gradient minimum (absorption edge).
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
        f"FEE spectrometer foil edge scan\n"
        f"Experiment: {exp}\n"
        f"Runs: {min(runs)}-{max(runs)}\n"
        f"Total good events: {total}\n"
        f"Edge pixel (gradient minimum): {edge_pixel}"
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
            files=[("files", ("fee_summed.jpg", buf, "image/jpeg"))],
            headers=krbheaders,
        )
        r.raise_for_status()
        result = r.json()
        if result.get("success"):
            print("  Spectrum posted to eLog successfully.")
        else:
            print(f"  eLog post returned an error: {result}")
    except Exception as e:
        print(f"  Warning: failed to post to eLog ({e})")


def parse_args(args):
    """Parse command-line arguments.

    Parameters
    ----------
    args : list of str
        Raw command-line arguments (typically ``sys.argv[1:]``).

    Returns
    -------
    argparse.Namespace
        Parsed arguments with attributes ``exp``, ``runs``, and
        ``post_to_elog``.
    """
    parser = argparse.ArgumentParser(
        description="Plot summed FEE spectrometer data for one or more runs."
    )
    parser.add_argument(
        "exp",
        help="Experiment name (e.g. mfxdaq13)",
    )
    parser.add_argument(
        "runs",
        nargs="+",
        type=int,
        help="Run number(s) to process",
    )
    parser.add_argument(
        "--no-post-to-elog",
        dest="post_to_elog",
        action="store_false",
        default=True,
        help="Disable posting the spectrum plot to the eLog",
    )
    return parser.parse_args(args)


def main(args):
    """Run the FEE summed spectrum pipeline.

    Accumulates FEE spectra from psana, produces diagnostic plots, and
    optionally posts the spectrum figure to the eLog.

    Parameters
    ----------
    args : list of str
        Command-line arguments (typically ``sys.argv[1:]``).
    """
    args = parse_args(args)
    data, events, maxes, total = process_runs(args.exp, args.runs)

    fig_spec, edge_pixel = plot_spectrum(args.exp, args.runs, data)
    plot_presence(events)
    plot_histogram(maxes)

    if args.post_to_elog:
        print("\nPosting spectrum plot to eLog...")
        post_to_elog(args.exp, fig_spec, args.runs, total, edge_pixel)

    plt.show()


if __name__ == "__main__":
    main(sys.argv[1:])
