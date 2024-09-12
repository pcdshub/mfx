import numpy as np
import periodictable as pt
#
import pcdscalc as calc
# Constants
eRad = pt.core.constants.electron_radius * 100  # Classical radius of an electron [cm]
p_be = pt.Be.density  # Density of Be at room temperature [g/cm^3]
m_be = pt.Be.mass  # Standard atomic weight
NA = pt.core.constants.avogadro_number  # Avogadro's Constant


# Prefocus energy range. Should probably be in a file under data
# format: (E_min, E_max): (xrt_lens_idx, lens_radius)
MFX_prefocus_energy_range = {
    (0, 7000): (None, None),
    (7000, 10000): (2, 750),
    (10000, 12000): (1, 428),
    (12000, 16000): (0, 333)
}
def focal_length(radius, energy,N=1):
    """
    Calculate focal length using the pcds version of the focal length calculator
    """
    if N!=1:
        print('N does not equal 1!')
    return calc.be_lens_calcs.calc_focal_length_for_single_lens(energy*1E-3,radius*1E-6)
def focal_length_old(radius, energy, N=1):
    """
    Calculate the focal length of a Beryllium lens
    Ref: HR Beguiristain et al. OPTICS LETTERS, Vol. 27, No. 9 (2002)

    Probably want to use pcdscalc instead eventually
    """
    # Get scattering factors
    f1, f2 = pt.Be.xray.scattering_factors(energy=energy/1000)

    # Calculate delta (refraction index)
    f = f1+f2*1j
    f = f*p_be*NA/m_be
    wavelength = (12389.4/energy)*1E-08  # [cm]
    delta = (eRad * wavelength**2 * f / (2*np.pi)).real
    # delta = be_calcs.get_delta(energy/1000, 'Be', p_be) # too slow

    # f = R / (2N*delta)
    return radius*1e-6/2/N/delta

def estimate_beam_fwhm(radius, energy, fwhm_unfocused = 300E-6, distance = 4.474):
    focal_len = focal_length(radius,energy)
    lam = calc.be_lens_calcs.photon_to_wavelength(energy) * 1E-9
    w_unfocused = calc.be_lens_calcs.gaussian_fwhm_to_sigma(fwhm_unfocused)*2
    waist = lam / np.pi * focal_len / w_unfocused
    rayleigh_range = np.pi *waist ** 2 /lam
    size = waist *np.sqrt(1.0 +(distance - focal_len) ** 2.0 / rayleigh_range **2)
    size_fwhm = calc.be_lens_calcs.gaussian_sigma_to_fwhm(size) /2.0
    print(waist,rayleigh_range,size_fwhm)
