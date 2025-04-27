class bs:
    def xfel_gui(self):
        import subprocess
        import logging
        from mfx.macros import get_exp

        logging.info("Checking xfel gui phil File")
        cctbx_settings = open("/cds/home/opr/mfxopr/.cctbx.xfel/settings_old.phil", "r", encoding="UTF-8")
        setting_lines = cctbx_settings.readlines()
        change = False

        if setting_lines[10] != f'name = "{get_exp()}"':
            logging.warning(f"Changing experiment to current: {get_exp()}")
            setting_lines[10] = f'  name = "{get_exp()}"\n'
            change = True

        if setting_lines[11] != f'user = "{get_exp()}"':
            logging.warning(f"Changing experiment to current: {get_exp()}")
            setting_lines[11] = f'  user = "{get_exp()}"\n'
            change = True

        if change:
            cctbx_settings = open("/cds/home/opr/mfxopr/.cctbx.xfel/settings.phil", "w", encoding="UTF-8")
            cctbx_settings.writelines(setting_lines)
            cctbx_settings.close
            cctbx_settings = open("/cds/home/opr/mfxopr/.cctbx.xfel/settings_old.phil", "w", encoding="UTF-8")
            cctbx_settings.writelines(setting_lines)
            cctbx_settings.close

        subprocess.Popen(
            [". /reg/g/cctbx/brewster/working/build/conda_setpaths.sh;cctbx.xfel &"],
            shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        

    def takepeds(self, daq=2):
        import os
        import logging
        from pcdsdaq.daq.lcls1 import DaqLCLS1

        logger = logging.getLogger(__name__)

        daq1=DaqLCLS1()
        logging.info("Taking Pedestals")
        if daq == 1:
            os.system(f"/reg/g/pcds/engineering_tools/latest-released/scripts/takepeds")
        elif daq ==2:
            from psdaq.control.DaqControl import DaqControl  # NOQA
            daq_control = DaqControl(
                host=daq_host,
                platform=daq_platform,
                timeout=10000,
            )
            instr = daq_control.getInstrument()
            if instr is None:
                logger.error('Failed to connect to LCLS-II DAQ')
                break
            start_state = daq_control.getState()
            if start_state == 'error':
                logger.error('DAQ is in an error state.')
                break
            daq.control.setState("configured")
            while daq.control.getState() != "configured":
                ...
            daq.control.setRecord(True)

            os.system(f"/reg/g/pcds/engineering_tools/latest-released/scripts/takepeds")
            daq.control.setRecord(False)
            daq.control.setState("configured")
            while daq.control.getState() != "configured":
                ...
            daq.control.setState("running")
            while daq.control.getState() != "running":
                ...
        else:
            logging.error("Please select daq 1 or 2")


    def makepeds(self, username, run_number=None, onshift=False, daq=2, det=None):
        import os
        import logging
        from mfx.db import daq
        from mfx.macros import get_exp
        from pcdsdaq.daq.lcls1 import DaqLCLS1

        logger = logging.getLogger(__name__)

        daq1=DaqLCLS1()
        logging.info("Making Pedestals")

        if run_number is None:
            try:
                run_number = daq1.run_number()
            except NameError:
                logging.error(
                    f"daq1.run_number() not working please enter run manually as follows\n"
                    f"bs.makepeds('{username}', run_number=XXX)")
        username = str(username)
        run_number = str(int(run_number))

        if daq == 1:
            if onshift:
                cmd = f"ssh -Y {username}@s3dflogin /sdf/group/lcls/ds/tools/mfx/scripts/makepeds.sh {1} {None} {get_exp()} {run_number} --reservation lcls:onshift"
            else:
                cmd = f"ssh -Y {username}@s3dflogin /sdf/group/lcls/ds/tools/mfx/scripts/makepeds.sh {1} {None} {get_exp()} {run_number}"
            logging.info(cmd)
            os.system(cmd)

        elif daq ==2:
            if det != jungfrau or det != epix:
                logging.error("please enter either 'jungfrau' or 'epix' or 'all'")
            cmd = f"ssh -Y {username}@s3dflogin /sdf/group/lcls/ds/tools/mfx/scripts/makepeds.sh {2} {det} {get_exp()} {run_number}"
            logging.info(cmd)
            os.system(cmd)

        else:
            logging.error("Please select daq 1 or 2")


    def restartdaq(self, daq=2):
        import subprocess
        import logging
        logging.info("Restarting the DAQ")
        if daq == 1:
            subprocess.Popen(
                ["/reg/g/pcds/engineering_tools/latest-released/scripts/restartdaq -w"],
                shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)

        elif daq ==2:
            subprocess.Popen(
                ["/reg/g/pcds/engineering_tools/latest-released/scripts/restartdaq"],
                shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)

        else:
            logging.error("Please select daq 1 or 2")



    def lecroy(self, res='2560x1440'):
        import subprocess
        import logging
        logging.info("Opening the fast Lecroy")
        subprocess.Popen(
            [f"xfreerdp -g {res} -u lecroyuser -p pcds scope-ics-mfx-lecroy01"],
            shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)


    def grabber(self):
        import subprocess
        import logging
        logging.info("Opening elog grabber")
        subprocess.Popen(
            [f"/reg/g/pcds/engineering_tools/mfx/scripts/eloggrabber"],
            shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)


    def cameras(self):   
        import subprocess
        import logging
        logging.info("Opening Cam Viewer")
        subprocess.Popen(
            [f"/reg/g/pcds/engineering_tools/latest-released/scripts/camViewer"],
            shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)


    def camera_list_out(self):
        import re   
        import logging
        logging.info("Opening Camera List")
        camlist = open("/reg/g/pcds/pyps/config/mfx/camviewer.cfg", "r", encoding="UTF-8")
        cam_list = camlist.readlines()
        avail_cams = [cam for cam in cam_list if cam.startswith('GE')]
        self.camera_names = [['camera_name', 'camera_pv']]
        print("Available Cameras")
        for cam in avail_cams:
            cam = re.split(';|,', cam)
            self.camera_names.append([cam[4].strip(),cam[2]])
            print(f"Camera {cam[4].strip()} ....  {cam[2]}")

        return self.camera_names


    def camera_list(self):
        camera_names = self.camera_list_out()


    def focus_scan(self, camera):
        import os
        import sys
        import logging
        logging.info(
            "Preparing for Focus Scan\n"
            "Please check the following\n"
            "One of the following cameras is selected\n\n")
        self.camera_list()
        logging.info(
            "\nCamera orientation set to none\n"
            "Slits are open\n"
            "Blue crosshair in upper left corner\n"
            "Red crosshair in bottom right corner\n")

        input("Press Enter to continue...")

        if camera not in [pv[1] for pv in self.camera_names]:
            logging.error("Desired Camera not in List. Please double check camera name.")

        logging.info("Checking Focus Scan Plot")
        os.system(f"/cds/home/opr/mfxopr/bin/focus_scan {camera} -p")
        input("Press Enter to continue...")

        logging.info("Running Focus Scan")
        os.system(f"/cds/home/opr/mfxopr/bin/focus_scan {camera} -s")

        tfs_position = input(
            "Please enter your desired z-position for the TFS from the plot provided as an interger between 1 and 299: ")

        if 0 < int(tfs_position) < 300:
            logging.info(f"Moving TFS to {tfs_position}")
            os.system(f'caput MFX:TFS:MMS:21.VAL {tfs_position}')
        else:
            logging.error(f"{tfs_position} is not a valid position please use an interger between 1 and 299")