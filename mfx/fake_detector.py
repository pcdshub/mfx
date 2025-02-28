import numpy as np

class FakeDetector:
    def __init__(self, detname='Rayonix'):
        try:
            self.detname = detname
            if detname == 'Rayonix':
                # below is 4x4 binning (https://www.rayonix.com/product/mx340-hs/)
                self.pixel_size_mm = 0.177
                self.pixel_per_side = 1920
                self.beam_stop_radius_mm = 5
            elif detname == 'epix10k2M':
                # see https://lcls.slac.stanford.edu/detectors/ePix10k
                self.pixel_size_mm = 0.100
                self.pixel_per_side = 1650 # approximate
                self.beam_stop_radius_mm = 9 # approximate
            elif detname == 'jungfrau16M':
                # see https://www.psi.ch/en/lxn/jungfrau
                self.pixel_size_mm = 0.075
                self.pixel_per_side = 4096 # approximate lower bound
                self.beam_stop_radius_mm = 9 # approximate, no idea
        except:
            print('Detector not implemented.')


    def _energy_keV_to_wavelength_A(self, energy_keV):
        return 12.398 / energy_keV


    def _pixel_index_to_radius_mm(self, pixel_index):
        return pixel_index * self.pixel_size_mm


    def _pixel_radius_mm_to_theta_radian(self, pixel_radius_mm, det_dist_mm):
        # angle between incident and outgoing wavevectors: 2*theta
        return np.arctan2(pixel_radius_mm, det_dist_mm) / 2.0


    def _pixel_theta_radian_to_q_invA(self, pixel_theta_radian, wavelength_A):
        # q = 2pi.s = 4pi.sin(theta)/lambda
        return 4 * np.pi * np.sin(pixel_theta_radian) / wavelength_A


    def _pixel_q_invA_to_resol_A(self, pixel_q_invA):
        # d = 1/s = 2pi/q
        return 2 * np.pi / pixel_q_invA


    def _pixel_radius_mm_to_q_invA(self, radius_mm, det_dist_mm, energy_keV):
        return \
            self._pixel_theta_radian_to_q_invA(
                self._pixel_radius_mm_to_theta_radian(radius_mm, det_dist_mm),
                self._energy_keV_to_wavelength_A(energy_keV)
        )


    def resolution_coverage(self, energy_keV=None, det_dist_mm=None):
        low_q_invA = self._pixel_radius_mm_to_q_invA(
            self.beam_stop_radius_mm, det_dist_mm, energy_keV
        )
        high_q_invA = self._pixel_theta_radian_to_q_invA(
            self._pixel_radius_mm_to_theta_radian(
                self._pixel_index_to_radius_mm(self.pixel_per_side/2.0), det_dist_mm
            ), self._energy_keV_to_wavelength_A(energy_keV)
        )
        highest_q_invA = self._pixel_theta_radian_to_q_invA(
            self._pixel_radius_mm_to_theta_radian(
                self._pixel_index_to_radius_mm(self.pixel_per_side / np.sqrt(2.0)), det_dist_mm
            ), self._energy_keV_to_wavelength_A(energy_keV)
	)

        print(f"### FakeDetector {self.detname} resolution range:")
        print(f"### - Energy: {energy_keV} keV")
        print(f"### - Distance: {det_dist_mm} mm")
        print(f">>> Low q    : {low_q_invA:.2f} A-1 | {self._pixel_q_invA_to_resol_A(low_q_invA):.2f} A")
        print(f">>> High q   : {high_q_invA:.2f} A-1 | {self._pixel_q_invA_to_resol_A(high_q_invA):.2f} A (detector edge)")
        print(f">>> Highest q: {highest_q_invA:.2f} A-1 | {self._pixel_q_invA_to_resol_A(highest_q_invA):.2f} A (detector corner)")
