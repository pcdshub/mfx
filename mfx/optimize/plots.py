"""
Matplotlib plotting utilities for tracking the optimizer's decisions.
"""
import matplotlib.figure
import matplotlib.pyplot as plt
import numpy as np

def centroid_path_plot(
    image: np.ndarray,
    goal: tuple[float, float],
    centroids: list[tuple[float, float]],
) -> matplotlib.figure.Figure:
    fig = plt.figure()
    plt.imshow(image)
    plt.plot(*goal, marker="o", color="red")
    for pt in centroids:
        plt.plot(*pt, marker=".", color="white")
    plt.show()
    return fig
