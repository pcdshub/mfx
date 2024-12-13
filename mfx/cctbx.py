class cctbx:
    def __init__(self):
        from mfx.macros import get_exp
        self.experiment = str(get_exp())


    def image_viewer(
        self,
        user: str,
        run: int,
        image_type: str,
        group: str,
        facility: str = "S3DF",
        debug: bool = False):
        """Launch CCTBX XFEL GUI.

        Parameters:

            user (str): username for computer account at facility.

            facility (str): Default: "S3DF". Options: "S3DF, NERSC".

            debug (bool): Default: False.

            image_type (str): Enter -t for type of image view

            run (int): Enter -r for the run number

            image_type (str): the trial and rungroup number in the format 000_rg005.
            Default is newest trial_rungroup

        """
        import logging
        import os
        import subprocess

        proc = [
            f"ssh -Yt {user}@s3dflogin "
            f"python /sdf/group/lcls/ds/tools/mfx/scripts/cctbx/image_viewer.py "
            f"-e {self.experiment} -f {facility} -d {str(debug)} -t {image_type} -r {run} -g {group}"
            ]

        logging.info(proc)

        if facility == 'NERSC':
            logging.warning(f"Have you renewed your token with sshproxy today?")
            token = input("(y/n)? ")

            if token.lower() == "n":
                self.sshproxy(user)

        if debug or 'refinement' in image_type:
            os.system(proc[0])
        else:
            subprocess.Popen(
                proc, shell=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)


    def sshproxy(
        self,
        user: str,
    ):

        """Launch sshproxy check for getting NERSC token if needed

        Parameters:

            user (str): username for computer account at facility.

            debug (bool): Default: False.
        """
        import logging
        import os
        import subprocess
        logging.info(f"Creating new sshproxy token for {user}.")
        proc = [
            f"ssh -Yt {user}@s3dflogin "
            f"/sdf/group/lcls/ds/tools/mfx/scripts/cctbx/sshproxy.sh "
            f"-c cctbx -u {user}"
            ]

        logging.info(proc)

        os.system(proc[0])


    def xfel_gui(
        self,
        user: str,
        facility: str = "S3DF",
        debug: bool = False,
    ):
        """Launch CCTBX XFEL GUI.

        Parameters:

            user (str): username for computer account at facility.

            facility (str): Default: "S3DF". Options: "S3DF, NERSC".

            debug (bool): Default: False.
        """
        import logging
        import os
        import subprocess

        proc = [
            f"ssh -Yt {user}@s3dflogin "
            f"/sdf/group/lcls/ds/tools/mfx/scripts/cctbx/cctbx.sh "
            f"{user} {self.experiment} {facility} 1 {str(debug)} "
            ]

        logging.info(proc)

        if facility == 'NERSC':
            logging.warning(f"Have you renewed your token with sshproxy today?")
            token = input("(y/n)? ")

            if token.lower() == "n":
                self.sshproxy(user)

        if debug:
            os.system(proc[0])
        else:
            subprocess.Popen(
                proc, shell=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)

    
    def notch_check(self, user, runs=[]):
        import logging
        import subprocess
        import sys
        if len(runs) > 0:
            run_list = []
            for run in runs:
                run_list.append(f'{experiment}:{run}')
            logging.info(f'Selected runs: {run_list}')
            runlist = ' '
            runlist = runlist.join(run_list)
            logging.info(f'Selected runs: {runlist}')
        else:
            logging.warning(f'No selected runs. Program will exit.')
            sys.exit()

        proc = [
            f'ssh -YAC {user}@s3dflogin '
            f'/sdf/group/lcls/ds/tools/mfx/scripts/cctbx/cctbx_notch_check.sh "{self.runlist}"'
            ]

        logging.info(proc)
        
        subprocess.Popen(
            proc, shell=True, 
            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
