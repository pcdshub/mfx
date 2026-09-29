#!/bin/bash


#
# AWR (are we ready)
#
# Script for checking TXI/MFX/CXI/MEC readiness status
#
# Copyright ©  2017 - 2025  SLAC National Accelerator Laboratory
#
# Authors:
#     2017 - 2025  Alex Batyuk <batyuk@stanford.edu>
#
# AWR is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# AWR is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with AWR.  If not, see <http://www.gnu.org/licenses/>.
#



# Get hutch from command line, give help in case of error
hutch=$1
options=$2

if [[ "$hutch" != "mfx" && "$hutch" != "cxi" && "$hutch" != "mec" && "$hutch" != "txi" ]]; then
    printf "\nScript for checking beamline readiness status\n"
    printf "\nSyntax: awr [hutch name]   Hutch name (txi, mfx, cxi, mec)\n\n"

    exit 1
fi


host_os_id=$(cat /etc/os-release | grep -m1 "ID=")

 if [[ "$host_os_id" == 'ID="rhel"' ]]; then
    printf "\n [*] Host OS ID appears to be RHEL. Sourcing EPICS Base for RHEL...\n"\

    # EPICS base is built locally from Git and is dynamically-linked
    # Setting env variables for the script, base built on rhel7 host
    export HOME=/cds/home/b/batyuk
    export EPICS_BASE=${HOME}/software/epics/base-7.0
    export EPICS_HOST_ARCH=$(${EPICS_BASE}/startup/EpicsHostArch)
    export PATH=${EPICS_BASE}/bin/${EPICS_HOST_ARCH}:${PATH}

 elif [[ "$host_os_id" == 'ID="rocky"' ]]; then
   printf "\n [*] Host OS ID appears to be Rocky. Sourcing EPICS Base for Rocky...\n"\

    # EPICS base is built locally from Git and is dynamically-linked
    # Setting env variables for the script, base built on rocky9 host
    export HOME=/cds/home/b/batyuk
    export EPICS_BASE=${HOME}/software/epics/base-7.0_rocky9
    export EPICS_HOST_ARCH=$(${EPICS_BASE}/startup/EpicsHostArch)
    export PATH=${EPICS_BASE}/bin/${EPICS_HOST_ARCH}:${PATH}

 fi

# Init variables
device=' '
device_good_state=' '
pv=' '
pv1=' '
pv2=' '
pv_warning_message=" "


# Warning color variables
red_color=$(tput setaf 1)
clear_color=$(tput sgr0)


# Check device function
check_device()

{

if [[ "$options" == "--verbose" ]]; then
 printf " [*] Checking device $device, should be $device_good_state \n"

fi

pv_pull=$(caget -t -w2 $pv 2>&1)

 if [[ "$pv_pull" == 'Channel connect timed out:'* ]]; then
  printf "${red_color} [!] Can't read $device state${clear_color}\n"

 elif [ "$pv_pull" != "$device_good_state" ]; then
  printf "${red_color}$pv_warning_message${clear_color}"

 fi

}


# Check 2-PV device function
check_2pv_device()

{

if [[ "$options" == "--verbose" ]]; then
 printf " [*] Checking device $device, should be $device_good_state \n"

fi

pv1_pull=$(caget -t $pv1 2>&1)
pv2_pull=$(caget -t $pv2 2>&1)

 if [[ "$pv1_pull" == 'Channel connect timed out:'* || "$pv2_pull" == 'Channel connect timed out:'* ]]; then
  printf "${red_color} [!] Can't read $device state${clear_color}\n"

 elif [[ "$pv1_pull" != "$component1_state" || "$pv2_pull" != "$component2_state" ]]; then
  printf "${red_color}$pv_warning_message${clear_color}"

 fi

}


# Actual photon energy function and BYKIK abort rate
photon_energy()

