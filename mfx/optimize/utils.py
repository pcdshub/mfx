"""
Utility functions for MFX optimization.
"""

import logging
import matplotlib.pyplot as plt
import numpy as np
import torch
import pandas as pd
from lcls_tools.common.image.fit import ImageProjectionFit

from .constraints import constraint_data
from .beamline_hw import sim_devices
from .user_select import select_diagnostic
from xopt.generators.bayesian.visualize import (
    _generate_input_mesh,
    _get_model_predictions,
)


def _to_numpy(x):
    """Convert torch.Tensor or array-like to numpy.ndarray safely."""
    if isinstance(x, np.ndarray):
        return x
    try:
        import torch as _torch  # local import to avoid hard dep at import time
        if isinstance(x, _torch.Tensor):
            return x.detach().cpu().numpy()
    except Exception:
        pass
    return np.asarray(x)

# Set up logging
logger = logging.getLogger(__name__)


def set_yag_constraints(
    location: str,
    roi_center: tuple[int, int] | None = None,
    roi_radius: int | None = None,
) -> None:
    """
    Update YAG constraints at runtime.

    Parameters
    ----------
    location : str
        YAG location key (e.g. "dg1", "dg2", "xcs1")
    roi_center : tuple[int, int] | None
        New ROI center in pixels. If None, leaves unchanged.
    roi_radius : int | None
        New ROI radius in pixels. If None, leaves unchanged.
    """
    if location not in constraint_data.yag:
        raise KeyError(f"Unknown YAG location '{location}'. Known: {list(constraint_data.yag.keys())}")
    yag_constr = constraint_data.yag[location]
    if roi_center is not None:
        logger.info(f"Setting YAG '{location}' ROI center to {roi_center}")
        yag_constr.roi_center = roi_center
    if roi_radius is not None:
        logger.info(f"Setting YAG '{location}' ROI radius to {roi_radius}")
        yag_constr.roi_radius = int(roi_radius)


def set_und_constraints(
    xy_delta: float | None = None,
    max_travel_distance: float | None = None,
) -> None:
    """
    Update Undulator constraints at runtime.

    Parameters
    ----------
    xy_delta : float | None
        New symmetric delta range around start position for both axes.
    max_travel_distance : float | None
        New max per-step travel distance in real units for each axis.
    """
    und = constraint_data.und
    if xy_delta is not None:
        logger.info(f"Setting Undulator xy_delta to {xy_delta}")
        und.xy_delta = float(xy_delta)
    if max_travel_distance is not None:
        logger.info(f"Setting Undulator max_travel_distance to {max_travel_distance}")
        und.max_travel_distance = float(max_travel_distance)

