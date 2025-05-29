
#
# focus_scan.py
#
# Script for finding optimal MFX Transfocator focus
#
# Copyright  2019 - 2023  SLAC National Accelerator Laboratory
#
# Authors:
#     2019 - 2023  Alex Batyuk <batyuk@stanford.edu>
#
# focus_scan is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# focus_scan is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with focus_scan.  If not, see <http://www.gnu.org/licenses/>.
#



# Algorithm:
#
# - import stuff, init
# - parse args, camera PV
# - camera color mode check
# - camera data stream check
# - camviewer config check
# - get markers 1 and 2
# - get roi size
# - generate x-axes for projections
#
# Main loop
# - get camera image
# - get roi from image between markers
# - get transfocator Z position
# - get projections from roi image
# - fit Gaussian to projections
# - calculate FWHM
# - print FWHM for X and Y, + lens Z (plot?, dynamically update?)


import time
import sys
import argparse
import numpy as np
import matplotlib.pyplot as plt
from scipy.optimize import curve_fit
# from scipy import ndimage
from epics import caget, caput
from tqdm import tqdm


tfs_current_Z = 'MFX:TFS:MMS:21.RBV'
tfs_set_Z = 'MFX:TFS:MMS:21.VAL'  # Transfocator Z translation target PV
tfs_Z_stop = 'MFX:TFS:MMS:21.STOP'


def get_markers(PV):
    marker1X = caget(PV + ':Cross1X')
    marker1Y = caget(PV + ':Cross1Y')
    marker2X = caget(PV + ':Cross2X')
    marker2Y = caget(PV + ':Cross2Y')
    return marker1X, marker1Y, marker2X, marker2Y


def roi_size(marker1X, marker1Y, marker2X, marker2Y):
    size_of_roi_x = marker2X - marker1X
    size_of_roi_y = marker2Y - marker1Y
    if size_of_roi_x < 0 or size_of_roi_y < 0:
        print(" [!] ROI doesn't make sense. ", '\n',
              "[!] Set Orientation to 'None'," '\n',
              "[!] Marker 1 to the upper left corner,", '\n',
              "[!] Marker 2 to the bottom right corner of the desired ROI", '\n',
              "[!] and enable 'Use Global Markers' in the menu Markers/ROI.", '\n',
              "[!] Exiting..."
              '\n')
        sys.exit(1)
    else:
        return size_of_roi_x, size_of_roi_y


def check_color_mode(PV):
    color_mode = caget(PV + ':ColorMode_RBV')
    if color_mode != 0:
        print(" [!] Camera", PV, "is not in Mono color mode.",
              "Exiting...", '\n')
        sys.exit(1)


def check_data_stream(PV):
    data_stream = caget(PV + ':IMAGE1:EnableCallbacks_RBV')
    if data_stream != 1:
        print(" [!] Data stream is disabled for", PV + ".", "Exiting...", '\n')
        sys.exit(1)


def check_camviewer_config(PV):
    hutch = str.lower(PV.split(':')[0])
    if hutch not in ['mfx', 'cxi', 'xcs']:
        print(" [!] Unsupported camera", PV + ".", "Exiting...", '\n')
        sys.exit(1)
    file = "/reg/g/pcds/pyps/config/" + hutch + "/camviewer.cfg"
    with open(file, 'r') as viewer_config:
        for line in viewer_config:
            if PV not in line:
                continue
            else:
                camconfig = (line.split(',')[1].split(';')[0].split(':')[3])
    if camconfig == 'IMAGE2':
        ArraySizeX_data = caget(PV + ':IMAGE1:ArraySize0_RBV')
        ArraySizeY_data = caget(PV + ':IMAGE1:ArraySize1_RBV')
        ArraySizeX_viewer = caget(PV + ':IMAGE2:ArraySize0_RBV')
        ArraySizeY_viewer = caget(PV + ':IMAGE2:ArraySize1_RBV')
        if ArraySizeX_data != ArraySizeX_viewer or \
           ArraySizeY_data != ArraySizeY_viewer:
            print('\n',
                  "[!] camViewer for",
                  PV, "is configured as", camconfig, '\n',
                  "[!] but data and viewer streams have different resolution",
                  '\n',
                  "[!] - data stream width is:", ArraySizeX_data, '\n',
                  "[!] - viewer stream width is:", ArraySizeX_viewer, '\n',
                  "[!] - data stream height is:", ArraySizeY_data, '\n',
                  "[!] - viewer stream height is:", ArraySizeY_viewer, '\n',
                  "[!] ROI defined with markers in camViewer won't make sense.", '\n',
                  "[!] Exiting...", '\n')
            sys.exit(1)


