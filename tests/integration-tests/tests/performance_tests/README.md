# Performance Tests

## Available Test Suites

| Test | Purpose | Instance Requirements |
|------|---------|----------------------|
| `test_osu.py` | MPI latency and bandwidth benchmarks | EFA-enabled (c5n.18xlarge, p5, p6) |
| `test_starccm.py` | Real CFD workload performance | EFA-enabled (hpc6a.48xlarge) |
| `test_scaling.py` | Cluster scale-up/down timing | Any instance type |
| `test_startup_time.py` | Compute node bootstrap time | Any instance type |
| `test_simple.py` | Job scheduling metrics | Any instance type |
| `test_openfoam.py` | OpenFOAM CFD workload | EFA-enabled |

---

## Choosing the Right Test Configuration

### Instance Type Selection

| Goal | Recommended Instance       | Why |
|------|----------------------------|-----|
| MPI latency/bandwidth baseline | EFA-enabled (c5n.18xlarge) | Measures true network performance |
| System-level jitter detection | Any (e.g. c5.xlarge)       | Issue is CPU-bound, not network-bound |
| Scaling/bootstrap tests | Any (e.g. c5.large)        | Network performance not relevant |

### Node Count Selection

| Benchmark Type | Recommended Nodes | Rationale |
|----------------|-------------------|-----------|
| pt2pt (osu_latency, osu_bibw) | 2 | Only 2 ranks communicate|
| Collective (osu_allreduce, osu_barrier) | 200-500 | More nodes increase probability of detecting issues |
| StarCCM/OpenFOAM | 8-32 | Matches typical customer usage; diminishing returns beyond |
| Scaling tests | 1000+ | Tests scheduler and infrastructure at scale |

### Placement Group

| Scenario | Use Placement Group? | Why |
|----------|---------------------|-----|
| MPI performance baseline | Yes | Reduces network variance, cleaner signal |
| System jitter detection | Yes | Lower baseline makes jitter more visible |
| Scaling tests | Optional | May hit capacity limits at large scale |

---

## OSU Benchmarks Deep Dive

### Benchmark Categories

**Point-to-Point (pt2pt)**
- `osu_latency`: Measures round-trip latency between 2 ranks
- `osu_bibw`: Measures bidirectional bandwidth between 2 ranks
- Always uses exactly 2 nodes regardless of cluster size

**Collective**
- `osu_allreduce`: All ranks contribute and receive result
- `osu_allgather`: All ranks gather data from all other ranks
- `osu_barrier`: Pure synchronization (most sensitive to jitter)
- `osu_bcast`: One-to-all broadcast
- `osu_alltoall`: All-to-all personalized exchange
- Performance depends on the **slowest node** - scales with node count

### When to Use Each

| Issue to Detect | Best Benchmark | Node Count |
|-----------------|----------------|------------|
| EFA driver regression | osu_latency, osu_bibw | 2 |
| Network baseline | osu_latency | 2 |
| System daemon interference | osu_allreduce, osu_barrier | 200-500 |
| MPI library scaling bugs | osu_allreduce | 100+ |
| Multi-NIC bandwidth | osu_mbw_mr | 2 |

---

## Detecting System-Level Performance Issues

Some performance regressions are caused by system-level interference (daemons, background processes) rather than network issues.

### Characteristics of System-Level Issues

- Affects collective operations more than pt2pt
- More visible at scale (more nodes = higher probability of hitting the issue)
- Causes latency spikes/jitter rather than sustained degradation
- May be periodic (e.g., processes running on timers)

### Recommended Test Strategy

1. **Use collective benchmarks** (osu_allreduce, osu_barrier) - they're bottlenecked by the slowest node
2. **Scale to 200-500 nodes** - increases probability of detection
3. **Run multiple iterations** - captures variance
4. **Measure percentiles (p95, p99)** - not just averages
5. **Use placement group** - reduces network noise, makes system jitter more visible

### Example: Detecting Periodic Daemon Impact

If a daemon runs every 60 seconds on each node, and each time it consumes 1 second:
- With 2 nodes: ~3% chance of hitting it during a benchmark
- With 100 nodes: ~81% chance
- With 500 nodes: ~99.8% chance

---

## StarCCM and Real Workload Tests

### When StarCCM is Appropriate

| Use Case | Appropriate? |
|----------|--------------|
| Validating real HPC performance | Yes |
| Detecting network regressions | Yes |
| Detecting system jitter | No (metric too coarse) |

### Scaling Considerations

Current baselines (8/16/32 nodes) are sufficient for most regression detection. Scaling to 100+ nodes makes it harder to maintain stable baselines.

---

## NCCL Tests

NCCL tests measure GPU-to-GPU communication performance.

### When NCCL Tests Are Useful

| Issue Type | NCCL Useful? |
|------------|--------------|
| EFA driver regression | Yes |
| NCCL library bugs | Yes |
| GPU driver issues | Yes |
| System daemon interference | No (GPU ops are async from CPU) |

### Current Configuration

- Runs on 2 GPU nodes (p4d, p5, p6)
- Measures `all_reduce_perf` bandwidth
- Validates multi-NIC EFA configuration


---

## Job Scheduling Metrics

The outcomes of a job time statistics:
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