def plot_yag_optimization_setup(
    roi_center: tuple[int, int] = None,
    roi_radius: int = None,
    goal_2d: tuple[int, int] = None,
    yag_location: str = "dg1",
    show_plot: bool = True,
) -> tuple[np.ndarray, tuple[float, float]]:
    """
    Plot YAG optimization setup with ROI center, goal, and beam centroid.
    
    Parameters
    ----------
    roi_center : tuple[int, int], optional
        ROI center coordinates (x, y)
    roi_radius : int, optional
        ROI radius
    goal_2d : tuple[int, int], optional
        Goal 2D coordinates (x, y)
    yag_location : str, optional
        YAG diagnostic location, by default "dg1"
    figsize : tuple[int, int], optional
        Figure size for the plot, by default (10, 8)
    show_plot : bool, optional
        Whether to display the plot, by default True
        
    Returns
    -------
    tuple[np.ndarray, tuple[float, float]]
        Tuple containing (image_array, beam_centroid_coordinates)
    """
    # if use_sim:
    #     logger.info("Initializing simulated devices...")
    #     sim_devices()
    #     logger.info("Simulated devices initialized.")
    
    if roi_center is None:
        print("No ROI center provided, using constraint data")
        roi_center = constraint_data.yag[yag_location].roi_center
    if roi_radius is None:
        print("No ROI radius provided, using constraint data")
        roi_radius = constraint_data.yag[yag_location].roi_radius
    if goal_2d is None:
        print("No goal 2D provided, using center of ROI")
        goal_2d = roi_center
    
    logger.info(f"ROI Center: {roi_center}")
    logger.info(f"ROI Radius: {roi_radius}")
    logger.info(f"Goal 2D: {goal_2d}")
    
    # Get YAG image and process it to find beam centroid
    yag = select_diagnostic(device_type="yag", location=yag_location)
    yag.image1.shaped_image.trigger().wait(timeout=1)
    img = yag.image1.shaped_image.get()
    
    # Fit the image to find beam centroid
    fit = ImageProjectionFit()
    fit_result = fit.fit_image(img)
    beam_centroid = (fit_result.centroid[0], fit_result.centroid[1])
    
    logger.info(f"Beam Centroid: {beam_centroid}")
    
    # Display image with crosses
    plt.figure(figsize=(10, 8))
    plt.imshow(img, cmap="gray")
    
    # Add cross at ROI center (red)
    plt.plot(roi_center[0], roi_center[1], 'r+', markersize=15, markeredgewidth=3, label='ROI Center')
    plt.plot(roi_center[0], roi_center[1], 'ro', markersize=8, fillstyle='none', markeredgewidth=2)
    
    # Add cross at goal_2d (green) 
    plt.plot(goal_2d[0], goal_2d[1], 'g+', markersize=15, markeredgewidth=3, label='Goal 2D')
    plt.plot(goal_2d[0], goal_2d[1], 'go', markersize=8, fillstyle='none', markeredgewidth=2)
    
    # Add cross at beam centroid (blue)
    plt.plot(beam_centroid[0], beam_centroid[1], 'b+', markersize=15, markeredgewidth=3, label='Beam Centroid')
    plt.plot(beam_centroid[0], beam_centroid[1], 'bo', markersize=8, fillstyle='none', markeredgewidth=2)
    
    # Add ROI circle using constraint data
    circle = plt.Circle(roi_center, roi_radius,
                       fill=False, color='red', linestyle='--', alpha=0.7, label='ROI Boundary')
    plt.gca().add_patch(circle)
    
    plt.legend()
    plt.title('YAG Image with ROI Center and Goal')
    plt.xlabel('X Position (pixels)')
    plt.ylabel('Y Position (pixels)')
    
    if show_plot:
        plt.show()
    
    return img, beam_centroid


def quick_yag_plot():
    """
    Quick function to plot YAG optimization setup with default parameters.
    Convenient for IPython usage.
    """
    return plot_yag_optimization_setup()