def get_image(PV):
    image = caget(PV + ':IMAGE1:ArrayData')
    if len(image) == 0:
        print(" [!] Can't read camera", PV + ".", "Exiting...", '\n')
        sys.exit(1)
    else:
        ArraySizeX = caget(PV + ':IMAGE1:ArraySize0_RBV')
        ArraySizeY = caget(PV + ':IMAGE1:ArraySize1_RBV')
        image = np.reshape(image, (ArraySizeY, ArraySizeX))
        # image = ndimage.gaussian_filter(image, 0.1) # test gaussian filter denoising
        # image = ndimage.median_filter(image, 1) # test median filter denoising
    return image


def get_roi(image, marker1X, marker1Y, marker2X, marker2Y):
    image = image[marker1Y:marker2Y, marker1X:marker2X]
    return image


def get_projections(image):
    x_projection = np.sum(image, axis=0)
    y_projection = np.sum(image, axis=1)

    x_projection -= x_projection.min()
    y_projection -= y_projection.min()

    return x_projection, y_projection


def gaussian(x, amplitude, mean, stddev):
    return amplitude * np.exp(-((x - mean) / 4 / stddev)**2)


def FWHM(x, y):
    d = y - (max(y) / 2)
    indexes = np.where(d > 0)[0]
    try:
        fwhm = abs(x[indexes[-1]] - x[indexes[0]])
    except IndexError:
        fwhm = 0
    return fwhm


def get_lens_z():
    return round(caget(tfs_current_Z), 0)


def fwhm_calc(PV, marker1X, marker1Y, marker2X, marker2Y, axis_x_x, axis_x_y):
    image = get_image(PV)
    image_roi = get_roi(image, marker1X, marker1Y, marker2X, marker2Y)

    x_projection, y_projection = get_projections(image_roi)

    try:
        popt_x, pcov_x = curve_fit(gaussian, axis_x_x, x_projection)
        popt_y, pcov_y = curve_fit(gaussian, axis_x_y, y_projection)

    except RuntimeError:
        print('\n', "[!] Can't fit a Gaussian. Exiting...", '\n')
        sys.exit(1)

    gauss_fit_x = gaussian(axis_x_x, *popt_x)
    gauss_fit_y = gaussian(axis_x_y, *popt_y)

    FWHM_X = FWHM(axis_x_x, gauss_fit_x)
    FWHM_Y = FWHM(axis_x_y, gauss_fit_y)

    return(image_roi, x_projection, y_projection,
           gauss_fit_x, gauss_fit_y, FWHM_X, FWHM_Y)


def park_lens():
    lens_z = get_lens_z()

    if lens_z <= 150:
        lens_direction_bit = 0  # 0 for 0 to 299, 1 for 299 to 0
        try:
            print(" [*] Transfocator is at Z =", lens_z, "mm", '\n',
                    "[*] Sending transfocator to the nearest end (Z = 0 mm)")
            caput(tfs_set_Z, 0)
            wait = round((lens_z / 2), 1) + 3
            print(" [*] Waiting", wait, "sec...", '\n')
            time.sleep(wait)
        except KeyboardInterrupt:
            print('\n', "[*] Stopping transfocator Z motion and exiting...",'\n')
            caput(tfs_Z_stop, 1)
            sys.exit()

    else:
        lens_direction_bit = 1  # 0 for 0 to 299, 1 for 299 to 0
        try:
            print(" [*] Transfocator is at Z =", lens_z, "mm", '\n',
                "[*] Sending transfocator to the nearest end (Z = 299 mm)")
            caput(tfs_set_Z, 299)
            wait = round(((300 - lens_z) / 2), 1) + 3
            print(" [*] Waiting", wait, "sec...", '\n')
            time.sleep(wait)
        except KeyboardInterrupt:
            print('\n', "[*] Stopping transfocator Z motion and exiting...",'\n')
            caput(tfs_Z_stop, 1)
            sys.exit()

    return(lens_direction_bit)


def plot_data(scan_data):
    lens_z_position = scan_data[:, 0]
    fwhm_data_x = scan_data[:, 1]
    fwhm_data_y = scan_data[:, 2]

    fig, (ax1, ax2) = plt.subplots(2, 1)
    fig.subplots_adjust(hspace=0.5)
    fig.canvas.manager.set_window_title('FWHM scan results')

    ax1.plot(lens_z_position[:], fwhm_data_x)
    ax1.set_xlabel('Transfocator Z')
    ax1.set_ylabel('FWHM X')
    ax1.grid(True)

    ax2.plot(lens_z_position[:], fwhm_data_y)
    ax2.set_xlabel('Transfocator Z')
    ax2.set_ylabel('FWHM Y')
    ax2.grid(True)

    plt.show()
    return()


