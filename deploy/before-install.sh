#!/bin/bash

name=pydtm
getent group $name >/dev/null 2>&1 \
    || groupadd -r $name >/dev/null 2>&1 \
    || true
getent passwd $name >/dev/null 2>&1 \
    || useradd  -g $name -c "$name service" \
        -d /var/lib/$name -M -s /sbin/nologin -r \
        -G video $name >/dev/null 2>&1 \
    || true
