#!/bin/bash
# Script for controller reinitialization, clearing power-up error and error 92 for all MFX devices
# Alex Batyuk, LCLS, 2019


printf "\nReinitialization and clearing out power-up errors for all MFX motors\n"


#------XRT block------#

printf "\n* XRT Pre-focusing lens X...  "
caput -w 3 MFX:DIA:MMS:08.RINI 1 > /dev/null
caput MFX:DIA:MMS:08:SEQ_SELN 36 > /dev/null
 sleep 1
caput MFX:DIA:MMS:08:SEQ_SELN 48 > /dev/null
 sleep 1
printf "ok"

printf "\n* XRT Pre-focusing lens Y...  "
caput -w 3 MFX:DIA:MMS:09.RINI 1 > /dev/null
caput MFX:DIA:MMS:09:SEQ_SELN 36 > /dev/null
 sleep 1
caput MFX:DIA:MMS:09:SEQ_SELN 48 > /dev/null
 sleep 1
printf "ok"

#------End XRT block------#

#------DG1 block------#

printf "\n* Reference laser mirror...   "
caput -w 3 MFX:DG1:MMS:01.RINI 1 > /dev/null
caput MFX:DG1:MMS:01:SEQ_SELN 36 > /dev/null
 sleep 1
caput MFX:DG1:MMS:01:SEQ_SELN 48 > /dev/null
 sleep 1
printf "ok"


printf "\n* DG1 Navitar Zoom...         "
caput -w 3 MFX:DG1:CLZ:01.RINI 1 > /dev/null
caput MFX:DG1:CLZ:01:SEQ_SELN 36 > /dev/null
 sleep 1
caput MFX:DG1:CLZ:01:SEQ_SELN 48 > /dev/null
 sleep 1
printf "ok"


printf "\n* DG1 Navitar Focus...        "
caput -w 3 MFX:DG1:CLF:01.RINI 1 > /dev/null
caput MFX:DG1:CLF:01:SEQ_SELN 36 > /dev/null
 sleep 1
caput MFX:DG1:CLZ:01:SEQ_SELN 48 > /dev/null
 sleep 1
printf "ok"


printf "\n* DG1 YAG Y...                "
caput -w 3 MFX:DG1:MMS:09.RINI 1 > /dev/null
caput MFX:DG1:MMS:09:SEQ_SELN 36 > /dev/null
 sleep 1
caput MFX:DG1:MMS:09:SEQ_SELN 48 > /dev/null
 sleep 1
printf "ok"


printf "\n* DG1 Wave8 Diode X...        "
caput -w 3 MFX:DG1:MMS:06.RINI 1 > /dev/null
caput MFX:DG1:MMS:06:SEQ_SELN 36 > /dev/null
 sleep 1
caput MFX:DG1:MMS:06:SEQ_SELN 48 > /dev/null
 sleep 1
printf "ok"


printf "\n* DG1 Wave8 Diode Y...        "
caput -w 3 MFX:DG1:MMS:07.RINI 1 > /dev/null
caput MFX:DG1:MMS:07:SEQ_SELN 36 > /dev/null
 sleep 1
caput MFX:DG1:MMS:07:SEQ_SELN 48 > /dev/null
 sleep 1
printf "ok"


printf "\n* DG1 Wave8 Target Y...       "
caput -w 3 MFX:DG1:MMS:08.RINI 1 > /dev/null
caput MFX:DG1:MMS:08:SEQ_SELN 36 > /dev/null
 sleep 1
caput MFX:DG1:MMS:08:SEQ_SELN 48 > /dev/null
 sleep 1
printf "ok"

#------end DG1 block------#

#------Transfocator block------#

printf "\n"
for j in 01 02 03 04 05 06 07 08 09 10 11 12 13 14 15 16 17 18 19 20 21
 do
printf "\r"
  printf "* TFS lens motor...           $j"
  
   caput -w 3 MFX:TFS:MMS:$j.RINI 1 > /dev/null
   caput MFX:TFS:MMS:$j:SEQ_SELN 36 > /dev/null
    sleep 1
   caput MFX:TFS:MMS:$j:SEQ_SELN 48 > /dev/null
 done

printf "\r"
printf "* TFS lens all motors...      "
printf "ok"

#------end Transfocator block------#

#------DG2 block------#

printf "\n* DG2 Navitar Zoom...         "
caput -w 3 MFX:DG2:CLZ:01.RINI 1 > /dev/null
caput MFX:DG2:CLZ:01:SEQ_SELN 36 > /dev/null
 sleep 1
caput MFX:DG2:CLZ:01:SEQ_SELN 48 > /dev/null
 sleep 1
