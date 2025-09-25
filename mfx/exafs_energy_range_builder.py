class EXAFSEnergyRangeBuilder:
    """
    A class to build energy range and corresponding acquisition time arrays for X-ray spectroscopy experiments.

    Attributes:
    - element (str): The element symbol (e.g., 'Fe', 'Ti').
    - min_before_pre_edge (float): Minimum energy value before the pre-edge region in eV.
    - max_before_pre_edge (float): Maximum energy value before the pre-edge region in eV.
    - min_K_value (float): Minimum wavenumber value in reciprocal angstroms (K) for the linear region.
    - max_K_value (float): Maximum wavenumber value in reciprocal angstroms (K) for the K-to-eV conversion.
    - before_edge_eV_increment (float): Increment spacing in eV for the "before pre-edge" energy region.
    - edge_eV_increment (float): Increment spacing in eV for the energy range up to the edge of the K-to-eV region.
    - K_spacing (float): K spacing for the K-to-eV energy range.
    - time_before_edge (float): Acquisition time per point before the pre-edge.
    - time_in_edge (float): Acquisition time per point in the edge region.
    - min_time_EXAFS (float): Minimum acquisition time in seconds for the EXAFS region.
    - max_time_EXAFS (float): Maximum acquisition time in seconds for the EXAFS region.
    - power (int): The power for the K-weighting.
    - foil_energies (dict): Dictionary containing foil energies for various elements.
    - threshold_energies (dict): Dictionary containing threshold energies for various elements.
    """
    def __init__(self):
        self.element = 'Fe'
        self.power=3
        self.foil_energies = {'Sc': 4492.8, 'Ti': 4966.4, 'V': 5465.1, 'Cr': 5989.2, 'Mn': 6539.0, 'Fe': 7111.2,
                 'Co': 7708.9, 'Ni': 8332.8, 'Cu': 8978.9, 'Zn': 9658.6}
        self.threshold_energies = {'Ti': 4985.00, 'Sc': 4510.00, 'V': 5485.00, 'Cr': 6010.00, 'Mn': 6560.00,
                    'Fe': 7130.00, 'Co': 7730.00, 'Ni': 8350.00, 'Cu': 9000.00, 'Zn': 9680.00}

    def K_to_eV(self, K_value):
        """
        Convert wavenumber (K) to energy (eV) for the specified element.

        Parameters:
        - K_value (float): The wavenumber value in reciprocal angstroms (K).

        Returns:
        - float: The energy in electronvolts (eV).
        """
        threshold_energy = self.threshold_energies[self.element]
        energy_eV = K_value**2 / 0.2625 + threshold_energy
        return energy_eV


    def eV_to_K(self, energy_eV):
        """
        Convert energy (eV) to wavenumber (K) for the specified element.

        Parameters:
        - energy_eV (float): The energy value in electronvolts (eV).

        Returns:
        - float: The wavenumber in reciprocal angstroms (K).
        """
        threshold_energy = self.threshold_energies[self.element]
        K_value = (0.2625 * (energy_eV - threshold_energy))**0.5
        return K_value


    def build_energy_range(
        self,
        min_before_pre_edge = 7010.0,
        max_before_pre_edge = 7080.0,
        preedge_end = 7118,
        preedge_eV_increment = 0.5,
        max_before_edge = 7020.0,
        min_K_value = 2.0,
        max_K_value = 12.0,
        before_edge_eV_increment = 5.0,
        edge_eV_increment = 1.0,
        K_spacing = 0.1,
        time_before_edge=0.5,
        time_in_edge = 1,
        time_in_preedge=1.5,
        min_time_EXAFS = 0.5, 
        max_time_EXAFS = 10,
        debug = False
        ):
        """
        Build the entire energy range for the specified element. Basically with 3 user defined ranges:
        the pre-pre-edge, the pre-edge+edge, and the EXAFS. The user must define the min/max energy of the first two ranges
        and their acquisition time per point. Then the third region is defined by the maximum K-value to measure to; the point spacing (in K);
        the minumum and maximum acquistion time for the EXAFS region; and the power with which that acqusition time range is mapped onto the K points.

        Attributes:
        - min_before_pre_edge (float): Minimum energy value before the pre-edge region in eV.
        - max_before_pre_edge (float): Maximum energy value before the pre-edge region in eV.
        - min_K_value (float): Minimum wavenumber value in reciprocal angstroms (K) for the linear region.
        - max_K_value (float): Maximum wavenumber value in reciprocal angstroms (K) for the K-to-eV conversion.
        - before_edge_eV_increment (float): Increment spacing in eV for the "before pre-edge" energy region.
        - edge_eV_increment (float): Increment spacing in eV for the energy range up to the edge of the K-to-eV region.
        - K_spacing (float): K spacing for the K-to-eV energy range. reciprocal angstroms (K)
        - time_before_edge (float): Acquisition time per point before the pre-edge.
        - time_in_edge (float): Acquisition time per point in the edge region.
        - min_time_EXAFS (float): Minimum acquisition time in seconds for the EXAFS region.
        - max_time_EXAFS (float): Maximum acquisition time in seconds for the EXAFS region.

        Returns:
        - tuple: A tuple containing the energy range array and the corresponding acquisition time array.
        """
        import numpy as np
        energy_before_pre_edge = np.arange(min_before_pre_edge, max_before_pre_edge +
                                           before_edge_eV_increment, before_edge_eV_increment)
        K_values = np.arange(min_K_value, max_K_value + K_spacing, K_spacing)
        energy_K_range = [self.K_to_eV(K) for K in K_values if self.K_to_eV(K) is not None]
        energy_in_preedge = np.arange(max_before_pre_edge+preedge_eV_increment, preedge_end, preedge_eV_increment)
        energy_in_edge = np.arange(preedge_end+edge_eV_increment, np.min(energy_K_range), edge_eV_increment)
        energy_range = np.concatenate((energy_before_pre_edge, energy_in_preedge, energy_in_edge, energy_K_range))

        num_points_before_pre_edge = len(energy_before_pre_edge)
        num_points_in_edge = len(energy_in_edge)
        num_points_in_preedge = len(energy_in_preedge)
        
        time_before_edge_arr = np.ones(num_points_before_pre_edge) * time_before_edge
        time_in_preedge_arr = np.ones(num_points_in_preedge) * time_in_preedge
        time_in_edge_arr = np.ones(num_points_in_edge) * time_in_edge
        time_EXAFS = self.map_time_to_K_weighting(min_time_EXAFS, max_time_EXAFS, K_values)
        
        time_range = np.concatenate((time_before_edge_arr,time_in_preedge_arr, time_in_edge_arr, time_EXAFS))
        self.time_range = time_range
        self.energy_range = energy_range
        self.energy_K_range = energy_K_range
        self.K_values = K_values
        if debug:
            self.current_scan_profile()
        return energy_range, time_range, energy_K_range, K_values


    def map_time_to_K_weighting(self, min_time, max_time, K_values):
        """
        Map acquisition times to a K-weighting with a specified power.

        Parameters:
        - min_time (float): Minimum acquisition time in seconds.
        - max_time (float): Maximum acquisition time in seconds.
        - K_values (array-like): Array of K-space values in reciprocal angstroms (K).

        Returns:
        - numpy.ndarray: An array of normalized acquisition times based on the K-weighting.
        """
        import numpy as np
        time_range = np.linspace(min_time, max_time, len(K_values))
        K_time = K_values ** self.power
        K_time_range = time_range * K_time
        min_weighted_time = min(K_time_range)
        max_weighted_time = max(K_time_range)
        normalized_time_range = min_time + (max_time - min_time) * (K_time_range - min_weighted_time) / (
                    max_weighted_time - min_weighted_time)
        self.normalized_time_range=normalized_time_range
        return normalized_time_range


    def current_scan_profile(self):
            self.plot_scan_profile(
                self.energy_range,
                self.time_range,
                self.energy_K_range,
                self.K_values
                )


    def plot_scan_profile(
        self,
        energy_range,
        time_range,
        energy_K_range,
        K_values
        ):
        """
        Plot the energy range, acquisition time, cumulative acquisition time, and estimated resolution.

        This method generates a multi-panel plot visualizing the scan profile. For informational purposes.
        """
        import numpy as np
        import matplotlib.pyplot as plt
        fig,axs=plt.subplots(3,2,dpi=300,figsize=(6,9))
        axs[0,0].plot(energy_range,color='k')
        axs[0,0].set_xlabel('Data Point')
        axs[0,0].set_ylabel('Requested Energy (eV)')
        
        axs[1,0].plot(time_range,color='k')
        axs[1,0].set_xlabel('Data Point')
        axs[1,0].set_ylabel('Acq. Time Per Point (s)')
        
        axs[2,0].plot(np.cumsum(time_range),color='k')
        axs[2,0].set_xlabel('Data Point')
        axs[2,0].set_ylabel('Total Acq. Time (s)')
        
        K_2=np.argmin(np.abs(K_values-2.0))
        expectedResolution=np.pi*0.5/(K_values[K_2:]-1.99)
        
        
        axs[0,1].plot(K_values[K_2:],expectedResolution,color='k')
        axs[0,1].set_xlabel('K-Value ($\AA^{-1}$)')
        axs[0,1].set_ylabel('Estimated Resolution ($\AA$)',rotation=270,labelpad=15)
        axs[0,1].yaxis.set_label_position("right")
        
        axs[0,1].set_ylim(0.05,0.5)
        
        
        axs[1,1].plot(energy_range,time_range,color='k')
        axs[1,1].set_xlabel('Energy (eV)')
    
        
        axs[2,1].plot(energy_range,np.cumsum(time_range),color='k')
        axs[2,1].set_xlabel('Energy (eV)')
        plt.tight_layout()
        
    def output_scan_profile(self,elist_name='elist',tlist_name='tlist'):
        import numpy as np
        np.savetxt(tlist_name+'.txt',time_range)
        np.savetxt(elist_name+'.txt',energy_range/1000.0)