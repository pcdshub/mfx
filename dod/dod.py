class dod: 
    def __init__(self, modules = 'None'):
        """
        Class definition of the DoD robot
        Parameters
        ----------
        modules : string
            Defines the optional modules of the robot. 
            Options: 'None', 'codi', 
        ip = "172.21.72.187" , port = 9999, supported_json = "supported.json"            
        """
        from dod.DropsDriver import myClient
        from dod.JsonFileHandler import JsonFileHandler
        from dod.ServerResponse import ServerResponse

        import time

        # Create object 
        # pytest encourages this pattern, apologies.
        ip = "172.21.72.187" #"172.21.148.101"
        port = 9999
        supported_json = '/cds/group/pcds/pyps/apps/hutch-python/mfx/dod/supported.json'

        # User input parameters: 
        # Safety parameters in hutch coordinate system. 
        # Note: hutch (x,y,z) = robot (x,-z, y) 
        # 
        self.y_min     = 10000 # minimum value in y.
        self.y_safety  = 50000 # value in y, above which the robot can only be in vertical configuration
        self.y_max     = 50000 # maximum value in y
        
        #Initialize safety regions for horizontal and vertical rotation: 
        self.forbidden_regions_horizontal = []
        self.forbidden_regions_vertical = []
        #minimum region: 
        self.set_forbidden_region(0, 300000, 0, self.y_min,rotation_state='both')
        #maximum region: 
        self.set_forbidden_region(0, 300000, self.y_max, 500000,rotation_state='both')
        #region where horizontal rotation is forbidden: 
        self.set_forbidden_region(0, 300000,  self.y_safety, self.y_max,rotation_state='horizontal')
        
        # Initializing the robot client that is used for communication
        self.client = myClient(ip=ip, port=port, supported_json=supported_json, reload=False)
        
        # create config parser handler
        json_handler = JsonFileHandler(supported_json)
        # load configs and launch web server
        json_handler.reload_endpoints()

        # Flag that can be used later on for safety aborts during task execution
        self.safety_abort = False
        if modules == 'codi': 
            from dod.codi import codi
            self.codi = codi()
        
        # Timing section
        from pcdsdevices.evr import Trigger
        self.delay = None

        # Trigger objects
        self.trigger_Xray = Trigger('MFX:LAS:EVR:01:TRIG7', name='trigger_X-ray_simulator')
        self.trigger_nozzle_1 = Trigger('MFX:LAS:EVR:01:TRIG2', name='trigger_nozzle_1')
        self.trigger_nozzle_2 = Trigger('MFX:LAS:EVR:01:TRIG3', name='trigger_nozzle_2')
        self.trigger_LED = Trigger('MFX:LAS:EVR:01:TRIG1', name='trigger_LED_array')

        # Timing parameter
        self.timing_Xray = self.trigger_Xray.ns_delay.get()
        self.timing_nozzle_1 = self.trigger_nozzle_1.ns_delay.get()
        self.timing_nozzle_2 = self.trigger_nozzle_2.ns_delay.get()
        self.timing_LED = self.trigger_LED.ns_delay.get()
        self.timing_delay_sciPulse = 60600
        self.timing_delay_LED = 1000 #delay of LED relative to X-ray timing
        self.timing_delay_reaction = 0
        self.timing_delay_nozzle_1 = self.timing_Xray - self.timing_nozzle_1 - self.timing_delay_sciPulse - self.timing_delay_reaction
        self.timing_delay_nozzle_2 = self.timing_Xray - self.timing_nozzle_2 - self.timing_delay_sciPulse - self.timing_delay_reaction


    def stop_task(self, verbose = True):
        """
        Stop task while running
        ** ISSUES **
        -  When stop task  is called, the Robot stays in "BUSY" Status.
        Parameters
        ----------
        verbose : boolean
            Defines whether the function returns the full output, or only the results
        Returns: 
        r : 
            status readback when aborted
        """
        r = self.client.connect("Test")
        self.safety_abort = False
        r = self.client.stop_task()
        r = self.client.disconnect()
        if verbose == True: 
            return r


    def clear_abort(self, verbose = True):
        """
        clear abort flag
        Parameters
        verbose : boolean
           Defines whether the function returns the full output, or only the results
        ----------
        Returns: 
        r : 
            status readback after error cleared
        '''
        """
        r = self.client.connect("Test")
        r = self.client.get_status()
        self.safety_abort = False
        rr = self.client.disconnect()
        
        if verbose == True: 
            return r
    
    
    # def clear_popup_window(self, verbose = True):
    #     """
    #     clears a popup window that might pop up on the robot gui
    #     Parameters
    #     verbose : boolean
    #        Defines whether the function returns the full output, or only the results
    #     ----------
    #     Returns: 
    #     r : 
    #         status readback after error cleared
    #     '''
    #     """
    #     r = self.client.connect("Test")
    #     r = self.client.get_status()

    #     self.client.close_dialog(reference, selection)

    #     if verbose == True: 
    #         return r


    def get_status(self, verbose = False):
        """
        returns the robot state
        
        Parameters
        verbose : boolean
           Defines whether the function returns the full output, or only the results
        ----------
        Returns: 
        r : dict
            different states of the robot
        """
        rr = self.client.connect("Test")
        r = self.client.get_status()
        # expected_keys = [
        #     'Position',
        #     'RunningTask',
        #     'Dialog',
        #     'LastProbe',
        #     'Humidity',
        #     'Temperature',
        #     'BathTemp',
        #     ]
        rr = self.client.disconnect()
        if verbose == True: 
            return r
        else: 
            return r.RESULTS
    

    def busy_wait(timeout: int):
        '''
                Busy wait untill timeout value is reached,
                timeout : sec
                returns true if timeout occured
        '''
        start = time.time()
        r = self.client.get_status()
        delta = 0
        
        while(r.STATUS['Status'] == "Busy"):
            if delta > timeout:
                return True
        
            time.sleep(0.1) #Wait a ms to stop spamming robot
            r = self.client.get_status()
            delta = time.time() - start    
        return False
    

    # def __del__(self):
    #     # close network connection
    #     self.client.conn.close()


    def get_task_details(self, task_name, verbose = False):
        """
            This gets the details of a task from the robot to see the scripted routines
            Parameters
            task_name : string
                Name of the task that we want to get
            verbose : boolean
                Defines whether the function returns the full output, or only the results
            ----------
            Returns: 
            r : 
                returns the robot tasks
        """
        rr = self.client.connect("Test")
        r = self.client.get_task_details(task_name)
        rr = self.client.disconnect()
        if verbose == True: 
            return r
        else: 
            return r.RESULTS


    def get_task_names(self, verbose = False):
        """
            This gets the names of available tasks from the robot
            Parameters
            task_name : string
                Name of the task that we want to get
            verbose : boolean
                Defines whether the function returns the full output, or only the results
            ----------
            Returns: 
            r : dict
                returns the robot tasks
        """
        # Check if reponse is not an empty array or any errors occured
        rr = self.client.connect("Test")
        r = self.client.get_task_names()
        rr = self.client.disconnect()
        if verbose == True: 
            return r
        else: 
            return r.RESULTS
    

    def get_current_position(self, verbose = False):
        '''
        Returns current robot position
        name and properties of the last selected position, together with the real current position coordinates
        Parameters
        
        verbose : boolean
                Defines whether the function returns the full output, or only the results
            ----------
        Returns: 
        r : 
            returns the current position.         
        # expected_keys = [
        #         'CurrentPosition',
        #         'Position',
        #         'PositionReal',
        #         ]
        '''
        rr = self.client.connect("Test")
        r = self.client.get_current_positions()
        rr = self.client.disconnect()
        if verbose == True: 
            return r
        else: 
            return r.RESULTS
    

    def get_nozzle_status(self, verbose = False):
        '''
        Returns current nozzle parameters position
        Parameters
        
        verbose : boolean
                Defines whether the function returns the full output, or only the results
        ----------
        Returns: 
        r : 
            returns the current nozzle parameters.         
        #         expected_keys = [
                "Activated Nozzles",
                "Selected Nozzles",
                "ID,Volt,Pulse,Freq,Volume",  # Intreseting? all one key
                "Dispensing",
                ]
        '''
        rr = self.client.connect("Test")
        r = self.client.get_nozzle_status()
        rr = self.client.disconnect()
        if verbose == True: 
            return r
        else: 
            return r.RESULTS


    def set_nozzle_dispensing(self, mode = "Off", verbose = False):
        '''
        Sets the dispensing, either "Free", "Triggered", or "Off"
        Parameters
        mode : string 
            either "free", "triggered", or "off"
        verbose : boolean
                Defines whether the function returns the full output, or only the results
        ----------
        Returns: 
        r : 
        '''
        rr = self.client.connect("Test")
        if mode == 'Free': 
            r = self.client.dispensing('Free')
        elif mode == 'Triggered':
            r = self.client.dispensing('Triggered')
        else: 
            #turns active nozzles off. Safer if all nozzles would be turned off
            r = self.client.dispensing('Off')
            for i in [1,2,3,4]: 
                r = self.client.select_nozzle(i)
                r = self.client.dispensing('Off')

        rr = self.client.disconnect()
        if verbose == True: 
            return r
        else: 
            return r.RESULTS
        

    def do_move(self, position, safety_test = False, verbose = False):
        '''
            Moves robot to new position
            
        Parameters
        position : string
            Position name to which the robot is supposed to move
        safety_test : Boolean
            question whether a safety test is to be performed or not
            True: Test will be performed
            False: Not performed
        verbose : boolean
                Defines whether the function returns the full output, or only the results
            ----------
        Returns: 
        r : current position
        '''

        r = self.client.connect("Test")
        r = self.client.get_current_positions()
        current_real_position = r.RESULTS['PositionReal']

        if safety_test == False:  
            r = self.client.move(new_position)
        else: 
            print('safety test of move has yet to be implemented')

        # WAIT FOR MOVEMENT TO BE DONE
        self.busy_wait(15)

        r = self.client.get_current_positions()
        new_real_position = r.RESULTS['PositionReal']
        
        rr = self.client.disconnect()
        if verbose == True: 
            return r
        else: 
            return r.RESULTS


    def move_x_abs(self, position_x, safety_test = False, verbose = False):
        '''
            Robot coordinate system!!!: 
            Moves robot to new absolute x position. 
            No safety test. 
            
        Parameters
        position : int
            Absolute position in um(?) to which the robot is supposed to move
        safety_test : Boolean
            question whether a safety test is to be performed or not
            True: Test will be performed
            False: Not performed
        verbose : boolean
                Defines whether the function returns the full output, or only the results
            ----------
        Returns: 
        r : current position
        '''

        r = self.client.connect("Test")
        r = self.client.get_current_positions()
        current_real_position = r.RESULTS['PositionReal']
        x_current, y_current, z_current = current_real_position

        if safety_test == False:  
            r = self.client.move_x(position_x)
        else: 
            print('safety test of move has yet to be implemented')
            if self.test_forbidden_region(position_x, y_current): 
                r = self.client.move_x(position_x)
                
            
        # WAIT FOR MOVEMENT TO BE DONE
        self.busy_wait(25)

        # r = self.client.get_current_positions()
        # new_real_position = r.RESULTS['PositionReal']
        
        rr = self.client.disconnect()
        if verbose == True: 
            return r
        else: 
            return r.RESULTS
    
    
    def move_y_abs(self, position_y, safety_test = False, verbose = False):
        '''
            Robot coordinate system!!!: 
            Moves robot to new absolute x position. 
            No safety test. 
            
        Parameters
        position : int
            Absolute position in um(?) to which the robot is supposed to move
        safety_test : Boolean
            question whether a safety test is to be performed or not
            True: Test will be performed
            False: Not performed
        verbose : boolean
                Defines whether the function returns the full output, or only the results
            ----------
        Returns: 
        r : current position
        '''

        r = self.client.connect("Test")
        r = self.client.get_current_positions()
        current_real_position = r.RESULTS['PositionReal']
        x_current, y_current, z_current = current_real_position

        if safety_test == False:  
            r = self.client.move_y(position_y)
        else: 
            print('safety test of move has yet to be implemented')
            if self.test_forbidden_region(x_current, position_y): 
                r = self.client.move_y(position_y)
                
            
        # WAIT FOR MOVEMENT TO BE DONE
        self.busy_wait(25)

        # r = self.client.get_current_positions()
        # new_real_position = r.RESULTS['PositionReal']
        
        rr = self.client.disconnect()
        if verbose == True: 
            return r
        else: 
            return r.RESULTS
        

    def move_z_abs(self, position_z, safety_test = False, verbose = False):
        '''
            Robot coordinate system!!!: 
            Moves robot to new absolute Z position. 
            No safety test. 
            
        Parameters
        position : int
            Absolute position in um(?) to which the robot is supposed to move
        safety_test : Boolean
            question whether a safety test is to be performed or not
            True: Test will be performed
            False: Not performed
        verbose : boolean
                Defines whether the function returns the full output, or only the results
            ----------
        Returns: 
        r : current position
        '''

        r = self.client.connect("Test")
        r = self.client.get_current_positions()
        current_real_position = r.RESULTS['PositionReal']
        x_current, y_current, z_current = current_real_position

        if safety_test == False:  
            r = self.client.move_z(position_z)
        else: 
            print('safety test of move has yet to be implemented')
            if self.test_forbidden_region(x_current, y_current): 
                r = self.client.move_z(position_z)
                
            
        # WAIT FOR MOVEMENT TO BE DONE
        self.busy_wait(25)

        # r = self.client.get_current_positions()
        # new_real_position = r.RESULTS['PositionReal']
        
        rr = self.client.disconnect()
        if verbose == True: 
            return r
        else: 
            return r.RESULTS


    def do_task(self, task_name, safety_check = False, verbose = False):
        '''
        Executes a task of the robot
            
        Parameters
        task_name : string
            task name which robot is supposed to perform
        safety_test : Boolean
            question whether a safety test is to be performed or not
            True: Test will be performed
            False: Not performed
        verbose : boolean
                Defines whether the function returns the full output, or only the results
            ----------
        Returns: 
        r : 
        '''
        import time

        rr = self.client.connect("Test")
        if safety_check == False: 
            r = self.client.execute_task(task_name)
        else: 
            print('safety check needs to be implemented')

        ## Wait for task to be done
        while(r.STATUS['Status'] == "Busy"):
            #Possible if loop is not enterd?
            time.sleep(0.5)
            r = self.client.get_status()
            if self.safety_abort == True: 
                r = self.client.stop_task()
                print('User aborted task execution')
                return r

        r = self.client.get_status()

        #Check if any error occured
        if r.ERROR_CODE == 0:
            print('no error')
        else: 
            print('error while performing task!')

        if verbose == True: 
            return r
        else: 
            return r.RESULTS
        

    def get_forbidden_region(self, rotation_state = 'both'): 
        """
        returns forbidden regions in the robot coordinate x y plane for end-point testing 
        defined via a rectangle in the x-y-plane. x_start<x_stop, y_start<y_stop
        returns the region depending on the rotation state, as some regions are forbidden only in one configuration
        
        Parameters
        rotation_state: string
            options are "horizontal" (nozzle sideways, base 90 degrees), "vertical" (nozzle vertical, base 0 degree), "both"
        ----------
    
        """
        
        #combine the lists depending on the rotation 
        if rotation_state == "vertical": 
            test_list_safety = self.forbidden_regions_vertical
        elif rotation_state == "horizontal": 
            test_list_safety = self.forbidden_regions_horizontal
        else:
            test_list_safety = self.forbidden_regions_horizontal + self.forbidden_regions_vertical
        
        return test_list_safety


    def set_forbidden_region(self, x_start, x_stop, y_start, y_stop, rotation_state = 'both'): 
        """
        set a forbidden region in the robot coordinate x y plane for end-point testing 
        defined via a rectangle in the x-y-plane. x_start<x_stop, y_start<y_stop
        set the region depending on the rotation state, as some regions are forbidden only in one configuration
        
        Parameters
        x_start : float
            x-position start 
        x_stop : float
            x-position stop
        y_start : float
            y-position start 
        y_stop : float
            y-position stop
        rotation_state: string
            options are "horizontal" (nozzle sideways, base 90 degrees), "vertical" (nozzle vertical, base 0 degree), "both"
        ----------
    
        """
        region_tuple = (min(x_start,x_stop), max(x_start,x_stop), min(y_start,y_stop), max(y_start,y_stop))
        if rotation_state == "horizontal": 
            self.forbidden_regions_horizontal.append(region_tuple)
        elif rotation_state == "vertical": 
            self.forbidden_regions_vertical.append(region_tuple)
        elif rotation_state == "both": 
            self.forbidden_regions_vertical.append(region_tuple)
            self.forbidden_regions_horizontal.append(region_tuple)
        else:
            print('invalid input of rotation state')
            
            
    def test_forbidden_region(self, x_test, y_test): 
        """
        tests if the end point of a motion is inside a forbidden region
        No testing of the path of a motion included!
        
        Parameters
        x_test : float
            x-position to test 
        y_test : float 
            y-position to test 
            
        ----------
        Returns: 
        safe_motion : bool
            boolean flag if endpoint of motion is safe or not
        """
        from dod.codi import CoDI_base
        # Get current rotation state
        pos_rot_base  = round(CoDI_base.wm(),0)
        
        #Initialize safe flag (True = safe)
        flag_safe_endpoint = True
        
        #combine the lists depending on the rotation 
        if pos_rot_base == 90: 
            test_list_safety = self.forbidden_regions_vertical
        elif pos_rot_base == 0:
            test_list_safety = self.forbidden_regions_horizontal
        else:
            test_list_safety = self.forbidden_regions_horizontal + self.forbidden_regions_vertical
        
        #Test for all regions if the end point is in the forbidden region
        for tuple_current in test_list_safety: 
            x_start, x_stop, y_start, y_stop = tuple_current
            if ((x_start < x_test) and (x_stop > x_test) and (y_start < y_test) and (y_stop > y_test)): 
                flag_safe_endpoint = flag_safe_endpoint and False
            else:
                flag_safe_endpoint = flag_safe_endpoint and True
            
        return flag_safe_endpoint


    def set_timing_update(self): 
        """
        updating the timing triggers according to the set relative and absolute timing values
        
        Parameters
               ----------
        Returns: 
        """
        # Nozzle 1
        self.timing_nozzle_1 = self.timing_Xray - self.timing_delay_nozzle_1 - self.timing_delay_sciPulse - self.timing_delay_reaction
        if self.timing_nozzle_1 < 0: 
            self.timing_nozzle_1 = self.timing_nozzle_1 + 1/120*1000000000
        self.trigger_nozzle_1.ns_delay.put(self.timing_nozzle_1)

        # Nozzle 2
        self.timing_nozzle_2 = self.timing_Xray - self.timing_delay_nozzle_2 - self.timing_delay_sciPulse - self.timing_delay_reaction
        if self.timing_nozzle_2 < 0: 
            self.timing_nozzle_2 = self.timing_nozzle_2 + 1/120*1000000000
        self.trigger_nozzle_2.ns_delay.put(self.timing_nozzle_2)
        
        # LED
        self.timing_LED = self.timing_Xray + self.timing_delay_LED
        self.trigger_LED.ns_delay.put(self.timing_LED)
        
        
    def set_timing_zero_nozzle(self, nozzle, timing_rel): 
        """
        Setting the time zero for the nozzles from the LED alignment in robot
        
        Parameters
        nozle : int
            nozzle number
        timing_rel : float
            relative delay in ns from robot alignment
        ----------
        Returns: 
        """
        if nozzle == 1: 
            self.timing_delay_nozzle_1 = timing_rel
        elif nozzle == 2: 
            self.timing_delay_nozzle_2 = timing_rel
        else: 
            print('no valid nozzle selected.')
            return
        
        # update timings
        self.set_timing_update()


    def set_timing_rel_LED(self, timing_rel): 
        """
        Setting the relative timing of the LED relative to the X-rays
        
        Parameters
        timing_rel : float
            relative delay in ns from robot alignment
        ----------
        Returns: 
        """
        self.timing_delay_LED = timing_rel #delay of LED relative to X-ray timing

        # update timings
        self.set_timing_update()


    def set_timing_rel_reaction(self, timing_rel): 
        """
        Setting the relative timing of the reaction relative to the X-rays
        
        Parameters
        timing_rel : float
            relative delay in ns from robot alignment
        ----------
        Returns: 
        """
        self.timing_delay_reaction = timing_rel #delay of LED relative to X-ray timing
        
        # update timings
        self.set_timing_update()


    def set_timing_abs_Xray(self, timing_abs): 
        """
        Setting the absolute timing of the X-rays for claculation purposes
        
        Parameters
        timing_abs : float
            abs timing in ns from robot alignment
        ----------
        Returns: 
        """
        self.timing_Xray = timing_abs #delay of LED relative to X-ray timing
        #self.trigger_Xray.ns_delay.put(self.timing_Xray)
        
        # update timings
        self.set_timing_update()

            
    def set_timing_relative_nozzle(self, nozzle, timing_rel): 
        """
        Changing the timing of the selected nozzle by a relative amount 
        
        Parameters
        nozle : int
            nozzle number
        timing_rel : float
            relative change in ns from robot alignment
        ----------
        Returns: 
        """
        if nozzle == 1: 
            current_timing = self.timing_delay_nozzle_1
            self.timing_delay_nozzle_1 = self.timing_delay_nozzle_1 + timing_rel
        elif nozzle == 2: 
            current_timing = self.timing_delay_nozzle_2
            self.timing_delay_nozzle_2 = self.timing_delay_nozzle_2 + timing_rel
        else: 
            print('no valid nozzle selected.')
            return
        
        # update timings
        self.set_timing_update()


    def logging_string(self):
        """
        Creating the string to post to the e-log. 
        
        Parameters
        ----------
        Returns: 
        post : string
            String with useful logging information for posting into the e-log 
        """
        post_str = ''
     
        # Info to be posted: 
         
        # Nozzle angles: 
        position = self.codi.get_CoDI_pos()
        position_str = 'CoDI data: name: ' str(position[0]) + 'rot_base: '+ str(position[1])+ 'rot_left: '+ str(position[2]) + 'rot_right: '+ str(position[3])+ 'z-transl: '+ str(position[4]) 
        post_str = post_str + position_str +'\n'
        
        #Timings:
        post_str = post_str + 'Timing:' + '\n'
        post_str = post_str + 'timing_Xray:' + str(self.timing_Xray) +'\n'
        post_str = post_str + 'timing_nozzle_1:' + str(self.timing_nozzle_1) +'\n'
        post_str = post_str + 'timing_nozzle_2:' + str(self.timing_nozzle_2) +'\n'
        post_str = post_str + 'timing_LED:' + str(self.timing_LED) +'\n'
        post_str = post_str + 'timing_delay_LED:' + str(self.timing_delay_LED) +'\n'
        post_str = post_str + 'timing_delay_reaction:' + str(self.timing_delay_reaction) +'\n'        
        post_str = post_str + 'timing_delay_nozzle_1:' + str(self.timing_delay_nozzle_1) +'\n'   
        post_str = post_str + 'timing_delay_nozzle_2:' + str(self.timing_delay_nozzle_2) +'\n'   
        

    # def move(self, name):
    #   '''
    #       Moves robot to posion of name 
    #       Parameters
    #       target_pos : string
    #           position to which robot needs to move

    #   '''
    #   # Connect
    #   r = self.client.connect("Test")
    
    #   # get current position
    #   r = self.client.get_current_positions()
    #   current_real_position = r.RESULTS['PositionReal']
    
    #   r = client.move(new_position)
    #   assert r.RESULTS == 'Accepted'
    
    #   # WAIT FOR MOVEMENT TO BE DONE
    #   busy_wait(30)
    
    #   # Comparison of expected and current position: 
    #   r = client.get_current_positions()
    #   new_real_position = r.RESULTS['PositionReal']
    #   if new_real_position != current_real_position: 
    
    #   r = client.disconnect()
    
    
    # Test orientation CoDI

    # Test pathing

    # Move 

    # Aspiration

    # Washing 

    # Start injection

    # Relative motion

    # Stop injection

    # Testing the class
    # robot1 = DoD_robot()

    # robot1.set_forbidden_region(0,1.5, 0, 1.5, rotation_state='both')
    # robot1.set_forbidden_region(0,1, 0, 1, rotation_state='horizontal')
    # robot1.set_forbidden_region(0,1, 0, 1, rotation_state='vertical')
    # robot1.get_forbidden_region(rotation_state='horizontal')
    # robot1.get_forbidden_region(rotation_state='vertical')
    # robot1.test_forbidden_region(0.5, 0.5)
    # robot1.test_forbidden_region(1.5, 1.5)