def plot_gp_landscape(
    opt,
    resolution: int = 50,
    figsize: tuple[int, int] = (12, 5),
    output_name: str = "objective",
):
    """
    Plot the Gaussian Process approximation of the objective landscape.
    
    This function visualizes what the GP thinks the optimization landscape looks like
    after being seeded with data points from random_evaluate().
    
    Parameters
    ----------
    opt : Xopt
        The Xopt optimization object that has been seeded with data
    resolution : int, optional
        Resolution of the grid for plotting, by default 50
    figsize : tuple[int, int], optional
        Figure size for the plot, by default (12, 5)
    """
    if not hasattr(opt, 'generator'):
        raise ValueError("Provided object does not look like an Xopt instance (missing generator)")

    # Train or retrieve the underlying GP model from the generator
    # This is the supported pattern in Xopt examples
    model = opt.generator.train_model()
    
    # Get variable bounds from VOCS
    vocs = opt.vocs
    variables = vocs.variables
    var_names = list(variables.keys())
    if len(var_names) == 0:
        raise ValueError("VOCs has no variables to plot")

    # Torch dtype/device kwargs (CPU + double precision)
    tkwargs = {"dtype": torch.double, "device": torch.device("cpu")}
    
    if len(var_names) == 1:
        # 1D case
        var_name = var_names[0]

        # Build input mesh using Xopt utilities (handles transforms/ordering)
        input_mesh = _generate_input_mesh(
            vocs, [var_name], reference_point=None, n_grid=resolution, tkwargs=tkwargs
        )

        # Get predictions for the desired output
        with torch.no_grad():
            mean_t, std_t, _ = _get_model_predictions(
                model, vocs, output_name, input_mesh
            )

        mean = _to_numpy(mean_t).squeeze()
        std = _to_numpy(std_t).squeeze()
        x_plot = _to_numpy(input_mesh.squeeze(1))
        
        # Plot
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=figsize)
        
        # Mean prediction
        ax1.plot(x_plot, mean, 'b-', label='GP Mean', linewidth=2)
        ax1.fill_between(x_plot, mean - 2*std, mean + 2*std, 
                        alpha=0.3, color='blue', label='±2σ Confidence')
        
        # Plot data points
        if hasattr(opt, 'data') and not opt.data.empty:
            data_x = opt.data[var_name].values
            data_y = opt.data['objective'].values
            ax1.scatter(data_x, data_y, color='red', s=50, zorder=5, label='Data Points')
        
        ax1.set_xlabel(var_name)
        ax1.set_ylabel('Objective')
        ax1.set_title('GP Mean Prediction')
        ax1.legend()
        ax1.grid(True, alpha=0.3)
        
        # Standard deviation (uncertainty)
        ax2.plot(x_plot, std, 'r-', linewidth=2, label='GP Uncertainty')
        ax2.set_xlabel(var_name)
        ax2.set_ylabel('Standard Deviation')
        ax2.set_title('GP Uncertainty')
        ax2.legend()
        ax2.grid(True, alpha=0.3)
        
    elif len(var_names) == 2:
        # 2D case
        var1_name, var2_name = var_names

        # Build input mesh using Xopt utilities (handles transforms/ordering)
        input_mesh = _generate_input_mesh(
            vocs, [var1_name, var2_name], reference_point=None, n_grid=resolution, tkwargs=tkwargs
        )

        # Predict for the desired output
        with torch.no_grad():
            mean_t, std_t, _ = _get_model_predictions(
                model, vocs, output_name, input_mesh
            )

        # Reshape predictions back to grid
        mean = _to_numpy(mean_t).reshape(resolution, resolution)
        std = _to_numpy(std_t).reshape(resolution, resolution)

        # Also reshape coordinates for contourf
        x1 = _to_numpy(input_mesh[:, 0]).reshape(resolution, resolution)
        x2 = _to_numpy(input_mesh[:, 1]).reshape(resolution, resolution)
        X1_np, X2_np = x1, x2
        
        # Plot
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=figsize)
        
        # Mean prediction
        im1 = ax1.contourf(X1_np, X2_np, mean, levels=20, cmap='viridis')
        ax1.set_xlabel(var1_name)
        ax1.set_ylabel(var2_name)
        ax1.set_title('GP Mean Prediction')
        plt.colorbar(im1, ax=ax1, label='Objective')
        
        # Plot data points
        if hasattr(opt, 'data') and not opt.data.empty:
            data_x1 = opt.data[var1_name].values
            data_x2 = opt.data[var2_name].values
            ax1.scatter(data_x1, data_x2, color='red', s=50, zorder=5, label='Data Points')
            ax1.legend()
        
        # Standard deviation (uncertainty)
        im2 = ax2.contourf(X1_np, X2_np, std, levels=20, cmap='Reds')
        ax2.set_xlabel(var1_name)
        ax2.set_ylabel(var2_name)
        ax2.set_title('GP Uncertainty')
        plt.colorbar(im2, ax=ax2, label='Standard Deviation')
        
        # Plot data points on uncertainty plot too
        if hasattr(opt, 'data') and not opt.data.empty:
            ax2.scatter(data_x1, data_x2, color='black', s=50, zorder=5, label='Data Points')
            ax2.legend()
    
    else:
        raise ValueError(f"Can only plot 1D or 2D landscapes. Found {len(var_names)} variables: {var_names}")
    
    plt.tight_layout()
    plt.show()


def snake_order(df, x="undp_x", y="undp_y", start="asc"):
    """
    Reorders rows in a serpentine ('snake') path.
      - start: 'asc' -> first row goes low→high in x, 'desc' -> high→low in x
    """
    # sort rows by y (outer) and x (inner) to get clean bands
    base = df.sort_values([y, x], ascending=[False, True]).reset_index(drop=True)

    # assign band index in the order of y levels (no resorting within groupby)
    bands = []
    for i, (_, g) in enumerate(base.groupby(y, sort=False)):
        # decide direction for this band
        go_asc = (i % 2 == 0) if start == "asc" else (i % 2 == 1)
        g = g.sort_values(x, ascending=go_asc)
        bands.append(g)

    return pd.concat(bands, ignore_index=True)
