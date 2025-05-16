"""
Matplotlib plotting utilities for tracking the optimizer's decisions.
"""

from typing import Optional, Union

from matplotlib.axes import Axes
from matplotlib.figure import Figure
import matplotlib.pyplot as plt
import numpy as np

from xopt import Xopt

from .constraints import YagConstraints
from .devices import YagCamera


def refresh_mpl_plots():
    """
    Call the required magic incantations to:
    - Show all open figures that haven't been shown yet
    - Make the active figure update in place right away

    To make something the "active figure", you simply
    need to call plt.figure(figure) on it.
    """
    plt.show(block=False)
    plt.pause(0.01)


def centroid_path_plot(
    image: np.ndarray,
    goal: Union[float, tuple[float, float]],
    markers: list[tuple[float, float]],
    centroids: list[tuple[float, float]],
    roi_center: Optional[tuple[int, int]] = None,
    roi_radius: Optional[int] = None,
    figure: Optional[Figure] = None,
) -> Figure:
    """
    Plot the path of a centroid alignment.

    The will include:
    - The YAG image in the background
    - The goal as a red x (or a vertical line)
    - The measured centroids as white dots
    - The camviewer markers as green + marks

    This is intended to help verify that the alignment
    is doing something useful and to debug when it does
    something unexpected. For example, if our coordinate
    system has an issue or the markers are set strangely
    it will become more obvious using this plot.

    Call refresh_mpl_plots afterwards if you'd like
    an immediate redraw.

    Parameters
    ----------
    image : np.ndarray
        The actual image of the YAG as a background.
    goal : float or tuple of floats
        The 1d goal (x) or 2d goal (x, y)
    markers : list of tuples of floats
        The locations of the markers to plot
    centroids : list of tuples of floats
        The locations of the centroids to plot
    roi_center : tuple[int, int], optional
        The center of a radial ROI to plot as a red circle.
    roi_radius : int, optional
        The radius of a radial ROI to plot as a red circle.
    figure : Figure, optional
        A figure to re-use (instead of making a new figure).
    """
    fig = plt.figure(figure)
    plt.clf()
    plt.imshow(image, "cividis")
    if roi_center is not None and roi_radius is not None:
        plt.gca().add_patch(plt.Circle(roi_center, roi_radius, color="r", fill=False))
    for pt in centroids:
        plt.plot(*pt, marker=".", color="white")
    for mk in markers:
        plt.plot(*mk, marker="+", color="lime")
    if isinstance(goal, float):
        plt.axvline(goal, color="red")
    else:
        plt.plot(*goal, marker="x", color="red")
    return fig


class UpdatingDeviceCentroidPathPlot:
    """
    Helper class for maintaining state and getting data for the path plot.

    This is intended to help us create a useful plot that updates
    as the scan proceeds.

    Parameters
    ----------
    imager : YagCamera
        The camera device instance.
    goal : tuple[float, float]
        The position we'd like the centroid to reach.
    constraints : YagConstraints, optional
        The constraints to include in the plot.
    """

    def __init__(self, imager: YagCamera, goal: tuple[float, float], constraints: Optional[YagConstraints] = None):
        self.fig = None
        self.imager = imager
        self.goal = goal
        self.points = []
        self.constraints = constraints
        if constraints is None:
            self.roi_center = None
            self.roi_radius = None
        else:
            self.roi_center = constraints.roi_center
            self.roi_radius = constraints.roi_radius

    def get_markers(self) -> list[tuple[int, int]]:
        """Helper to get the relevant global marker positions from the imager."""
        markers = []
        for num in range(4):
            try:
                coord = getattr(self.imager.coords, f"marker{num + 1}").get_coordinate()
            except RuntimeError:
                continue
            markers.append(coord)
        return markers

    def add_point(self, centroid: tuple[float, float]):
        """
        Add a new centroid to the plot and re-render.

        Parameters
        ----------
        centroid : tuple[float, float]
            The point to add.
        """
        self.points.append(centroid)
        self.refresh()

    def add_points(self, centroids: list[tuple[float, float]]):
        """
        Add multiple centroids to the plot at once and re-render.

        Parameters
        ----------
        centroids : list[tuple[float, float]]
            The points to add.
        """
        self.points.extend(centroids)
        self.refresh()

    def refresh(self):
        """
        Update plots without adding any points, e.g. to update the YAG image.
        """
        self.fig = centroid_path_plot(
            image=self.imager.image1.image,
            goal=self.goal,
            markers=self.get_markers(),
            centroids=self.points,
            roi_center=self.roi_center,
            roi_radius=self.roi_radius,
            figure=self.fig,
        )
        refresh_mpl_plots()


class UpdatingXoptVisualizeModelPlot:
    """
    Helpers for updating XOpt model plots in place.
    """

    def __init__(self, xopt: Xopt):
        self.xopt = xopt
        self.fig: Optional[Figure] = None
        self.axs: Optional[Union[Axes, np.ndarray]] = None

    def refresh(self):
        """
        Close the old plot and render the new plot.

        Re-rendering this in place without aberrations has been surprisingly difficult.
        """
        newfig, newaxs = self.xopt.generator.visualize_model(
            show_acquisition=False,
        )
        plt.figure(self.fig)
        plt.close()
        plt.figure(newfig)
        refresh_mpl_plots()
        self.fig = newfig
        self.axs = newaxs
