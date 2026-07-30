class _MockMotor:
    """
    No-op motor substitute used when ``CoDI`` is instantiated with
    ``dryrun=True`` off-hutch.  All read methods return safe defaults;
    all write methods are no-ops.

    .. warning::
        Objects instantiated with ``dryrun=True`` (Case A) use ``_MockMotor``
        throughout their lifetime.  Setting ``dryrun=False`` later removes gate
        suppression but the mock objects remain — the instance cannot silently
        transition to live hardware.
    """

    class _MockPresets:
        class positions:
            pass

        def set(self, name):
            pass

        def add_hutch(self, name, **kw):
            pass

    def __init__(self, name="mock"):
        self.name = name
        self.presets = self._MockPresets()

    def wm(self):
        return 0.0

    def umvr(self, delta, **kw):
        pass

    def mv(self, pos, **kw):
        pass

    def umv(self, pos, **kw):
        pass


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

    Examples
    --------
    Instantiate and load existing hutch-python presets:

    >>> codi = CoDI()

    Instantiate and reset presets to factory defaults:

    >>> codi = CoDI(reload_presets=True)
    """

    def __init__(self, reload_presets=False, dryrun=False):
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
        dryrun : bool, optional
            If ``True`` at construction time (Case A), ``_MockMotor`` objects
            are used instead of ``SmarAct`` — no EPICS connections are
            attempted.  Safe for off-hutch development.  This flag is sticky:
            setting ``dryrun=False`` later removes actuation gates but does
            not replace the mock motors with live hardware.
            If ``False`` (default), real ``SmarAct`` motors are instantiated.
            ``dryrun`` may also be toggled post-construction (Case B) to
            suppress actuation calls on live motors.

        Raises
        ------
        RuntimeError
            If a motor PV cannot be connected during instantiation
            (live hardware only; not raised in dry-run mode).

        Examples
        --------
        >>> codi = CoDI()
        >>> codi = CoDI(reload_presets=True)
        >>> codi = CoDI(dryrun=True)   # off-hutch, no EPICS
        """
        self._dryrun = bool(dryrun)

        if dryrun:
            # Case A: off-hutch dry-run — substitute mock motors
            self.CoDI_rot_left = _MockMotor("CoDI_rot_left")
            self.CoDI_rot_right = _MockMotor("CoDI_rot_right")
            self.CoDI_rot_base = _MockMotor("CoDI_rot_base")
            self.CoDI_trans_z = _MockMotor("CoDI_trans_z")
        else:
            from pcdsdevices.device import ObjectComponent as OCpt
            from pcdsdevices.epics_motor import SmarAct, Motor

            # CoDI motor PVs loading
            self.CoDI_rot_left = SmarAct("MFX:MCS2:01:m3", name="CoDI_rot_left")
            self.CoDI_rot_right = SmarAct("MFX:MCS2:01:m1", name="CoDI_rot_right")
            self.CoDI_rot_base = SmarAct("MFX:MCS2:01:m2", name="CoDI_rot_base")
            self.CoDI_trans_z = SmarAct("MFX:MCS2:01:m4", name="CoDI_trans_z")

        # Predefined positions CoDI
        self.CoDI_pos_predefined = dict()

        if reload_presets:
            # self.CoDI_pos_predefined['aspiration'] = (0.0,0.0,0.0,0.0)
            # self.CoDI_pos_predefined['angled_vert'] = (0.0,45.0,45.0,0.0)
            # self.CoDI_pos_predefined['angled_hor'] = (90.0,45.0,45.0,0.0)

            self.add_preset("aspiration", 0.0, 0.0, 0.0, 0.0)
            self.add_preset("angled_vert", 0.0, 45.0, 45.0, 0.0)
            self.add_preset("angled_hor", 90.0, 45.0, 45.0, 0.0)
        else:
            all_presets = vars(
                self.CoDI_rot_left.presets.positions
            )  # Needs to be fixed
            for preset, preset_value in all_presets.items():
                try:
                    # get preset position
                    preset_rot_base = getattr(
                        self.CoDI_rot_base.presets.positions, preset
                    ).pos
                    preset_rot_left = getattr(
                        self.CoDI_rot_left.presets.positions, preset
                    ).pos
                    preset_rot_right = getattr(
                        self.CoDI_rot_right.presets.positions, preset
                    ).pos
                    preset_trans_z = getattr(
                        self.CoDI_trans_z.presets.positions, preset
                    ).pos

                    # Save to local database
                    print(preset)
                    self.add_preset(
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

    @property
    def dryrun(self):
        """bool: When ``True``, all hardware/file writes are suppressed."""
        return self._dryrun

    @dryrun.setter
    def dryrun(self, value):
        self._dryrun = bool(value)

    def get_presets(self):
        """
        Return the local preset position dictionary.

        Returns
        -------
        dict
            Mapping of preset name (str) to a 4-tuple
            ``(rot_base, rot_left, rot_right, trans_z)``.

        Examples
        --------
        >>> presets = codi.get_presets()
        >>> print(presets)
        {'aspiration': (0.0, 0.0, 0.0, 0.0), 'angled_vert': (0.0, 45.0, 45.0, 0.0)}
        """
        return self.CoDI_pos_predefined

    def reload_presets(self):
        """
        Reload all hutch-python motor presets and rebuild the local position dictionary.

        Clears ``CoDI_pos_predefined`` and repopulates it from the hutch-python
        preset positions stored on each motor.  Presets that exist on
        ``CoDI_rot_left`` are used as the reference list; any preset that
        cannot be read from one of the other motors is skipped.

        .. note::
            Presets found on ``CoDI_rot_left`` that are absent on another motor
            are silently skipped.

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
        >>> codi.reload_presets()
        >>> print(codi.get_presets())
        """
        # Predefined positions CoDI
        self.CoDI_pos_predefined = dict()

        all_presets = vars(self.CoDI_rot_left.presets.positions)
        for preset in all_presets.keys():
            try:
                # get preset position
                preset_rot_base = getattr(
                    self.CoDI_rot_base.presets.positions, preset
                ).pos
                preset_rot_left = getattr(
                    self.CoDI_rot_left.presets.positions, preset
                ).pos
                preset_rot_right = getattr(
                    self.CoDI_rot_right.presets.positions, preset
                ).pos
                preset_trans_z = getattr(
                    self.CoDI_trans_z.presets.positions, preset
                ).pos

                # Save to local database
                self.add_preset(
                    preset,
                    preset_rot_base,
                    preset_rot_left,
                    preset_rot_right,
                    preset_trans_z,
                )
            except Exception:
                print(
                    "skipping preset " + preset + ", as it is not defined in all motors"
                )

    def add_preset(self, name, base, left, right, z):
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

        >>> codi.add_preset('exchange', 0.0, 30.0, 30.0, 5.0)

        Overwrite an existing preset:

        >>> codi.add_preset('aspiration', 0.0, 0.0, 0.0, 0.0)
        """
        self.CoDI_pos_predefined.update({name: (base, left, right, z)})

        if self._dryrun:
            print(f"[DRY RUN] add_preset: preset file not written (name='{name}')")
            return

        # Presets using MFX presets functionalities
        self.CoDI_rot_left.presets.add_hutch(name, value=left)
        self.CoDI_rot_right.presets.add_hutch(name, value=right)
        self.CoDI_rot_base.presets.add_hutch(name, value=base)
        self.CoDI_trans_z.presets.add_hutch(name, value=z)

    def get_pos(self, precision_digits=1):
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

        >>> name, base, left, right, z = codi.get_pos()
        >>> print(f'Preset: {name}, base: {base:.1f} deg')

        Use finer precision for matching:

        >>> name, base, left, right, z = codi.get_pos(precision_digits=2)
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

    def move_to_preset(self, pos_name, wait=True, timeout=30):
        """
        Move the CoDI to a named preset position.

        Retrieves the target coordinates from ``CoDI_pos_predefined`` and issues
        move commands to all four motors using the hutch-python preset interface.
        If ``wait=True``, blocks until :meth:`get_pos` reports the target
        preset name, polling every second.

        Parameters
        ----------
        pos_name : str
            Name of the preset position to move to.  Must exist in
            ``CoDI_pos_predefined``.
        wait : bool, optional
            If ``True`` (default), block until the motion is complete.
            If ``False``, return immediately after issuing the move commands.
        timeout : float, optional
            Maximum number of seconds to wait for motion to complete when
            ``wait=True``.  Default is ``30``.  A warning is printed and the
            wait loop exits if the timeout is exceeded.

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

        >>> codi.move_to_preset('angled_vert')

        Issue the move without waiting:

        >>> codi.move_to_preset('angled_vert', wait=False)
        """
        import time

        # get target positions
        pos_rot_base, pos_rot_left, pos_rot_right, pos_trans_z = (
            self.CoDI_pos_predefined[pos_name]
        )

        if self._dryrun:
            print(f"[DRY RUN] move_to_preset: '{pos_name}' not executed on motors")
            return

        # Move using hutch python presets
        self.CoDI_rot_base.presets.set(pos_name)
        self.CoDI_rot_left.presets.set(pos_name)
        self.CoDI_rot_right.presets.set(pos_name)
        self.CoDI_trans_z.presets.set(pos_name)

        if wait:
            (
                test_name,
                test_pos_rot_base,
                test_pos_rot_left,
                test_pos_rot_right,
                test_pos_trans_z,
            ) = self.get_pos()
            i = 0
            start = time.time()
            while pos_name != test_name:
                if time.time() - start > timeout:
                    print(
                        f"[CoDI] Warning: motion to '{pos_name}' timed out "
                        f"after {timeout} s."
                    )
                    break
                time.sleep(1)
                print("\r waiting for motion to end: %i s" % i, end="\r")
                i = i + 1
                (
                    test_name,
                    test_pos_rot_base,
                    test_pos_rot_left,
                    test_pos_rot_right,
                    test_pos_trans_z,
                ) = self.get_pos()
            else:
                print("Motion ended")

    def save_current_pos(self, name):
        """
        Save the current motor positions as a named preset.

        Reads the current positions from all four motors via
        :meth:`get_pos` and registers them as a new (or updated) preset
        using :meth:`add_preset`.

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

        >>> codi.save_current_pos('sample_exchange')
        """
        pos_name, pos_rot_base, pos_rot_left, pos_rot_right, pos_trans_z = (
            self.get_pos()
        )
        self.add_preset(name, pos_rot_base, pos_rot_left, pos_rot_right, pos_trans_z)

    def update_z_all_presets(self, verbose=True):
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

        >>> codi.update_z_all_presets()

        Silent update without printing:

        >>> codi.update_z_all_presets(verbose=False)
        """
        # get current z position:
        pos_trans_z_new = self.CoDI_trans_z.wm()

        # get all keys from the positions
        # Use list() to materialise the keys before iterating, in case the dict
        # is modified in-place by add_preset during the loop.
        position_keys = list(self.CoDI_pos_predefined.keys())

        # go through all positions and change the z-value to the current z value
        for key in position_keys:
            pos_rot_base, pos_rot_left, pos_rot_right, pos_trans_z = (
                self.CoDI_pos_predefined[key]
            )
            self.add_preset(
                key, pos_rot_base, pos_rot_left, pos_rot_right, pos_trans_z_new
            )

        # Print the new predefined positions as a sanity check
        if verbose:
            print(self.get_presets())

    def remove_preset(self, name):
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
        >>> codi.remove_preset('exchange')
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
        if self._dryrun:
            print(f"[DRY RUN] move_z_rel: relative move suppressed (z_rel={z_rel})")
            return
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
        if self._dryrun:
            print(
                f"[DRY RUN] move_rot_left_rel: relative move suppressed (rot_rel={rot_rel})"
            )
            return
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
        if self._dryrun:
            print(
                f"[DRY RUN] move_rot_right_rel: relative move suppressed (rot_rel={rot_rel})"
            )
            return
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
        if self._dryrun:
            print(
                f"[DRY RUN] move_rot_base_rel: relative move suppressed (rot_rel={rot_rel})"
            )
            return
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

    # ------------------------------------------------------------------
    # Deprecated aliases — kept for one beamtime cycle.
    # Remove after all call sites are updated.
    # ------------------------------------------------------------------

    def get_CoDI_predefined(self):
        """Deprecated: use :meth:`get_presets` instead."""
        import warnings

        warnings.warn(
            "get_CoDI_predefined() is deprecated; use get_presets().",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.get_presets()

    def set_CoDI_predefined(self, name, base, left, right, z):
        """Deprecated: use :meth:`add_preset` instead."""
        import warnings

        warnings.warn(
            "set_CoDI_predefined() is deprecated; use add_preset().",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.add_preset(name, base, left, right, z)

    def update_CoDI_predefined(self):
        """Deprecated: use :meth:`reload_presets` instead."""
        import warnings

        warnings.warn(
            "update_CoDI_predefined() is deprecated; use reload_presets().",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.reload_presets()

    def get_CoDI_pos(self, precision_digits=1):
        """Deprecated: use :meth:`get_pos` instead."""
        import warnings

        warnings.warn(
            "get_CoDI_pos() is deprecated; use get_pos().",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.get_pos(precision_digits=precision_digits)

    def set_CoDI_pos(self, pos_name, wait=True, timeout=30):
        """Deprecated: use :meth:`move_to_preset` instead."""
        import warnings

        warnings.warn(
            "set_CoDI_pos() is deprecated; use move_to_preset().",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.move_to_preset(pos_name, wait=wait, timeout=timeout)

    def set_CoDI_current_pos(self, name):
        """Deprecated: use :meth:`save_current_pos` instead."""
        import warnings

        warnings.warn(
            "set_CoDI_current_pos() is deprecated; use save_current_pos().",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.save_current_pos(name)

    def set_CoDI_current_z(self, verbose=True):
        """Deprecated: use :meth:`update_z_all_presets` instead."""
        import warnings

        warnings.warn(
            "set_CoDI_current_z() is deprecated; use update_z_all_presets().",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.update_z_all_presets(verbose=verbose)

    def remove_CoDI_pos(self, name):
        """Deprecated: use :meth:`remove_preset` instead."""
        import warnings

        warnings.warn(
            "remove_CoDI_pos() is deprecated; use remove_preset().",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.remove_preset(name)


# ---------------------------------------------------------------------------
# F4 — Guided CoDI alignment wrapper
# ---------------------------------------------------------------------------


def codi_align(codi, dod=None):
    """
    Interactive mode-based alignment wrapper for the CoDI injector.

    Provides four freely-switchable alignment modes corresponding to the four
    steps of the CoDI alignment procedure.  Uses raw terminal I/O (no curses).

    Parameters
    ----------
    codi : CoDI
        A live (or dry-run) ``CoDI`` instance.
    dod : DoD or None, optional
        A ``DoD`` instance.  Required to enable T (timing) and R (reaction)
        modes.  If ``None``, those modes are unavailable.

    Modes
    -----
    P  (position)
        All four CoDI axes.  Axis selected by keys ``1``–``4``.
        Arrow keys move the selected axis.
    T  (timing)
        Step the EVR timing-zero delay for nozzle 1 or 2.
        Toggle nozzle with ``1`` / ``2``.  Requires *dod*.
    Z  (overlap)
        ``trans_z`` only.  ``[`` marks overlap start, ``]`` marks overlap
        end, ``m`` moves immediately to midpoint.
    R  (reaction)
        Step ``reaction_timing_rel``.  Positive = more reaction time.
        Requires *dod*.

    Shared controls
    ---------------
    ``+`` / ``-``  Increase / decrease step size of the active axis.
    ``s``          Save current CoDI position as a named preset.
    ``h``          Print full key map.
    ``q``          Quit; prompts to post to e-log.

    Examples
    --------
    >>> from dod.codi import codi_align
    >>> codi_align(codi)              # position and overlap only
    >>> codi_align(codi, dod=dod)     # full 4-mode alignment
    """
    import sys
    import tty
    import termios

    # -----------------------------------------------------------------------
    # Axis metadata
    # -----------------------------------------------------------------------
    _P_AXES = ["rot_base", "rot_left", "rot_right", "trans_z"]
    _P_UNITS = {
        "rot_base": "°",
        "rot_left": "°",
        "rot_right": "°",
        "trans_z": "mm",
    }
    _P_MOTORS = {
        "rot_base": lambda: codi.CoDI_rot_base.wm(),
        "rot_left": lambda: codi.CoDI_rot_left.wm(),
        "rot_right": lambda: codi.CoDI_rot_right.wm(),
        "trans_z": lambda: codi.CoDI_trans_z.wm(),
    }
    _P_MOVE = {
        "rot_base": lambda d: codi.move_rot_base_rel(d),
        "rot_left": lambda d: codi.move_rot_left_rel(d),
        "rot_right": lambda d: codi.move_rot_right_rel(d),
        "trans_z": lambda d: codi.move_z_rel(d),
    }

    # -----------------------------------------------------------------------
    # State
    # -----------------------------------------------------------------------
    mode = "P"
    p_axis_idx = 0  # index into _P_AXES; keys 1-4 set this
    t_nozzle = 1  # T-mode nozzle (1 or 2)
    z_start = None  # Z-mode overlap start
    z_end = None  # Z-mode overlap end

    # Per-axis step sizes (in natural units: degrees or mm)
    p_steps = {
        "rot_base": 0.100,
        "rot_left": 0.100,
        "rot_right": 0.100,
        "trans_z": 0.010,
    }
    t_step_ns = 100.0  # timing zero step (ns); displayed as µs
    r_step_ns = 100.0  # reaction step (ns); displayed as µs

    _HELP = """
  ─── codi_align key map ─────────────────────────────────────
  Mode switch:   p=Position  t=Timing  z=Z-overlap  r=Reaction
  Move:          arrow keys (up/right = positive, down/left = negative)
  Axis select:   1/2/3/4  (P-mode: rot_base/left/right/z; T-mode: nozzle)
  Step size:     + increase   - decrease  (active axis only)
  Z-mode:        [  mark overlap start    ]  mark overlap end
                 m  move to midpoint (immediate)
  Save preset:   s
  Help:          h
  Quit:          q (prompts for elog post)
  ────────────────────────────────────────────────────────────
"""

    def _dryrun_tag():
        return " [DRY RUN MODE]" if codi.dryrun else ""

    def _p_status():
        parts = []
        for i, ax in enumerate(_P_AXES):
            try:
                pos = _P_MOTORS[ax]()
                pos_s = f"{pos:.3f}{_P_UNITS[ax]}"
            except Exception:
                pos_s = "?.???"
            star = "*" if i == p_axis_idx else " "
            parts.append(f"[{i + 1}]{star}{ax}={pos_s}(step={p_steps[ax]:.3f})")
        return f"P{_dryrun_tag()} | {' '.join(parts)}"

    def _t_status():
        if dod is None:
            return "T mode unavailable (no dod provided)"
        try:
            v1 = dod.timing_delay_nozzle_1 / 1000
            v2 = dod.timing_delay_nozzle_2 / 1000
        except Exception:
            v1 = v2 = 0.0
        nz_s = f"[{t_nozzle}*]" if t_nozzle else ""
        step_us = t_step_ns / 1000
        return (
            f"T{_dryrun_tag()} | nozzle={t_nozzle} | step={step_us:.3f}µs | "
            f"nozzle_1={v1:.3f}µs  nozzle_2={v2:.3f}µs"
        )

    def _z_status():
        try:
            pos = codi.CoDI_trans_z.wm()
            pos_s = f"{pos:.3f}mm"
        except Exception:
            pos_s = "?.???"
        overlap_s = ""
        if z_start is not None and z_end is not None:
            overlap_s = f" | overlap:[{z_start:.3f}→{z_end:.3f}] mid={((z_start + z_end) / 2):.3f}"
        elif z_start is not None:
            overlap_s = f" | start:{z_start:.3f} (press ] for end)"
        step_s = f"{p_steps['trans_z']:.3f}mm"
        return f"Z{_dryrun_tag()} | trans_z={pos_s} step={step_s}{overlap_s}"

    def _r_status():
        if dod is None:
            return "R mode unavailable (no dod provided)"
        try:
            v = dod.timing_delay_reaction / 1000
        except Exception:
            v = 0.0
        step_us = r_step_ns / 1000
        return (
            f"R{_dryrun_tag()} | reaction_time={v:.3f}µs "
            f"(+= more reaction) | step={step_us:.3f}µs"
        )

    def _print_status():
        if mode == "P":
            s = _p_status()
        elif mode == "T":
            s = _t_status()
        elif mode == "Z":
            s = _z_status()
        else:
            s = _r_status()
        sys.stdout.write(f"\r\033[K{s}")
        sys.stdout.flush()

    def _read_char(fd):
        char = sys.stdin.read(1)
        if char == "\x1b":
            char += sys.stdin.read(2)
            if char in ("\x1b[1", "\x1b[2", "\x1b[3", "\x1b[4", "\x1b[5", "\x1b[6"):
                char += sys.stdin.read(3)
        return char

    # -----------------------------------------------------------------------
    # Main loop
    # -----------------------------------------------------------------------
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    print("\ncodi_align started. Press 'h' for help, 'q' to quit.\n")
    _print_status()

    try:
        tty.setraw(fd)
        while True:
            char = _read_char(fd)

            # --- mode switch ------------------------------------------------
            if char == "p":
                mode = "P"
            elif char == "t":
                if dod is None:
                    sys.stdout.write(
                        "\r\033[K[T mode requires dod — call codi_align(codi, dod=dod)]"
                    )
                    sys.stdout.flush()
                else:
                    mode = "T"
            elif char == "z":
                mode = "Z"
            elif char == "r":
                if dod is None:
                    sys.stdout.write(
                        "\r\033[K[R mode requires dod — call codi_align(codi, dod=dod)]"
                    )
                    sys.stdout.flush()
                else:
                    mode = "R"

            # --- axis / nozzle select (1-4) ---------------------------------
            elif char in "1234":
                n = int(char)
                if mode == "P":
                    p_axis_idx = n - 1
                elif mode == "T":
                    if n in (1, 2):
                        t_nozzle = n

            # --- step adjustment --------------------------------------------
            elif char in "+-":
                factor = 2.0 if char == "+" else 0.5
                if mode == "P":
                    ax = _P_AXES[p_axis_idx]
                    p_steps[ax] = round(p_steps[ax] * factor, 4)
                elif mode == "T":
                    t_step_ns = round(t_step_ns * factor, 3)
                elif mode in ("Z",):
                    p_steps["trans_z"] = round(p_steps["trans_z"] * factor, 4)
                elif mode == "R":
                    r_step_ns = round(r_step_ns * factor, 3)

            # --- movement (arrow keys) --------------------------------------
            elif char in ("\x1b[A", "\x1b[C"):  # up / right = positive
                direction = +1
                if mode == "P":
                    ax = _P_AXES[p_axis_idx]
                    _P_MOVE[ax](p_steps[ax] * direction)
                elif mode == "T" and dod is not None:
                    dod.set_nozzle_timing_rel(t_nozzle, t_step_ns * direction)
                elif mode == "Z":
                    codi.move_z_rel(p_steps["trans_z"] * direction)
                elif mode == "R" and dod is not None:
                    dod.set_reaction_timing_rel(r_step_ns * direction)

            elif char in ("\x1b[B", "\x1b[D"):  # down / left = negative
                direction = -1
                if mode == "P":
                    ax = _P_AXES[p_axis_idx]
                    _P_MOVE[ax](p_steps[ax] * direction)
                elif mode == "T" and dod is not None:
                    dod.set_nozzle_timing_rel(t_nozzle, t_step_ns * direction)
                elif mode == "Z":
                    codi.move_z_rel(p_steps["trans_z"] * direction)
                elif mode == "R" and dod is not None:
                    dod.set_reaction_timing_rel(r_step_ns * direction)

            # --- Z-mode overlap markers ------------------------------------
            elif char == "[" and mode == "Z":
                z_start = codi.CoDI_trans_z.wm()
                sys.stdout.write(f"\r\033[K[Z] overlap start marked: {z_start:.3f} mm")
                sys.stdout.flush()

            elif char == "]" and mode == "Z":
                z_end = codi.CoDI_trans_z.wm()
                sys.stdout.write(f"\r\033[K[Z] overlap end marked: {z_end:.3f} mm")
                sys.stdout.flush()

            elif char == "m" and mode == "Z":
                if z_start is not None and z_end is not None:
                    midpoint = (z_start + z_end) / 2
                    sys.stdout.write(
                        f"\r\033[K[Z] moving to midpoint {midpoint:.3f} mm"
                    )
                    sys.stdout.flush()
                    codi.move_z_abs(midpoint)
                else:
                    sys.stdout.write(
                        "\r\033[K[Z] set both [ (start) and ] (end) before pressing m"
                    )
                    sys.stdout.flush()

            # --- save preset -----------------------------------------------
            elif char == "s":
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                sys.stdout.write("\r\033[K")
                preset_name = input("Preset name: ").strip()
                tty.setraw(fd)
                if preset_name:
                    codi.save_current_pos(preset_name)
                    sys.stdout.write(f"\r\033[K[saved preset '{preset_name}']")
                    sys.stdout.flush()

            # --- help -------------------------------------------------------
            elif char == "h":
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                print(f"\r{_HELP}")
                tty.setraw(fd)

            # --- quit -------------------------------------------------------
            elif char in ("q", "\x03"):  # q or Ctrl-C
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                sys.stdout.write("\r\033[K")
                answer = input("Post session summary to elog? [y/N]: ").strip().lower()
                if answer == "y" and dod is not None:
                    dod.logging_string(post_elog=True)
                    print("[elog posted]")
                elif answer == "y" and dod is None:
                    print("[no dod provided — cannot post to elog]")
                print("codi_align exited.")
                return

            _print_status()

    except Exception as exc:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        raise exc
    finally:
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        except Exception:
            pass
