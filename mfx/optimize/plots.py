"""
Matplotlib plotting utilities for tracking the optimizer's decisions.
"""

from typing import Optional

import matplotlib.figure
import matplotlib.pyplot as plt
import numpy as np

from .devices import YagCamera


def refresh_mpl_plots():
    """
    Call the required magic incantations to:
    - Show all open figures that haven't been shown yet
    - Make every figure do a draw update right away.

    Do this outside of the plotting logic so we can
    decide when to draw updates and when not to.

    For example, you can do this once to update all
    four of your plots.
    """
    plt.show(block=False)
    plt.pause(0.01)


def centroid_path_plot(
    image: np.ndarray,
    goal: tuple[float, float],
    markers: list[tuple[float, float]],
    centroids: list[tuple[float, float]],
    figure: Optional[matplotlib.figure.Figure] = None,
) -> matplotlib.figure.Figure:
    """
    Plot the path of a centroid alignment.

    The will include:
    - The YAG image in the background
    - The goal as a red x
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

    """
    fig = plt.figure(figure)
    plt.clf()
    plt.imshow(image, "cividis")
    for pt in centroids:
        plt.plot(*pt, marker=".", color="white")
    for mk in markers:
        plt.plot(*mk, marker="+", color="lime")
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
    """

    def __init__(self, imager: YagCamera, goal: tuple[float, float]):
        self.fig = None
        self.imager = imager
        self.goal = goal
        self.points = []

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
        self.update_plot()

    def add_points(self, centroids: list[tuple[float, float]]):
        """
        Add multiple centroids to the plot at once and re-render.

        Parameters
        ----------
        centroids : list[tuple[float, float]]
            The points to add.
        """
        self.points.extend(centroids)
        self.update_plot()

    def update_plot(self):
        """
        Update plots without adding any points, e.g. to update the YAG image.

        Note: you still need to call refresh_mpl_plots or self.refresh to
        display the updated image.
        """
        self.fig = centroid_path_plot(
            image=self.imager.image1.image,
            goal=self.goal,
            markers=self.get_markers(),
            centroids=self.points,
            figure=self.fig,
        )

    def refresh(self):
        """
        Convenience helper if this is the only updating plot you have.
        """
        self._plot_updates()
        refresh_mpl_plots()