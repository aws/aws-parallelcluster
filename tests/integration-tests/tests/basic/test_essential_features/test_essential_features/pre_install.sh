#!/bin/bash

echo "pre-install script has $# arguments"
for arg in "$@"
do
    echo "arg: ${arg}"
done

case $# in
    3)
        sudo mkdir -p /etc/systemd/system/nfs-mountd.service.d
        printf '[Service]\nExecStartPre=/bin/false\n' | sudo tee /etc/systemd/system/nfs-mountd.service.d/inject-fail.conf
        sudo systemctl daemon-reload
        exit 0
    ;;
    *)
        exit 1
esac
