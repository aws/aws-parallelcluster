#!/bin/bash

OUTPUT="/shared/SubspaceBenchmarks/results/openfoam/openfoam.csv"

cut -d, -f5 $OUTPUT
