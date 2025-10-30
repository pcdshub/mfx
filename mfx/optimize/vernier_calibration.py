from __future__ import annotations
import traceback
import datetime
import time
import json
from typing import Optional, Tuple
import numpy as np
import pandas as pd
from pathlib import Path
from pydantic import validate_call
from sklearn.linear_model import LinearRegression
from ophyd import EpicsSignalRO
from ophyd.device import Device
from pcdsdevices.pv_positioner import OnePVMotor
import logging

from .beamline_hw import (
    DG1_WAVE8_XPOS,
    DG2_WAVE8_XPOS,
    IP_YAG_XPOS,
    init_devices,
)


logger = logging.getLogger(__name__)


class FakeDaq:
    """Fake DAQ class for simulation mode."""
    
    def __init__(self):
        self.name = "fake_daq"
        self.parent = None
    
    def configure(self, *args, **kwargs):
        """Fake configure method - does nothing in simulation."""
        pass
    
    def stage(self, *args, **kwargs):
        """Fake stage method - does nothing in simulation."""
        pass
    
    def unstage(self, *args, **kwargs):
        """Fake unstage method - does nothing in simulation."""
        pass
    
    def describe(self, *args, **kwargs):
        """Fake describe method - returns empty dict."""
        return {}
    
    def read(self, *args, **kwargs):
        """Fake read method - returns empty dict."""
        return {}
    
    def collect(self, *args, **kwargs):
        """Fake collect method - returns empty iterator."""
        return iter([])


