class cctbx:
    def xfel_gui(self, user):
        import logging
        import subprocess
        from mfx.macros import get_exp
        self.experiment = str(get_exp())
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