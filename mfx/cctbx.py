class cctbx:
    def __init__(self):
        from mfx.macros import get_exp
        self.experiment = str(get_exp())


    def geom_refine(
        self,
        user: str,
        group: str,
        level: int = None,
        facility: str = "NERSC",
        exp: str = ''):
        """Launch CCTBX XFEL GUI.

        Parameters:

            user (str): username for computer account at facility.

            group (str): the trial and rungroup number in the format 000_rg005.
            Default is newest trial_rungroup

            level (int): the level of geometry refinement.
            0 = whole detector and 1 = individual detector panels.
            Default is to systematically do both.

            facility (str): Default: "NERSC". Options: "S3DF, NERSC".

            exp (str): experiment number in format 'mfxp1047723'.
                       If none selected default is the current experiment.

            debug (bool): Default: False.
        """
        import logging
        import os

        if exp != '':
            experiment = exp
        else:
            experiment = self.experiment

        proc = [
            f"ssh -Yt {user}@s3dflogin "
            f"python /sdf/group/lcls/ds/tools/mfx/scripts/cctbx/geom_refine.py "
            f"-e {experiment} -f {facility} -g {group} -l {level} "
            ]

        logging.info(proc)

        if facility == 'NERSC':
            logging.warning(f"Have you renewed your token with sshproxy today?")
            token = input("(y/n)? ")

            if token.lower() == "n":
                self.sshproxy(user)

        os.system(proc[0])


    def average(
        self,
        user: str,
        run: int,
        facility: str = "NERSC",
        exp: str = '',
        debug: bool = False):
        """Launch CCTBX XFEL GUI.

        Parameters:

            user (str): username for computer account at facility.

            run (int): Enter -r for the run number

            facility (str): Default: "NERSC". Options: "S3DF, NERSC".

            exp (str): experiment number in format 'mfxp1047723'.
                       If none selected default is the current experiment.

            debug (bool): Default: False.
        """
        import logging
        import os
        import subprocess

        if exp != '':
            experiment = exp
        else:
            experiment = self.experiment

        proc = [
            f"ssh -Yt {user}@s3dflogin "
            f"python /sdf/group/lcls/ds/tools/mfx/scripts/cctbx/average.py "
            f"-e {experiment} -f {facility} -d {str(debug)} -r {run}"
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


    def image_viewer(
        self,
        user: str,
        run: int,
        image_type: str,
        group: str = None,
        facility: str = "NERSC",
        exp: str = '',
        debug: bool = False):
        """Launch CCTBX XFEL GUI.

        Parameters:

            user (str): username for computer account at facility.

            run (int): Enter -r for the run number

            image_type (str): Enter -t for type of image view

            group (str): the trial and rungroup number in the format 000_rg005.
            Default is newest trial_rungroup

            facility (str): Default: "NERSC". Options: "S3DF, NERSC".

            exp (str): experiment number in format 'mfxp1047723'.
                       If none selected default is the current experiment.

            debug (bool): Default: False.
        """
        import logging
        import os
        import subprocess

        if exp != '':
            experiment = exp
        else:
            experiment = self.experiment

        proc = [
            f"ssh -Yt {user}@s3dflogin "
            f"python /sdf/group/lcls/ds/tools/mfx/scripts/cctbx/image_viewer.py "
            f"-e {experiment} -f {facility} -d {str(debug)} -t {image_type} -r {run} -g {group}"
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
        facility: str = "NERSC",
        exp: str  = '',
        debug: bool = False,
    ):
        """Launch CCTBX XFEL GUI.

        Parameters:

            user (str): username for computer account at facility.

            facility (str): Default: "NERSC". Options: "S3DF, NERSC".

            exp (str): experiment number in format 'mfxp1047723'.
                       If none selected default is the current experiment.

            debug (bool): Default: False.
        """
        import logging
        import os
        import subprocess

        if exp != '':
            experiment = exp
        else:
            experiment = self.experiment

        proc = [
            f"ssh -Yt {user}@s3dflogin "
            f"/sdf/group/lcls/ds/tools/mfx/scripts/cctbx/cctbx.sh "
            f"{user} {experiment} {facility} 1 {str(debug)} "
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
