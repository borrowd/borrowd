#!/bin/sh
set -eu

if [ -w /dev/tty ]; then
    printf "\n" > /dev/tty
    uv run manage.py test --verbosity 1 > /dev/tty 2>&1
    printf "\n" > /dev/tty
else
    uv run manage.py test --verbosity 1
fi
