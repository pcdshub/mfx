class cctbx:
    def __init__(self):
        from mfx.macros import get_exp
        self.experiment = str(get_exp())


    def xfel_gui(self, user):
        import logging
        import subprocess
        self.settings = f"/sdf/home/{user[0]}/{user}/.cctbx.xfel/settings.phil"
        self.cctbx_dir = f"/sdf/home/{user[0]}/{user}"

        proc = [
            f"ssh -YAC {user}@s3dflogin "
            f"/sdf/home/d/djr/scripts/cctbx_step1.sh {user} {self.experiment}"
            ]

        logging.info(proc)
        
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
            f'/sdf/home/d/djr/scripts/cctbx_notch_check.sh "{self.runlist}"'
            ]

        logging.info(proc)
        
        subprocess.Popen(
            proc, shell=True, 
            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