print("done.", '\n')  # Print message after init


# Main routine

parser = argparse.ArgumentParser(
    prog='focus_scan', usage='%(prog)s [options] PV', add_help=False)
parser.add_argument(
    "PV", help="Camera PV. Example: MFX:GIGE:01")
parser.add_argument(
    "-p", "--plot", action="store_true", help="show projections plot")
parser.add_argument(
    "-i", "--image", action="store_true", help="show ROI image")
parser.add_argument(
    "-s", "--scan", action="store_true", help="scan focus automatically")
parser.add_argument(
    "-r", "--record", action="store_true", help="record with daq")
parser.add_argument(
    "-d", "--daq_num", dest="daq_num", default=2, help="choose daq number")

if len(sys.argv) == 1:
    parser.print_help(sys.stderr)
    sys.exit(1)

args = parser.parse_args()

PV = args.PV

print(' [*] Camera PV: ', PV)

# A few camera checks before start

check_color_mode(PV)  # Camera should be in Mono color mode
check_data_stream(PV)  # Data stream (IMAGE1:ArrayData) should be enabled
check_camviewer_config(PV)  # Check for IMAGE1 or IMAGE2 config in camViewer


# Get markers, ROI size, generate x-axes

marker1X, marker1Y, marker2X, marker2Y = get_markers(PV)

print(' [*] Marker 1: ', marker1X, marker1Y)
print(' [*] Marker 2: ', marker2X, marker2Y, '\n')

size_of_roi_x, size_of_roi_y = roi_size(marker1X, marker1Y, marker2X, marker2Y)

axis_x_x = np.linspace(1, size_of_roi_x, size_of_roi_x)
axis_x_y = np.linspace(1, size_of_roi_y, size_of_roi_y)


# Main loop

