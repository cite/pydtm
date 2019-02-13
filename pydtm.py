#!/usr/bin/env python

# Python (Euro)DOCSIS Traffic Meter
# Copyright (C) 2018 Stefan Förster

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import argparse
import ctypes
import fcntl
import logging
import os
import select
import time
import timeit
import traceback
import socket
import sys

# DVB constants from Linux kernel files
DMX_IMMEDIATE_START = 0x4
DMX_IN_FRONTEND = 0x0
DMX_OUT_TS_TAP = 0x2
DMX_PES_OTHER = 0x14
DMX_SET_BUFFER_SIZE = 0x6f2d # ioctl
DMX_SET_PES_FILTER = 0x40146f2c # ioctl
DMX_STOP = 0x6f2a
DTV_DELIVERY_SYSTEM = 0x11
DTV_FREQUENCY = 0x3
DTV_INNER_FEC = 0x9
DTV_INVERSION = 0x6
DTV_MODULATION = 0x4
DTV_SYMBOL_RATE = 0x8
DTV_TUNE = 0x1
FEC_AUTO = 0x9
FE_READ_STATUS = -0x7ffb90bb # ioctl
FE_SET_PROPERTY = 0x40086f52 # ioctl
INVERSION_OFF = 0x0
QAM_256 = 0x5
QAM_64 = 0x3
SYS_DVBC_ANNEX_AC = 0x1

# mappings for DVB API data types - this code was copied
# more or less verbatim from: https://pypi.org/project/linuxdvb/
class dtv_property(ctypes.Structure):
    class _u(ctypes.Union):
        class _s(ctypes.Structure):
            _fields_ = [
                ('data', ctypes.c_uint8 * 32),
                ('len', ctypes.c_uint32),
                ('reserved1', ctypes.c_uint32 * 3),
                ('reserved2', ctypes.c_void_p)
            ]
        _fields_ = [
            ('data', ctypes.c_uint32),
            ('buffer', _s)
        ]
    _fields_ = [
        ('cmd', ctypes.c_uint32),
        ('reserved', ctypes.c_uint32 * 3),
        ('u', _u),
        ('result', ctypes.c_int)
    ]
    _pack_ = True
class dtv_properties(ctypes.Structure):
    _fields_ = [
        ('num', ctypes.c_uint32),
        ('props', ctypes.POINTER(dtv_property))
    ]
class dvb_qam_parameters(ctypes.Structure):
    _fields_ = [
        ('symbol_rate', ctypes.c_uint32),
        ('fec_inner', ctypes.c_uint),
        ('modulation', ctypes.c_uint)
    ]
class dvb_frontend_parameters(ctypes.Structure):
    class _u(ctypes.Union):
        _fields_ = [
            ('qam', dvb_qam_parameters),
        ]
    _fields_ = [
        ('frequency', ctypes.c_uint32),
        ('inversion', ctypes.c_uint),
        ('u', _u)
    ]
class dvb_frontend_status(ctypes.Structure):
    _fields_ = [
        ('status', ctypes.c_uint),
    ]
class dmx_pes_filter_params(ctypes.Structure):
    _fields_ = [
        ('pid', ctypes.c_uint16),
        ('input', ctypes.c_uint),
        ('output', ctypes.c_uint),
        ('pes_type', ctypes.c_uint),
        ('flags', ctypes.c_uint32)
    ]
# end code copied from https://pypi.org/project/linuxdvb/


def init_logging():
    logger.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(levelname)s: %(message)s')
    ch.setFormatter(formatter)
    logger.addHandler(ch)

