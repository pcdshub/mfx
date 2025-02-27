class OM:
    def __init__(self):
        from mfx.macros import get_exp
        self.experiment = str(get_exp())
        self.cwd = f'/cds/home/opr/mfxopr/OM-GUI'
        self.pwd = f'{self.cwd}/{self.experiment}'


    def fix_run_om(self, path: str):
        """
        Fixes the run_om.sh file to have current experiment number

        Parameters:
            path (str): run_om.sh file path.

        Operations:

        """
        from subprocess import check_output
        import logging
        logging.info(f"Updating run_om.sh file: {path}")
        wherepsana = check_output("wherepsana",shell=True).decode().strip('\n')

        with open(path, "r") as file:
            lines = file.readlines()
            for ind, line in enumerate(lines):
                if '--host' in lines[ind]:
                    newline = f'     --host {wherepsana} $(pwd)/monitor_wrapper.sh\n'
                    logging.info(f'Changing line {ind} to {newline}')
                    lines[ind] = newline

        with open(path, 'w') as file:
            file.writelines(lines)


    def fix_yaml(self, yaml: str, mask='', geom=''):
        """
        Fixes the yaml file to have current experiment number

        Parameters:
            yaml (str): monitor.yaml file path.

            mask (str): mask file path.

            geom (str): geom file path.

        Operations:

        """
        import logging
        logging.info(f"Updating yaml file: {yaml}")
        with open(yaml, "r") as file:
            lines = file.readlines()
            for ind, line in enumerate(lines):
                if 'psana_calibration_directory' in lines[ind]:
                    newline = f'  psana_calibration_directory: /sdf/data/lcls/ds/mfx/{self.experiment}/calib\n'
                    logging.info(f'Changing line {ind} to {newline}')
                    lines[ind] = newline
            if mask != '':
                for ind, line in enumerate(lines):
                    if 'bad_pixel_map_filename' in lines[ind]:
                        newline = f'  bad_pixel_map_filename: {mask}\n'
                        logging.info(f'Changing line {ind} to {newline}')
                        lines[ind] = newline

            if geom != '':
                for ind, line in enumerate(lines):
                    if 'geometry_file' in lines[ind]:
                        newline = f'  geometry_file: {geom}\n'
                        logging.info(f'Changing line {ind} to {newline}')
                        lines[ind] = newline

        with open(yaml, 'w') as file:
            file.writelines(lines)


    def check_settings(self):
        """
        Checks OM's file system and sets it up if needed

        Parameters
        ----------

        Operations
        ----------
        """
        import os
        import sys
        import logging
        from shutil import copy2
        logging.info("Checking OM Files")
        if not os.path.exists(self.pwd) or len(os.listdir(self.pwd)) == 0:
            logging.warning(f"No Directory Exists for Experiment: {self.experiment}. Would you like to create it?")
            mkdir = input("(y/n)? ")

            if mkdir.lower() == "y":
                logging.info(f"Creating Directory for Experiment: {self.experiment}.")
                pre_pwd = max(
                    [os.path.join(self.cwd, d) for d in os.listdir(
                        self.cwd) if os.path.isdir(os.path.join(self.cwd, d))], key=os.path.getmtime)

                os.makedirs(self.pwd)
                det_dirs=[f'{self.pwd}/om_workspace', f'{self.pwd}/om_workspace_rayonix', f'{self.pwd}/om_workspace_xes']
                logging.info(f"Creating Directories for Epix10k2M.")
                os.makedirs(det_dirs[0])
                logging.info(f"Creating Directories for Rayonix.")
                os.makedirs(det_dirs[1])
                logging.info(f"Creating Directories for XES.")
                os.makedirs(det_dirs[2])

                pre_det_dirs=[f'{pre_pwd}/om_workspace', f'{pre_pwd}/om_workspace_rayonix', f'{pre_pwd}/om_workspace_xes']

                logging.info(f"Copying Key Files from Previous Experiment: {pre_pwd}")

                for ind, det in enumerate(det_dirs):
                    logging.info(f"Copying Key Files for: {pre_det_dirs[ind]}")
                    shell_list = [os.path.join(pre_det_dirs[ind], file) for file in os.listdir(
                        pre_det_dirs[ind]) if file.endswith(".sh")]
                    if len(shell_list) != 0:
                        for sh in shell_list:
                            copy2(sh, det_dirs[ind])
                    else:
                        logging.error(f'No shell scripts found in: {det}')

                    if os.path.isfile(os.path.join(det, 'run_om.sh')):
                        self.fix_run_om(os.path.join(det, 'run_om.sh'))

                    geom_list = [os.path.join(
                        pre_det_dirs[ind], file) for file in os.listdir(
                            pre_det_dirs[ind]) if file.endswith(".geom")]
                    if len(geom_list) != 0:
                        geom = max(geom_list, key=os.path.getmtime)
                        copy2(geom, det_dirs[ind])
                    else:
                        logging.error(f'No geom found in: {det}')

                    mask_list = [os.path.join(
                        pre_det_dirs[ind], file) for file in os.listdir(
                            pre_det_dirs[ind]) if 'mask' in file]
                    if len(mask_list) != 0:
                        mask = max(mask_list, key=os.path.getmtime)
                        copy2(mask, det_dirs[ind])
                    else:
                        logging.error(f'No mask found in: {det}')

                    yaml_list = [os.path.join(
                        pre_det_dirs[ind], file) for file in os.listdir(
                            pre_det_dirs[ind]) if file.endswith(".yaml")]
                    if len(yaml_list) != 0:
                        yaml = max(yaml_list, key=os.path.getmtime)
                        copy2(yaml, det_dirs[ind])
                        self.fix_yaml(
                            os.path.join(
                                det_dirs[ind], os.path.basename(yaml)), mask=os.path.basename(mask), geom=os.path.basename(geom))
                    else:
                        logging.error(f'No yaml found in: {det}')

                logging.info(f"Copying om_reset_plots.py")
                copy2(os.path.join(pre_pwd, 'om_reset_plots.py'), self.pwd)
            else:
                logging.info(f"You've decided not to continue. Program will exit")
                sys.exit()


    def gui(
        self,
        user: str,
        facility: str = "S3DF",
        debug: bool = False,
    ):
        """Launch OM GUI.

        Parameters:

            user (str): username for computer account at facility.

            facility (str): Default: "S3DF". Options: "S3DF, NERSC".

            debug (bool): Default: False.
        """
        import logging
        import os
        import subprocess

        proc = [
            f"ssh -YAC {user}@s3dflogin "
            f"/sdf/group/lcls/ds/tools/mfx/scripts/unknown "
            f"{user} {self.experiment} {facility} 1 {str(debug)}"
            ]

        logging.info(proc)

        if debug:
            os.system(proc[0])
        else:
            subprocess.Popen(
                proc, shell=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)

    
    def kill(self):
        import logging
        import subprocess

        proc = [
            "ssh -YAC mfx-monitor "
            "kill -9  `ps ux | grep monitor_wrapper.sh | grep -v grep | awk '{ print $2 }'`"
            ]

        logging.info(proc)

        subprocess.Popen(
            proc, shell=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)


    def om(self, det=None, start='all', calibdir=None, debug: bool = False):
        """
        Launches OM

        Parameters
        ----------
        det: str, optional
            Detector name. Example 'Rayonix', 'Epix10k2M', or 'XES' for spectroscopy

        start: str, optional
            Which process to start. All by default

        calibdir: str, optional
            path to calib directory

        debug (bool): Default: False.

        Operations
        ----------

        """
        import logging
        import subprocess
        import os
        self.check_settings()
        monitor_wrapper = ''
        monitor_wrapper = subprocess.check_output(
            "ssh -YAC mfx-monitor ps aux | grep monitor_wrapper.sh | grep -v grep | awk '{ print $2 }'",shell=True).decode()

        det_dir = None

        if str(det).lower() == 'rayonix':
                det_dir = f'{self.pwd}/om_workspace_rayonix'
        elif str(det).lower() == 'epix10k2m':
                det_dir = f'{self.pwd}/om_workspace'
        elif str(det).lower() == 'xes':
                det_dir = f'{self.pwd}/om_workspace_xes'
        else:
            logging.error(
                "No proper detector seclected. Please use either"
                "'Rayonix', 'Epix10k2M', or 'XES' for spectroscopy")

        if monitor_wrapper == '':
            proc = [
                f'{det_dir}/run_gui.sh',
                f'{det_dir}/run_frame_viewer.sh',
                f'ssh -YAC mfx-monitor "cd {det_dir}; ./run_om.sh"'
                ]
        else:
            proc = [
                f'{det_dir}/run_gui.sh',
                f'{det_dir}/run_frame_viewer.sh'
                ]

        logging.info(proc)

        if debug:
            logging.info(proc[0])
            subprocess.Popen(
                proc[0], shell=True, 
                    stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
            logging.info(proc[1])
            subprocess.Popen(
                proc[1], shell=True, 
                    stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
            logging.info(proc[-1])
            os.system(proc[-1])
        else:
            for cmd in proc:
                subprocess.Popen(
                    cmd, shell=True, 
                    stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)

    def reset(self):
        """
        Resets OM

        Parameters
        ----------

        Operations
        ----------

        """
        import logging
        import subprocess

        proc = [
            f'ssh -YAC mfx-monitor "source /reg/g/pcds/engineering_tools/mfx/scripts/pcds_conda; '
            f'conda deactivate; source /cds/sw/ds/ana/conda1/manage/bin/psconda.sh; '
            f'python {self.pwd}/om_reset_plots.py daq-mfx-mon10"',
            ]

        logging.info(proc)
        
        subprocess.Popen(
            proc, shell=True, 
            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
