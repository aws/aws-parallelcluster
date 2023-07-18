#!/bin/bash

OUTPUT=/shared/ec2-user/SubspaceBenchmarks/results/openfoam/openfoam.csv

cut -d, -f5 $OUTPUT
