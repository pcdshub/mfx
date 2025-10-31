import itertools
import logging
# from unittest import skip

import numpy as np

from tfs.lens import LensConnect
from tfs.utils import MFX_prefocus_energy_range

logger = logging.getLogger(__name__)


class TFS_Calculator(object):
    def __init__(self, tfs_lenses, prefocus_lenses=None,exclusions=None):
        self.tfs_lenses = tfs_lenses
        self.prefocus_lenses = prefocus_lenses
        if exclusions:
            logger.debug(f"Lens exclusions considered. The following lenses will be excluded from the calculation: {exclusions}")
            self.tfs_lenses=np.delete(self.tfs_lenses,exclusions)
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

    def check_forbidden(self, pre_focus_lens_radius, energy, radius):
        from transfocate.table.info import data as spreadsheet_data

        LENS_MAP = {
            750: "LENS1_750",
            428: "LENS2_428",
            333: "LENS3_333"
        }
        lens = LENS_MAP.get(int(pre_focus_lens_radius), "NO_LENS")

        lens_data = spreadsheet_data[lens]
        closest_energy_idx = (lens_data['energy'] - energy).abs().idxmin()
        closest_row = lens_data.loc[closest_energy_idx]

        forbidden = closest_row['trip_min'] <= radius <= closest_row['trip_max']
        log_level = logger.error if forbidden else logger.info
        log_level(f"TFS Configuration is {'Forbidden' if forbidden else 'Allowed'}")

        return forbidden

    def find_solution(self, target, energy, n=4, z_obj=0.0,
                      avoid_forbidden=True, enable_prefocus=True):
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

        pre_focus_lens = None
        if enable_prefocus:
            pre_focus_lens = self.get_pre_focus_lens(energy)

        combos = []
        diff = []
        for combo in self.combos:

            # Step 1
            if pre_focus_lens is None:
                lens_combo = combo
            else:
                c = LensConnect(pre_focus_lens)
                lens_combo = LensConnect.connect(c, combo)

            # Step 1bis
            if avoid_forbidden:
                if self.check_forbidden(pre_focus_lens.radius, energy, lens_combo.tfs_radius):
                    continue
            combos.append(lens_combo)

            # Step 2
            if combo.nlens > n:
                continue
            image = combo.image(z_obj, energy)
            diff.append(np.abs(image - target))

        # Step 3
        best_allowed_combo_idx = np.argmin(diff)
        smallest_diff = diff[best_allowed_combo_idx]
        best_combo_solution = combos[best_allowed_combo_idx]

        return best_combo_solution, smallest_diff
