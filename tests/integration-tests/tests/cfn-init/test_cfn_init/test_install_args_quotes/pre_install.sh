#!/bin/bash

echo "pre-install script has $# arguments"
for arg in "$@"
do
    echo "arg: ${arg}"
done

case $# in
    4)
        exit 0
    ;;
    *)
        exit 1
esac