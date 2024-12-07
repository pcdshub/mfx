class OM:
    def __init__(self):
        from mfx.macros import get_exp
        self.experiment = str(get_exp())


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


    def om(self, det=None, start='all', calibdir=None):
        """
        Launches OM

        Parameters
        ----------
        det: str, optional
            Detector name. Example 'Rayonix', 'Epix10k2M', or 'XES' for spectroscopy

        calibdir: str, optional
            path to calib directory

        Operations
        ----------

        """
        import logging
        import subprocess

        pwd = f'/cds/home/opr/mfxopr/OM-GUI/{self.experiment}'
        monitor_wrapper = None
        monitor_wrapper = subprocess.check_output(
            "ssh -YAC mfx-monitor ps aux | grep monitor_wrapper.sh | grep -v grep | awk '{ print $2 }'",shell=True).decode()

        det_dir = None

        if str(det).lower() == 'rayonix':
                det_dir = f'{pwd}/om_workspace_rayonix'
        elif str(det).lower() == 'epix10k2m':
                det_dir = f'{pwd}/om_workspace'
        elif str(det).lower() == 'xes':
                det_dir = f'{pwd}/om_workspace_xes'
        else:
            logging.error(
                "No proper detector seclected. Please use either"
                "'Rayonix', 'Epix10k2M', or 'XES' for spectroscopy")

        if monitor_wrapper is None:
            proc = [
                f'{det_dir}/run_om.sh',
                f'{det_dir}/run_gui.sh',
                f'{det_dir}/run_frame_viewer.sh'
                ]
        else:
            proc = [
                f'{det_dir}/run_gui.sh',
                f'{det_dir}/run_frame_viewer.sh'
                ]

        logging.info(proc)
        
        subprocess.Popen(
            proc, shell=True, 
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

        pwd = f'/cds/home/opr/mfxopr/OM-GUI/{self.experiment}'
        proc = [
            f'source /cds/sw/ds/ana/conda1/manage/bin/psconda.sh | python {pwd}/om_reset_plots.py daq-mfx-mon10',
            ]

        logging.info(proc)
        
        subprocess.Popen(
            proc, shell=True, 
            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