def build_configuration():
    # parse command line arguments
    parser = argparse.ArgumentParser(
        description="pydtm - measure EuroDOCSIS 3.0 data rate",
        epilog="Note: By default, each frequency is scanned for step/num(frequencies) seconds. " \
               "All parameters can also be passed as environment variables, e.g. PYDTM_ADAPTER, " \
               "PYDTM_CARBON, PYDTM_DEBUG, PYDTM_FREQUENCIES, PYDTM_PREFIX, PYDTM_STEP and" \
               "PYTDM_TUNER."
    )
    parser.add_argument("-a", "--adapter", type=int, default=0, help="use /dev/dvb/adapterN devices (default: 0)")
    parser.add_argument("-c", "--carbon", type=str, default="localhost:2003", help="address:port of carbon sink (default: localhost:2003)")
    parser.add_argument("-d", "--debug", action="store_true", help="enable debug logging (default: not enabled)")
    parser.add_argument("-f", "--frequencies", type=str, default="546", help="a list of 'frequency' or 'frequency:modulation' pairs (default: 546:256)")
    parser.add_argument("-p", "--prefix", type=str, default="docsis", help="carbon prefix/tree location (default: docsis)")
    parser.add_argument("-s", "--step", type=int, default="60", help="metrics backend default resolution in seconds (default: 60)")
    parser.add_argument("-t", "--tuner", type=int, default=0, help="use adapter's frontendN/dmxN/dvrN devices (default: 0)")
    args = parser.parse_args()

    # overwrite with environment values
    if 'PYDTM_ADAPTER' in os.environ:
        logger.debug('reading adapter from environment')
        try:
            args.adapter = os.environ['PYDTM_ADAPTER']
        except:
             logger.error('error parsing PYDTM_ADAPTER value {} as integer, using {} instead'.format(os.environ['PYDTM_ADAPTER'], args.adapter))
    if 'PYDTM_CARBON' in os.environ:
        logger.debug('reading carbon sink from environment')
        args.carbon = os.environ['PYDTM_CARBON']
    if 'PYDTM_DEBUG' in os.environ:
        logger.debug('reading debug flag from environment')
        args.debug = True
    if 'PYDTM_FREQUENCIES' in os.environ:
        logger.debug('reading frequency list from environment')
        args.frequencies = os.environ['PYDTM_FREQUENCIES']
    if 'PYDTM_PREFIX' in os.environ:
        logger.debug('reading carbon prefix/tree location from environment')
        args.frequencies = os.environ['PYDTM_PREFIX']
    if 'PYDTM_STEP' in os.environ:
        logger.debug('reading metrics store resolution from environment')
        try:
            args.step = int(os.environ['PYDTM_STEP'])
        except:
            logger.error('error parsing PYDTM_STEP value {} as integer, using {} instead'.format(os.environ['PYDTM_STEP'], args.step))
    if 'PYDTM_TUNER' in os.environ:
        logger.debug('reading tuner from environment')
        try:
            args.adapter = os.environ['PYDTM_TUNER']
        except:
             logger.error('error parsing PYDTM_TUNER value {} as integer, using {} instead'.format(os.environ['PYDTM_TUNER'], args.tuner))

    # generate a list of frequencies
    frequencies=[]
    for f in args.frequencies.split(","):
        if (f.find(":") < 0):
            try:
                frequencies.append((int(f), QAM_256))
            except:
                logger.critical('error parsing frequency {} as string, aborting'.format(f))
                exit(1)
            logger.debug('added frequency {}MHz'.format(f))
        else:
            f, m = f.split(":")
            try:
                f = int(f)
            except:
                logger.critical('error parsing frequency {} as string, aborting'.format(f))
                exit(1)
            if (m == "256"):
                logger.debug('adding frequency {}MHz with modulation QAM_{}'.format(f, m))
                frequencies.append((f, QAM_256))
            elif (m == "64"):
                logger.debug('adding frequency {}MHz with modulation QAM_{}'.format(f, m))
                frequencies.append((f, QAM_64))
            else:
                logger.critical('invalid modulation QAM_{} detected, aborting'.format(m))
                exit(1)

    # generate carbon destination
    carbon_port = 2003
    carbon_host = "localhost"
    if (args.carbon.find(":") > 0):
        carbon_host, carbon_port = args.carbon.split(':')
        try:
            carbon_port = int(carbon_port)
        except:
            logger.critical('unable to parse port {} as an integer, aborting'.format(carbon_port))
            exit(1)
    elif (args.carbon.find(':') < 0):
        carbon_host = args.carbon
    else:
        logger.error('invalid carbon sink, aborting')
        exit(1)


    # show all log settings
    logger.debug('adapter={}'.format(args.adapter))
    logger.debug('carbon={}'.format(args.carbon))
    logger.debug('debug={}'.format(args.debug))
    logger.debug('frequencies={}'.format(frequencies))
    logger.debug('prefix={}'.format(args.prefix))
    logger.debug('step={}'.format(args.step))
    logger.debug('tuner={}'.format(args.tuner))

    # make sure we got at least one second per frequency
    if (args.step / len(frequencies) < 1):
        logger.warning(
            'A step of {} seconds with {} different frequencies will result in less than one second' \
            'of scan time per frequency, which is not suppored. Aborting'.format(args.step, len(frequencies))
        )

    return args.adapter, (carbon_host, carbon_port), args.debug, frequencies, args.prefix, args.step, args.tuner


