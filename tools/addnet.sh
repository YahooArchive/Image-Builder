#!/bin/bash

# Adds a simple network (basically a dhcp net)
# to a given image, useful for allowing it to boot
# under the given libvirt.xml (without modifications)

set -u
set -e

if [ "$(id -u)" != "0" ]
then
   echo "This script must be run as root!" 1>&2
   exit 1
fi

if [ $# -ne 1 ]
then
    echo "Usage: `basename $0` raw-img-file"
    exit 1
fi

FILE=$1
DATE=`date`
CREATED_BY=`whoami`

WHERE=`losetup -f --show $1`
echo "Loopback device created at $WHERE..."

TMP_DIR=$(mktemp -d)
mount $WHERE $TMP_DIR
echo "Mounted at $TMP_DIR..."

echo "Beginning 'basic' network injection..."

touch $TMP_DIR/etc/sysconfig/network
cat >> $TMP_DIR/etc/sysconfig/network <<EOF
# Created by $CREATED_BY on $DATE
NETWORKING=yes
EOF

cat $TMP_DIR/etc/sysconfig/network

touch $TMP_DIR/etc/sysconfig/network-scripts/ifcfg-eth0
cat > $TMP_DIR/etc/sysconfig/network-scripts/ifcfg-eth0 <<EOF
# Created by $CREATED_BY on $DATE
DEVICE=eth0
BOOTPROTO=dhcp
ONBOOT=yes
EOF

cat $TMP_DIR/etc/sysconfig/network-scripts/ifcfg-eth0

echo "Cleaning up..."
sync
/bin/umount $TMP_DIR
losetup -d $WHERE
rm -rf $TMP_DIR

echo "Done!"
exit 0

