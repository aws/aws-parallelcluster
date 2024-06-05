#!/usr/bin/env python3

import aws_cdk as cdk
from external_slurmdbd.external_slurmdbd_stack import ExternalSlurmdbdStack

app = cdk.App()
ExternalSlurmdbdStack(
    app, "ExternalSlurmdbdStack", synthesizer=cdk.DefaultStackSynthesizer(generate_bootstrap_version_rule=False)
)

app.synth()