printf "ok"


printf "\n* DG2 Navitar Focus...        "
caput -w 3 MFX:DG2:CLF:01.RINI 1 > /dev/null
caput MFX:DG2:CLF:01:SEQ_SELN 36 > /dev/null
 sleep 1
caput MFX:DG2:CLZ:01:SEQ_SELN 48 > /dev/null
 sleep 1
printf "ok"


printf "\n* DG2 YAG Y...                "
caput -w 3 MFX:DG2:MMS:08.RINI 1 > /dev/null
caput MFX:DG2:MMS:08:SEQ_SELN 36 > /dev/null
 sleep 1
caput MFX:DG2:MMS:08:SEQ_SELN 48 > /dev/null
 sleep 1
printf "ok"


printf "\n* DG2 Wave8 Diode X...        "
caput -w 3 MFX:DG2:MMS:05.RINI 1 > /dev/null
caput MFX:DG2:MMS:05:SEQ_SELN 36 > /dev/null
 sleep 1
caput MFX:DG2:MMS:05:SEQ_SELN 48 > /dev/null
 sleep 1
printf "ok"


printf "\n* DG2 Wave8 Diode Y...        "
caput -w 3 MFX:DG2:MMS:06.RINI 1 > /dev/null
caput MFX:DG2:MMS:06:SEQ_SELN 36 > /dev/null
 sleep 1
caput MFX:DG2:MMS:06:SEQ_SELN 48 > /dev/null
 sleep 1
printf "ok"


printf "\n* DG2 Wave8 Target Y...       "
caput -w 3 MFX:DG2:MMS:07.RINI 1 > /dev/null
caput MFX:DG2:MMS:07:SEQ_SELN 36 > /dev/null
 sleep 1
caput MFX:DG2:MMS:07:SEQ_SELN 48 > /dev/null
 sleep 1
printf "ok"

#------end DG2 block------#


#------Sample Table block------#

printf "\n"
for j in 01 02 03 04 05 06
 do
printf "\r"
  printf "* Sample Table motor...       $j"
  
   caput -w 3 MFX:TAB:MMS:$j.RINI 1 > /dev/null
   caput MFX:TAB:MMS:$j:SEQ_SELN 36 > /dev/null
    sleep 1
   caput MFX:TAB:MMS:$j:SEQ_SELN 48 > /dev/null
 done

printf "\r"
printf "* Sample Table all motors...  "
printf "ok"

#------end Sample Table block------#


#------Detector Mover block------#

printf "\n"
for j in 01 02 03 04
 do
printf "\r"
  printf "* Detector Mover motor...     $j"
  
   caput -w 3 MFX:DET:MMS:$j.RINI 1 > /dev/null
   caput MFX:DET:MMS:$j:SEQ_SELN 36 > /dev/null
    sleep 1
   caput MFX:DET:MMS:$j:SEQ_SELN 48 > /dev/null
 done

printf "\r"
printf "* Detector Mover all motors..."
printf "ok"

#------end Detector Mover block------#

#------DG3 block------#

printf "\n* DG3 Navitar Focus...        "
caput -w 3 MFX:USR:MMS:19.RINI 1 > /dev/null
caput MFX:USR:MMS:19:SEQ_SELN 36 > /dev/null
 sleep 1
caput MFX:USR:MMS:19:SEQ_SELN 48 > /dev/null
 sleep 1
printf "ok"

#------end DG3 block------#1



#------Slits block------#

printf "\n"
# Explicit motor PVs
for i in 02 03 04 05
 do
 printf "\r"
 printf "* DG1 Slits...                $i"
  caput -w 3 MFX:DG1:MMS:$i.RINI 1  > /dev/null
  caput MFX:DG1:MMS:$i:SEQ_SELN 36 > /dev/null
   sleep 1
  caput MFX:DG1:MMS:$i:SEQ_SELN 48 > /dev/null
 done
printf "\r"
printf "* DG1 all slits...            "
printf "ok"



printf "\n"
#Explicit motor PVs
for j in 01 02 03 04 12 13 14 15 16 17 18 19
 do
  printf "\r"
 printf "* DG2 Slits...                $j"
  caput -w 3 MFX:DG2:MMS:$j.RINI 1  > /dev/null
  caput MFX:DG2:MMS:$j:SEQ_SELN 36 > /dev/null
   sleep 1
  caput MFX:DG2:MMS:$j:SEQ_SELN 48 > /dev/null
 done
printf "\r"
printf "* DG2 all slits...            "
printf "ok"


#------end Slits block------#



printf "\n\nAll done.\n\n"