{

printf "\n [*] Acquiring current photon energy... \n\n"
ph_energy_pv1=$(caget -t -f2 SIOC:SYS0:ML00:AO627)
ph_energy_pv2=$(caget -t -f2 PMPS:LFE:PE:UND:CurrentPhotonEnergy_RBV)
# ph_energy_pv3=$(caget -t -f4 XPP:MON:LOM:E1C)
printf "     PV1 (SIOC:SYS0:ML00:AO627):                      $ph_energy_pv1 eV\n"
printf "     PV2 (PMPS:LFE:PE:UND:CurrentPhotonEnergy_RBV):   $ph_energy_pv2 eV\n"
# printf "     PV3 (XPP:MON:LOM:E1C):                           $ph_energy_pv3 keV\n"

bykik_rate_pv=$(caget -t IOC:IN20:EV01:BYKIK_ABTPRD)
printf "\n [*] BYKIK abort rate: $bykik_rate_pv Hz"

bykik_state_pv=$(caget -t IOC:IN20:EV01:BYKIK_ABTACT)
printf "\n [*] BYKIK state:      $bykik_state_pv"d" \n"

vmtg_reference_pv=$(caget -f6 -t -w2 IOC:GBL0:EV02:SyncFRQMHZ 2>&1)
 if [[ "$vmtg_reference_pv" == 'Channel connect timed out:'* ]]; then
  printf "\n${red_color} [!] Can't read VMTG reference frequency${clear_color}\n"

 else
  vmtg_reference_khz=$(echo "scale=3; 1000 * $vmtg_reference_pv / 1 " | bc)
  printf "\n [*] VMTG reference frequency: $vmtg_reference_khz kHz \n"

 fi

printf "\n  May the Force be with you \n\n"

}


# EPICS Version
epics_version()

{

epics_ver=$(echo $(caget -V))
printf "\n ----------------------------------------------------------- \n"
printf "  $epics_ver\n"

# git_hash=$(git rev-parse --short HEAD)
# printf "  Git hash: $git_hash\n"
printf " ----------------------------------------------------------- \n"

}



# =========================================================================== #
# =============== Begin checking EBD, FEE, TMO, TXI, XPP ==================== #
# =========================================================================== #

epics_version


# EBD Checks
printf "\n [*] Checking EBD...\n"


# EBD TV1L0 VGC01, should be OPEN
device='EBD TV1L0 VGC01 gate valve'
device_good_state='OPEN'
pv='TV1L0:VGC:01:POS_STATE_RBV'
pv_warning_message=" [!] $device is not ${device_good_state,,}\n"

check_device


# EBD IM1L0 XTES, should be OPEN
device='EBD IM1L0 XTES gate valve'
device_good_state='OPEN'
pv='IM1L0:XTES:VGC:01:POS_STATE_RBV'
pv_warning_message=" [!] $device is not ${device_good_state,,}\n"

check_device


# EBD IM1L0, should be OUT
device='EBD IM1L0'
device_good_state='OUT'
pv='IM1L0:XTES:MMS:STATE:GET_RBV'
pv_warning_message=" [!] $device is not ${device_good_state,,}\n"

check_device


# EBD TV2L0 VGC01, should be OPEN
device='EBD TV2L0 VGC01 gate valve'
device_good_state='OPEN'
pv='TV2L0:VGC:01:POS_STATE_RBV'
pv_warning_message=" [!] $device is not ${device_good_state,,}\n"

check_device


# FEE Checks
printf "\n [*] Checking FEE...\n"


# FEE TV2L0 VGC02, should be OPEN
device='FEE TV2L0 VGC02 gate valve'
device_good_state='OPEN'
pv='TV2L0:VGC:02:POS_STATE_RBV'
pv_warning_message=" [!] $device is not ${device_good_state,,}\n"

check_device


# FEE EM1L0 GEM VGC10, should be OPEN
device='FEE EM1L0 GEM VGC10 gate valve'
device_good_state='OPEN'
pv='EM1L0:GEM:VGC:10:POS_STATE_RBV'
pv_warning_message=" [!] $device is not ${device_good_state,,}\n"

check_device


# FEE EM2L0 GEM VGC70, should be OPEN
device='FEE EM2L0 GEM VGC70 gate valve'
device_good_state='OPEN'
pv='EM2L0:GEM:VGC:70:POS_STATE_RBV'
pv_warning_message=" [!] $device is not ${device_good_state,,}\n"

check_device


## FEE solid attenuators 1 - 9, should be OUT
## loopa-loopa
#for i in {1..9};
#do
#
# device="FEE solid attenuator $i"
# device_good_state='OUT'
# pv="SATT:FEE1:32$i:STATE"
# pv_warning_message=" [!] $device is not ${device_good_state,,}\n"
#
# check_device
#
#done
#

# DCCM, should be Out (Out -10, In -1.3)
device='DCCM'
device_good_state='Out'
pv='SP1L0:DCCM:MMS:TX'
pv_state=$(caget -t -f0 $pv 2>&1) # get the actual PV state for the warning message below
pv_warning_message=" [!] $device is not $device_good_state (-10 mm) but is at $pv_state mm\n"

