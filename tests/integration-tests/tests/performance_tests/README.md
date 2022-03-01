# Performance Test

Performance tests allow you to compare the performance of a given cluster configuration with respect to a pre-defined baseline.

The outcomes of a performance test are:
1. statistics from the observed metrics
2. box-plots comparing the candidate configuration under tests with respect to the baseline
3. test failure if the candidate configuration under test
4. if the test fails it suggests the empirical tolerance level, that is the tolerance that would have made the test to succeed.

### Requirements
Install dependencies in `tests/integration-tests/requirements.txt`.

### Baseline
We consider as a baseline the results produced by a cluster v3.1.1 having the configuration defined in 
`tests/integration-tests/tests/performance_tests/test_simple/test_simple/pcluster.config.yaml`.

### Metrics
Performance tests allow you to observe the following metrics:
1. **jobRunTime:** `jobEndTimestamp - jobStartTimestamp`
2. **jobWaitingTime:** `jobStartTimestamp - jobSubmissionTimestamp`
3. **jobWarmupFirstNodeTime:** `jobStartTimestamp - firstComputeNode.instancePreInstallTimestamp`,
   where the *first compute node* is the compute node that started first.
4. **jobWarmupLastNodeTime:** `jobStartTimestamp - lastComputeNode.instancePreInstallTimestamp`,
   where the *last compute node* is the compute node that started last.
5. **jobWarmupLeaderNodeTime:** `jobStartTimestamp - leaderComputeNode.instancePreInstallTimestamp`,
   where the *leader compute node* is the compute node that starts the job execution.
6. **instancePreInstallUpTime:** the uptime of compute nodes recorded in pre-install phase.
7. **instancePostInstallUpTime:** the uptime of compute nodes recorded in post-install phase.


### Tolerance
A performance test fails if the statistics for the candidate configuration are worse than the baseline over the given level of tolerance.
In particular a check fails if the following holds true:

```
threshold_value = float(baseline_value * (1.0 + tolerance_value))
candidate_value > threshold_value
```

The tolerance level is defined for every statistic in `tests/integration-tests/tests/performance_tests/resources/results/tolerance.json`.
The structure of this file is as follows:
```
{
  "[Metric Name]": {
    "min": "[Float value or inf]",
    "max": "[Float value or inf]",
    "avg": "[Float value or inf]",
    "std": "[Float value or inf]",
    "med": "[Float value or inf]",
    "prc25": "[Float value or inf]",
    "prc75": "[Float value or inf]"
  },
  ... Other metrics ...
}
```

If `inf` is specified as a tolerance level (infinite tolerance), than any candidate value will pass the check.

When a performance test fails due to a candidate configuration exceeding the tolerance level, 
the suit suggest an alternative tolerance level that would have made the test to succeed.


### Results
Results are stored in `test-outputs/TEST_ID.out/performance-tests`:
1. Samples and statistics are stored in `test-outputs/TEST_ID.out/performance-tests/data`
2. Plots from the above data are stored in `test-outputs/TEST_ID.out/performance-tests/plots`

In particular, the following artifacts are created:
4. **samples.json:** contains samples of all the observed metrics.
   The structure of this file is as follows:
```
{
  "jobRunTimeSample": [Comma separated list of int (millis)],
  "jobWaitingTimeSample": [Comma separated list of int (millis)],
  "jobWarmupLeaderNodeTimeSample": [Comma separated list of int (millis)],
  "jobWarmupFirstNodeTimeSample": [Comma separated list of int (millis)],
  "jobWarmupLastNodeTimeSample": [Comma separated list of int (millis)],
  "instancePreInstallUpTimeSample": [Comma separated list of int (seconds)],
  "instancePostInstallUpTimeSample": [Comma separated list of int (seconds)]
}
```

2. **statistics.json:** contains the following statistics for every observed metric: minimum, maximum, average, standard deviation, median, 25th percentile, 75th percentile.
   The structure of this file is as follows:
```
{
  "[Metric Name]": {
    "min": "[Float value]",
    "max": "[Float value]",
    "avg": "[Float value]",
    "std": "[Float value]",
    "med": "[Float value]",
    "prc25": "[Float value]",
    "prc75": "[Float value]"
  },
  ... Other metrics ...
}
```

3. **Plots:** for every observed metric, a box-plot is created to compare the cluster under test with the given baseline.

## Usage
Performance tests are implemented as a self-enclosed dedicated test case, so you can execute them as any other test case.
In particular, you can launch them locally using the `test_runner` provided by our integration testing framework.

See below an example of launch:
```
#!/bin/bash

TEST_SCOPE="performance-test"

current_time=$(date "+%Y.%m.%d-%H.%M.%S")
logfile=$(mktemp /tmp/test-runner.${TEST_SCOPE}.${current_time})

VPC_STACK=[Name of the VPC stack, if any]
IAM_STACK=[Name of the IAM stack, if any]
CLUSTER_STACK=[Name of the Cluster stack, if any]

[[ -n "${VPC_STACK}" ]] && VPC_PARAM="--vpc-stack ${VPC_STACK}"
[[ -n "${IAM_STACK}" ]] && IAM_PARAM="--iam-user-role-stack-name ${IAM_STACK}"
[[ -n "${CLUSTER_STACK}" ]] && CLUSTER_PARAM="--cluster ${CLUSTER_STACK}"

echo "Launching test with scope ${TEST_SCOPE} using pcluster ${PCLUSTER_VERSION}"

AWS_DEFAULT_REGION=[Region Name, e.g. eu-west-1]
KEY_NAME="my-pem-key-name"
KEY_PATH="/path/to/my-pem-key-name.pem"
CONFIG_PATH="/path/to/aws-parallelcluster/tests/integration-tests/configs/performance_tests.yaml"
NO_DELETE_PARAM="--no-delete"

PYTHONPATH="${AWS_PCLUSTER_REPO_PATH}/cli/src" \
python3 -m test_runner \
    -c ${CONFIG_PATH} \
    --key-name ${KEY_NAME} \
    --key-path ${KEY_PATH} \
    --show-output \
    --sequential \
    --stackname-suffix ${TEST_SCOPE} ${VPC_PARAM} ${IAM_PARAM} ${CLUSTER_PARAM} ${NO_DELETE_PARAM} | tee -a ${logfile}

echo "Logfile: ${logfile}"
```



