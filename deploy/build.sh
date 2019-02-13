#/bin/bash

release=${RELEASE:-0}
# TODO: read from git tags?
if [ -z "$VERSION" ]; then
  echo '$VERSION not set, exiting' 1>&2
  exit 1
fi

# build root filesystem
root=$(mktemp -d)
install -m 0755 -d $root/{lib/systemd/system,etc,usr/bin,var/lib/pydtm}
install -m 0644 pydtm.service $root/lib/systemd/system/
install -m 0644 pydtm.env $root/etc/
install -m 0755 -T ../pydtm.py $root/usr/bin/pydtm

# build package
fpm -s dir -t deb -n pydtm -v $VERSION-$release -C $root \
    --description "carbon API server"                    \
    --before-install before-install.sh                   \
    -d python                                            \
    etc lib usr var