# Custom check function because there is no state for this device yet
# Replace with check_device after state PV is implemented (also update the PV)
if [[ "$options" == "--verbose" ]]; then
 printf " [*] Checking device $device, should be $device_good_state \n"

fi

pv_pull=$(caget -t -w2 -f0 $pv 2>&1)

 if [[ "$pv_pull" == 'Channel connect timed out:'* ]]; then
  printf "${red_color}[!] Can't read $device state${clear_color}\n"

 elif [ "$pv_pull" -gt -10 ]; then
  printf "${red_color}$pv_warning_message${clear_color}"

 fi


# FEE PC1L0 XTES, should be OPEN
device='FEE PC1L0 XTES gate valve'
device_good_state='OPEN'
pv='PC1L0:XTES:VGC:01:POS_STATE_RBV'
pv_warning_message=" [!] $device is not ${device_good_state,,}\n"

check_device


# FEE IM2L0, should be OUT
device='FEE IM2L0'
device_good_state='OUT'
pv='IM2L0:XTES:MMS:STATE:GET_RBV'
pv_warning_message=" [!] $device is not ${device_good_state,,}\n"

check_device


# # Device is physically present but not readable (!)
# # FEE PA1L0 VFS01, should be OPEN
# device='FEE PA1L0 VFS01 gate valve'
# device_good_state='OPEN'
# pv='PA1L0:VFS:01:POS_STATE_RBV'
# pv_warning_message=" [!] $device is not ${device_good_state,,}\n"
#
# check_device


# FEE MR1L0 HOMS VGC01, should be OPEN
device='FEE MR1L0 HOMS VGC01 gate valve'
device_good_state='OPEN'
pv='MR1L0:HOMS:VGC:01:POS_STATE_RBV'
pv_warning_message=" [!] $device is not ${device_good_state,,}\n"

check_device


# FEE BT2L0 PLEG VGC01, should be OPEN
device='FEE BT2L0 PLEG VGC01 gate valve'
device_good_state='OPEN'
pv='BT2L0:PLEG:VGC:01:POS_STATE_RBV'
pv_warning_message=" [!] $device is not ${device_good_state,,}\n"

check_device


# FEE IM3L0, should be OUT
device='FEE IM3L0'
device_good_state='OUT'
pv='IM3L0:PPM:MMS:STATE:GET_RBV'
pv_warning_message=" [!] $device is not ${device_good_state,,}\n"

check_device


# FEE MR2L0 HOMS VGC01, should be OPEN
device='FEE MR2L0 HOMS VGC01 gate valve'
device_good_state='OPEN'
pv='MR2L0:HOMS:VGC:01:POS_STATE_RBV'
pv_warning_message=" [!] $device is not ${device_good_state,,}\n"

check_device


# FEE MR2L0 HOMS VGC02, should be OPEN
device='FEE MR2L0 HOMS VGC02 gate valve'
device_good_state='OPEN'
pv='MR2L0:HOMS:VGC:02:POS_STATE_RBV'
pv_warning_message=" [!] $device is not ${device_good_state,,}\n"

check_device


# FEE TV3L0 VFS01, should be OPEN
device='FEE TV3L0 VFS01 gate valve'
device_good_state='OPEN'
pv='TV3L0:VFS:01:POS_STATE_RBV'
pv_warning_message=" [!] $device is not ${device_good_state,,}\n"

check_device


# FEE IM4L0, should be OUT
device='FEE IM4L0'
device_good_state='OUT'
pv='IM4L0:XTES:MMS:STATE:GET_RBV'
pv_warning_message=" [!] $device is not ${device_good_state,,}\n"

check_device


# ST1L0 stopper, should be NOT_IN
device='FEE ST1L0 (former SH1) stopper'
device_good_state='NOT_IN'
pv='PPS:NEH1:1:ST1L0INSUM'
pv_warning_message=" [!] $device is in\n"

check_device


# TMO Checks
printf "\n [*] Checking TMO...\n"


# TMO TV4L0 VGC01, should be OPEN
device='TMO TV4L0 VGC01 gate valve'
device_good_state='OPEN'
pv='TV4L0:VGC:01:POS_STATE_RBV'
pv_warning_message=" [!] $device is not ${device_good_state,,}\n"

check_device


# TXI Checks
printf "\n [*] Checking TXI...\n"


# TXI TV5L0 VGC01, should be OPEN
device='TXI TV5L0 VGC01 gate valve'
device_good_state='OPEN'
pv='TV5L0:VGC:01:POS_STATE_RBV'
pv_warning_message=" [!] $device is not ${device_good_state,,}\n"

check_device


