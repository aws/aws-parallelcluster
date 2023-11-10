#!/usr/bin/env python3

import aws_cdk as cdk
from external_slurmdbd.external_slurmdbd_stack import ExternalSlurmdbdStack

app = cdk.App()
ExternalSlurmdbdStack(app, "ExternalSlurmdbdStack")

app.synth()
