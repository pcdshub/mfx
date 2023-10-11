import sys

def get_info(argv):
    import argparse
    import socket
    import os
    import sys

    parser = argparse.ArgumentParser()
    parser.add_argument("--run", help="get last run", action='store_true')
    parser.add_argument("--exp", help="get experiment name", action='store_true')
    parser.add_argument("--live", help="ongoing?", action='store_true')
    parser.add_argument("--ended", help="ended", action='store_true')
    parser.add_argument("--hutch", help="get experiment for hutch xxx")
    parser.add_argument("--station", help="optional station for hutch with two daqs, e.g. cxi and mfx")
    parser.add_argument("--getHutch", help="get hutch (uppercase)", action='store_true')
    parser.add_argument("--gethutch", help="get hutch (lowercase)", action='store_true')
    parser.add_argument("--getstation", help="get hutch station (for multiple daqs)", action='store_true')
    parser.add_argument("--getbase", help="get base daq name (hutch_station if multiple daqs, otherwise hutch)", action='store_true')
    parser.add_argument("--getinstrument", help="get instrument (HUTCH_station if multiple daqs, otherwise hutch)", action='store_true')
    parser.add_argument("--getcnf", help="get cnf file name)", action='store_true')
    parser.add_argument("--files_for_run", help="get xtc files for run")
    parser.add_argument("--nfiles_for_run", help="get xtc files for run")
    parser.add_argument("--setExp", help="set experiment name")
    args = parser.parse_args()

    hutches=['tmo','txi','rix','xpp','xcs','mfx','cxi','mec', 'ued', 'det', 'lfe','kfe','tst', 'las', 'hpl']
    foundHutch=False
    hutch=''

    #populate hutch-specific subnets here:
    hutch_subnets={'tmo': ['28','132','133','134','135'],
                'txi': ['29','136','137','138','139'],
                'rix': ['31','144','145','146','147'],
                'xpp': ['22','84','85','86','87'],
                'xcs': ['25','80','81','82','83'],
                'cxi': ['26','68','69','70','71'],
                'mfx': ['24','72','73','74','75'],
                'mec': ['27','76','77','78','79'],
                'ued': ['36'],
                'det': ['58', '59'],
                'lfe': ['88','89','90','91'],
                'kfe': ['92','93','94','95'],
                'tst': ['23','148','149','150','151'],
                'las': ['35','160','161','162','163'],
                'hpl': ['64']}

    if args.hutch:
        hutch=args.hutch
        if hutch in hutches:
            hutch=hutch.upper()
        else:
            for ihutch in hutches:
                if hutch.find(ihutch.upper())>=0:
                    hutch=ihutch.upper()
                    foundHutch=True
                    break
            if not foundHutch:
                print('unknown_hutch')
                sys.exit()
    else:
        hostname=socket.gethostname()
        ip=socket.gethostbyname(hostname)
        subnet=ip.split('.')[2]
        for ihutch in hutches: #use the IP address to match the host to a hutch by subnet
            if subnet in hutch_subnets.get(ihutch):
                hutch=ihutch.upper()
                foundHutch=True
                break
        if not foundHutch:
            for ihutch in hutches:
                if hostname.find(ihutch)>=0:
                    hutch=ihutch.upper()
                    foundHutch=True
                    break
        if not foundHutch:
            if hostname.find('psusr')>=0:
                if hostname.find('psusr13')>=0:
                    hutch='XPP'
                elif hostname.find('psusr21')>=0:
                    hutch='XCS'
                elif hostname.find('psusr22')>=0:
                    hutch='CXI'
                elif hostname.find('psusr23')>=0:
                    hutch='MEC'
                elif hostname.find('psusr24')>=0:
                    hutch='MFX'
                if hutch!='':
                    foundHutch=True
            else:
                #then check current path
                path=os.getcwd()
                for ihutch in hutches:
                    if path.find(ihutch)>=0:
                        hutch=ihutch.upper()
                        foundHutch=True
                        break
                if not foundHutch and path.find('xrt')+hostname.find('xrt')>=-1 or path.find('xtod')+hostname.find('xtod')>=-1:
                    hutch='LFE' #because we have so many names for the same subnet.
                    foundHutch=True
        if not foundHutch:
            #then ask.....outside of python
            print('unknown_hutch')
            sys.exit()
        if args.getHutch:
            print(hutch.upper())
            sys.exit()
        if args.gethutch:
            print(hutch.lower())
            sys.exit()

    #if hutch.lower() in ['mfx','cxi']:
    if hutch.lower() in ['cxi']:
        nstations = 2
        if args.station is not None:
            station = int(args.station)
        else:
            hostname=socket.gethostname()
            if 'monitor' in hostname:
                station = 1
            else:
                station = 0
        daq_base = '{:}_{:}'.format(hutch.lower(),station)
        instrument = '{:}:{:}'.format(hutch.upper(),station)
    elif hutch.lower() in ['rix']:
        station=2
    else:
        daq_base = hutch.lower()
        instrument = hutch.upper()
        nstations = 1
        if args.station:
            station = int(args.station)
        else:
            station=0

    if hutch.lower()!='rix' and station >= nstations:
        print("Invalid --station={:} keyword set for hutch {:}".format(hutch))
        sys.exit()

    if args.getstation:
        print(station)
        sys.exit()
    elif args.getinstrument:
        print(instrument)
        sys.exit()
    elif args.getbase:
        print(daq_base)
        sys.exit()
    elif args.getcnf:
        print(daq_base+'.cnf')
        sys.exit()

    import requests
    import logging
    ws_url = "https://pswww.slac.stanford.edu/ws/lgbk"
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    if args.exp:
        resp = requests.get(ws_url + "/lgbk/ws/activeexperiment_for_instrument_station", {"instrument_name": hutch, "station": station})
        exp = resp.json().get("value", {}).get("name")
        print(exp)

    if args.run:
        try:
            resp = requests.get(ws_url + "/lgbk/ws/activeexperiment_for_instrument_station", {"instrument_name": hutch, "station": station})
            exp = resp.json().get("value", {}).get("name")
            rundoc = requests.get(ws_url + "/lgbk/" + exp  + "/ws/current_run").json()["value"]
            if not rundoc:
                #logger.error("Invalid response from server")
                print('No runs taken yet')
            else:    
                if args.ended:
                    if rundoc.get('end_time', None) is not None:
                        print(int(rundoc['num']))
                    else:
                        print(int(rundoc['num'] - 1)) # Really bogus way to determine this; but copying over from previous code.
                else:
                    print(int(rundoc['num']))
                    if args.live:
                        if not rundoc.get('end_time', None):
                            print('live')
                        else:
                            print('ended')
        except:
            logger.exception("No runs?")
            print('No runs taken yet')

    if args.files_for_run or args.nfiles_for_run:
        if args.files_for_run:
            run = int(args.files_for_run)
        if args.nfiles_for_run:
            run = int(args.nfiles_for_run)

        if args.setExp:
            exp=args.setExp
        else:
            resp = requests.get(ws_url + "/lgbk/ws/activeexperiment_for_instrument_station", {"instrument_name": hutch, "station": station})
            exp = resp.json().get("value", {}).get("name")

        currundoc = requests.get(ws_url + "/lgbk/" + exp  + "/ws/current_run").json()["value"]
        runLast = int(currundoc['num'])
        if run > runLast:
            print('run %s not taken yet, last run is %s'%(run,runLast))
        else:
            file_list = requests.get(ws_url + "/lgbk/" + exp + "/ws/" + str(run) + "/files_for_live_mode").json()["value"]
            if args.files_for_run:
                for tfile in file_list:
                    print('/reg/d/psdm/'+tfile)
            elif args.nfiles_for_run:
                #look at files, remove stream 80, only first chunk, return number.
                nFiles=0
                for tfile in file_list:
                    tfilename = '/reg/d/psdm/'+tfile
                    if tfilename.find('c00')>=0 and tfilename.find('-s8')<0:
                        nFiles=nFiles+1
                print('%d %d'%(nFiles,len(file_list)))

if __name__ == "__main__":
   get_info(sys.argv[1:])