printf "\n [*] Skipping SB1 PIM check... \n"
## SB1 PIM (former hx2_shared YAG) position, should be OUT
#device='SB1 PIM (former hx2_shared YAG)'
#device_good_state='OUT'
#pv='HX2:SB1:PIM.VAL'
#pv_warning_message=" [!] $device is in\n"
#
#check_device
#

# TXI TV6L0 VGC01, should be OPEN
device='TXI TV6L0 VGC01 gate valve'
device_good_state='OPEN'
pv='TV6L0:VGC:01:POS_STATE_RBV'
pv_warning_message=" [!] $device is not ${device_good_state,,}\n"

check_device


# TXI Checks (placeholder)
if [ "$hutch" = "txi" ]; then

# Insert TXI-specific checks below, before photon_energy function

printf "\n [*] AИDY was here ;-) \n"

photon_energy

exit
fi



# XPP Checks
# 2025: Skipping XPP checks due to HE upgrade/reconfiguration
printf "\n [*] Skipping XPP checks...\n"


# # XPP CCM status, should be out
# device='XPP CCM'
# device_good_state='OUT'
# pv1='XPP:MON:MMS:22'
# component1_state='0'
# pv2='XPP:MON:MMS:23'
# component2_state='0'
# pv_warning_message=" [!] $device is in\n"

# check_2pv_device


# # HX3 MON VGC01, should be OPEN
# device='HX3 MON VGC01 gate valve'
# device_good_state='OPEN'
# pv1='HX3:MON:VGC:01:OPN_DI'
# component1_state='High'
# pv2='HX3:MON:VGC:01:CLS_DI'
# component2_state='Low'
# pv_warning_message=" [!] $device is not ${device_good_state,,}\n"

# check_2pv_device


# # HX3 MON VGC02, should be OPEN
# device='HX3 MON VGC02 gate valve'
# device_good_state='OPEN'
# pv1='HX3:MON:VGC:02:OPN_DI'
# component1_state='High'
# pv2='HX3:MON:VGC:02:CLS_DI'
# component2_state='Low'
# pv_warning_message=" [!] $device is not ${device_good_state,,}\n"

# check_2pv_device


# # XPP:SB2:VGC:{01,03,04}:OPN_DI are on the pink XPP line


# # HX3 DVD VGC01, should be OPEN
# device='HX3 DVD VGC01 gate valve'
# device_good_state='OPEN'
# pv1='HX3:DVD:VGC:01:OPN_DI'
# component1_state='High'
# pv2='HX3:DVD:VGC:01:CLS_DI'
# component2_state='Low'
# pv_warning_message=" [!] $device is not ${device_good_state,,}\n"

# check_2pv_device


# XRT Checks, common components
printf "\n [*] Checking XRT, common components...\n"


# XRT Access should be NO
device='XRT Access'
device_good_state='NO'
pv='PPS:XRT1:1:SUMACCESS'
pv_state=$(caget -t $pv 2>&1) # get the actual PV state for the warning message below
pv_warning_message=" [!] $device is ${pv_state}\n"

check_device


# XRT SH2 stopper, should be OUT
device='XRT SH2 stopper'
device_good_state='OUT'
pv='STPR:XRT1:1:SH2_PPSSUM'
pv_warning_message=" [!] $device is in\n"

check_device


# XRT Spectrometer, check state PV
device='XRT Spectrometer'
device_good_state='Is OUT !'
pv='XRT:HXS:ISOUT'
pv_warning_message=" [!] $device is in\n"

check_device


# XRT UM6 PIM (xcs_yag1), should be OUT
device='XRT UM6 PIM (xcs_yag1)'
device_good_state='OUT'
pv='HXX:UM6:PIM.VAL'
pv_warning_message=" [!] $device is in\n"

check_device


# HXX MXT VGC01 gate valve state, should be open
device='HXX MXT VGC01 gate valve'
device_good_state='OPEN'
pv1='HXX:MXT:VGC:01:OPN_DI'
component1_state='High'
pv2='HXX:MXT:VGC:01:CLS_DI'
component2_state='Low'
pv_warning_message=" [!] $device is not ${device_good_state,,}\n"

check_2pv_device


# XRT MR1L3 mirror, should be out
device='XRT MR1L3 mirror'
device_good_state='OUT'
pv='MR1L3:HOMS:MMS:XUP:STATE:GET_RBV'
pv_warning_message=" [!] $device is not ${device_good_state,,}\n"

check_device


