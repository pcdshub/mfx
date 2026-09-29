#! /bin/bash

DIR=`dirname $(readlink -f $0)`
PATH=$PATH:$DIR

usage()
{
cat << EOF
usage: $0 options

Make a pedestal file for offline use

OPTIONS:
        -u|--user
               user (needs to be able to log into the s3df)
        -p|--post <text>
               add <text> to elog post
        -t|--test
                do not deploy pedestals (epix10k only)
        -r|--run
               runnumber for pedestal
        -e|--experiment <expname>
               in case you do not want pedestals for the ongoing experiment
        -q|--queue <queue>
               queue for batch submisson
        -A|--alvium
               make pedestals for Alvium (default only cspad/EPIX detectors)
        -O|--opal
               make pedestals for Opals (default only cspad/EPIX detectors)
        -Z|--zyla
               make pedestals for Zyla (default only cspad/EPIX detectors)
        -R|--Rayonix
               make pedestals for Rayonix (please note that this is not the correct procedure for this detector)
        -U|--uxi
               make pedestals for Uxi/Icarus detector
        -j|--jungfrau3
               make pedestals for Jungfrau - 3 run version(default only cspad/EPIX detectors)
        -r|--reservation <reservation>
               reservation for batch submisson
        -D|--xtcav_dark
                dark run for XTCAV
        -L|--xtcav_lasingoff
               lasing off run for XTCAV
        -v|--validity_start <val_run>
               validity range (set to <val_run>-end)
        -N|--nevents <#>
                use this number of events (default 1000). Needed when using -c as original events are counted
        -c|--eventcode <evtcode x>
                use events with eventcode <x> set
        -n|--noise_max <#>
                if you have created a noise file, then write pixel mask file for pixels with noise above #sigmas
        -C|--noise_min <#>
                if noise filecreated, write pixel mask file for pixels with noise below xxx (currently integer only)
        -m|--adu_min <#>
                write pixel mask file for pixels with pedestal below xxx (currently integer only)
        -x|--adu_max <#>
                write pixel mask file for pixels with pedestal above xxx )currently integer only)
        -i|--interactive
                start calibman. -r 0: show all darks, -r n: show runs (n-25) - 25
        -d|--calibdir
                give path for alternative calibdir
        -b|--nbunch
                number of bunches for the laseroff XTCAV calculations
        --lcls2
                force lcls2 (to be used for MFX)
        --sdfdir
                Directory where engineering tool in on S3DF. For development work only.
EOF
}


elogMessage="DARK"
POSITIONAL=()
while [[ $# -gt 0 ]]
do
    key="$1"
    case $key in
        -h|--help)
            usage
            exit
            ;;
        -p|--post)
            ELOGTEXT="$2"
            shift
            shift
            ;;
        -D|--xtcav_dark)
            POSITIONAL+=("$1")
            elogMessage="DARK for XTCAV"
            shift
            ;;
        -L|--xtcav_lasingoff)
            POSITIONAL+=" $1"
            elogMessage="Lasing off for XTCAV"
            shift
            ;;
        -i|--interactive)
            POSITIONAL+=("$1")
            elogMessage="start calibman GUI"
            shift
            ;;
        -U|--uxi)
            POSITIONAL+=("$1")
            elogMessage="DARK for Uxi"
            shift
            ;;
        -Z|--zyla)
            POSITIONAL+=("$1")
            elogMessage="DARK for Zyla"
            shift
            ;;
        -A|--alvium)
            POSITIONAL+=("$1")
            elogMessage="DARK for Alvium"
            shift
            ;;
        -O|--opal)
            POSITIONAL+=("$1")
            elogMessage="DARK for opal"
            shift
            ;;
        -R|--rayonix)
            POSITIONAL+=("$1")
            elogMessage="DARK for Rayonix"
            shift
            ;;
        -j|--jungfrau3)
            POSITIONAL+=("$1")
            elogMessage="DARK for jungfrau, also next two runs."
            shift
            ;;
        -u|--user)
            USER="$2"
            shift
            shift
            ;;
        -r|--run)
            RUN="$2"
            POSITIONAL+=("--run $2")
            shift
            shift
            ;;
        -e|--experiment)
            EXP="$2"
            POSITIONAL+=("--experiment $2")
            shift
            shift
            ;;
        -q|--queue)
            QUEUE="$2"
            POSITIONAL+=("--queue $2")
            shift
            shift
            ;;
        -r|--reservation)
            POSITIONAL+=("--reservation $2")
            shift
            shift
            ;;
	--nstage1)
	    POSITIONAL+=("--nstage1 $2")
            shift
            shift
            ;;
        --sdfdir)
            SDFDIR="$2"
            shift
            shift
            ;;
        --lcls2)
            LCLS2=True
            shift
            ;;
        *)
            POSITIONAL+=("$1")
            shift
            ;;
        esac
done
set -- "${POSITIONAL[@]}"

ELOGTEXT=${ELOGTEXT:=""}
RUN=${RUN:=0}
EXP=${EXP:='xxx'}
QUEUE=${QUEUE:='xxx'}
INTERACTIVE=${INTERACTIVE:=0}

if [[ $RUN == 0 ]]; then
    if [[ $INTERACTIVE == 0 ]]; then
        printf "Please enter a run number: \n"; read RUN
        set -- "$@" '--run ' $RUN
    fi
fi