def tune(fd, frequency, modulation):
    logger.debug('tuning to frequency {} with modulation {}'.format(frequency, modulation))
    # we are about to issue 7 commands to the DVB frontend
    # let's do the ctypes dance
    proptype = dtv_property * 7
    prop = proptype()
    # set delivery system to DVB-C
    prop[0].cmd = DTV_DELIVERY_SYSTEM
    prop[0].u.data = SYS_DVBC_ANNEX_AC
    # set modulation
    # TODO: support QAM_AUTO?
    prop[1].cmd = DTV_MODULATION
    prop[1].u.data = modulation
    # set EuroDOCSIS symbol rate
    prop[2].cmd = DTV_SYMBOL_RATE
    prop[2].u.data = 6952000
    # DOCSIS profiles always set frequency inversion to off
    prop[3].cmd = DTV_INVERSION
    prop[3].u.data = INVERSION_OFF
    # autodetect Forward Error Correction
    prop[4].cmd = DTV_INNER_FEC
    prop[4].u.data = FEC_AUTO
    # set frequency
    prop[5].cmd = DTV_FREQUENCY
    prop[5].u.data = frequency
    # tell the kernel to actually tune into the given frequency
    prop[6].cmd = DTV_TUNE
    dtv_props = dtv_properties()
    dtv_props.num = 7
    dtv_props.props = ctypes.pointer(prop[0])
    if (fcntl.ioctl(fd, FE_SET_PROPERTY, dtv_props) == 0):
        # determine wheter the frontend actually has a lock
        # FIXME: why do I need this?
        time.sleep(0.250)
        # make sure the FE has a lock
        festatus = dvb_frontend_status()
        if (fcntl.ioctl(fd, FE_READ_STATUS, festatus) == 0):
            if (festatus.status & 0x10) == 0:
                logger.error('frontend has no lock')
                return -1
        else:
            logger.error('FE_READ_STATUS failed, unable to verify signal lock')
            return -1
    else:
        logger.error('FE_SET_PROPERTY failed, unable to tune')
        return -1
    logger.debug('tuning successful')
    return 0

def start_demuxer(fd):
    # DOCSIS uses the MPEG-TS Packet Identifier 8190
    # tell the demuxer to get us the transport stream
    logger.debug('starting demuxer')
    pesfilter = dmx_pes_filter_params()
    pesfilter.pid = 8190
    pesfilter.input = DMX_IN_FRONTEND
    pesfilter.output = DMX_OUT_TS_TAP
    pesfilter.pes_type = DMX_PES_OTHER
    pesfilter.flags = DMX_IMMEDIATE_START
    if (fcntl.ioctl(fd, DMX_SET_PES_FILTER, pesfilter) != 0):
        logger.error('unable to start demuxer')
        return -1
    logger.debug('demuxer initialization successful')
    return 0

def stop_demuxer(fd):
    logger.debug('stopping demuxer')
    if(fcntl.ioctl(fd, DMX_STOP) != 0):
        logger.error('DMX_STOP failed, unable to stop demuxer (erm, what?)')
        return -1
    return 0