# XRT MEC YAG0 (mec_yag0), should be OUT
device='XRT MEC YAG0 (mec_yag0)'
device_good_state='OUT'
pv='HXX:HXM:PIM.VAL'
pv_warning_message=" [!] $device is in\n"

check_device


# HXX MXT VGC02 gate valve state, should be open
device='HXX MXT VGC02 gate valve'
device_good_state='OPEN'
pv1='HXX:MXT:VGC:02:OPN_DI'
component1_state='High'
pv2='HXX:MXT:VGC:02:CLS_DI'
component2_state='Low'
pv_warning_message=" [!] $device is not ${device_good_state,,}\n"

check_2pv_device


# =========================================================================== #
# ================= End checking EBD, FEE, TMO, TXI, XPP ==================== #
# =========================================================================== #


if [ "$hutch" = "mfx" ]; then


# =========================================================================== #
# ===================== Begin checking MFX beamline ========================= #
# =========================================================================== #


# Initial MFX variables
mfx_jaws_nom_val=0.70 # MFX DG1, DG2 Jaws nominal value in mm


# XRT Checks, MFX beamline
printf "\n [*] Checking XRT, beamline: MFX...\n"


# XRT MR1L4 mirror, should be in
device='XRT MR1L4 mirror'
device_good_state='IN'
pv='MR1L4:HOMS:MMS:XUP:STATE:GET_RBV'
pv_warning_message=" [!] $device is not ${device_good_state,,}\n"

check_device


# HXX MXT VGC04, should be OPEN
device='HXX MXT VGC04 gate valve'
device_good_state='High'
pv='HXX:MXT:VGC:04:OPN_DI'
pv_warning_message=" [!] $device is not open\n"

check_device


# MFX DVD VGC01, should be OPEN
device='MFX DVD VGC01 gate valve'
device_good_state='High'
pv='MFX:DVD:VGC:01:OPN_DI'
pv_warning_message=" [!] $device is not open\n"

check_device


# XRT HFX DG2 stopper state, should be in
device='XRT HFX DG2 stopper'
device_good_state='IN'
pv1='HFX:DG2:STP:01:OPEN'
component1_state='Inactive'
pv2='HFX:DG2:STP:01:CLOSE'
component2_state='Active'
pv_warning_message=" [!] $device is out\n"

check_2pv_device


# MFX DIA VGC01, should be OPEN
device='MFX DIA VGC01 gate valve'
device_good_state='High'
pv='MFX:DIA:VGC:01:OPN_DI'
pv_warning_message=" [!] $device is not open\n"

check_device


# MFX DIA VGC02, should be OPEN
device='MFX DIA VGC02 gate valve'
device_good_state='High'
pv='MFX:DIA:VGC:02:OPN_DI'
pv_warning_message=" [!] $device is not open\n"

check_device


# MFX Checks
printf "\n [*] Checking MFX...\n"


# MFX DG1 VGC01, should be OPEN
device='MFX DG1 VGC01 gate valve'
device_good_state='High'
pv='MFX:DG1:VGC:01:OPN_DI'
pv_warning_message=" [!] $device is not open\n"

check_device


# MFX DG1 VGC02, should be OPEN
device='MFX DG1 VGC02 gate valve'
device_good_state='High'
pv='MFX:DG1:VGC:02:OPN_DI'
pv_warning_message=" [!] $device is not open\n"

check_device


# MFX Reference Laser Mirror, should be Out
device='MFX Reference Laser Mirror'
device_good_state='Out'
pv='MFX:DG1:MMS:01.RBV'
pv_state=$(caget -t -f0 $pv 2>&1) # get the actual PV state for the warning message below
pv_warning_message=" [!] $device is not $device_good_state (0 mm) but is at $pv_state mm\n"

# Custom check function because there is no state for this device yet
# Replace with check_device after state PV is implemented (also update the PV)
if [[ "$options" == "--verbose" ]]; then
 printf " [*] Checking device $device, should be $device_good_state \n"

fi

pv_pull=$(caget -t -w2 -f0 $pv 2>&1)

 if [[ "$pv_pull" == 'Channel connect timed out:'* ]]; then
  printf "${red_color}[!] Can't read $device state${clear_color}\n"

 elif [ "$pv_pull" -gt 0 ]; then
  printf "${red_color}$pv_warning_message${clear_color}"

 fi


## MFX DG1 Yag Camera trigger polarity, should be Inverted
#device='MFX DG1 Yag Camera trigger polarity'
#device_good_state='Inverted'
#pv='MFX:EVR:DG1:P6740:TRIG0:TPOL'
#pv_warning_message=" [!] $device is not $device_good_state\n"
#
#check_device


