# pydtm
Python (Euro)DOCSIS (3.0) Traffic Meter

## Overview

This tool uses a DVB-C capable video card (e.g. a cheap USB stick) to measure
the EuroDOCSIS 3.0 traffic per frequency, allowing you to venture an educated
guess about your local segment's utilization.

Data is written to a UDP socket in [graphite](https://graphiteapp.org/)
format.

## Requirements

This was tested with cPython 2.7.13 and cPython 3.5.3 using a Hauppauge WinTV
soloHD USB stick on a Raspberry Pi 3 running Raspbian/stretch.

It should however work with most Python versions as long as the DVB-C card
is supported by your kernel and it's driver complies with the DVBv5 API.


## FAQ

### How and why does this even  work?

EuroDOCSIS 3.0 uses standard DVB-C mechanisms to transport it's data: It's
encoded as a standard MPEG Transport Stream on
[PID](https://en.wikipedia.org/wiki/MPEG_transport_stream#Packet_Identifier_\(PID\))
8190 with either 64- or 256-
[QAM](https://en.wikipedia.org/wiki/QAM_\(television\))
modulation with a symbol rate of 6952ksyms/s. Since cable is a shared medium,
determining the total amount of data transferred and comparing this to the total
amount possible after
[FEC](https://en.wikipedia.org/wiki/Forward_error_correction) (which is about
51Mbit/s for 256-QAM and 34 MBit/s for 64-QAM) will show you how much capacity
is used.

# How do I determine downstream frequencies?

Take a look at your cable modem's management pages.

### Wait, I can read my neighbours data with this?

No, you can't.

### Why Python?

I wanted to learn Python.

### Why output data to UDP? Why not text files, sockets, ...?

You can easily use tools like `netcat` to capture the data.

### This is downstream only, right?

Yes. You would probably not see other cable modems upstream signals due to...
erm, "electrical" stuff.