if [[ $EXP == 'xxx' ]]; then
    HUTCH=$(get_info --gethutch)
    EXP=$(/cds/group/pcds/pyps/apps/hutch-python/mfx/scripts/get_info --exp --hutch $HUTCH --station 1)
    set -- "$@" '--experiment ' $EXP
else
    HUTCH=${EXP:0:3}
fi

LCLS2_HUTCHES="rix, tmo, txi, ued"
if [ -v LCLS2 ]; then
    MAKEPEDSEXE=makepeds_psana2
elif echo "$LCLS2_HUTCHES" | grep -iw "$HUTCH" > /dev/null; then
    echo "This is a LCLS-II experiment"
    MAKEPEDSEXE=makepeds_psana2
    LCLS2=1
else
    echo "This is a LCLS-I experiment"
    MAKEPEDSEXE=makepeds_psana
fi

if [[ $HOSTNAME =~ "sdf" ]]; then
    echo $DIR/$MAKEPEDSEXE $@
    $DIR/$MAKEPEDSEXE $@
    chk="$?"

else
    if [[ $USER =~ "opr" ]]; then
        printf "Please enter user name (cannot run as from operator account): \n"; read USER
    fi
    echo calling on SDF system: $MAKEPEDSEXE $@
    # We need to change paths here as the S3DF filesytem is completely independent
    if [ -v SDFDIR  ]; then
        DIR=$SDFDIR
    else
        DIR=`echo $DIR | sed 's/\/cds\/group\/pcds/\/sdf\/group\/lcls\/ds\/tools/g' | sed 's/\/reg\/g\/pcds/\/sdf\/group\/lcls\/ds\/tools/g'`
        #this line was needed for testing from personal checkouts
        DIR=`echo $DIR | sed 's/cds/sdf/g'`
        DIR=/sdf/group/lcls/ds/tools/engineering_tools/latest/scripts
    fi

    echo ssh -Y "$USER"@psana.sdf ssh -Y psana "$DIR/$MAKEPEDSEXE $@"
    ssh -Y "$USER"@psana.sdf ssh -Y psana "$DIR/$MAKEPEDSEXE $@"
    chk="$?"
fi

if [ $chk -gt 0 ]; then
    echo !!! Something went wrong !!!
    if [ $chk -eq 255 ]; then
        echo User $USER has no access to the psana pool on S3DF, will exit
    elif [ $chk -eq 130 ]; then
	echo makepeds was aborted w/ crtl-c
    elif [ $chk -eq 2 ]; then
	echo makepeds could not make its work directory
    elif [ $chk -eq 3 ]; then
	echo After waiting for 5 minutes, XTC files were still not present
    elif [ $chk -eq 4 ]; then
	echo $USER has no valid kerberos token - needed for LCLS2 deployment of calibration constants
    elif [ $chk -eq 5 ]; then
	echo Deployment of geometry failed
    elif [ $chk -eq 6 ]; then
	echo Deployment of gain constants
    elif [ $chk -eq 7 ]; then
	echo Additional command failed -- jungfrau constants
    elif [ $chk -eq 1 ]; then
	echo makepeds calibration jobs failed, exited as requested.
    else
	echo something else went wrong, received error code $sshchk, will exit
    fi
    exit 1
fi

if [[ $HOSTNAME =~ "sdf" ]]; then
    source /sdf/group/lcls/ds/ana/sw/conda1/manage/bin/psconda.sh
else
    source pcds_conda
fi

elog_par_post --file pedestal -e "$EXP" -r "$RUN"

#if this is a default pedestal run, then do not post as this is handled in takepeds
if [[ $elogMessage == 'DARK' ]] && [[ $ELOGTXT == '' ]] ; then
    echo ---- Done processing pedestals for Run "$RUN" -----
    exit 0
fi

if [[ $HOSTNAME =~ "sdf" ]]; then
    echo Posting messages to the elog is currently not implemented from S3DF yet
    exit 0
fi

PYCMD=LogBookPost.py
echo -- Now posting special message to elog --
echo -- "$elogMessage" --

elogMessage+=$ELOGTEXT
if [[ $(whoami) =~ "opr" ]]; then
    echo "$BINPATH" $PYCMD -i "${HUTCH^^}" -u $(whoami) -e "$EXP"  -t DARK  -r "$RUN" -m "$elogMessage"
    if [[ $HOSTNAME == 'cxi-monitor' ]]; then
        $BINPATH $PYCMD -i "${HUTCH^^}" -u $(whoami) -p pcds -e "$EXP"  -t DARK  -r "$RUN" -m "$elogMessage" -s 1&
    else
        $BINPATH $PYCMD -i "${HUTCH^^}" -u $(whoami) -p pcds -e "$EXP"  -t DARK  -r "$RUN" -m "$elogMessage"&
    fi
else
    echo $BINPATH $PYCMD -i "${HUTCH^^}" -e "$EXP"  -t DARK -r "$RUN" -m "$elogMessage"
    if [[ $HOSTNAME == 'cxi-monitor' ]]; then
        $BINPATH $PYCMD -i "${HUTCH^^}" -e "$EXP" -t DARK -r "$RUN" -m "$elogMessage" -s 1&
    else
        $BINPATH $PYCMD -i "${HUTCH^^}" -e "$EXP" -t DARK -r "$RUN" -m "$elogMessage"&
    fi
fi
