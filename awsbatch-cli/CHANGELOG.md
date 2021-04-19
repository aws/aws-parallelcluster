CHANGELOG
=========

1.0.0
------

**ENHANCEMENTS**

- Add check to verify if the cluster provided with the `--cluster` command is using AWS Batch as a scheduler.

**CHANGES**

- First release on PyPI. AWS Batch related commands `awsbhosts`, `awsbkill`, `awsbout`, `awsbqueues`, `awsbstat` 
  and `awsbsub` have been moved from `aws-parallelcluster` to `aws-parallelcluster-awsbatch-cli` PyPI package.