## MFX DG2 Yag Camera trigger polarity, should be Inverted
#device='MFX DG2 Yag Camera trigger polarity'
#device_good_state='Inverted'
#pv='MFX:EVR:DG2:P6740:TRIG1:TPOL'
#pv_warning_message=" [!] $device is not $device_good_state\n"
#
#check_device


# MFX Emergency Stop Buttons
device='MFX Emergency Stop Button'
device_good_state='OK'
pv='PPS:FEH1:45:EMEROFFLATA'
pv_warning_message=" [!] $device is pressed\n"

check_device


# MFX MPS status, should be ok
device='MFX MPS'
device_good_state='IS_OK'
pv='MFX:MPS:1:SUM_MPSC'
pv_warning_message=" [!] $device is not OK\n"

check_device


# MFX S4.5 stopper, should be out
device='MFX S4.5 stopper'
device_good_state='OUT'
pv='PPS:FEH1:45:S45STPRSUM'
pv_warning_message=" [!] $device is not ${device_good_state,,}\n"

check_device


photon_energy


exit
fi


# Future dev
#
# Check all slits (re-write old code)
# Check if the Wave8 targets and diodes are in the beampath for DG1 and DG2
# Check XRT pre-focusing lens
# Check transfocator


# =========================================================================== #
# ======================= End checking MFX beamline ========================= #
# =========================================================================== #



if [ "$hutch" = "cxi" ]; then

# =========================================================================== #
# ===================== Begin checking CXI beamline ========================= #
# =========================================================================== #



# Initial CXI variables
# cxi_jaws_nom_val=xx # CXI Jaws nominal value in mm


# XRT Checks, CXI beamline
printf "\n [*] Checking XRT, beamline: CXI...\n"


# XRT MR1L4 mirror, should be in
device='XRT MR1L4 mirror'
device_good_state='OUT'
pv='MR1L4:HOMS:MMS:XUP:STATE:GET_RBV'
pv_warning_message=" [!] $device is not ${device_good_state,,}\n"

check_device


# HXX MXT VGC03, should be OPEN
device='HXX MXT VGC03 gate valve'
device_good_state='High'
pv='HXX:MXT:VGC:03:OPN_DI'
pv_warning_message=" [!] $device is not open\n"

check_device


# HFX DVD VGC01, should be OPEN
device='HFX DVD VGC01 gate valve'
device_good_state='High'
pv='HFX:DVD:VGC:01:OPN_DI'
pv_warning_message=" [!] $device is not open\n"

check_device


# HFX DG2 YAG (xcs_yag2), should be OUT
device='HFX DG2 PIM (xcs_yag2)'
device_good_state='OUT'
pv='HFX:DG2:PIM.VAL'
pv_warning_message=" [!] $device is in\n"

check_device


# XRT HFX DG2 stopper state, should be out
device='XRT HFX DG2 stopper'
device_good_state='OUT'
pv1='HFX:DG2:STP:01:OPEN'
component1_state='Active'
pv2='HFX:DG2:STP:01:CLOSE'
component2_state='Inactive'
pv_warning_message=" [!] $device is in\n"

check_2pv_device


# HFX DG2 VGC 01 gate valve, should be open
device='HFX DG2 VGC 01 gate valve'
device_good_state='OPEN'
pv1='HFX:DG2:VGC:01:OPN_DI'
component1_state='High'
pv2='HFX:DG2:VGC:01:CLS_DI'
component2_state='Low'
pv_warning_message=" [!] $device is not ${device_good_state,,}\n"

check_2pv_device


# HFX MON VGC01 gate valve, should be open
device='HFX MON VGC01 gate valve'
device_good_state='OPEN'
pv1='HFX:MON:VGC:01:OPN_DI'
component1_state='High'
pv2='HFX:MON:VGC:01:CLS_DI'
component2_state='Low'
pv_warning_message=" [!] $device is not ${device_good_state,,}\n"

check_2pv_device


# HFX MON VGC02 gate valve, should be open
device='HFX MON VGC02 gate valve'
device_good_state='OPEN'
pv1='HFX:MON:VGC:02:OPN_DI'
component1_state='High'
pv2='HFX:MON:VGC:02:CLS_DI'
component2_state='Low'
pv_warning_message=" [!] $device is not ${device_good_state,,}\n"

check_2pv_device


# HFX DG3 IPM (XCS YAG 3m), should be OUT
device='HFX DG3 IPM (XCS YAG 3m)'
device_good_state='OUT'
pv='HFX:DG3:PIM.VAL'
pv_warning_message=" [!] $device is in\n"

