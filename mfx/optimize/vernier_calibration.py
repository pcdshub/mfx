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
    
    def _predict_vernier_offset(self, vernier_energy_eV: float, calib: dict) -> float:
        """
        Predict vernier offset from vernier energy using calibration coefficients.
        
        Parameters
        ----------
        vernier_energy_eV : float
            Vernier energy in eV
        calib : dict
            Calibration dictionary containing coefficients
            
        Returns
        -------
        float
            Predicted vernier offset in eV
        """
        a0, a1 = calib["coeff_offset"]
        pred_offset = a0 + a1 * vernier_energy_eV
        return float(pred_offset)
    
    def _vernier_solve(self, target_energy_eV: float, calib: dict) -> float:
        """
        Solve for vernier energy that achieves target DCCM energy given calibration.
        
        Parameters
        ----------
        target_energy_eV : float
            Target DCCM energy in eV
        calib : dict
            Calibration dictionary containing coefficients
            
        Returns
        -------
        float
            Required vernier energy in eV
        """
        a0, a1 = calib["coeff_offset"]
        # Solve: target_energy = vernier_energy + offset
        # offset = a0 + a1 * vernier_energy
        # target_energy = vernier_energy + a0 + a1 * vernier_energy
        # target_energy = vernier_energy * (1 + a1) + a0
        # vernier_energy = (target_energy - a0) / (1 + a1)
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
            
            # Get average DCCM energy for vertical line
            avg_dccm_energy = np.mean(dccm_energy)
            
            # Plot 1: Vernier offset vs Vernier Energy (top left)
            axs[0,0].scatter(vernier_energy, vernier_offset, s=20, alpha=0.7)
            energy_range = np.linspace(vernier_energy.min(), vernier_energy.max(), 100)
            offset_pred = reg_offset.predict(energy_range.reshape(-1, 1))
            axs[0,0].plot(energy_range, offset_pred, 'r--', linewidth=2)
            # Add vertical line showing average DCCM energy
            axs[0,0].axvline(x=avg_dccm_energy, color='green', linestyle=':', linewidth=2, label=f'Avg DCCM: {avg_dccm_energy:.1f} eV')
            axs[0,0].set_xlabel("Vernier Energy [eV]")
            axs[0,0].set_ylabel("Vernier Offset [eV]")
            axs[0,0].set_title("Offset vs Vernier Energy")
            axs[0,0].legend()
            axs[0,0].grid(True, alpha=0.3)
            
            # Plot 2: Intensity vs Vernier Energy (top right)
            axs[0,1].scatter(vernier_energy, intensity, s=20, alpha=0.7, color='green')
            axs[0,1].axvline(x=avg_dccm_energy, color='red', linestyle=':', linewidth=2, label=f'Avg DCCM: {avg_dccm_energy:.1f} eV')
            axs[0,1].set_xlabel("Vernier Energy [eV]")
            axs[0,1].set_ylabel("Intensity [arb. units]")
            axs[0,1].set_title("Intensity vs Vernier Energy")
            axs[0,1].legend()
            axs[0,1].grid(True, alpha=0.3)
            
            # Plot 3: Vernier offset vs DCCM Energy (bottom left)  
            axs[1,0].scatter(dccm_energy, vernier_offset, s=20, alpha=0.7)
            axs[1,0].set_xlabel("DCCM Energy [eV]")
            axs[1,0].set_ylabel("Vernier Offset [eV]")
            axs[1,0].set_title("Offset vs DCCM Energy")
            axs[1,0].grid(True, alpha=0.3)
            
            # Plot 4: Intensity vs Offset (bottom right)
            axs[1,1].scatter(vernier_offset, intensity, s=20, alpha=0.7, color='orange')
            axs[1,1].axvline(x=0, color='red', linestyle='--', linewidth=2, alpha=0.5, label='Zero Offset')
            axs[1,1].set_xlabel("Vernier Offset [eV]")
            axs[1,1].set_ylabel("Intensity [arb. units]")
            axs[1,1].set_title("Intensity vs Offset")
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
            
            # Get current DCCM energy
            current_dccm_energy = float(dccm_energy_pv.get())
            
            # Get current vernier energy
            current_vernier_energy = float(vernier_energy_pv.position)
            
            # Predict vernier offset for current vernier energy
            pred_offset = self._predict_vernier_offset(current_vernier_energy, calib)
            
            # Calculate actual offset
            actual_offset = current_dccm_energy - current_vernier_energy
            
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
        try:
            from mfx.db import RE, daq
        except ImportError:
            from bluesky import RunEngine
            RE = RunEngine({})
            daq = FakeDaq()
            print("[calibrate] Cannot import mfx.db - running in simulation mode")
        
        try:
            import bluesky.plans as bp
        except ImportError:
            print("[calibrate] Could not import bluesky.plans")
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
                if "vernier_energy" not in event_data:
                    return
                
                vernier_energy = event_data["vernier_energy"]
                
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
                    # Real hardware mode - use read()
                    try:
                        intensity_dict = intensity_pv.read()
                        intensity = float(intensity_dict["vernier_intensity"]["value"])
                    except Exception as e:
                        print(f"[calibrate] Failed to read intensity: {e}")
                        return
                    
                    try:
                        dccm_dict = dccm_energy_pv.read()
                        dccm_energy = float(dccm_dict["vernier_dccm_energy"]["value"])
                    except Exception as e:
                        print(f"[calibrate] Failed to read DCCM energy: {e}")
                        return
                
                offset = dccm_energy - vernier_energy
                
                print(f"[calibrate] Collected: vernier={vernier_energy:.2f}, dccm={dccm_energy:.2f}, offset={offset:.2f}, intensity={intensity:.2f}")
                
                data["energy_eV"].append(dccm_energy)
                data["vernier_offset"].append(offset)
                data["intensity"].append(intensity)
                data["dccm_energy"].append(dccm_energy)
                data["vernier_energy"].append(vernier_energy)
            
            sid = RE.subscribe(on_event)
            
            try:
                # Run the scan
                RE(bp.scan(
                    [daq],
                    vernier_energy_pv,
                    energy_start_eV,
                    energy_end_eV,
                    energy_steps
                ))
            finally:
                RE.unsubscribe(sid)
                
        except Exception as exc:
            print(f"[calibrate] Error during scan: {exc}")
            raise
        
        # Convert to DataFrame for analysis
        df = pd.DataFrame(data)
        print(f"[calibrate] Collected {len(df)} data points")
        
        # Fit linear regression model for offset vs vernier energy
        X = df["vernier_energy"].values.reshape(-1, 1)
        y_offset = df["vernier_offset"].values
        
        reg_offset = LinearRegression().fit(X, y_offset)
        
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
    
    def align_to_dccm(self, target_energy_eV: float, use_calibration: bool = True,
                     energy_range_eV: float = 10.0, energy_steps: int = 11,
                     events_per_step: int = 12) -> bool:
        """
        Align vernier to DCCM energy using intensity-based optimization.
        
        Parameters
        ----------
        target_energy_eV : float
            Target DCCM energy in eV
        use_calibration : bool
            Whether to use calibration for initial positioning (only if available and fresh)
        energy_range_eV : float
            Range around target energy to scan (in eV)
        energy_steps : int
            Number of steps in alignment scan
        events_per_step : int
            Number of events per step
            
        Returns
        -------
        bool
            True if alignment was successful, False otherwise
        """
        print(f"[align_to_dccm] Aligning vernier to DCCM energy: {target_energy_eV:.2f} eV")
        
        # Get devices from beamline_hw (will be real or simulated based on sim_devices() call)
        devices = init_devices()
        dccm_energy_pv = devices["vernier_dccm_energy"]
        vernier_energy_pv = devices["vernier_energy"]
        intensity_pv = devices["vernier_intensity"]
        
        # Check if calibration is available and fresh - ONLY use if it exists and is fresh
        initial_vernier_energy = target_energy_eV  # Default to target energy
        
        if use_calibration:
            calib = self._load_calibration()
            if calib and self.check_calibration():
                print(f"[align_to_dccm] Using existing fresh calibration for initial positioning")
                # Use calibration to get initial vernier position
                initial_vernier_energy = self._vernier_solve(target_energy_eV, calib)
                print(f"[align_to_dccm] Calibration suggests vernier energy: {initial_vernier_energy:.2f} eV")
            else:
                print(f"[align_to_dccm] No fresh calibration available, using intensity-based alignment only")
                print(f"[align_to_dccm] Starting from target energy: {target_energy_eV:.2f} eV")
        else:
            print(f"[align_to_dccm] Using intensity-based alignment only (calibration disabled)")
        
        # Define scan range around initial position
        scan_start = initial_vernier_energy - energy_range_eV / 2
        scan_end = initial_vernier_energy + energy_range_eV / 2
        
        print(f"[align_to_dccm] Scanning vernier from {scan_start:.2f} to {scan_end:.2f} eV")
        
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
            
            # For simulation mode, get tracker from vernier device
            tracker = None
            try:
                if hasattr(vernier_energy_pv, 'pos_tracker'):
                    tracker = vernier_energy_pv.pos_tracker
            except AttributeError:
                pass
            
            def on_event(name, doc):
                nonlocal best_intensity, best_vernier_energy
                if name != "event":
                    return
                event_data = doc.get("data", {})
                if "vernier_energy" not in event_data:
                    return
                
                vernier_energy = event_data["vernier_energy"]
                
                # Update tracker in simulation mode
                if tracker is not None:
                    tracker.value = float(vernier_energy)
                
                # Read intensity (use read() for simulation mode to force recalculation)
                try:
                    intensity_dict = intensity_pv.read()
                    intensity = float(intensity_dict["vernier_intensity"]["value"])
                except Exception as e:
                    print(f"[align_to_dccm] Failed to read intensity: {e}")
                    return
                
                if intensity > best_intensity:
                    best_intensity = intensity
                    best_vernier_energy = vernier_energy
                    print(f"[align_to_dccm] New best intensity: {intensity:.2f} at vernier energy: {vernier_energy:.2f} eV")
            
            sid = RE.subscribe(on_event)
            
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
            
            # Move to best position
            if best_vernier_energy is not None:
                print(f"[align_to_dccm] Moving to best vernier energy: {best_vernier_energy:.2f} eV")
                vernier_energy_pv.move(best_vernier_energy).wait()
                
                # Verify final DCCM energy
                final_dccm_energy = float(dccm_energy_pv.get())
                final_offset = final_dccm_energy - best_vernier_energy
                
                print(f"[align_to_dccm] Final DCCM energy: {final_dccm_energy:.2f} eV")
                print(f"[align_to_dccm] Final vernier energy: {best_vernier_energy:.2f} eV")
                print(f"[align_to_dccm] Final offset: {final_offset:.2f} eV")
                print(f"[align_to_dccm] Alignment completed successfully")
                
                return True
            else:
                print(f"[align_to_dccm] No valid intensity measurements found")
                return False
                
        except Exception as exc:
            print(f"[align_to_dccm] Error during alignment: {exc}")
            return False
    
    def align_with_calibration(self, target_energy_eV: float, 
                              force_recalibrate: bool = False) -> bool:
        """
        Align vernier to DCCM using calibration method.
        
        Parameters
        ----------
        target_energy_eV : float
            Target DCCM energy in eV
        force_recalibrate : bool
            Force recalibration even if existing calibration is fresh (NOT recommended during scans)
            
        Returns
        -------
        bool
            True if alignment was successful, False otherwise
        """
        print(f"[align_with_calibration] Aligning vernier to DCCM energy: {target_energy_eV:.2f} eV")
        
        # Check calibration freshness - ONLY recalibrate if forced (not recommended during scans)
        if force_recalibrate:
            print(f"[align_with_calibration] WARNING: Force recalibration requested - this will interrupt scans!")
            print(f"[align_with_calibration] Performing calibration scan...")
            # Perform calibration scan
            energy_range = 50.0  # eV range for calibration
            calib = self.calibrate(
                energy_start_eV=target_energy_eV - energy_range/2,
                energy_end_eV=target_energy_eV + energy_range/2,
                energy_steps=10,
                events_per_step=120
            )
        else:
            # Check if existing calibration is fresh
            calib = self._load_calibration()
            if not calib:
                print(f"[align_with_calibration] No calibration found - cannot use calibration method")
                print(f"[align_with_calibration] Consider using align_to_dccm() for intensity-based alignment")
                return False
            
            if not self.check_calibration():
                print(f"[align_with_calibration] Calibration is stale - cannot use calibration method")
                print(f"[align_with_calibration] Consider using align_to_dccm() for intensity-based alignment")
                return False
            
            print(f"[align_with_calibration] Using existing fresh calibration from {calib.get('timestamp')}")
        
        # Get devices from beamline_hw
        devices = init_devices()
        dccm_energy_pv = devices["vernier_dccm_energy"]
        vernier_energy_pv = devices["vernier_energy"]
        
        # Solve for vernier energy
        vernier_energy = self._vernier_solve(target_energy_eV, calib)
        print(f"[align_with_calibration] Moving vernier to: {vernier_energy:.2f} eV")
        
        # Move vernier
        try:
            vernier_energy_pv.move(vernier_energy).wait()
            
            # Verify final position
            final_dccm_energy = float(dccm_energy_pv.get())
            final_offset = final_dccm_energy - vernier_energy
            
            print(f"[align_with_calibration] Final DCCM energy: {final_dccm_energy:.2f} eV")
            print(f"[align_with_calibration] Final vernier energy: {vernier_energy:.2f} eV")
            print(f"[align_with_calibration] Final offset: {final_offset:.2f} eV")
            print(f"[align_with_calibration] Alignment completed successfully")
            
            return True
            
        except Exception as exc:
            print(f"[align_with_calibration] Error during alignment: {exc}")
            return False


# Convenience function for easy integration
def create_vernier_calibration() -> VernierCalibration:
    """Create and return a VernierCalibration instance."""
    return VernierCalibration()