def main():
    # initialize console logger
    init_logging()

    # simulate frequency and modulation list
    adapter, carbon, debug, frequencies, prefix, step, tuner = build_configuration()

    # update log level
    if not debug:
        logger.setLevel(logging.INFO)
    else:
        logger.setLevel(logging.DEBUG)

    # open the frontend device, demuxer and DVR device
    logger.debug('about to open adapter {}, tuner {} devices'.format(adapter, tuner))
    adapter = '/dev/dvb/adapter' + str(adapter)
    try:
        fefd =  open(adapter + '/frontend' + str(tuner), 'r+')
        dmxfd = open(adapter +'/demux'     + str(tuner), 'r+')
        dvrfd = open(adapter +'/dvr'       + str(tuner), 'rb')
    except Exception as err:
        logger.error('Unable to open devices, aborting. Stacktrace was: ' + traceback.format_exc())
        exit(1)

    # the demux device needs to be opened non blocking
    flag = fcntl.fcntl(dvrfd, fcntl.F_GETFL)
    fcntl.fcntl(dvrfd, fcntl.F_SETFL, flag | os.O_NONBLOCK)

    # we will need to poll the DVR
    dvr_poller = select.poll()
    dvr_poller.register(dvrfd, select.POLLIN | select.POLLPRI)

    # create sending socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    # set appropriate buffer size
    # MPEG-TS are chopped into (at most) 188 sections
    ts_length = 188
    ts_buffer = ts_length * 2048
    logger.debug('setting demuxer buffer size to {}'.format(ts_buffer))
    if (fcntl.ioctl(dmxfd, DMX_SET_BUFFER_SIZE, ts_buffer) != 0):
        logger.error('DMX_SET_BUFFER_SIZE failed, aborting')
        fefd.close()
        dmxfd.close()
        dvrfd.close()
        exit(1)

    # begin main loop
    logger.debug('starting main event loop')
    while True:
        # prepare message array for sending to carbon
        carbon_messages = []
        # iterate over all given frequency and modulation paris
        for f, m in frequencies:
            # try tuning
            if (tune(fefd, (f * 1000000), m) != 0):
                break

            # at this point, we can poll data from /dev/dvb/adapter0/dvr0,
            # which we will promptly do, defining a 2s timeout
            timeout = 2
            count=0

            if(start_demuxer(dmxfd) != 0):
                break

            start_time = timeit.default_timer()
            end_time = start_time
            # make sure we spend at most (step / number of frequencies) second per frequency
            logger.debug('spending about {}s with data retrieval'.format((step / len(frequencies))))
            while (end_time - start_time) < (step / len(frequencies)):
                # interrupting a poll() system call will cause a traceback
                # using try/except will suppress that for SIGTERM, but not for SIGINT 
                # (Python got it's own SIGINT handler)
                try:
                    events = dvr_poller.poll(timeout * 1000)
                except:
                    logger.warn('event polling was interrupted, stacktrace: ' + traceback.format_exc())
                    # try to stop the demuxer
                    stop_demuxer(dmxfd)
                    break

                for fd, flag in events:
                    if flag & (select.POLLIN | select.POLLPRI):
                        data = dvrfd.read(ts_buffer)
                        count += len(data)
                        end_time = timeit.default_timer()
                        elapsed = (end_time - start_time)
            # record final end time
            end_time = timeit.default_timer()
            elapsed = (end_time - start_time)

            # stop filtering
            if (stop_demuxer(dmxfd) != 0):
                break

            # append data to carbon message
            if (m == QAM_256):
                m_type = 'qam256'
            else:
                m_type = 'qam64'
            carbon_messages.append('{}.{}.{} {} {}'.format(prefix, m_type, f, (count/elapsed), int(time.time())))
            # for debugging purposes, output data
            logger.debug('frequency {}: spent {}s, got {} packets ({} bytes) equaling a rate of {}kBit/s'.format(
                f, elapsed, len(data)/ts_length, len(data), ((count*8)/elapsed)/1024
            ))
        # send data
        for cm in carbon_messages:
            logger.debug('sending to carbon: {}'.format(cm))
            sock.sendto((cm + '\n').encode(), carbon)

    # close devices
    # TODO: this will actually never be called, right?
    dvrfd.close()
    dmxfd.close()
    fefd.close()
    sock.close()

if __name__ == '__main__':
    logger = logging.getLogger()
    main()