check_device


# HFX DIA VGC02 gate valve, should be open
device='HFX DIA VGC02 gate valve'
device_good_state='OPEN'
pv1='HFX:DIA:VGC:02:OPN_DI'
component1_state='High'
pv2='HFX:DIA:VGC:02:CLS_DI'
component2_state='Low'
pv_warning_message=" [!] $device is not ${device_good_state,,}\n"

check_2pv_device


# HFX DIA VGC01 gate valve, should be open
device='HFX DIA VGC01 gate valve'
device_good_state='OPEN'
pv1='HFX:DIA:VGC:01:OPN_DI'
component1_state='High'
pv2='HFX:DIA:VGC:01:CLS_DI'
component2_state='Low'
pv_warning_message=" [!] $device is not ${device_good_state,,}\n"

check_2pv_device


# HFA SND VGC01 gate valve, should be open
device='HFA SND VGC01 gate valve'
device_good_state='OPEN'
pv1='HFA:SND:VGC:01:OPN_DI'
component1_state='High'
pv2='HFA:SND:VGC:01:CLS_DI'
component2_state='Low'
pv_warning_message=" [!] $device is not ${device_good_state,,}\n"

check_2pv_device


# CXI Checks at MFX
printf "\n [*] Checking CXI components at MFX...\n"


# HF4 LAM VGC01 gate valve, should be open
device='HF4 LAM VGC01 gate valve'
device_good_state='OPEN'
pv1='HF4:LAM:VGC:01:OPN_DI'
component1_state='High'
pv2='HF4:LAM:VGC:01:CLS_DI'
component2_state='Low'
pv_warning_message=" [!] $device is not ${device_good_state,,}\n"

check_2pv_device


# CXI S5B stopper in MFX
device='CXI S5B stopper'
device_good_state='IS_OUT'
pv='STPR:FEH1:5:S5BOUT_MPSC'
pv_warning_message=" [!] $device is not out\n"

check_device


# CXI Checks
printf "\n [*] Checking CXI...\n"


# CXI DG1 reference laser mirror
device='CXI DG1 Reference Laser Mirror'
device_good_state='OUT'
pv='CXI:DG1:RLM:MIRROR:GO'
pv_warning_message=" [!] $device is not ${device_good_state,,}\n"

check_device


# CXI DG1 VGC01 gate valve, should be open
device='CXI DG1 VGC01 gate valve'
device_good_state='OPEN'
pv1='CXI:DG1:VGC:01:OPN_DI'
component1_state='High'
pv2='CXI:DG1:VGC:01:CLS_DI'
component2_state='Low'
pv_warning_message=" [!] $device is not ${device_good_state,,}\n"

check_2pv_device


# CXI DG1 VGC02 gate valve, should be open
device='CXI DG1 VGC02 gate valve'
device_good_state='OPEN'
pv1='CXI:DG1:VGC:02:OPN_DI'
component1_state='High'
pv2='CXI:DG1:VGC:02:CLS_DI'
component2_state='Low'
pv_warning_message=" [!] $device is not ${device_good_state,,}\n"

check_2pv_device


# CXI KB1 VGC01 gate valve, should be open
device='CXI KB1 VGC01 gate valve'
device_good_state='OPEN'
pv1='CXI:KB1:VGC:01:OPN_DI'
component1_state='High'
pv2='CXI:KB1:VGC:01:CLS_DI'
component2_state='Low'
pv_warning_message=" [!] $device is not ${device_good_state,,}\n"

check_2pv_device


# CXI KB1 VGC02 gate valve, should be open
device='CXI KB1 VGC02 gate valve'
device_good_state='OPEN'
pv1='CXI:KB1:VGC:02:OPN_DI'
component1_state='High'
pv2='CXI:KB1:VGC:02:CLS_DI'
component2_state='Low'
pv_warning_message=" [!] $device is not ${device_good_state,,}\n"

check_2pv_device


# CXI KB2 VGC01 gate valve, should be open
device='CXI KB2 VGC01 gate valve'
device_good_state='OPEN'
pv1='CXI:KB2:VGC:01:OPN_DI'
component1_state='High'
pv2='CXI:KB2:VGC:01:CLS_DI'
component2_state='Low'
pv_warning_message=" [!] $device is not ${device_good_state,,}\n"

check_2pv_device


