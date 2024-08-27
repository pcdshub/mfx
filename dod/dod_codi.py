class codi: 
    def __init__(self):
        """
        Class definition of the DoD codi injector 
        Parameters
        ----------
        """
        
        from pcdsdevices.device import ObjectComponent as OCpt
        from pcdsdevices.epics_motor import SmarAct


        #Predefined positions CoDI
        self.CoDI_pos_predefined = dict()
        self.CoDI_pos_predefined['aspiration'] = (0.0,0.0,0.0,0.0) 
        self.CoDI_pos_predefined['angled_vert'] = (0.0,45.0,45.0,0.0)
        self.CoDI_pos_predefined['angled_hor'] = (90.0,45.0,45.0,0.0)
        
        # CoDI motor PVs loading 
        self.CoDI_rot_left = SmarAct('MFX:MCS2:01:m3', name='CoDI_rot_left')
        self.CoDI_rot_right = SmarAct('MFX:MCS2:01:m1', name='CoDI_rot_right')
        self.CoDI_rot_base = SmarAct('MFX:MCS2:01:m2', name='CoDI_rot_base')
        self.CoDI_trans_z = SmarAct('MFX:MCS2:01:m4', name='CoDI_trans_z')
        
        # # create config parser handler
        # json_handler = JsonFileHandler(supported_json)
        # # load configs and launch web server
        # json_handler.reload_endpoints()

        # Flag that can be used later on for safety aborts during task execution
        self.safety_abort = False


    def get_CoDI_predefined(self):
        return self.CoDI_pos_predefined
    

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
            if self.CoDI_pos_predefined[preset][:-1] == pos_rounded[:-1]: 
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
        
        # get target positions
        pos_rot_base, pos_rot_left, pos_rot_right, pos_trans_z = self.CoDI_pos_predefined[pos_name]
        
        # Move motors

        self.CoDI_rot_base.umv(pos_rot_base)
        self.CoDI_rot_left.umv(pos_rot_left)
        self.CoDI_rot_right.umv(pos_rot_right)
        self.CoDI_trans_z.umv(pos_trans_z)
        
        if wait == True: 
            test_name, test_pos_rot_base, test_pos_rot_left, test_pos_rot_right, test_pos_trans_z = self.get_CoDI_pos()
            i = 0
            while pos_name != test_name: 
                time.sleep(1)
                print('\r waiting for motion to end: %i s' %i, end="\r")
                i = i+1
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
    

    def remove_CoDI_pos(self, name):
        """
        removes the defined motor combination for CoDI
        
        Parameters
        name : str
            name of the pre-definition to be deleted
        ----------
    
        """
        del self.CoDI_pos_predefined[name]

'''
robot1.get_CoDI_predefined()
robot1.set_CoDI_predefined('test',1,1,1,1)
robot1.get_CoDI_predefined()
robot1.get_CoDI_pos()

robot1.get_CoDI_pos()
robot1.set_CoDI_current_pos('test2')
'''