while True:

    if args.plot:

        lens_z = get_lens_z()

        image_roi, x_projection, y_projection, gauss_fit_x, \
            gauss_fit_y, FWHM_X, FWHM_Y = fwhm_calc(PV, marker1X,
            marker1Y, marker2X, marker2Y, axis_x_x, axis_x_y)

        plt.plot(axis_x_x, x_projection, label='x_projection')
        plt.plot(axis_x_y, y_projection, label='y_projection')

        plt.plot(axis_x_x, gauss_fit_x, label='gauss_fit_x')
        plt.plot(axis_x_y, gauss_fit_y, label='gauss_fit_y')

        print(
            " Lens Z =", lens_z,
            " FWHM X =", FWHM_X,
            " FWHM Y =", FWHM_Y, '\n')
        plt.legend()
        plt.show()
        sys.exit()

    elif args.image:

        lens_z = get_lens_z()

        image_roi, x_projection, y_projection, gauss_fit_x, \
            gauss_fit_y, FWHM_X, FWHM_Y = fwhm_calc(PV, marker1X,
            marker1Y, marker2X, marker2Y, axis_x_x, axis_x_y)

        plt.imshow(image_roi, cmap='hot')
        
        print(
            " Lens Z =", lens_z,
            " FWHM X =", FWHM_X,
            " FWHM Y =", FWHM_Y, '\n')

        plt.show()
        sys.exit()

    elif args.scan:
        print(" [*] Scanning mode")
        lens_z = get_lens_z()
        if lens_z <= 150:
            try:
                print(" [*] Transfocator is at Z =", lens_z, "mm", '\n',
                    "[*] Sending transfocator to the nearest end (Z = 0 mm)")
                caput(tfs_set_Z, 0)
                wait = round((lens_z / 2), 1) + 3
                print(" [*] Waiting", wait, "sec...", '\n')
                time.sleep(wait)
            except KeyboardInterrupt:
                print('\n', "[*] Stopping transfocator Z motion and exiting...",'\n')
                caput(tfs_Z_stop, 1)
                sys.exit()
            lens_z = get_lens_z()
            print(" [*] Transfocator is at Z =", lens_z, "mm")
            print(" [*] Starting scan...", '\n')

            try:
                fwhm_data = np.zeros((142, 3))
                caput(tfs_set_Z, 299)
                for i in tqdm(range(0, 142, 1), ascii=" *"):
                    image = get_image(PV)
                    image = get_roi(image, marker1X, marker1Y, marker2X, marker2Y)

                    lens_z = get_lens_z()

                    x_projection, y_projection = get_projections(image)

                    try:
                        popt_x, pcov_x = curve_fit(gaussian, axis_x_x, x_projection)
                        popt_y, pcov_y = curve_fit(gaussian, axis_x_y, y_projection)

                    except:
                        pass
                        
                        #     RuntimeError:
                        # print('\n', "[!] Can't fit a Gaussian. Exiting...", '\n')
                        # caput(tfs_Z_stop, 1)
                        # sys.exit()

                    FWHM_X = FWHM(axis_x_x, gaussian(axis_x_x, *popt_x))
                    FWHM_Y = FWHM(axis_x_y, gaussian(axis_x_y, *popt_y))

                    fwhm_data[i] = (lens_z, FWHM_X, FWHM_Y)
                    time.sleep(1)
            except KeyboardInterrupt:
                print('\n', "[*] Stopping scan and exiting...",'\n')
                caput(tfs_Z_stop, 1)
                sys.exit()

            plot_data(fwhm_data)

            sys.exit()

        else:
            try:
                print(" [*] Transfocator is at Z =", lens_z, "mm", '\n',
                    "[*] Sending transfocator to the nearest end (Z = 299 mm)")
                caput(tfs_set_Z, 299)
                wait = round(((300 - lens_z) / 2), 1) + 3
                print(" [*] Waiting", wait, "sec...", '\n')
                time.sleep(wait)
            except KeyboardInterrupt:
                print('\n', "[*] Stopping transfocator Z motion and exiting...",'\n')
                caput(tfs_Z_stop, 1)
                sys.exit()
            lens_z = get_lens_z()
            print(" [*] Transfocator is at Z =", lens_z, "mm")
            print(" [*] Starting scan...", '\n')
            print(args.record)
            print(args.daq_num)
            if args.record:
                print(recording)
                import threading
                from mfx.autorun import autorun
                thread = threading.Thread(
                    target=autorun(
                        sample='Focus_scan',
                        run_length=153, 
                        record=True,
                        runs=1,
                        daq_num=args.daq_num))
                thread.daemon = True  # Allow the main program to exit even if the thread is running
                thread.start()

            try:
                fwhm_data = np.zeros((142, 3))
                caput(tfs_set_Z, 0)
                for i in tqdm(range(0, 142, 1), ascii=" *"):
                    image = get_image(PV)
                    image = get_roi(image, marker1X, marker1Y, marker2X, marker2Y)

                    lens_z = get_lens_z()

                    x_projection, y_projection = get_projections(image)

                    try:
                        popt_x, pcov_x = curve_fit(gaussian, axis_x_x, x_projection)
                        popt_y, pcov_y = curve_fit(gaussian, axis_x_y, y_projection)

                    except RuntimeError:
                        print('\n', "[!] Can't fit a Gaussian. Exiting...", '\n')
                        pass
                        # caput(tfs_Z_stop, 1)
                        # sys.exit()

                    FWHM_X = FWHM(axis_x_x, gaussian(axis_x_x, *popt_x))
                    FWHM_Y = FWHM(axis_x_y, gaussian(axis_x_y, *popt_y))

                    fwhm_data[i] = (lens_z, FWHM_X, FWHM_Y)
                    time.sleep(1)
            except KeyboardInterrupt:
                print('\n', "[*] Stopping scan and exiting...", '\n')
                caput(tfs_Z_stop, 1)
                sys.exit()

            fwhm_data = np.flip(fwhm_data, 0)  # Flipping array for 299 - 0 scan direction

            plot_data(fwhm_data)

            sys.exit()

    else:
        while True:
            try:
                image = get_image(PV)
                image = get_roi(image, marker1X, marker1Y, marker2X, marker2Y)

                lens_z = get_lens_z()

                x_projection, y_projection = get_projections(image)

                try:
                    popt_x, pcov_x = curve_fit(gaussian, axis_x_x, x_projection)
                    popt_y, pcov_y = curve_fit(gaussian, axis_x_y, y_projection)

                except RuntimeError:
                    print('\n', "[!] Can't fit a Gaussian. Exiting...", '\n')
                    pass
                    # sys.exit()

                FWHM_X = FWHM(axis_x_x, gaussian(axis_x_x, *popt_x))
                FWHM_Y = FWHM(axis_x_y, gaussian(axis_x_y, *popt_y))

                print(
                    " Lens Z =", lens_z,
                    " FWHM X =", FWHM_X,
                    " FWHM Y =", FWHM_Y)
                time.sleep(0.5)
            except KeyboardInterrupt:
                print('\n', "[*] Exiting...", '\n')
                sys.exit()
