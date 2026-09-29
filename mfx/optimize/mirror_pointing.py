from mfx.optimize.devices import YagCamera
from mfx.optimize.beamline_hw import init_devices
from lcls_tools.common.image.fit import ImageProjectionFit

import numpy as np, matplotlib.pyplot as plt
from epics import caget
import argparse
import time

def get_yag_centroid(prefix, name, num_frames=10, timeout=10):
    camera = YagCamera(prefix, name=name)
    image_dev = camera.image1.shaped_image

    images = []
    for i in range(num_frames):
        image_dev.trigger().wait(timeout=timeout)
        image = image_dev.get()
        images.append(image)
    
    averaged_image = np.mean(images, axis=0)

    fitter = ImageProjectionFit()
    result = fitter.fit_image(averaged_image)

    return result.centroid


def optimize_mirror_pointing(
    instrument: str,
    diagnostic_pvname: str,
    window_size: float = 5.0,
    num_frames: int = 10,
    num_points: int = 10,
):
    """
    Simple mirror pointing optimization.
    
    Parameters
    ----------
    instrument : str
        "mfx" or "mec"
    diagnostic_pvname : str
        PV prefix for YAG camera (e.g., "MFX:GIGE:DG1:YAG:" or "MEC:GIGE:13:")
    window_size : float
        Window size around nominal position, default 5.0
    num_frames : int
        Number of frames to average, default 10
    num_points : int
        Number of points in scan, default 10
    """
    # Get nominal position
    if instrument.lower() == "mfx":
        pv_name = "MR1L4:PITCH:MFX:Coating1"
    else:  # MEC
        pv_name = "MR1L4:PITCH:MEC:Coating1"
    nominal_position = caget(pv_name)
    print(f"Nominal position: {nominal_position}")
    
    # Create mirror positions
    mirror_bounds = [nominal_position - window_size, nominal_position + window_size]
    mirror_positions = np.linspace(mirror_bounds[0], mirror_bounds[1], num_points)
    
    # Initialize devices
    devices = init_devices()
    mirror_device = devices["mr1l4_homs"]
    
    # Get YAG camera and goal
    yag_camera = YagCamera(diagnostic_pvname, name=f"{instrument}_yag")
    goal_x, goal_y = yag_camera.coords.standard_two_corners_target()
    print(f"Goal position: ({goal_x}, {goal_y})")
    
    # Scan mirror positions and collect centroids
    centroids_x = []
    centroids_y = []
    
    for pos in mirror_positions:
        print(f"Moving mirror to {pos}")
        mirror_device.pitch.mv(pos)
        time.sleep(2)  # Wait for motion to settle
        
        centroid = get_yag_centroid(
            prefix=diagnostic_pvname,
            name=f"{instrument}_yag",
            num_frames=num_frames,
        )
        centroids_x.append(centroid[0])
        centroids_y.append(centroid[1])
        print(f"  Centroid: ({centroid[0]:.2f}, {centroid[1]:.2f})")
    
    # Fit lines
    slope_x, intercept_x = np.polyfit(mirror_positions, centroids_x, 1)
    slope_y, intercept_y = np.polyfit(mirror_positions, centroids_y, 1)
    
    # Solve for mirror position
    mirror_solution_x = (goal_x - intercept_x) / slope_x
    mirror_solution_y = (goal_y - intercept_y) / slope_y
    
    # Use the one with better fit (or average)
    r2x = 1 - np.sum((centroids_x - (slope_x * mirror_positions + intercept_x))**2) / np.sum((centroids_x - np.mean(centroids_x))**2)
    r2y = 1 - np.sum((centroids_y - (slope_y * mirror_positions + intercept_y))**2) / np.sum((centroids_y - np.mean(centroids_y))**2)
    
    print(f"R^2 x: {r2x:.3f}, R^2 y: {r2y:.3f}")
    
    if r2x >= r2y:
        mirror_solution = mirror_solution_x
        print(f"Using x fit (better R^2)")
    else:
        mirror_solution = mirror_solution_y
        print(f"Using y fit (better R^2)")
    
    print(f"Mirror solution: {mirror_solution:.3f}")
    
    # Move to solution
    print(f"Moving mirror to solution: {mirror_solution}")
    mirror_device.pitch.mv(mirror_solution)
    
    # Plot results
    plt.figure()
    plt.plot(mirror_positions, centroids_x, 'o-', label='centroid_x')
    plt.axvline(mirror_solution, color='r', linestyle='--', label='solution')
    plt.axhline(goal_x, color='g', linestyle='--', label='goal_x')
    plt.xlabel("mirror_position")
    plt.ylabel("centroid_x")
    plt.legend()
    plt.show(block=False)
    
    plt.figure()
    plt.plot(mirror_positions, centroids_y, 'o-', label='centroid_y')
    plt.axvline(mirror_solution, color='r', linestyle='--', label='solution')
    plt.axhline(goal_y, color='g', linestyle='--', label='goal_y')
    plt.xlabel("mirror_position")
    plt.ylabel("centroid_y")
    plt.legend()
    plt.show(block=False)
    
    return mirror_solution


def main():
    parser = argparse.ArgumentParser(description="Mirror pointing optimization script")
    parser.add_argument(
        "--instrument", "-i",
        choices=["mfx", "mec"],
        default="mfx",
        help="Instrument name (default: mfx)"
    )
    parser.add_argument(
        "--diagnostic", "-d",
        type=str,
        required=True,
        help="Diagnostic PV prefix (e.g., MFX:GIGE:DG1:YAG: or MEC:GIGE:13:)"
    )
    parser.add_argument(
        "--window", "-w",
        type=float,
        default=5.0,
        help="Window size around nominal position (default: 5.0)"
    )
    parser.add_argument(
        "--num-frames", "-n",
        type=int,
        default=10,
        help="Number of frames to average (default: 10)"
    )
    parser.add_argument(
        "--num-points", "-p",
        type=int,
        default=10,
        help="Number of points in scan (default: 10)"
    )
    args = parser.parse_args()
    
    optimize_mirror_pointing(
        instrument=args.instrument,
        diagnostic_pvname=args.diagnostic,
        window_size=args.window,
        num_frames=args.num_frames,
        num_points=args.num_points,
    ) 

if __name__ == "__main__":
    main()
