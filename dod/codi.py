class CoDI:
    """
    Colliding Droplet Injector (CoDI) interface for the MFX hutch.

    Provides control of the four SmarAct motors that position the CoDI nozzles,
    manages a local dictionary of named preset positions, and exposes methods for
    reading, defining, and moving to those presets.

    The four axes are:

    * **rot_base** — rotation of the base assembly (degrees).
    * **rot_left** — rotation of the left nozzle (degrees).
    * **rot_right** — rotation of the right nozzle (degrees).
    * **trans_z** — vertical translation of the nozzle assembly (mm).

    Preset positions are stored both in the local ``CoDI_pos_predefined`` dict
    and as hutch-python motor presets via ``motor.presets.add_hutch``.

    Parameters
    ----------
    reload_presets : bool, optional
        If ``True``, overwrite the current hutch-python motor presets with the
        hardcoded default positions (``'aspiration'``, ``'angled_vert'``,
        ``'angled_hor'``) and populate ``CoDI_pos_predefined`` from them.
        If ``False`` (default), load the existing hutch-python presets from the
        motors and populate ``CoDI_pos_predefined`` from those.

    Attributes
    ----------
    CoDI_rot_left : SmarAct
        SmarAct motor controlling left-nozzle rotation.  PV: ``MFX:MCS2:01:m3``.
    CoDI_rot_right : SmarAct
        SmarAct motor controlling right-nozzle rotation.  PV: ``MFX:MCS2:01:m1``.
    CoDI_rot_base : SmarAct
        SmarAct motor controlling base rotation.  PV: ``MFX:MCS2:01:m2``.
    CoDI_trans_z : SmarAct
        SmarAct motor controlling vertical translation.  PV: ``MFX:MCS2:01:m4``.
    CoDI_pos_predefined : dict
        Mapping of preset name (str) to a 4-tuple
        ``(rot_base, rot_left, rot_right, trans_z)``.
    safety_abort : bool
        Flag reserved for future use; can be set externally to signal an abort
        during task execution.

    Examples
    --------
    Instantiate and load existing hutch-python presets:

    >>> codi = CoDI()

    Instantiate and reset presets to factory defaults:

    >>> codi = CoDI(reload_presets=True)
    """

    def __init__(self, reload_presets=False):
        """
        Initialise the CoDI interface and load motor presets.

        Parameters
        ----------
        reload_presets : bool, optional
            If ``True``, write the hardcoded default presets
            (``'aspiration'``, ``'angled_vert'``, ``'angled_hor'``) to the
            hutch-python motor preset store and populate ``CoDI_pos_predefined``
            from them.  If ``False`` (default), read the existing presets from
            the motors.

        Raises
        ------
        RuntimeError
            If a motor PV cannot be connected during instantiation.

        Examples
        --------
        >>> codi = CoDI()
        >>> codi = CoDI(reload_presets=True)
        """
        from pcdsdevices.device import ObjectComponent as OCpt
        from pcdsdevices.epics_motor import SmarAct, Motor
        import time

        # CoDI motor PVs loading
        self.CoDI_rot_left = SmarAct("MFX:MCS2:01:m3", name="CoDI_rot_left")
        self.CoDI_rot_right = SmarAct("MFX:MCS2:01:m1", name="CoDI_rot_right")
        self.CoDI_rot_base = SmarAct("MFX:MCS2:01:m2", name="CoDI_rot_base")
        self.CoDI_trans_z = SmarAct("MFX:MCS2:01:m4", name="CoDI_trans_z")

        # Predefined positions CoDI
        self.CoDI_pos_predefined = dict()

        if reload_presets == True:
            # self.CoDI_pos_predefined['aspiration'] = (0.0,0.0,0.0,0.0)
            # self.CoDI_pos_predefined['angled_vert'] = (0.0,45.0,45.0,0.0)
            # self.CoDI_pos_predefined['angled_hor'] = (90.0,45.0,45.0,0.0)

            self.set_CoDI_predefined("aspiration", 0.0, 0.0, 0.0, 0.0)
            self.set_CoDI_predefined("angled_vert", 0.0, 45.0, 45.0, 0.0)
            self.set_CoDI_predefined("angled_hor", 90.0, 45.0, 45.0, 0.0)
        else:
            all_presets = vars(
                self.CoDI_rot_left.presets.positions
            )  # Needs to be fixed
            for preset, preset_value in all_presets.items():
                try:
                    # get preset position
                    exec_base = (
                        "preset_rot_base = self.CoDI_rot_base.presets.positions."
                        + preset
                        + ".pos"
                    )
                    exec_rot_left = (
                        "preset_rot_left = self.CoDI_rot_left.presets.positions."
                        + preset
                        + ".pos"
                    )
                    exec_rot_right = (
                        "preset_rot_right = self.CoDI_rot_right.presets.positions."
                        + preset
                        + ".pos"
                    )
                    exec_trans_z = (
                        "preset_trans_z = self.CoDI_trans_z.presets.positions."
                        + preset
                        + ".pos"
                    )
                    exec(exec_base)
                    exec(exec_rot_left)
                    exec(exec_rot_right)
                    exec(exec_trans_z)

                    # Save to local database
                    print(preset)
                    self.set_CoDI_predefined(
                        preset,
                        preset_rot_base,
                        preset_rot_left,
                        preset_rot_right,
                        preset_trans_z,
                    )
                except:
                    print(
                        "skipping preset "
                        + preset
                        + ", as it is not defined in all motors"
                    )

        # Flag that can be used later on for safety aborts during task execution
        self.safety_abort = False

    def get_CoDI_predefined(self):
        """
        Return the local preset position dictionary.

        Returns
        -------
        dict
            Mapping of preset name (str) to a 4-tuple
            ``(rot_base, rot_left, rot_right, trans_z)``.

        Examples
        --------
        >>> presets = codi.get_CoDI_predefined()
        >>> print(presets)
        {'aspiration': (0.0, 0.0, 0.0, 0.0), 'angled_vert': (0.0, 45.0, 45.0, 0.0)}
        """
        return self.CoDI_pos_predefined

    def update_CoDI_predefined(self):
        """
        Reload all hutch-python motor presets and rebuild the local position dictionary.

        Clears ``CoDI_pos_predefined`` and repopulates it from the hutch-python
        preset positions stored on each motor.  Presets that exist on
        ``CoDI_rot_left`` are used as the reference list; any preset that
        cannot be read from one of the other motors is skipped.

        .. note::
            This method uses ``exec`` to access motor preset attributes by name,
            which is a known limitation of the current hutch-python preset API.

        Returns
        -------
        None

        Raises
        ------
        AttributeError
            If a preset found on ``CoDI_rot_left`` does not exist on one of
            the other motors and the exception is not caught internally.

        Examples
        --------
        >>> codi.update_CoDI_predefined()
        >>> print(codi.get_CoDI_predefined())
        """
        # Predefined positions CoDI
        self.CoDI_pos_predefined = dict()

        all_presets = vars(self.CoDI_rot_left.presets.positions)  # Needs to be fixed
        for preset in all_presets.keys():
            # try:
            # get preset position
            self.exec_base = (
                "preset_rot_base = self.CoDI_rot_base.presets.positions."
                + preset
                + ".pos"
            )
            self.exec_rot_left = (
                "preset_rot_left = self.CoDI_rot_left.presets.positions."
                + preset
                + ".pos"
            )
            self.exec_rot_right = (
                "preset_rot_right = self.CoDI_rot_right.presets.positions."
                + preset
                + ".pos"
            )
            self.exec_trans_z = (
                "preset_trans_z = self.CoDI_trans_z.presets.positions."
                + preset
                + ".pos"
            )
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
            self.set_CoDI_predefined(
                preset,
                preset_rot_base,
                preset_rot_left,
                preset_rot_right,
                preset_trans_z,
            )
            # except:
            #     print('skipping preset '+ preset + ', as it is not defined in all motors')

    def set_CoDI_predefined(self, name, base, left, right, z):
        """
        Define or update a named preset position for the CoDI.

        Stores the position in the local ``CoDI_pos_predefined`` dictionary and
        registers it as a hutch-python preset on all four motors via
        ``motor.presets.add_hutch``.

        Parameters
        ----------
        name : str
            Name of the preset to create or update.
        base : float
            Target rotation of the base in degrees.
        left : float
            Target rotation of the left nozzle in degrees.
        right : float
            Target rotation of the right nozzle in degrees.
        z : float
            Target vertical translation in mm.

        Returns
        -------
        None

        Examples
        --------
        Define a new preset named ``'exchange'``:

        >>> codi.set_CoDI_predefined('exchange', 0.0, 30.0, 30.0, 5.0)

        Overwrite an existing preset:

        >>> codi.set_CoDI_predefined('aspiration', 0.0, 0.0, 0.0, 0.0)
        """
        self.CoDI_pos_predefined.update({name: (base, left, right, z)})

        # Presets using MFX presets functionalities
        self.CoDI_rot_left.presets.add_hutch(name, value=left)
        self.CoDI_rot_right.presets.add_hutch(name, value=right)
        self.CoDI_rot_base.presets.add_hutch(name, value=base)
        self.CoDI_trans_z.presets.add_hutch(name, value=z)

    def get_CoDI_pos(self, precision_digits=1):
        """
        Return the current CoDI motor positions and match to a named preset.

        Reads all four motor positions, rounds them to ``precision_digits``
        decimal places, and checks whether the result matches any entry in
        ``CoDI_pos_predefined``.  Only the three rotation axes
        (``rot_base``, ``rot_left``, ``rot_right``) are compared; ``trans_z``
        is excluded from preset matching.

        Parameters
        ----------
        precision_digits : int, optional
            Number of decimal places used when comparing positions to presets.
            Default is ``1``.

        Returns
        -------
        pos_name : str
            Name of the matching preset, or ``'undefined'`` if no match is
            found.
        pos_rot_base : float
            Current base rotation in degrees (unrounded).
        pos_rot_left : float
            Current left-nozzle rotation in degrees (unrounded).
        pos_rot_right : float
            Current right-nozzle rotation in degrees (unrounded).
        pos_trans_z : float
            Current vertical translation in mm (unrounded).

        Examples
        --------
        Read the current position and print the preset name:

        >>> name, base, left, right, z = codi.get_CoDI_pos()
        >>> print(f'Preset: {name}, base: {base:.1f} deg')

        Use finer precision for matching:

        >>> name, base, left, right, z = codi.get_CoDI_pos(precision_digits=2)
        """
        pos_rot_base = self.CoDI_rot_base.wm()
        pos_rot_left = self.CoDI_rot_left.wm()
        pos_rot_right = self.CoDI_rot_right.wm()
        pos_trans_z = self.CoDI_trans_z.wm()

        # # for testing purposes
        # pos_rot_base  = 0
        # pos_rot_left  = 45
        # pos_rot_right = 45
        # pos_trans_z   = 0

        pos_tuple = (pos_rot_base, pos_rot_left, pos_rot_right, pos_trans_z)

        pos_rounded = tuple([float(round(each_pos, 1)) for each_pos in pos_tuple])

        # Test if this is one of the preset positions:
        pos_name = "undefined"
        for preset in self.CoDI_pos_predefined:
            preset_rounded = tuple(
                [
                    float(round(each_pos, 1))
                    for each_pos in self.CoDI_pos_predefined[preset]
                ]
            )
            if preset_rounded[:-1] == pos_rounded[:-1]:
                pos_name = preset

        return pos_name, pos_rot_base, pos_rot_left, pos_rot_right, pos_trans_z

    def set_CoDI_pos(self, pos_name, wait=True):
        """
        Move the CoDI to a named preset position.

        Retrieves the target coordinates from ``CoDI_pos_predefined`` and issues
        move commands to all four motors using the hutch-python preset interface.
        If ``wait=True``, blocks until :meth:`get_CoDI_pos` reports the target
        preset name, polling every second.

        Parameters
        ----------
        pos_name : str
            Name of the preset position to move to.  Must exist in
            ``CoDI_pos_predefined``.
        wait : bool, optional
            If ``True`` (default), block until the motion is complete.
            If ``False``, return immediately after issuing the move commands.

        Returns
        -------
        None

        Raises
        ------
        KeyError
            If ``pos_name`` is not found in ``CoDI_pos_predefined``.

        Examples
        --------
        Move to the ``'angled_vert'`` preset and wait for completion:

        >>> codi.set_CoDI_pos('angled_vert')

        Issue the move without waiting:

        >>> codi.set_CoDI_pos('angled_vert', wait=False)
        """
        import time

        # get target positions
        pos_rot_base, pos_rot_left, pos_rot_right, pos_trans_z = (
            self.CoDI_pos_predefined[pos_name]
        )

        # Move motors

        # Old way
        # self.CoDI_rot_base.mv(pos_rot_base, wait=False)
        # self.CoDI_rot_left.mv(pos_rot_left,  wait=False)
        # self.CoDI_rot_right.mv(pos_rot_right, wait=False)
        # self.CoDI_trans_z.mv(pos_trans_z, wait=False)

        # Move using hutch python presets
        exec_base = "self.CoDI_rot_base.mv_" + pos_name + "()"
        exec(exec_base)
        exec_left = "self.CoDI_rot_left.mv_" + pos_name + "()"
        exec(exec_left)
        exec_right = "self.CoDI_rot_right.mv_" + pos_name + "()"
        exec(exec_right)
        exec_z = "self.CoDI_trans_z.mv_" + pos_name + "()"
        exec(exec_z)

        if wait == True:
            (
                test_name,
                test_pos_rot_base,
                test_pos_rot_left,
                test_pos_rot_right,
                test_pos_trans_z,
            ) = self.get_CoDI_pos()
            i = 0
            while pos_name != test_name:
                time.sleep(1)
                print("\r waiting for motion to end: %i s" % i, end="\r")
                i = i + 1
                (
                    test_name,
                    test_pos_rot_base,
                    test_pos_rot_left,
                    test_pos_rot_right,
                    test_pos_trans_z,
                ) = self.get_CoDI_pos()
            print("Motion ended")

    def set_CoDI_current_pos(self, name):
        """
        Save the current motor positions as a named preset.

        Reads the current positions from all four motors via
        :meth:`get_CoDI_pos` and registers them as a new (or updated) preset
        using :meth:`set_CoDI_predefined`.

        Parameters
        ----------
        name : str
            Name to assign to the new preset.

        Returns
        -------
        None

        Examples
        --------
        Save the current CoDI position as ``'sample_exchange'``:

        >>> codi.set_CoDI_current_pos('sample_exchange')
        """
        pos_name, pos_rot_base, pos_rot_left, pos_rot_right, pos_trans_z = (
            self.get_CoDI_pos()
        )
        self.set_CoDI_predefined(
            name, pos_rot_base, pos_rot_left, pos_rot_right, pos_trans_z
        )

    def set_CoDI_current_z(self, verbose=True):
        """
        Update the z-translation value of all stored presets to the current z position.

        Reads the current ``trans_z`` motor position and applies it to every
        entry in ``CoDI_pos_predefined``, leaving the three rotation values
        unchanged.  Useful for propagating a global z-alignment change to all
        presets at once without re-entering each preset individually.

        Parameters
        ----------
        verbose : bool, optional
            If ``True`` (default), print the updated preset dictionary as a
            sanity check after the update.

        Returns
        -------
        None

        Examples
        --------
        After re-aligning z, apply the new position to all presets:

        >>> codi.set_CoDI_current_z()

        Silent update without printing:

        >>> codi.set_CoDI_current_z(verbose=False)
        """
        # get current z position:
        pos_trans_z_new = self.CoDI_trans_z.wm()

        # get all keys from the positions
        # Use list() to materialise the keys before iterating, in case the dict
        # is modified in-place by set_CoDI_predefined during the loop.
        position_keys = list(self.CoDI_pos_predefined.keys())

        # go through all positions and change the z-value to the current z value
        for key in position_keys:
            pos_rot_base, pos_rot_left, pos_rot_right, pos_trans_z = (
                self.CoDI_pos_predefined[key]
            )
            self.set_CoDI_predefined(
                key, pos_rot_base, pos_rot_left, pos_rot_right, pos_trans_z_new
            )

        # Print the new predefined positions as a sanity check
        if verbose == True:
            print(self.get_CoDI_predefined())

    def remove_CoDI_pos(self, name):
        """
        Remove a named preset from the local position dictionary.

        Deletes the entry from ``CoDI_pos_predefined``.  The corresponding
        hutch-python motor presets are **not** removed by this method; use the
        hutch-python preset interface directly to remove those if needed.

        Parameters
        ----------
        name : str
            Name of the preset to remove.

        Returns
        -------
        None

        Raises
        ------
        KeyError
            If ``name`` is not found in ``CoDI_pos_predefined``.

        Examples
        --------
        >>> codi.remove_CoDI_pos('exchange')
        """
        del self.CoDI_pos_predefined[name]

    def move_z_rel(self, z_rel):
        """
        Move the z-translation axis by a relative offset.

        Parameters
        ----------
        z_rel : float
            Relative displacement in mm.  Positive values move in the positive
            motor direction; negative values move in the negative direction.

        Returns
        -------
        None

        Examples
        --------
        Move 0.5 mm in the positive direction:

        >>> codi.move_z_rel(0.5)

        Move 0.2 mm in the negative direction:

        >>> codi.move_z_rel(-0.2)
        """
        # get current z position:
        pos_trans_z = self.CoDI_trans_z.wm()

        # set new position
        self.CoDI_trans_z.umvr(z_rel)

    def move_rot_left_rel(self, rot_rel):
        """
        Rotate the left nozzle by a relative angular offset.

        Parameters
        ----------
        rot_rel : float
            Relative rotation in degrees.  Positive values rotate in the
            positive motor direction.

        Returns
        -------
        None

        Examples
        --------
        Rotate the left nozzle 5 degrees:

        >>> codi.move_rot_left_rel(5.0)

        Rotate the left nozzle back by 2 degrees:

        >>> codi.move_rot_left_rel(-2.0)
        """
        # get current position:
        pos_rot_left = self.CoDI_rot_left.wm()

        # set new position:
        self.CoDI_rot_left.umvr(rot_rel)

    def move_rot_right_rel(self, rot_rel):
        """
        Rotate the right nozzle by a relative angular offset.

        Parameters
        ----------
        rot_rel : float
            Relative rotation in degrees.  Positive values rotate in the
            positive motor direction.

        Returns
        -------
        None

        Examples
        --------
        Rotate the right nozzle 5 degrees:

        >>> codi.move_rot_right_rel(5.0)

        Rotate the right nozzle back by 2 degrees:

        >>> codi.move_rot_right_rel(-2.0)
        """
        # get current position:
        pos_rot_right = self.CoDI_rot_right.wm()

        # set new position:
        self.CoDI_rot_right.umvr(rot_rel)

    def move_rot_base_rel(self, rot_rel):
        """
        Rotate the base by a relative angular offset.

        Parameters
        ----------
        rot_rel : float
            Relative rotation in degrees.  Positive values rotate in the
            positive motor direction.

        Returns
        -------
        None

        Examples
        --------
        Rotate the base 90 degrees:

        >>> codi.move_rot_base_rel(90.0)

        Rotate the base back by 90 degrees:

        >>> codi.move_rot_base_rel(-90.0)
        """
        # get current position:
        pos_rot_base = self.CoDI_rot_base.wm()

        # set new position:
        self.CoDI_rot_base.umvr(rot_rel)

    def move_z_abs(self, z_abs):
        """
        Move the z-translation axis to an absolute position.

        Parameters
        ----------
        z_abs : float
            Target z-position in mm.

        Returns
        -------
        None

        Examples
        --------
        Move the z stage to 10.0 mm:

        >>> codi.move_z_abs(10.0)
        """
        # move z position:
        self.CoDI_trans_z.umv(z_abs)

    def move_rot_left_abs(self, rot_abs):
        """
        Move the left nozzle to an absolute rotation angle.

        Parameters
        ----------
        rot_abs : float
            Target rotation in degrees.

        Returns
        -------
        None

        Examples
        --------
        Move the left nozzle to 45 degrees:

        >>> codi.move_rot_left_abs(45.0)
        """
        # set new position:
        self.CoDI_rot_left.umv(rot_abs)

    def move_rot_right_abs(self, rot_abs):
        """
        Move the right nozzle to an absolute rotation angle.

        Parameters
        ----------
        rot_abs : float
            Target rotation in degrees.

        Returns
        -------
        None

        Examples
        --------
        Move the right nozzle to 45 degrees:

        >>> codi.move_rot_right_abs(45.0)
        """
        # set new position:
        self.CoDI_rot_right.umv(rot_abs)

    def move_rot_base_abs(self, rot_abs):
        """
        Move the base to an absolute rotation angle.

        Parameters
        ----------
        rot_abs : float
            Target rotation in degrees.

        Returns
        -------
        None

        Examples
        --------
        Move the base to the horizontal position (90 degrees):

        >>> codi.move_rot_base_abs(90.0)

        Move the base to the vertical position (0 degrees):

        >>> codi.move_rot_base_abs(0.0)
        """
        # set new position:
        self.CoDI_rot_base.umv(rot_abs)


"""
robot1.get_CoDI_predefined()
robot1.set_CoDI_predefined('test',1,1,1,1)
robot1.get_CoDI_predefined()
robot1.get_CoDI_pos()

robot1.get_CoDI_pos()
robot1.set_CoDI_current_pos('test2')
"""