# CXI DG2 VGC01 gate valve, should be open
device='CXI DG2 VGC01 gate valve'
device_good_state='OPEN'
pv1='CXI:DG2:VGC:01:OPN_DI'
component1_state='High'
pv2='CXI:DG2:VGC:01:CLS_DI'
component2_state='Low'
pv_warning_message=" [!] $device is not ${device_good_state,,}\n"

check_2pv_device


# CXI DG2 VGC02 gate valve, should be open
device='CXI DG2 VGC02 gate valve'
device_good_state='OPEN'
pv1='CXI:DG2:VGC:02:OPN_DI'
component1_state='High'
pv2='CXI:DG2:VGC:02:CLS_DI'
component2_state='Low'
pv_warning_message=" [!] $device is not ${device_good_state,,}\n"

check_2pv_device


# CXI SC1 VGC01 gate valve, should be open
device='CXI SC1 VGC01 gate valve'
device_good_state='OPEN'
pv1='CXI:SC1:VGC:01:OPN_DI'
component1_state='High'
pv2='CXI:SC1:VGC:01:CLS_DI'
component2_state='Low'
pv_warning_message=" [!] $device is not ${device_good_state,,}\n"

check_2pv_device


# CXI SC1 VGC02 gate valve, should be open
device='CXI SC1 VGC02 gate valve'
device_good_state='OPEN'
pv1='CXI:SC1:VGC:02:OPN_DI'
component1_state='High'
pv2='CXI:SC1:VGC:02:CLS_DI'
component2_state='Low'
pv_warning_message=" [!] $device is not ${device_good_state,,}\n"

check_2pv_device


# CXI SC1 VGC02 gate valve pin, should be in (if the gate valve is open)
# Ugly temporary check below. Re-write for next update
cxi_sc1_vgc02_open=$(caget -t CXI:SC1:VGC:02:OPN_DI)
cxi_sc1_vgc02_close=$(caget -t CXI:SC1:VGC:02:CLS_DI)
cxi_sc1_vgc02_pin=$(caget -t CXI:SC1:VGC:02:PININ_DI)
 if [[ "$cxi_sc1_vgc02_open" = "High" &&  "$cxi_sc1_vgc02_close" = "Low" && "$cxi_sc1_vgc02_pin" != "Pin In" ]]; then
  printf "${red_color} [!] CXI SC1 VGC02 gate valve is open but unpinned${clear_color}\n"
 fi


# CXI Emergency Stop Buttons
device='CXI Emergency Stop Button'
device_good_state='OK'
pv='PPS:FEH1:5:EMEROFFLATA'
pv_warning_message=" [!] $device is pressed\n"

check_device


# # CXI MPS status (find PV and good state)
# device='CXI MPS'
# device_good_state='XXX'
# pv='XXX'
# pv_warning_message=" [!] $device is not OK\n"
#
# check_device


# CXI S5 stopper
device='CXI S5 stopper'
device_good_state='OUT'
pv='PPS:FEH1:5:S5STPRSUM'
pv_warning_message=" [!] $device is not ${device_good_state,,}\n"

check_device


photon_energy


exit
fi


# Future dev
#
# Further gate valve checks (include opn_di and cls_di in the logic for all of them):
# CALC\{!A&&!B}(CXI:KB2:VGC:02:CLS_DI,CXI:KB2:VGC:02:OPN_DI) #this valve has a diamond window and is always closed

# Check CXI slits, should all be at the nominal (mm)



# =========================================================================== #
# ======================= End checking CXI beamline ========================= #
# =========================================================================== #


if [ "$hutch" = "mec" ]; then


# =========================================================================== #
# ===================== Begin checking MEC beamline ========================= #
# =========================================================================== #


# XRT Checks, MEC beamline
printf "\n [*] Checking XRT, beamline: MEC...\n"

# XRT MR1L4 mirror, should be in
device='XRT MR1L4 mirror'
device_good_state='IN'
pv='MR1L4:HOMS:MMS:XUP:STATE:GET_RBV'
pv_warning_message=" [!] $device is not ${device_good_state,,}\n"

check_device


# XRT HFX DG2 stopper state, should be in
device='XRT HFX DG2 stopper'
device_good_state='IN'
pv1='HFX:DG2:STP:01:OPEN'
component1_state='Inactive'
pv2='HFX:DG2:STP:01:CLOSE'
component2_state='Active'
pv_warning_message=" [!] $device is out\n"

check_2pv_device


# MEC Checks
printf "\n [*] Checking MEC...\n"

# Add MEC-specific checks here


photon_energy

fi
exit

# =========================================================================== #
# ======================= End checking MEC beamline ========================= #
# =========================================================================== #

# End of script