class VernierCalibration:
    """
    Vernier calibration and alignment system for synchrotron beamlines.
    
    This class provides methods to:
    1. Calibrate the relationship between energy and vernier offset
    2. Align vernier to DCCM based on intensity measurements
    """
    
    def __init__(self):
        """Initialize VernierCalibration. Devices are loaded from beamline_hw when methods are called."""
        # Calibration storage directory
        self.calib_dir = Path(__file__).parent.parent.parent / "logs" / "vernier_calibration"
        self.calib_dir.mkdir(parents=True, exist_ok=True)
    
    def _predict_vernier_offset(self, target_energy_eV: float, calib: dict) -> float:
        """
        Predict vernier offset for a given target energy using calibration coefficients.
        
        Parameters
        ----------
        target_energy_eV : float
            Target energy (DCCM energy) in eV
        calib : dict
            Calibration dictionary containing coefficients
            
        Returns
        -------
        float
            Predicted vernier offset in eV (vernier - DCCM)
        """
        a0, a1 = calib["coeff_offset"]
        # offset = vernier - DCCM, where vernier lands at target + (a0 + a1*target)
        pred_offset = a0 + a1 * target_energy_eV
        return float(pred_offset)
    
    def _vernier_solve(self, target_energy_eV: float, calib: dict) -> float:
        """
        Solve for vernier energy that achieves zero offset at target DCCM energy.
        
        During calibration, we learned that when we command both DCCM and vernier 
        to a target energy E:
          - DCCM lands at E (with small noise)
          - Vernier lands with systematic offset: offset = a0 + a1 * E
          - Where offset = vernier_actual - DCCM_actual
        
        To achieve zero offset (vernier = DCCM = target):
          We want to command vernier to energy E such that it lands at target.
          If we command vernier to energy E, it will land at: E + (a0 + a1 * E)
          We need: target = E + (a0 + a1 * E)
          Solving: E = (target - a0) / (1 + a1)
        
        Parameters
        ----------
        target_energy_eV : float
            Target DCCM energy in eV
        calib : dict
            Calibration dictionary containing coefficients
            
        Returns
        -------
        float
            Required vernier energy in eV to minimize offset
        """
        a0, a1 = calib["coeff_offset"]
        
        vernier_energy = (target_energy_eV - a0) / (1 + a1)
        return float(vernier_energy)
    
    def _save_calibration_plots(self, res, reg_offset, out_dir, ts):
        """Save calibration plots to file."""
        plot_path = None
        try:
            import matplotlib.pyplot as plt
            # Create 4 plots: 2 rows, 2 columns
            fig, axs = plt.subplots(2, 2, figsize=(14, 10))
            
            vernier_energy = res["vernier_energy"]
            vernier_offset = res["vernier_offset"]
            intensity = res["intensity"]
            dccm_energy = res["dccm_energy"]
            
            # Plot 1: Vernier offset vs Vernier Energy (top left)
            axs[0,0].scatter(vernier_energy, vernier_offset, s=20, alpha=0.7)
            energy_range = np.linspace(vernier_energy.min(), vernier_energy.max(), 100)
            offset_pred = reg_offset.predict(energy_range.reshape(-1, 1))
            axs[0,0].plot(energy_range, offset_pred, 'r--', linewidth=2, label='Calibration fit')
            axs[0,0].set_xlabel("Vernier Energy [eV]")
            axs[0,0].set_ylabel("Vernier Offset [eV]")
            axs[0,0].set_title("Vernier Offset vs Vernier Energy")
            axs[0,0].legend()
            axs[0,0].grid(True, alpha=0.3)
            
            # Plot 2: Intensity vs Vernier Energy (top right)
            axs[0,1].scatter(vernier_energy, intensity, s=20, alpha=0.7, color='green')
            axs[0,1].set_xlabel("Vernier Energy [eV]")
            axs[0,1].set_ylabel("Intensity [arb. units]")
            axs[0,1].set_title("Intensity vs Vernier Energy")
            axs[0,1].grid(True, alpha=0.3)
            
            # Plot 3: Vernier offset vs DCCM Energy (bottom left)  
            axs[1,0].scatter(dccm_energy, vernier_offset, s=20, alpha=0.7)
            axs[1,0].set_xlabel("DCCM Energy [eV]")
            axs[1,0].set_ylabel("Vernier Offset [eV]")
            axs[1,0].set_title("Vernier Offset vs DCCM Energy")
            axs[1,0].grid(True, alpha=0.3)
            
            # Plot 4: Intensity vs Vernier Offset (bottom right)
            axs[1,1].scatter(vernier_offset, intensity, s=20, alpha=0.7, color='orange')
            axs[1,1].axvline(x=0, color='red', linestyle='--', linewidth=2, alpha=0.5, label='Zero Offset')
            axs[1,1].set_xlabel("Vernier Offset [eV]")
            axs[1,1].set_ylabel("Intensity [arb. units]")
            axs[1,1].set_title("Intensity vs Vernier Offset")
            axs[1,1].legend()
            axs[1,1].grid(True, alpha=0.3)
            
            fig.tight_layout()
            plot_path = str(out_dir / f"vernier_calib_{ts}.png")
            fig.savefig(plot_path, dpi=120)
            plt.close(fig)
            print(f"[calibrate] Wrote calibration plot: {plot_path}")
        except Exception as exc:
            print(f"[calibrate] Warning: failed to save plot: {exc}")
        return plot_path
    
    def _load_calibration(self) -> Optional[dict]:
        """Load most recent calibration coefficients."""
        try:
            candidates = sorted(self.calib_dir.glob("vernier_calib_*.json"))
            if not candidates:
                return None
            with open(candidates[-1], "r") as f:
                return json.load(f)
        except Exception:
            return None
    
    def check_calibration(self, threshold_sigma: float = 2.0) -> bool:
        """
        Check if current calibration is still accurate.
        
        Parameters
        ----------
        threshold_sigma : float
            Threshold for calibration validation (in sigma units)
            
        Returns
        -------
        bool
            True if calibration is still accurate, False otherwise
        """
        calib = self._load_calibration()
        if calib is None:
            print(f"[check_calibration] No calibration found")
            return False
        
        print(f"[check_calibration] Loading calibration from {calib.get('timestamp')}")
        
        try:
            # Get devices from beamline_hw
            devices = init_devices()
            dccm_energy_pv = devices["vernier_dccm_energy"]
            vernier_energy_pv = devices["vernier_energy"]
            
            # Get current DCCM energy (this is what we're trying to reach)
            current_dccm_energy = float(dccm_energy_pv.get())
            
            # Get current vernier energy
            current_vernier_energy = float(vernier_energy_pv.position)
            
            # Predict offset for the current DCCM energy
            # (the energy we're trying to reach - the target energy)
            pred_offset = self._predict_vernier_offset(current_dccm_energy, calib)
            
            # Calculate actual offset (vernier - DCCM)
            actual_offset = current_vernier_energy - current_dccm_energy
            
            # Calculate error
            error = abs(pred_offset - actual_offset)
            expected_error = float(calib["sigma_offset"])
            
            print(f"[check_calibration] Current DCCM: {current_dccm_energy:.2f} eV")
            print(f"[check_calibration] Current Vernier: {current_vernier_energy:.2f} eV")
            print(f"[check_calibration] Predicted offset: {pred_offset:.2f} eV")
            print(f"[check_calibration] Actual offset: {actual_offset:.2f} eV")
            print(f"[check_calibration] Error: {error:.2f} eV (threshold: {threshold_sigma * expected_error:.2f} eV)")
            
            return error < threshold_sigma * expected_error
            
        except Exception as exc:
            print(f"[check_calibration] Failed to check calibration: {exc}")
            return False
    
    def calibrate(self, energy_start_eV: float, energy_end_eV: float, 
                  energy_steps: int = 10, events_per_step: int = 120) -> dict:
        """
        Run calibration scan to determine energy-vernier offset relationship.
        
        Parameters
        ----------
        energy_start_eV : float
            Starting energy for calibration scan
        energy_end_eV : float
            Ending energy for calibration scan
        energy_steps : int
            Number of energy steps in calibration scan
        events_per_step : int
            Number of events per step
            
        Returns
        -------
        dict
            Calibration dictionary containing coefficients and metadata
        """
        print(f"[calibrate] Starting vernier calibration scan...")
        print(f"[calibrate] Energy range: {energy_start_eV:.2f} - {energy_end_eV:.2f} eV")
        print(f"[calibrate] Steps: {energy_steps}")
        
        # Get devices from beamline_hw (will be real or simulated based on sim_devices() call)
        devices = init_devices()
        dccm_energy_pv = devices["vernier_dccm_energy"]
        vernier_energy_pv = devices["vernier_energy"]
        intensity_pv = devices["vernier_intensity"]
        
        # Check if we're in simulation mode
        try:
            from mfx.db import RE, daq
            is_simulation = False
        except ImportError:
            is_simulation = True
            print("[calibrate] Simulation mode detected")
        
        # For real hardware, import DCCM device to move both DCCM and vernier together
        dccm_motor = None
        energy_start_keV = None
        energy_end_keV = None
        if not is_simulation:
            try:
                from mfx.dccm import DCCM
                dccm = DCCM(name='DCCM')
                dccm_motor = dccm.energy_with_vernier.energy  # This moves BOTH DCCM and vernier
                # Convert eV to keV for DCCM
                energy_start_keV = energy_start_eV / 1000.0
                energy_end_keV = energy_end_eV / 1000.0
                print("[calibrate] Using DCCM energy_with_vernier to move both DCCM and vernier together")
            except Exception as e:
                print(f"[calibrate] WARNING: Could not import DCCM device: {e}")
                print(f"[calibrate] Will use vernier-only scan")
                dccm_motor = None
        
        # Generate energy grid
        energies = np.linspace(energy_start_eV, energy_end_eV, energy_steps)
        
        # Initialize data storage
        data = {
            "energy_eV": [],
            "vernier_offset": [],
            "intensity": [],
            "dccm_energy": [],
            "vernier_energy": []
        }
        
        # Perform calibration scan
        # RE and daq already imported above when checking simulation mode
        if is_simulation:
            from bluesky import RunEngine
            RE = RunEngine({})
            daq = FakeDaq()
        
        try:
            import bluesky.plans as bp
        except ImportError:
            print("[calibrate] Could not import bluesky.plans")
            raise
        
        try:
            # Configure DAQ - use DCCM motor in real hardware, vernier motor in simulation
            if dccm_motor is not None:
                # Real hardware: use DCCM motor to move both DCCM and vernier together
                dccm_motor.kind = "hinted"
                scan_motor = dccm_motor
                vernier_energy_pv.kind = "hinted"  # Also track vernier position
                motors = [scan_motor, vernier_energy_pv]
                print("[calibrate] Using DCCM motor for scanning, will move both DCCM and vernier")
            else:
                # Simulation mode: use vernier motor only
                vernier_energy_pv.setpoint.kind = "hinted"
                scan_motor = vernier_energy_pv
                motors = [scan_motor]
                print("[calibrate] Using vernier motor only (simulation mode)")
            
            daq.configure(
                motors=motors,
                group_mask=0x1,
                events=events_per_step,
                record=False
            )
            
            # For simulation mode, we need to update the tracker before reading signals
            # This ensures SynSignals get the current motor position
            tracker = None
            get_intensity_func = None
            get_dccm_func = None
            try:
                # Try to get the tracker from the vernier device (simulation mode)
                if hasattr(vernier_energy_pv, 'pos_tracker'):
                    tracker = vernier_energy_pv.pos_tracker
                    # Get the underlying functions for direct calls in simulation
                    if hasattr(intensity_pv, '_func'):
                        get_intensity_func = intensity_pv._func
                    if hasattr(dccm_energy_pv, '_func'):
                        get_dccm_func = dccm_energy_pv._func
            except AttributeError:
                pass
            
            # Subscribe to events to collect data
            def on_event(name, doc):
                if name != "event":
                    return
                event_data = doc.get("data", {})
                print(f"[calibrate] Event data keys: {list(event_data.keys())}")
                
                # Get vernier energy from event data
                # In simulation: key is "vernier_energy" (from vernier motor)
                # In real hardware: key is "vernier_energy" (from vernier_energy_pv in motors list)
                if "vernier_energy" in event_data:
                    vernier_energy = event_data["vernier_energy"]
                else:
                    print(f"[calibrate] WARNING: No vernier_energy found in event data")
                    print(f"[calibrate] Available keys: {list(event_data.keys())}")
                    return
                
                # In simulation mode, update tracker with current motor position
                # and call functions directly to force re-evaluation
                if tracker is not None:
                    tracker.value = float(vernier_energy)
                    
                    # Call functions directly in simulation mode to force re-evaluation
                    try:
                        intensity = float(get_intensity_func())
                    except Exception as e:
                        print(f"[calibrate] Failed to get intensity: {e}")
                        return
                    
                    try:
                        dccm_energy = float(get_dccm_func())
                    except Exception as e:
                        print(f"[calibrate] Failed to get DCCM energy: {e}")
                        return
                else:
                    # Real hardware mode - use get() for simple reading
                    try:
                        intensity = float(intensity_pv.get())
                    except Exception as e:
                        print(f"[calibrate] Failed to read intensity: {e}")
                        return
                    
                    try:
                        dccm_energy = float(dccm_energy_pv.get())
                    except Exception as e:
                        print(f"[calibrate] Failed to read DCCM energy: {e}")
                        return
                
                offset = vernier_energy - dccm_energy
                
                print(f"[calibrate] Collected: vernier={vernier_energy:.2f}, dccm={dccm_energy:.2f}, offset={offset:.2f}, intensity={intensity:.2f}")
                
                data["energy_eV"].append(dccm_energy)
                data["vernier_offset"].append(offset)
                data["intensity"].append(intensity)
                data["dccm_energy"].append(dccm_energy)
                data["vernier_energy"].append(vernier_energy)
            
            # Set calibration mode flag
            try:
                from mfx.optimize.beamline_hw import get_calibration_scan_mode
                calibration_scan_mode = get_calibration_scan_mode()
                calibration_scan_mode[0] = True
            except Exception as e:
                print(f"[calibrate] Failed to set calibration mode: {e}")
            
            sid = RE.subscribe(on_event)
            
            try:
                # Run the scan - use keV for DCCM motor, eV for vernier motor
                if dccm_motor is not None:
                    # Real hardware: scan with DCCM motor (uses keV)
                    RE(bp.scan(
                        [daq],
                        scan_motor,
                        energy_start_keV,
                        energy_end_keV,
                        energy_steps
                    ))
                else:
                    # Simulation: scan with vernier motor (uses eV)
                    RE(bp.scan(
                        [daq],
                        scan_motor,
                        energy_start_eV,
                        energy_end_eV,
                        energy_steps
                    ))
            finally:
                RE.unsubscribe(sid)
                # Unset calibration mode flag after scan
                try:
                    from mfx.optimize.beamline_hw import get_calibration_scan_mode
                    calibration_scan_mode = get_calibration_scan_mode()
                    calibration_scan_mode[0] = False
                except Exception:
                    pass
                
        except Exception as exc:
            print(f"[calibrate] Error during scan: {exc}")
            raise
        
        # Convert to DataFrame for analysis
        df = pd.DataFrame(data)
        print(f"[calibrate] Collected {len(df)} data points")
        
        # During calibration, we scan to target energies
        # DCCM moves to the target energy (where we command)
        # Vernier moves to target energy but lands with systematic offset
        # The offset depends on the target energy: higher target → larger offset
        
        # Fit model: offset = a0 + a1 * target_energy
        # Where target_energy is what we're trying to reach (the DCCM energy)
        X = df["dccm_energy"].values.reshape(-1, 1)  # Use DCCM energy as the target
        y_offset = df["vernier_offset"].values
        
        reg_offset = LinearRegression().fit(X, y_offset)
        
        # Print what we learned
        avg_dccm = np.mean(df["dccm_energy"].values)
        print(f"[calibrate] Average DCCM energy during scan: {avg_dccm:.2f} eV")
        print(f"[calibrate] Calibration models: offset = f(target_energy)")
        
        # Calculate coefficients
        coeff_offset = np.concatenate([[reg_offset.intercept_], reg_offset.coef_])
        
        # Calculate prediction errors
        pred_offset = reg_offset.predict(X)
        err_offset = np.abs(pred_offset - y_offset)
        sigma_offset = float(np.std(err_offset))
        
        print(f"[calibrate] Offset coefficients: a0={coeff_offset[0]:.3f}, a1={coeff_offset[1]:.6f}")
        print(f"[calibrate] Offset sigma: {sigma_offset:.3f} eV")
        
        # Save calibration data
        ts = datetime.datetime.now().strftime("%y-%m-%d-%H:%M:%S")
        
        # Save raw data
        csv_path = str(self.calib_dir / f"vernier_calib_data_{ts}.csv")
        df.to_csv(csv_path, index=False)
        print(f"[calibrate] Saved calibration data: {csv_path}")
        
        # Save plots
        plot_path = self._save_calibration_plots(df, reg_offset, self.calib_dir, ts)
        
        # Create calibration dictionary
        calib = {
            "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
            "coeff_offset": [float(v) for v in coeff_offset.tolist()],
            "sigma_offset": sigma_offset,
            "energy_range": [float(energy_start_eV), float(energy_end_eV)],
            "energy_steps": int(energy_steps),
            "data_csv": csv_path,
            "plot_path": plot_path,
            "num_points": len(df)
        }
        
        # Save calibration
        calib_path = self.calib_dir / f"vernier_calib_{ts}.json"
        try:
            with open(calib_path, "w") as f:
                json.dump(calib, f, indent=2)
            print(f"[calibrate] Saved calibration: {calib_path}")
        except Exception as exc:
            print(f"[calibrate] Warning: failed to save calibration: {exc}")
        
        return calib
    
    def measure_offset_at_energy(self, events: int = 120) -> dict:
        """
        Collect vernier offset data at the current energy.
        
        This is a helper method for collecting data point-by-point when
        energy is controlled externally (e.g., in a loop).
        
        Parameters
        ----------
        events : int
            Number of events to average for intensity measurement
            
        Returns
        -------
        dict
            Dictionary with keys: "dccm_energy", "vernier_energy", "vernier_offset", "intensity"
        """
        from .beamline_hw import init_devices
        
        devices = init_devices()
        dccm_energy_pv = devices["vernier_dccm_energy"]
        vernier_energy_pv = devices["vernier_energy"]
        intensity_pv = devices["vernier_intensity"]
        
        # Read current positions
        try:
            dccm_energy = float(dccm_energy_pv.get())
            vernier_energy = float(vernier_energy_pv.position)
            # Average intensity over multiple readings
            intensities = []
            for _ in range(events):
                try:
                    intensities.append(float(intensity_pv.get()))
                except Exception:
                    pass
            intensity = np.mean(intensities) if intensities else float(intensity_pv.get())
        except Exception as e:
            print(f"[collect_offset_data_at_energy] Failed to read data: {e}")
            raise
        
        offset = vernier_energy - dccm_energy
        
        data = {
            "dccm_energy": dccm_energy,
            "vernier_energy": vernier_energy,
            "vernier_offset": offset,
            "intensity": intensity
        }
        
        print(f"[collect_offset_data_at_energy] Collected: dccm={dccm_energy:.2f} eV, "
              f"vernier={vernier_energy:.2f} eV, offset={offset:.2f} eV, intensity={intensity:.2f}")
        
        return data
    
    def fit(self, data_points: list[dict]) -> dict:
        """
        Fit vernier calibration model from collected data points.
        
        Parameters
        ----------
        data_points : list[dict]
            List of data dictionaries, each with keys: "dccm_energy", "vernier_offset", etc.
            
        Returns
        -------
        dict
            Calibration dictionary containing coefficients and metadata
        """
        if not data_points:
            raise ValueError("No data points provided for calibration")
        
        # Convert to DataFrame
        df = pd.DataFrame(data_points)
        print(f"[fit_calibration_from_data] Fitting model from {len(df)} data points")
        
        # Fit model: offset = a0 + a1 * target_energy
        # Where target_energy is the DCCM energy (what we're trying to reach)
        X = df["dccm_energy"].values.reshape(-1, 1)
        y_offset = df["vernier_offset"].values
        
        reg_offset = LinearRegression().fit(X, y_offset)
        
        # Calculate coefficients
        coeff_offset = np.concatenate([[reg_offset.intercept_], reg_offset.coef_])
        
        # Calculate prediction errors
        pred_offset = reg_offset.predict(X)
        err_offset = np.abs(pred_offset - y_offset)
        sigma_offset = float(np.std(err_offset))
        
        print(f"[fit_calibration_from_data] Offset coefficients: a0={coeff_offset[0]:.3f}, a1={coeff_offset[1]:.6f}")
        print(f"[fit_calibration_from_data] Offset sigma: {sigma_offset:.3f} eV")
        
        # Save calibration data
        ts = datetime.datetime.now().strftime("%y-%m-%d-%H:%M:%S")
        
        # Save raw data
        csv_path = str(self.calib_dir / f"vernier_calib_data_{ts}.csv")
        df.to_csv(csv_path, index=False)
        print(f"[fit_calibration_from_data] Saved calibration data: {csv_path}")
        
        # Save plots
        plot_path = self._save_calibration_plots(df, reg_offset, self.calib_dir, ts)
        
        # Get energy range from data
        energy_start_eV = float(df["dccm_energy"].min())
        energy_end_eV = float(df["dccm_energy"].max())
        
        # Create calibration dictionary
        calib = {
            "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
            "coeff_offset": [float(v) for v in coeff_offset.tolist()],
            "sigma_offset": sigma_offset,
            "energy_range": [energy_start_eV, energy_end_eV],
            "energy_steps": len(df),
            "data_csv": csv_path,
            "plot_path": plot_path,
            "num_points": len(df)
        }
        
        # Save calibration
        calib_path = self.calib_dir / f"vernier_calib_{ts}.json"
        try:
            with open(calib_path, "w") as f:
                json.dump(calib, f, indent=2)
            print(f"[fit_calibration_from_data] Saved calibration: {calib_path}")
        except Exception as exc:
            print(f"[fit_calibration_from_data] Warning: failed to save calibration: {exc}")
        
        return calib
    
    def align_to_dccm(self, energy_range_eV: float = 10.0, energy_steps: int = 11,
                     events_per_step: int = 12) -> bool:
        """
        Align vernier to current DCCM energy using intensity-based optimization.
        
        This function scans the vernier around the current DCCM energy and finds
        the vernier position that maximizes intensity. This is a pure intensity-based
        alignment without using calibration prediction.
        
        Parameters
        ----------
        energy_range_eV : float
            Range around current DCCM energy to scan (in eV)
        energy_steps : int
            Number of steps in alignment scan
        events_per_step : int
            Number of events per step
            
        Returns
        -------
        bool
            True if alignment was successful, False otherwise
        """
        # Get devices from beamline_hw (will be real or simulated based on sim_devices() call)
        devices = init_devices()
        dccm_energy_pv = devices["vernier_dccm_energy"]
        vernier_energy_pv = devices["vernier_energy"]
        intensity_pv = devices["vernier_intensity"]
        
        # Get current DCCM energy
        print(f"[align_to_dccm] Reading current DCCM energy...")
        current_dccm_energy = float(dccm_energy_pv.get())
        print(f"[align_to_dccm] Current DCCM energy: {current_dccm_energy:.2f} eV")
        
        # Update DCCM tracker to current DCCM energy (important for simulation mode)
        try:
            from mfx.optimize.beamline_hw import get_dccm_tracker
            dccm_tracker = get_dccm_tracker()
            if dccm_tracker is not None:
                dccm_tracker.value = current_dccm_energy
                print(f"[align_to_dccm] Updated DCCM tracker to: {current_dccm_energy:.2f} eV")
        except Exception as e:
            print(f"[align_to_dccm] Could not update DCCM tracker: {e}")
        
        # Scan vernier around current DCCM energy
        # In alignment mode, vernier lands exactly where commanded (no systematic offset)
        # So vernier_actual = vernier_command
        # Intensity peaks when vernier_actual = DCCM, i.e., when vernier_command = DCCM
        scan_start = current_dccm_energy - energy_range_eV / 2
        scan_end = current_dccm_energy + energy_range_eV / 2
        
        print(f"[align_to_dccm] Scanning vernier from {scan_start:.2f} to {scan_end:.2f} eV (range: ±{energy_range_eV/2:.1f} eV around DCCM at {current_dccm_energy:.2f} eV)")
        
        # Perform intensity-based alignment scan
        try:
            from mfx.db import RE, daq
        except ImportError:
            from bluesky import RunEngine
            RE = RunEngine({})
            daq = FakeDaq()
            print("[align_to_dccm] Cannot import mfx.db - running in simulation mode")
        
        try:
            import bluesky.plans as bp
        except ImportError:
            print("[align_to_dccm] Could not import bluesky.plans")
            raise
        
        try:
            # Configure DAQ
            vernier_energy_pv.setpoint.kind = "hinted"
            daq.configure(
                motors=[vernier_energy_pv],
                group_mask=0x1,
                events=events_per_step,
                record=False
            )
            
            # Track best intensity
            best_intensity = float("-inf")
            best_vernier_energy = None
            
            # For simulation mode, get tracker and functions from devices
            tracker = None
            get_intensity_func = None
            get_dccm_func = None
            try:
                if hasattr(vernier_energy_pv, 'pos_tracker'):
                    tracker = vernier_energy_pv.pos_tracker
                # Get the underlying functions for direct calls in simulation
                if hasattr(intensity_pv, '_func'):
                    get_intensity_func = intensity_pv._func
                if hasattr(dccm_energy_pv, '_func'):
                    get_dccm_func = dccm_energy_pv._func
            except AttributeError:
                pass
            
            def on_event(name, doc):
                nonlocal best_intensity, best_vernier_energy
                if name != "event":
                    return
                event_data = doc.get("data", {})
                print(f"[align_to_dccm] Event data keys: {list(event_data.keys())}")
                if "vernier_energy" not in event_data:
                    print(f"[align_to_dccm] WARNING: vernier_energy not in event data!")
                    return
                
                vernier_energy = event_data["vernier_energy"]
                
                # In simulation mode, update tracker first
                if tracker is not None and get_intensity_func is not None:
                    # Update the tracker
                    tracker.value = float(vernier_energy)
                    
                    # Also directly update the global tracker to ensure it's updated
                    import mfx.optimize.beamline_hw as bl_hw
                    if bl_hw._vernier_pos_tracker is not None:
                        bl_hw._vernier_pos_tracker.value = float(vernier_energy)
                    
                    print(f"[align_to_dccm] Updated trackers to: {vernier_energy:.2f} eV")
                    
                    # Call the underlying intensity function directly to force fresh evaluation
                    try:
                        intensity = float(get_intensity_func())
                        print(f"[align_to_dccm] Read intensity: {intensity:.2f}")
                    except Exception as e:
                        print(f"[align_to_dccm] Failed to get intensity: {e}")
                        return
                else:
                    # Use get() for real hardware
                    try:
                        intensity = float(intensity_pv.get())
                        print(f"[align_to_dccm] Read intensity: {intensity:.2f}")
                    except Exception as e:
                        print(f"[align_to_dccm] Failed to read intensity: {e}")
                        return
                
                if intensity > best_intensity:
                    best_intensity = intensity
                    best_vernier_energy = vernier_energy
                    print(f"[align_to_dccm] New best intensity: {intensity:.2f} at vernier energy: {vernier_energy:.2f} eV")
                
                # Print all points for debugging
                print(f"[align_to_dccm] Point: vernier={vernier_energy:.2f} eV, intensity={intensity:.2f}")
            
            sid = RE.subscribe(on_event)
            
            # Set alignment mode flag (no offset during scan)
            try:
                from mfx.optimize.beamline_hw import get_alignment_scan_mode
                alignment_scan_mode = get_alignment_scan_mode()
                alignment_scan_mode[0] = True
                print(f"[align_to_dccm] Alignment mode enabled - vernier will land at exact commanded position (no systematic offset)")
            except Exception as e:
                print(f"[align_to_dccm] Failed to set alignment mode: {e}")
            
            try:
                # Run the alignment scan
                RE(bp.scan(
                    [daq],
                    vernier_energy_pv,
                    scan_start,
                    scan_end,
                    energy_steps
                ))
            finally:
                RE.unsubscribe(sid)
            
            # Move to best position (still in alignment mode, vernier will land exactly at commanded position with no offset)
            if best_vernier_energy is not None:
                print(f"[align_to_dccm] Moving to best vernier energy: {best_vernier_energy:.2f} eV")
                vernier_energy_pv.move(best_vernier_energy).wait()
            
            # Unset alignment mode flag after scan AND final move
            try:
                from mfx.optimize.beamline_hw import get_alignment_scan_mode
                alignment_scan_mode = get_alignment_scan_mode()
                alignment_scan_mode[0] = False
                print(f"[align_to_dccm] Alignment mode disabled")
            except:
                pass
                
            # Verify final positions
            if best_vernier_energy is not None:
                # Verify final DCCM energy
                final_dccm_energy = float(dccm_energy_pv.get())
                final_vernier_actual = float(vernier_energy_pv.position)
                final_offset = final_vernier_actual - final_dccm_energy
                
                print(f"[align_to_dccm] Final DCCM energy: {final_dccm_energy:.2f} eV")
                print(f"[align_to_dccm] Final vernier energy: {final_vernier_actual:.2f} eV")
                print(f"[align_to_dccm] Final offset: {final_offset:.2f} eV")
                print(f"[align_to_dccm] Alignment completed successfully")
                
                return True
            else:
                print(f"[align_to_dccm] No valid intensity measurements found")
                return False
                
        except Exception as exc:
            print(f"[align_to_dccm] Error during alignment: {exc}")
            return False
    
    def move_to_energy_with_calibration(self) -> bool:
        """
        Move vernier to align with current DCCM energy using calibration to correct for offset.
        
        This function:
        1. Reads the current DCCM energy
        2. Calculates the required vernier energy using calibration to achieve zero offset
        3. Moves vernier to that calculated energy
        
        The calibration learned that when moving to energy E, vernier has offset (a0 + a1*E).
        To achieve vernier = DCCM, we command vernier to (DCCM - a0)/(1 + a1).
            
        Returns
        -------
        bool
            True if successful, False otherwise
        """
        print(f"[move_to_energy_with_calibration] Aligning vernier to current DCCM energy")
        
        # Load calibration
        calib = self._load_calibration()
        if not calib:
            print(f"[move_to_energy_with_calibration] No calibration found")
            return False
        
        print(f"[move_to_energy_with_calibration] Using calibration from {calib.get('timestamp')}")
        
        # Get devices from beamline_hw
        devices = init_devices()
        dccm_energy_pv = devices["vernier_dccm_energy"]
        vernier_energy_pv = devices["vernier_energy"]
        
        # Get current DCCM energy
        current_dccm_energy = float(dccm_energy_pv.get())
        print(f"[move_to_energy_with_calibration] Current DCCM energy: {current_dccm_energy:.2f} eV")
        
        # Calculate what vernier command is needed to achieve vernier = DCCM
        vernier_command = self._vernier_solve(current_dccm_energy, calib)
        
        # Move vernier to the calculated command
        print(f"[move_to_energy_with_calibration] Moving vernier to: {vernier_command:.2f} eV")
        
        try:
            vernier_energy_pv.move(vernier_command).wait()
            
            # Verify final positions
            final_dccm_energy = float(dccm_energy_pv.get())
            final_vernier_actual = float(vernier_energy_pv.position)
            final_offset = final_vernier_actual - final_dccm_energy
            
            print(f"[move_to_energy_with_calibration] Final DCCM energy: {final_dccm_energy:.2f} eV")
            print(f"[move_to_energy_with_calibration] Final vernier energy: {final_vernier_actual:.2f} eV")
            print(f"[move_to_energy_with_calibration] Final offset: {final_offset:.2f} eV")
            print(f"[move_to_energy_with_calibration] Completed successfully")
            
            return True
            
        except Exception as exc:
            print(f"[move_to_energy_with_calibration] Error: {exc}")
            return False


# Convenience function for easy integration
def create_vernier_calibration() -> VernierCalibration:
    """Create and return a VernierCalibration instance."""
    return VernierCalibration()

