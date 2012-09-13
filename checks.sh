#!/bin/bash

function find_src {
  files=`find builder -type f | grep "py\$"`
  echo "build.py $files"
}

function run_pylint {
    echo "Running pylint ..."
    opts="--rcfile=pylintrc --output-format=parseable"
    files=$(find_src)
    output_filename="pylint.log"
    pylint ${opts} ${files} 2>&1 > $output_filename
    echo "Check '$output_filename' for a full report."
}

run_pylint
