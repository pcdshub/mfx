"""
Matplotlib plotting utilities for tracking the optimizer's decisions.
"""
from typing import Optional

import matplotlib.figure
import matplotlib.pyplot as plt
import numpy as np

from .devices import YagCamera


def centroid_path_plot(
    image: np.ndarray,
    goal: tuple[float, float],
    markers: list[tuple[float, float]],
    centroids: list[tuple[float, float]],
    figure: Optional[matplotlib.figure.Figure] = None,
) -> matplotlib.figure.Figure:
    fig = plt.figure(figure)
    plt.clf()
    plt.imshow(image, "cividis")
    for pt in centroids:
        plt.plot(*pt, marker=".", color="white")
    for mk in markers:
        plt.plot(*mk, marker="+", color="lime")
    plt.plot(*goal, marker="x", color="red")
    plt.show(block=False)
    plt.pause(0.01)
    return fig


class UpdatingDeviceCentroidPathPlot:
    def __init__(self, imager: YagCamera, goal: tuple[float, float]):
        self.fig = None
        self.imager = imager
        self.goal = goal
        self.points = []

    def get_markers(self) -> list[tuple[int, int]]:
        markers = []
        for num in range(4):
            try:
                coord = getattr(self.imager.coords, f"marker{num+1}").get_coordinate()
            except RuntimeError:
                continue
            markers.append(coord)
        return markers

    def add_point(self, centroid: tuple[float, float]):
        self.points.append(centroid)
        self.refresh()

    def refresh(self):
        self.fig = centroid_path_plot(
            image=self.imager.image1.image,
            goal=self.goal,
            markers=self.get_markers(),
            centroids=self.points,
            figure=self.fig,
        )
