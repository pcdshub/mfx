#!/bin/bash

usage()
{
cat << EOF
usage: $0

Takes a run with dark images for use in pedestals, and posts to the elog.

REMOVED MFX FROM LCLS2 HUTCHES. FORCED STATION TO BE 1. DO NOT RUN WITH OTHER HUTCHES.

EOF
}

if [[($1 == "--help") || ($1 == "-h")]]; then
        usage
        exit 0
fi

EXP=$(/cds/group/pcds/pyps/apps/hutch-python/mfx/scripts/get_info --exp --hutch $HUTCH --station 1)
HUTCH=${EXP:0:3}

#SIT_ENV_DIR="/sdf/group/lcls/ds/ana/sw"
SIT_ENV_DIR="/cds/group/psdm/sw"

LCLS2_HUTCHES="rix, tmo, ued"
HUTCH=$(get_info --gethutch)
if echo "$LCLS2_HUTCHES" | grep -iw "$HUTCH" > /dev/null; then
    echo "This is an LCLS-II experiment"
    
    SIT_ENV_DIR='/cds/group/pcds/dist/pds/'$HUTCH'/scripts/'
    LCLS2=1
    if [[ ${HUTCH} =~ 'ued' ]]; then
        source $SIT_ENV_DIR/setup_env.sh
        epixquad_pedestal_scan --record 1 --hutch ${HUTCH}
    elif [[ ${HUTCH} =~ 'mfx' ]]; then
        source $SIT_ENV_DIR/setup_env.sh
        jungfrau_pedestal_scan --record 1 --hutch ${HUTCH} -p 0 -g 1 -v -t 10000 -C drp-srcf-cmp014
    fi
else
    echo "This is an LCLS-I experiment"
    SIT_ENV_DIR=$SIT_ENV_DIR'/conda1/'
    DAQ_RELEASE=/cds/group/pcds/dist/pds/current

    # -R: for norecord , -r forces recording
    #station=$(get_info --getstation)
    station=0
    $DAQ_RELEASE/tools/scanning/take_pedestals -p $station -r
fi

if [ $? -eq 0 ]; then
    elogMessage="DARK"
    source pcds_conda
    PYCMD=LogBookPost

    RUN=$(/cds/group/pcds/pyps/apps/hutch-python/mfx/scripts/get_info --run --hutch $HUTCH --station 1)
    echo $PYCMD -i "${HUTCH^^}" -u `whoami` -e "$EXP"  -t DARK  -r $RUN -m "$elogMessage"
    $PYCMD -i "${HUTCH^^}" -u `whoami` -p pcds -e "$EXP"  -t DARK  -r $RUN -m "$elogMessage"&

    echo "Please call: makepeds -q milano -r $RUN -u <userID>"
else
    echo 'takepeds failed, make sure the DAQ is setup appropriately!'
fi
