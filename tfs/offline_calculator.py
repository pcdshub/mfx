import itertools
import logging
# from unittest import skip

import numpy as np

from tfs.lens import LensConnect
from tfs.utils import MFX_prefocus_energy_range

logger = logging.getLogger(__name__)


class TFS_Calculator(object):
    def __init__(self, tfs_lenses, prefocus_lenses=None):
        self.tfs_lenses = tfs_lenses
        self.prefocus_lenses = prefocus_lenses
        self.combos = self.combinations()
        return

    def combinations(self):
        """
        All possible combinations of the given lenses

        Parameters
        ----------

        Returns
        -------
        combos: list
            List of LensConnect objects
        """

        tfs_combos = list()
        for i in range(1, len(self.tfs_lenses)+1):
            list_combos = list(itertools.combinations(self.tfs_lenses, i))
            # Create LensConnect objects from all of our possible combinations
            tfs_combos.extend([LensConnect(*combo) for combo in list_combos])
        logger.debug("Found %s combinations of Transfocator lenses",
                     len(tfs_combos))
        return tfs_combos

    def _update_combos(self):
        self.combos = self.combinations()

    def get_pre_focus_lens(self, energy):
        for e_range, lens in MFX_prefocus_energy_range.items():
            if energy >= e_range[0] and energy < e_range[1]:
                pre_focus_lens_idx = lens[0]
                break
        if pre_focus_lens_idx is None:
            pre_focus_lens = None
            print(f"No pre-focussing lens at {energy} eV")
        else:
            pre_focus_lens = self.prefocus_lenses[pre_focus_lens_idx]
            print(f"Pre-focussing lens for {energy} eV:\n{pre_focus_lens}")
            print(f'Radius: {pre_focus_lens.radius} um\n')
        return pre_focus_lens

    @staticmethod
    def get_combo_image(combo, z_obj=0.0):
        return combo.image(z_obj)

    def find_solution(self, target, energy, n=4, z_obj=0.0):
        """
        Find a combination to reach a specific focus

        Parameters
        ----------
        target: float
            The desired position of the focal plane in accelerator coordinates

        n : int, optional
            The maximum number of lenses in a valid combination. This saves
            time by avoiding calculating the focal plane of combinations with a
            large number of lenses

        z_obj : float, optional
            The source point of the beam

        Returns
        -------
        array: LensConnect
            An array of lens combinations with the closest possible image to
            the target_image

        Steps:
        1) find the right pre-focussing lens. These are pre-defined based on
        the photon energy (see prefocus_energy_range) and add it to the combos.
        2) Calculate the focus and the difference to the target for each TFS
        lens combination.
        3) Pick the combo with the smallest difference
        """

        # Step 1
        pre_focus_lens = self.get_pre_focus_lens(energy)
        if pre_focus_lens is None:
            combos = self.combos
        else:
            pre_focus_lens = self.get_pre_focus_lens(energy)
            combos = []
            for combo in self.combos:
                c = LensConnect(pre_focus_lens)
                lens_combo = LensConnect.connect(c, combo)
                combos.append(lens_combo)

        # Step 2
        diff = []
        for ii, combo in enumerate(self.combos):
            if combo.nlens > n:
                continue
            image = combo.image(z_obj, energy)
            diff.append(np.abs(image - target))

        # Step 3
        solution = combos[np.argmin(diff)]
        return solution, np.min(diff)
