#!/bin/bash

echo "post-install script has $# arguments"
for arg in "$@"
do
    echo "arg: ${arg}"
done

case $# in
    3)
        exit 0
    ;;
    *)
        exit 1
esac
