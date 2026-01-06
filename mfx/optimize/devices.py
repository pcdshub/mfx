"""
Ophyd devices created for these optimize routines.
"""

from __future__ import annotations

from typing import Callable

import numpy as np
from ophyd.areadetector.plugins import ImagePlugin
from ophyd.device import Component as Cpt
from ophyd.device import Device
from ophyd.signal import AttributeSignal, EpicsSignalRO, Signal


class Marker(Device):
    """
    Device representing a single camviewer global marker.

    Parameters
    ----------
    prefix : str
        The base prefix of the marker, for example MFX:DG1:P6740:Cross1
    """

    xpos = Cpt(EpicsSignalRO, "X")
    ypos = Cpt(EpicsSignalRO, "Y")

    def get_coordinate(self) -> tuple[int, int]:
        coords = (self.xpos.get(), self.ypos.get())
        if coords == (0, 0):
            raise RuntimeError(f"Marker coordinates for {self.name} not initialized!")
        return coords


class CamViewerCoords(Device):
    """
    Device for interpretting camviewer's global markers as scan targets.

    Parameters
    ----------
    prefix : str
        The base prefix of the camera, for example MFX:DG1:P6740
    """

    marker1 = Cpt(Marker, "Cross1")
    marker2 = Cpt(Marker, "Cross2")
    marker3 = Cpt(Marker, "Cross3")
    marker4 = Cpt(Marker, "Cross4")

    def specific_marker_target(self, marker_num: int) -> tuple[int, int]:
        """
        Get the coordinates of the specified marker for use as a scan target.
        """
        return getattr(self, f"marker{marker_num}").get_coordinate()

    def average_marker_target(
        self, marker_nums: tuple[int, ...] | list[int]
    ) -> tuple[float, float]:
        """
        Get the coordinate of the average position of the numbered markers.
        """
        if not marker_nums:
            raise ValueError("At least one marker number must be provided.")
        tot = sum(np.array(self.specific_marker_target(num)) for num in marker_nums)
        return tuple(tot / len(marker_nums))

    def standard_two_corners_target(self) -> tuple[float, float]:
        """
        Get the coordinate defined by markers 1 and 2 placed at the corners.

        Old camviewer versions only allow the user to change markers 1 and 2
        as global markers, so by convention these markers are placed at
        diagonally opposite corners of the apparent slit aperture.
        """
        return self.average_marker_target((1, 2))

    def standard_box_target(self) -> tuple[float, float]:
        """
        Get the coordinate defined by all four markers placed at the corners.

        New camviewer versions allow the user to change all four markers
        as global markers, so if these are all placed at the four corners
        the average of four markers may be preferrable to the average of two
        markers. This makes it so the function is not sentitive to
        marker ordering, for example.
        """
        return self.average_marker_target((1, 2, 3, 4))


class LCLSImagePlugin(ImagePlugin):
    """
    Small patch on top of built-in Image plugin to work around bug/incompatibility.
    """

    shaped_image = Cpt(AttributeSignal, "image", add_prefix=(), kind="omitted")


class YagCamera(Device):
    """
    One area detector camera on the beamline.

    Customized with what is most useful for us during an optimization routine.
    """

    image1 = Cpt(LCLSImagePlugin, "IMAGE1:")
    coords = Cpt(CamViewerCoords, "")


class FakeMarker(Marker):
    """
    Fake Marker to facilitate testing.
    """

    xpos = Cpt(Signal)
    ypos = Cpt(Signal)


class FakeCoords(CamViewerCoords):
    """
    Fake CamViewerCoords to facilitate testing.
    """

    marker1 = Cpt(FakeMarker, "")
    marker2 = Cpt(FakeMarker, "")
    marker3 = Cpt(FakeMarker, "")
    marker4 = Cpt(FakeMarker, "")


class FakeLCLSImagePlugin(LCLSImagePlugin):
    """
    Fake LCLSImagePlugin to facilitate testing.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.__size = (500, 500)
        self.__centroid = (100, 100)
        self.__fwhm = 10
        self.__peak = 255
        self.__updater = lambda _: None

    @property
    def image(self):
        self.__updater(self)
        return fake_yag_image(
            size=self.__size,
            centroid=self.__centroid,
            fwhm=self.__fwhm,
            peak=self.__peak,
        )

    def get_centroid(self):
        return self.__centroid

    def sim_set_image(
        self,
        size: tuple[int, int] | None = None,
        centroid: tuple[int, int] | None = None,
        fwhm: int | None = None,
        peak: int | None = None,
    ):
        """Test-only helper to set up the image."""
        if size is not None:
            self.__size = size
        if centroid is not None:
            self.__centroid = centroid
        if fwhm is not None:
            self.__fwhm = fwhm
        if peak is not None:
            self.__fwhm = fwhm

    def sim_install_updater(self, updater: Callable[[FakeLCLSImagePlugin], None]):
        """
        Install an imager updater function to be run before we get the image.
        """
        self.__updater = updater


def fake_yag_image(
    size: tuple[int, int],
    centroid: tuple[int, int],
    fwhm: int,
    peak: int,
) -> np.ndarray:
    """
    Return a gaussian blob that sort of looks like a beam profile.
    """
    # Adapted from https://stackoverflow.com/questions/7687679/how-to-generate-2d-gaussian-with-python
    x = np.arange(0, size[0], 1, float)
    y = np.arange(0, size[1], 1, float)[:, np.newaxis]
    x0 = centroid[0]
    y0 = centroid[1]
    arr = np.exp(-4 * np.log(2) * ((x - x0) ** 2 + (y - y0) ** 2) / fwhm**2)
    return arr * peak


class FakeYagCamera(YagCamera):
    """
    Fake YagCamera for testing.
    """

    image1 = Cpt(FakeLCLSImagePlugin, "IMAGE1:")
    coords = Cpt(FakeCoords, "")
