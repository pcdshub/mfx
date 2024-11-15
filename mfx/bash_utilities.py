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
        

    def takepeds(self):
        import os
        import logging
        logging.info("Taking Pedestals")
        os.system(f"/reg/g/pcds/engineering_tools/latest-released/scripts/takepeds")


    def makepeds(self, username, run_number=None, onshift=False):
        import os
        import logging
        from mfx.db import daq
        from mfx.macros import get_exp
        logging.info("Making Pedestals")
        if run_number is None:
            try:
                run_number = daq.run_number()
            except NameError:
                logging.error(
                    f"daq.run_number() not working please enter run manually as follows\n"
                    f"bs.makepeds('{username}', run_number=XXX)")
        username = str(username)
        run_number = str(int(run_number))
        if onshift:
            cmd = f"ssh -Y {username}@s3dflogin /sdf/group/lcls/ds/tools/mfx/scripts/makepeds.sh {run_number} {get_exp()} --reservation lcls:onshift"
        else:
            cmd = f"ssh -Y {username}@s3dflogin /sdf/group/lcls/ds/tools/mfx/scripts/makepeds.sh {run_number} {get_exp()}"
        logging.info(cmd)
        os.system(cmd)


    def restartdaq(self):
        import subprocess
        import logging
        logging.info("Restarting the DAQ")
        subprocess.Popen(
            ["/reg/g/pcds/engineering_tools/latest-released/scripts/restartdaq -w"],
            shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)


    def cameras(self, time=12):   
        import subprocess
        import logging
        logging.info("Opening Cam Viewer")
        subprocess.Popen(
            [f"/reg/g/pcds/engineering_tools/latest-released/scripts/camViewer -w {time}"],
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
