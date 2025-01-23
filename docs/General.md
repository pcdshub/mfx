# **General**

**Last Revised:** 09/01/23  
**By:** Victor Sosa Alfaro

-   Link to open [grafana](https://pswww.slac.stanford.edu/ctl/grafana/d/fb52599d-27cb-4879-97a5-f6e7a18c730b/mfx-basic?orgId=1&from=now-6h&to=now&refresh=5s)

+----------------------------------+----------------------------------+
| **Operations notes**             | **Side notes**                   |
+==================================+==================================+
| -   XRT_Mz_Mi4A is the first yag | (started alignment around 8pm)   |
|     that goes into check beam    |                                  |
|     alignment                    | If there are issues viewing the  |
|                                  | beam always check XPP and see if |
| -   When we first arrive an hour | they have their shutter on       |
|     early, if we are planning to |                                  |
|     use the Rayonix start He(g)  |                                  |
|     purging.                     |                                  |
|                                  |                                  |
| -   During beam alignment they   |                                  |
|     notices that beam might be   |                                  |
|     clipping. So double check    |                                  |
|     and call XPP to pull out     |                                  |
|     their monochromator (when we |                                  |
|     did this nothing changed,    |                                  |
|     but always good to double    |                                  |
|     check).                      |                                  |
|                                  |                                  |
| -   Kept trying to trouble shoot |                                  |
|     the beam issue (it looks     |                                  |
|     like an oval beam rather     |                                  |
|     than circle size) (It turned |                                  |
|     out that a slit before the   |                                  |
|     FEE was closed and it was    |                                  |
|     clipping the beam \[SL1LO    |                                  |
|     was moved 1mm from 2.5 to    |                                  |
|     3.5\]. XXP also noticed this |                                  |
|     issue and helped resolve     |                                  |
|     it.)                         |                                  |
+----------------------------------+----------------------------------+
| -   Working on MFX-dg1-yag (this | F12 is the "oh-shit" button      |
|     is the first one to look at  |                                  |
|     while aligning the beam)     |                                  |
|     before the lenses            |                                  |
|                                  |                                  |
| -   Keep moving the beam up/down |                                  |
|     to look at the beam size in  |                                  |
|     increments of 20 microns     |                                  |
|                                  |                                  |
| -   Then put in to mfx-dg2-yag   |                                  |
|     (after the lenses) this is   |                                  |
|     the last one right before    |                                  |
|     the sample interactions      |                                  |
|                                  |                                  |
| -   The final YAG in the         |                                  |
|     LBL_inline                   |                                  |
+----------------------------------+----------------------------------+
| -   Looking at laser alignment   | Overall having trouble getting   |
|     and timing is being          | laser timing                     |
|     troubleshoot                 |                                  |
|                                  | (this an ongoing issue)          |
| -   Having trouble view the peak |                                  |
|     that correlates to the       |                                  |
|     proper timing.               |                                  |
|                                  |                                  |
| -   Adding an amplifier to help  |                                  |
|     increase laser intensity     |                                  |
|                                  |                                  |
| -   Overall timing was done:     |                                  |
|                                  |                                  |
| terminated BNC cable with 50 ohm |                                  |
| resistance                       |                                  |
|                                  |                                  |
| -   Then timing                  |                                  |
|                                  |                                  |
| -                                |                                  |
+----------------------------------+----------------------------------+
| -   ACR is trying to increase    |                                  |
|     beam photons by changing the |                                  |
|     beam laser we need above     |                                  |
|     1.2-1.5mJ at 8-9mhz          |                                  |
+----------------------------------+----------------------------------+
|                                  | **09/02/23**                     |
+----------------------------------+----------------------------------+
| The overall workflow plan for    | Plan to move the beam up since   |
| the day:                         | last time there was an issue     |
|                                  | with beam clipping               |
| -   Bring the beam to the        |                                  |
|     alvum_u2 for beam alignment  |                                  |
|                                  |                                  |
| -   Try to optimize the beam     |                                  |
|     slits to have better focus   |                                  |
|     in the beam                  |                                  |
|                                  |                                  |
| -   Last night they did a wire   |                                  |
|     scan to determine the laser  |                                  |
|     size (in microns) it helps   |                                  |
|     to focus the beam.           |                                  |
|                                  |                                  |
| -   Focus the beam for better    |                                  |
|     alignment                    |                                  |
|                                  |                                  |
| -   Change the laser delay by    |                                  |
|     20sec (Panel 6 on FS timing  |                                  |
|     EVI)                         |                                  |
|                                  |                                  |
| -                                |                                  |
+----------------------------------+----------------------------------+
| Initial setup                    | Save setup with all the windows  |
|                                  |                                  |
| 1.  Turn on the epix1 and epix2  | Does not work with               |
|     (done after dot is purged    |                                  |
|     for 45min)                   | Takepeds with rayonix it's a     |
|                                  | calibration                      |
| 2.  Restart the DAQ use command  |                                  |
|     ( resartdaq -w)              |                                  |
|                                  |                                  |
| 3.  Load all the windows under   |                                  |
|     the DAQ online monitor       |                                  |
|     window                       |                                  |
|                                  |                                  |
| 4.  Open all the windows ( )     |                                  |
|                                  |                                  |
| he Rayonix ( done when the box   |                                  |
| has been purged)                 |                                  |
|                                  |                                  |
| 5.  Takepeds                     |                                  |
|                                  |                                  |
| 6.  Blank Rayonix                |                                  |
|                                  |                                  |
| 9\. Cd into slac                 |                                  |
|                                  |                                  |
| 1.                               |                                  |
+----------------------------------+----------------------------------+
|                                  |                                  |
+----------------------------------+----------------------------------+
| Takepeds                         |                                  |
|                                  |                                  |
| 1.  To Take pedistals use        |                                  |
|     command (takepeds)           |                                  |
|                                  |                                  |
| 2.  Copy and paste command line  |                                  |
|     and Enter username and then  |                                  |
|     password                     |                                  |
|                                  |                                  |
| 3.  then stop DAQ and restart it |                                  |
|     to update graphs             |                                  |
|                                  |                                  |
| (this helps epix100 detects      |                                  |
| become more flat, better         |                                  |
| signal-to-noise)                 |                                  |
|                                  |                                  |
| Take dark/blank on t             |                                  |
|                                  |                                  |
| (make sure to do this before     |                                  |
| running sample and after the LBL |                                  |
| box has been purged for a while, |                                  |
| the more purge occurs the        |                                  |
| overall baseline it gives)       |                                  |
+----------------------------------+----------------------------------+
| Insert the Rayonix into the LBL  |                                  |
| chamber                          |                                  |
|                                  |                                  |
| 1.  Rayonix postion starts at    |                                  |
|     1100mm and initially you     |                                  |
|     move it to **500mm**         |                                  |
|                                  |                                  |
| 2.  Move every 100mm steps until |                                  |
|     you get to **300mm**         |                                  |
|                                  |                                  |
| 3.  At this point the LBL group  |                                  |
|     clamps the Rayonix with      |                                  |
|     their DOT chamber            |                                  |
|                                  |                                  |
| 4.  Move by 50mm until you get   |                                  |
|     to **200mm**                 |                                  |
|                                  |                                  |
| 5.  Lastly type 188 get to the   |                                  |
|     final position of **188mm**  |                                  |
+----------------------------------+----------------------------------+
| EPix100.1 turn on                | FEE on channel 2                 |
|                                  |                                  |
| 1.  Under detectors go to        |                                  |
|     epix100.1                    |                                  |
|                                  |                                  |
| 2.  Click on detector idle       |                                  |
|                                  |                                  |
| 3.  Wait until the current is    |                                  |
|     below 20 (this is based in   |                                  |
|     the LBL box purging)         |                                  |
|                                  |                                  |
| 4.  Turn on by clicking detector |                                  |
|     on                           |                                  |
|                                  |                                  |
| 5.  Then do the same for         |                                  |
|     epix100.2                    |                                  |
+----------------------------------+----------------------------------+
| Take Rayonix blank               | Trying to develop a way to move  |
|                                  | rayonix motors without the MFX   |
| Go to Users home                 | home screen as a script:         |
|                                  |                                  |
| 1.  Ssh into the comptur ssh. -x |                                  |
|     <hsuser@con-ics-mfx.rayonix> |                                  |
|                                  |                                  |
| 2.  Kill the terminal by opening |                                  |
|     \$ killall proServ (         |                                  |
|     disconnects computer, make   |                                  |
|     sure nothing is              |                                  |
|     running)(look by clicking    |                                  |
|     up)                          |                                  |
|                                  |                                  |
| 3.  Open Capxure                 |                                  |
|                                  |                                  |
| ```{=html}                       |                                  |
| <!-- -->                         |                                  |
| ```                              |                                  |
| 2.  Change frame to none         |                                  |
|                                  |                                  |
| 3.  Click normal then collect    |                                  |
|     new background               |                                  |
|                                  |                                  |
| 4.  Click on Dark then collect   |                                  |
|     new background               |                                  |
|                                  |                                  |
| 5.  Then quite/close capxure (go |                                  |
|     to file tab and exit)        |                                  |
|                                  |                                  |
| 6.  On terminal Reconnect to the |                                  |
|     original daq ( look for it   |                                  |
|     moving up)                   |                                  |
+----------------------------------+----------------------------------+
| Beam alignment                   | Alvium-u2 takes the beam on a    |
|                                  | YAG                              |
| 1.  Attenuate to Att(1e-5)       |                                  |
|                                  | MEC after, XCS is before MFX     |
| 2.  Put all three YAG on         | (mirrors)                        |
|     \[camviewer\]                |                                  |
|                                  | Grab YAG images as you go        |
| 3.  Click on yag dia, dia1, dia2 |                                  |
|                                  | If beam looks bad in the         |
| 4.  Check that the MR14 mirror   | detectors try to move the        |
|     is open (under lcls: xrt     |                                  |
|                                  |                                  |
| 5.  First mfx-dia_yag; att(1e-2) |                                  |
|                                  |                                  |
| 6.  Remove the 1^st^ yag (click  |                                  |
|     on out)                      |                                  |
|                                  |                                  |
| 7.  Move to align next one       |                                  |
|     MFX_dg1_yag                  |                                  |
|                                  |                                  |
| 8.  Move YAG with MR1L4 (left    |                                  |
|     moves to the right and right |                                  |
|     click moves to the left) to  |                                  |
|     center the beam              |                                  |
|                                  |                                  |
| 9.  To move the beam up call     |                                  |
|     ARC, moves in increments of  |                                  |
|     20microns                    |                                  |
|                                  |                                  |
| 10. Take out DG1 and bring dg2   |                                  |
|                                  |                                  |
| 11. If it looks good remove dg2  |                                  |
|                                  |                                  |
| 12. Bring down att(1e-7) and     |                                  |
|     close beam (you don't want   |                                  |
|     to accidentally burn a       |                                  |
|     camera)                      |                                  |
|                                  |                                  |
| 13. Then bring the beam into     |                                  |
|     detectors Alvium and rayonix |                                  |
|                                  |                                  |
| 14. Make sure beam is centered   |                                  |
|     and everything looks good    |                                  |
|     before moving to the LBL yag |                                  |
+----------------------------------+----------------------------------+
| Look at LBL YAG to [focus        | When daq fails restart           |
| scan]{.ul}                       |                                  |
|                                  | If terminal is dead restart the  |
| 1.  When doing a focus remove    | whole computer                   |
|     all the mirrors to avoid any |                                  |
|     clipping ( move up 1mm)      | During focusing if the beam is   |
|                                  | unstable the focus scan would    |
| 2.  Att (1e-4)                   | not be great ( if you need to    |
|                                  | rerun it)                        |
| 3.  Local average (at 5Hz / \#)  |                                  |
|     from 1 to 5                  | The projection did not look      |
|                                  | good.                            |
| 4.  Clear out the markers then   |                                  |
|     add the new Marker on left   | Things are not working with the  |
|     up corner marker 2 bottom    | focusing                         |
|     left                         |                                  |
|                                  |                                  |
| 5.  Go to cd/cds/                |                                  |
|                                  |                                  |
| 6.  Run focus scan: greg focus   |                                  |
|     scan (under daniels folder)  |                                  |
|                                  |                                  |
| 7.  Run Script: ./focus \_scan   |                                  |
|     MFX: GIGE:LBL:01 --scan (    |                                  |
|     moves the transfocator in    |                                  |
|     the Z-position) (integrates  |                                  |
|     the area of the              |                                  |
|     full-half-max between the    |                                  |
|     two markers that were added) |                                  |
|                                  |                                  |
| 8.  Open all the slits up to     |                                  |
|     2.00 from all the yag        |                                  |
|                                  |                                  |
| Move to the previous focus that  |                                  |
| was found previously on the Z    |                                  |
| translation 120 ( this was typed |                                  |
| in under (MFX Lens System)       |                                  |
|                                  |                                  |
| \*It plots the xrays hitting a   |                                  |
| yag and fitting a gaussian. Then |                                  |
| the plot (transforcator z        |                                  |
| position vs transforcator y or   |                                  |
| x) then the dip of the graph     |                                  |
| indicates the good beam focus,   |                                  |
| then you can use this            |                                  |
| information to update the beam   |                                  |
| focus                            |                                  |
+----------------------------------+----------------------------------+
| Focus Scan with Python script    | Can either run the python script |
|                                  | that Leland wrote or do it       |
| Run fucus_Scan('MFX_TFS.....)    | manually (see above).            |
+----------------------------------+----------------------------------+
| Wire scans                       |                                  |
|                                  |                                  |
| 1.  Setup a projection of the    |                                  |
|     alvium_u2 (image projection) |                                  |
|                                  |                                  |
| 2.  Grab image                   |                                  |
|                                  |                                  |
| 3.  Name (alv2)                  |                                  |
|                                  |                                  |
| 4.  Normalize Y                  |                                  |
|                                  |                                  |
| 5.  On DG2 and (click T1 on DG2) |                                  |
|                                  |                                  |
| 6.  Post                         |                                  |
|                                  |                                  |
| 7.  Go to Env on daq: under post |                                  |
|     to plot: alv2 with jet_y     |                                  |
|                                  |                                  |
| 8.  Att(2e-3) slowly             |                                  |
|                                  |                                  |
| 9.  Run script for vertical :    |                                  |
|     RE(bp.daq                    |                                  |
|     \_                           |                                  |
| dscan(\[\],x.jety.0.00,0.025,51, |                                  |
|     events                       |                                  |
|                                  |                                  |
| 10. See elog run28               |                                  |
|                                  |                                  |
| 11. Run horizontal: RE(bp.daq    |                                  |
|     \_d                          |                                  |
| scan(\[\],x.trans.0.00,0.025,51, |                                  |
|     events                       |                                  |
|                                  |                                  |
| 12. See elog run29               |                                  |
|                                  |                                  |
| 13.                              |                                  |
+----------------------------------+----------------------------------+
| Optimize/check the slits:        |                                  |
|                                  |                                  |
| 1.  Checking by looking at the   |                                  |
|     YAG and then on the          |                                  |
|     alvium_u2                    |                                  |
|                                  |                                  |
| 2.  Take the slits in and out    |                                  |
|     (still unclear what to look  |                                  |
|     for when we move the stilts  |                                  |
|     to further refine the beam)  |                                  |
|                                  |                                  |
| 3.                               |                                  |
+----------------------------------+----------------------------------+
| Run Samples:                     | Their Tape had some contaminants |
|                                  | and they washed it               |
| Run samples with scripts, but    |                                  |
| can also use regular daq to run  |                                  |
| samples.                         |                                  |
|                                  |                                  |
| 1.  Have it at flip flop mode    |                                  |
|                                  |                                  |
| 2.  Att(1) full beam             |                                  |
|                                  |                                  |
| 3.  Before run start the         |                                  |
|     flip-flop mode on then start |                                  |
|     run on DAQ or use script     |                                  |
|     which can run multiple runs  |                                  |
|     back-to-back                 |                                  |
|                                  |                                  |
| 4.  Inspirational_autor          |                                  |
| un(sample='name',run_length=300, |                                  |
|     run=5) run=37                |                                  |
|                                  |                                  |
| 5.  If you stop the run          |                                  |
|     premature: stop the          |                                  |
|     flip-flop and daq.disconnect |                                  |
|                                  |                                  |
| 6.                               |                                  |
+----------------------------------+----------------------------------+
|                                  |                                  |
+----------------------------------+----------------------------------+
| Wherepsana to see where shared   |                                  |
| memory is located                |                                  |
|                                  |                                  |
| Pick mon05 and copy paste        |                                  |
|                                  |                                  |
| Search history for grep source   |                                  |
|                                  |                                  |
| The grep lbgee                   |                                  |
|                                  |                                  |
| Take the python3 /cds /home      |                                  |
+----------------------------------+----------------------------------+
| Event sequencer 12 is the new    |                                  |
| for the flip-flop                |                                  |
|                                  |                                  |
| Want to make sure we are sinking |                                  |
| on a 30hz with the DOT system    |                                  |
+----------------------------------+----------------------------------+
| In case the actual photon energy |                                  |
| readout in the attenuator is     |                                  |
| wrong; (SIOC:SYS:ML00:A0627)     |                                  |
| operating point process in LCLS  |                                  |
| home may not be running          |                                  |
+----------------------------------+----------------------------------+
| Type takepeds                    |                                  |
|                                  |                                  |
| When taking peds make sure to    |                                  |
| shutdown and rerestart the DAQ   |                                  |
| in order to actually implement   |                                  |
| the new baseline.                |                                  |
+----------------------------------+----------------------------------+
|                                  |                                  |
+----------------------------------+----------------------------------+
| Command xkill then point at the  |                                  |
| window that you want to close    |                                  |
| and this should close any window |                                  |
| that you need to close (only do  |                                  |
| this as a last resort; make sure |                                  |
| never to point at the desktop    |                                  |
| since this will kill everything) |                                  |
+----------------------------------+----------------------------------+
|                                  | **09/05/23**                     |
+----------------------------------+----------------------------------+
| How to setup/connect to XFEL GUI |                                  |
|                                  |                                  |
| 1.  Edit the cctbx.xfel file; by |                                  |
|     changing to the proper       |                                  |
|     experiment name              |                                  |
|                                  |                                  |
| 2.  Source the file into Python  |                                  |
|                                  |                                  |
| 3.  The cctbx.XFEL login window  |                                  |
|     will then shows up           |                                  |
|                                  |                                  |
| 4.  Click on the ok button       |                                  |
|                                  |                                  |
| 5.  Change trail number to users |                                  |
|     preference                   |                                  |
|                                  |                                  |
| 6.  Click on (Auto plot last     |                                  |
|     five run)                    |                                  |
|                                  |                                  |
| 7.  Go to hide options if you    |                                  |
|     cannot see plots             |                                  |
+----------------------------------+----------------------------------+
|                                  |                                  |
+----------------------------------+----------------------------------+
| Adjust Slits for optimized Beam  | Want to prevent clipping.        |
|                                  |                                  |
| 1.  Dg1 slits adjust the slits   |                                  |
|     around it by adjusting the   |                                  |
|     slits in 4jaw X-ray slit     |                                  |
|     window (Jaws)                |                                  |
|                                  |                                  |
| 2.  Moving the center, width,    |                                  |
|     and height by moving in 0.05 |                                  |
|     movements                    |                                  |
|                                  |                                  |
| 3.  Then move to the next YAG    |                                  |
|     dg2 (Jaws:US)                |                                  |
|                                  |                                  |
| 4.  move to the YAG dg3          |                                  |
|     (Jaws:MS)                    |                                  |
|                                  |                                  |
| 5.  View the alvium_u2 (make     |                                  |
|     sure to zoom-in to really    |                                  |
|     view the camera) (Jaws:DS)   |                                  |
|                                  |                                  |
| \*Looking for:                   |                                  |
|                                  |                                  |
| -Center the beam                 |                                  |
|                                  |                                  |
| -You don't want parstatic        |                                  |
| scattering form the slits, you   |                                  |
| want them close but not clipping |                                  |
| the beam                         |                                  |
+----------------------------------+----------------------------------+
| Moved the Rayonix detector away  |                                  |
| from the original position (273  |                                  |
| instead of 188mm), makes the     |                                  |
| water ring broad on the detector |                                  |
+----------------------------------+----------------------------------+





