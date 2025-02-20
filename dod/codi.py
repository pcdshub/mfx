class CoDI: 
    def __init__(self, reload_presets = False):
        """
        Class definition of the DoD codi injector 
        Parameters
        reload_presets : Boolean
            force resetting the presets (overwriting existing hutch presets)
        ----------
        """
        
        from pcdsdevices.device import ObjectComponent as OCpt
        from pcdsdevices.epics_motor import SmarAct, Motor
        import time

        # CoDI motor PVs loading 
        self.CoDI_rot_left = SmarAct('MFX:MCS2:01:m3', name='CoDI_rot_left')
        self.CoDI_rot_right = SmarAct('MFX:MCS2:01:m1', name='CoDI_rot_right')
        self.CoDI_rot_base = SmarAct('MFX:MCS2:01:m2', name='CoDI_rot_base')
        self.CoDI_trans_z = SmarAct('MFX:MCS2:01:m4', name='CoDI_trans_z')

        #Predefined positions CoDI
        self.CoDI_pos_predefined = dict()

        if reload_presets == True: 
            # self.CoDI_pos_predefined['aspiration'] = (0.0,0.0,0.0,0.0) 
            # self.CoDI_pos_predefined['angled_vert'] = (0.0,45.0,45.0,0.0)
            # self.CoDI_pos_predefined['angled_hor'] = (90.0,45.0,45.0,0.0)

            self.set_CoDI_predefined('aspiration',0.0,0.0,0.0,0.0)
            self.set_CoDI_predefined('angled_vert',0.0,45.0,45.0,0.0)
            self.set_CoDI_predefined('angled_hor',90.0,45.0,45.0,0.0)
        else: 
            all_presets = vars(self.CoDI_rot_left.presets.positions) #Needs to be fixed
            for preset, preset_value in all_presets.items(): 
                try: 
                    # get preset position
                    exec_base = "preset_rot_base = self.CoDI_rot_base.presets.positions." + preset + '.pos'
                    exec_rot_left = "preset_rot_left = self.CoDI_rot_left.presets.positions." + preset + '.pos'
                    exec_rot_right = "preset_rot_right = self.CoDI_rot_right.presets.positions." + preset + '.pos'
                    exec_trans_z = "preset_trans_z = self.CoDI_trans_z.presets.positions." + preset + '.pos'
                    exec(exec_base)
                    exec(exec_rot_left)
                    exec(exec_rot_right)
                    exec(exec_trans_z)

                    # Save to local database
                    print(preset)
                    self.set_CoDI_predefined(preset, preset_rot_base, preset_rot_left, preset_rot_right, preset_trans_z)
                except: 
                    print('skipping preset '+ preset + ', as it is not defined in all motors')    

                
        # # create config parser handler
        # json_handler = JsonFileHandler(supported_json)
        # # load configs and launch web server
        # json_handler.reload_endpoints()

        # Flag that can be used later on for safety aborts during task execution
        self.safety_abort = False


    def get_CoDI_predefined(self):
        
        
        return self.CoDI_pos_predefined
    

    def update_CoDI_predefined(self): 
        'reloads all the hutch python presets for motors and overwrites local position preset dict'
        
        #Predefined positions CoDI
        self.CoDI_pos_predefined = dict()

        all_presets = vars(self.CoDI_rot_left.presets.positions) #Needs to be fixed
        for preset in all_presets.keys(): 
            # try: 
            # get preset position
            self.exec_base = "preset_rot_base = self.CoDI_rot_base.presets.positions." + preset + '.pos'
            self.exec_rot_left = "preset_rot_left = self.CoDI_rot_left.presets.positions." + preset + '.pos'
            self.exec_rot_right = "preset_rot_right = self.CoDI_rot_right.presets.positions." + preset + '.pos'
            self.exec_trans_z = "preset_trans_z = self.CoDI_trans_z.presets.positions." + preset + '.pos'
            print(self.exec_base)
            exec(self.exec_base)

            exec(self.exec_rot_left)
            print(self.exec_rot_left)

            exec(self.exec_rot_right)
            print(self.exec_rot_left)
            
            exec(self.exec_trans_z)
            print(self.exec_trans_z)
            print(preset_trans_z)

            # Save to local database
            print(preset)
            self.set_CoDI_predefined(preset, preset_rot_base, preset_rot_left, preset_rot_right, preset_trans_z)
            # except: 
            #     print('skipping preset '+ preset + ', as it is not defined in all motors')    

    def set_CoDI_predefined(self, name, base, left, right, z):
        """
        defines or updates a predefined combination for CoDI
        
        Parameters
        name : str
            name of the pre-definition
        base : float
            rotation of base
        left : float
            rotation of left injector
        right : float
            rotation of right injector
        z : float
            translation of right injector
        ----------
    
        """
        self.CoDI_pos_predefined.update({name: (base,left, right, z)})
        
        # Presets using MFX presets functionalities 
        self.CoDI_rot_left.presets.add_hutch(name, value = left)
        self.CoDI_rot_right.presets.add_hutch(name, value = right)
        self.CoDI_rot_base.presets.add_hutch(name, value = base)
        self.CoDI_trans_z.presets.add_hutch(name, value = z)

    

    def get_CoDI_pos(self, precision_digits = 1): 
        """
        gets the colliding droplet injector motor positions as tuple
        
        Parameters
        precision_digits : int
            precision with which the pre-defined positions are checked 
        
        ----------
        Return : (tuple, 5)
            motor positions of the CoDI motors. (name of preset, rot_base, rot_left, rot_right, trans_z)
        """
        pos_rot_base  = self.CoDI_rot_base.wm()
        pos_rot_left  = self.CoDI_rot_left.wm()
        pos_rot_right = self.CoDI_rot_right.wm()
        pos_trans_z   = self.CoDI_trans_z.wm()
        
        # # for testing purposes
        # pos_rot_base  = 0
        # pos_rot_left  = 45
        # pos_rot_right = 45
        # pos_trans_z   = 0
        
        pos_tuple = (pos_rot_base,pos_rot_left, pos_rot_right,pos_trans_z)
        
        pos_rounded = tuple([float(round(each_pos,1)) for each_pos in pos_tuple])
        
        # Test if this is one of the preset positions: 
        pos_name = 'undefined'
        for preset in self.CoDI_pos_predefined:
            preset_rounded = tuple([float(round(each_pos,1)) for each_pos in self.CoDI_pos_predefined[preset]])
            if preset_rounded[:-1] == pos_rounded[:-1]: 
                pos_name = preset
                
        return pos_name, pos_rot_base, pos_rot_left, pos_rot_right, pos_trans_z
    
        
    def set_CoDI_pos(self, pos_name, wait = True): 
        """
        Moves the colliding droplet injector into a pre-defined position. 
        
        Parameters
        pos_name : string
            name of the pre-defined position
        wait : boolean
            if the robot waits before continuing further steps
        
        ----------
        Return : 
    
        """
        # pos_rot_base  = CoDI_base.wm()
        # pos_rot_left  = CoDI_left.wm()
        # pos_rot_right = CoDI_right.wm()
        # pos_trans_z   = CoDI_z.wm()
        import time

        # get target positions
        pos_rot_base, pos_rot_left, pos_rot_right, pos_trans_z = self.CoDI_pos_predefined[pos_name]
        
        # Move motors
        
        # Old wayy 
        # self.CoDI_rot_base.mv(pos_rot_base, wait=False)
        # self.CoDI_rot_left.mv(pos_rot_left,  wait=False)
        # self.CoDI_rot_right.mv(pos_rot_right, wait=False)
        # self.CoDI_trans_z.mv(pos_trans_z, wait=False)

        # Move using hutch python presets
        exec_base = "self.CoDI_rot_base.mv_" + pos_name + '()'
        exec(exec_base)
        exec_left = "self.CoDI_rot_left.mv_" + pos_name + '()'
        exec(exec_left)
        exec_right = "self.CoDI_rot_right.mv_" + pos_name + '()'
        exec(exec_right)
        exec_z = "self.CoDI_trans_z.mv_" + pos_name + '()'
        exec(exec_z)

        if wait == True: 
            test_name, test_pos_rot_base, test_pos_rot_left, test_pos_rot_right, test_pos_trans_z = self.get_CoDI_pos()
            i = 0
            while pos_name != test_name: 
                time.sleep(1)
                print('\r waiting for motion to end: %i s' %i, end="\r")
                i = i+1
                test_name, test_pos_rot_base, test_pos_rot_left, test_pos_rot_right, test_pos_trans_z = self.get_CoDI_pos()
            print('Motion ended')
        
    
    def set_CoDI_current_pos(self, name):
        """
        defines or updates the current motor combination for CoDI
        
        Parameters
        name : str
            name of the pre-definition
        ----------
    
        """
        pos_name, pos_rot_base, pos_rot_left, pos_rot_right, pos_trans_z = self.get_CoDI_pos()
        self.set_CoDI_predefined(name, pos_rot_base, pos_rot_left, pos_rot_right, pos_trans_z)
    

    def set_CoDI_current_z(self, verbose = True):
        """
        sets the current z position to all preloaded positions
        Useful for global change of z after aligning
        
        Parameters
        verbose : Boolean
            prints the new positions as a sanity check if True
        ----------
    
        """
        # get current z position:
        pos_trans_z_new  = self.CoDI_trans_z.wm()

        # get all keys from the positions
        position_keys = self.CoDI_pos_predefined.keys
        
        #go through all positions and change the z-value to the current z value
        for key in position_keys: 
            pos_name, pos_rot_base, pos_rot_left, pos_rot_right, pos_trans_z = self.CoDI_pos_predefined[key]
            self.set_CoDI_predefined(pos_name,pos_rot_base, pos_rot_left, pos_rot_right, pos_trans_z_new)
        
        #Print the new predefined positions as a sanity check
        if verbose == True:
            print(self.get_CoDI_predefined)
        

    def remove_CoDI_pos(self, name):
        """
        removes the defined motor combination for CoDI from local database
        
        Parameters
        name : str
            name of the pre-definition to be deleted
        ----------
    
        """
        del self.CoDI_pos_predefined[name]


    def move_z_rel(self, z_rel):
        """
        moves the z position relative to the current position 
        
        Parameters
        z_rel : float
            relative motion in mm
        ----------
    
        """
        # get current z position:
        pos_trans_z  = self.CoDI_trans_z.wm()

        # set new position
        self.CoDI_trans_z.umvr(z_rel)

    def move_rot_left_rel(self, rot_rel):
        """
        moves the rotation of the left nozzle relative to the current position in degree
        
        Parameters
        rot_rel : float
            relative motion in degree
        ----------
    
        """
        # get current position:
        pos_rot_left  = self.CoDI_rot_left.wm()

        # set new position: 
        self.CoDI_rot_left.umvr(rot_rel)


    def move_rot_right_rel(self, rot_rel):
        """
        moves the rotation of the right nozzle relative to the current position in degree
        
        Parameters
        rot_rel : float
            relative motion in degree
        ----------
    
        """
        # get current position:
        pos_rot_right  = self.CoDI_rot_right.wm()

        # set new position: 
        self.CoDI_rot_right.umvr(rot_rel)


    def move_rot_base_rel(self, rot_rel):
        """
        moves the rotation of the base relative to the current position in degree
        
        Parameters
        rot_rel : float
            relative motion in degree
        ----------
    
        """
        # get current position:
        pos_rot_base  = self.CoDI_rot_base.wm()

        # set new position: 
        self.CoDI_rot_base.umvr(rot_rel)
        

    def move_z_abs(self, z_abs):
        """
        moves the z position to the absolute position in mm
        
        Parameters
        z_abs : float
            absolute motion in mm
        ----------
    
        """
        # move z position:
        self.CoDI_trans_z.umv(z_abs)


    def move_rot_left_abs(self, rot_abs):
            """
            moves the rotation of the left nozzle to the absolute position in degree
            
            Parameters
            rot_abs : float
                abs motion in degree
            ----------
        
            """

            # set new position: 
            self.CoDI_rot_left.umv(rot_abs)


    def move_rot_right_abs(self, rot_abs):
            """
            moves the rotation of the right nozzle to the absolute position in degree
            
            Parameters
            rot_abs : float
                abs motion in degree
            ----------
        
            """

            # set new position: 
            self.CoDI_rot_right.umv(rot_abs)


    def move_rot_base_abs(self, rot_abs):
            """
            moves the rotation of the base to the absolute position in degree
            
            Parameters
            rot_abs : float
                abs motion in degree
            ----------
        
            """

            # set new position: 
            self.CoDI_rot_base.umv(rot_abs)
'''
robot1.get_CoDI_predefined()
robot1.set_CoDI_predefined('test',1,1,1,1)
robot1.get_CoDI_predefined()
robot1.get_CoDI_pos()

robot1.get_CoDI_pos()
robot1.set_CoDI_current_pos('test2')
'''