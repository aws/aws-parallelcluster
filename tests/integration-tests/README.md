# AWS ParallelCluster Integration Testing Framework

The framework used to implement and run integration tests for AWS ParallelCluster is made of two main components:
* **Integration Tests Orchestrator**: is a cli that allows to submit the integration tests. It takes care of setting
up the test environment, it orchestrates parallel tests execution and generates the final tests reports.
* **Integration Tests Framework**: the actual testing framework, based on pytest, which defines a series of
fixtures and markers that allows to parametrize tests execution across several dimensions, to easily manage clusters
lifecycle and re-usage and to perform cleanup on failures. It also offers a set of utility functions
that implement features which are common to all tests such as remote command execution and ParallelCluster
config generation.

## Run Integration Tests

Before executing integration tests it is required to install all the python dependencies required by the framework.
In order to do that simply run the following command:
```bash
pip install -rtests/integration-tests/requirements.txt
```

Once this is done you can look at the helper of the orchestrator cli in order to list all the available options:
```bash
cd tests/integration-tests
python -m test_runner -h
```

Here is an example of tests submission:
```bash
python -m test_runner \
    --key-name "ec2-key-name" \
    --key-path "~/.ssh/ec2-key.pem" \
    --regions "eu-west-1" "us-east-1" \
    --instances "c4.xlarge" "c5.xlarge" \
    --oss "alinux" "centos7" \
    --schedulers "awsbatch" "sge" \
    --parallelism 8 \
    --retry-on-failures \
    --reports html junitxml json
```

Executing the command will run an integration testing suite with the following features:
* "ec2-key-name" is used to configure EC2 keys
* "~/.ssh/ec2-key.pem" is used to ssh into cluster instances and corresponds to the EC2 key ec2-key-name
* tests are executed in all combinations of (region, instance, os, scheduler) where each dimension is expanded
with the specified values.
* tests are executed in parallel in all regions and for each region 8 tests are executed concurrently
* in case of failures the failed tests are retried once more after a delay of 60 seconds
* tests reports are genarated in html, junitxml and json formats

#### Tests Outputs & Reports

The following options can be used to control test outputs and reports:
* `--output-dir path/to/dir`: specifies the base dir where test outputs and logs will be saved.
Defaults to tests_outputs.
* `--reports {html,junitxml,json}`: allows to select what tests reports to generate.
* `--show-output`: when specified does not redirect stdout to file. Useful when developing the tests but not
recommended when running parallel tests.

Here is what files are produced by the tests and where these files are stored when running with default `output-dir`
and `--reports html junitxml json`:
```
tests_outputs
├── $timestamp.logs: directory containing log files
│   ├── $region_i.log: log outputs for a single region
│   └── ...
└── $timestamp.out: directory containing tests reports
    ├── $region_i: directory contaitning tests reports for a single region
    │   ├── clusters_configs: directory storing all cluster configs used by test
    │   │   ├── test_awsbatch.py::test_job_submission[c5.xlarge-eu-west-1-alinux-awsbatch].config
    │   │   └── ...
    │   ├── pytest.out: stdout of pytest for the given region
    │   ├── results.html: html report for the given region
    │   └── results.xml: junitxml report for the given region
    ├── test_report.json: global json report 
    └── test_report.xml: global junitxml report
```

If tests are ran sequentially by adding the `--sequential` option the result is the following:
```
tests_outputs
├── $timestamp..logs
│   └── all_regions.log: log outputs for all regions
└── $timestamp..out
    ├── clusters_configs: directory storing all cluster configs used by test
    │   ├── test_playground.py::test_factory.config
    │   └── ...
    ├── pytest.out: global pytest stdout
    ├── results.html: global html report 
    ├── results.xml: same as test_report.xml
    ├── test_report.json: global json report 
    └── test_report.xml: global junitxml report
```

#### Specify Tests Dimensions
The following options can be used to control the parametrization of test cases:
* `-r REGIONS [REGIONS ...], --regions REGIONS [REGIONS ...]`: AWS region where tests are executed.
* `-i INSTANCES [INSTANCES ...], --instances INSTANCES [INSTANCES ...]`: AWS instances under test.
* `-o OSS [OSS ...], --oss OSS [OSS ...]`: OSs under test.
* `-s SCHEDULERS [SCHEDULERS ...], --schedulers SCHEDULERS [SCHEDULERS ...]`: Schedulers under test.

Note that each test case can specify a subset of dimensions it is allowed to run against (For example
a test case written specifically for the awsbatch scheduler should only be executed against the awsbatch scheduler.
This means that the final parametrization of the tests is given by an intersection of the input dimensions and
the tests specific dimensions so that all constraints are verified.

#### Parallelize Tests Execution
The following options can be used to control tests parallelism:
* `--sequential`: by default the tests orchestrator executes a separate parallel process for each region under test.
By specifying this option all tests are executed sequentially in a single process. 
* `-n PARALLELISM, --parallelism PARALLELISM`: allows to specify the degree of parallelism for each process. It is
useful to limit the number of clusters that are crated concurrently in a specific region so that AWS account limits
can be guaranteed.

#### Retry On Failures
When passing the `--retry-on-failures` flag failed tests are retried once more after a delay of 60 seconds.

#### Run Tests For Specific Features 
The `-f FEATURES [FEATURES ...], --features FEATURES [FEATURES ...]` option allows to limit the number of test
cases to execute by only running those that are meant to verify a specific feature or subset of features.

To execute a subset of features simply pass with the `-f` option a list of markers that identify the test cases
to run. For example when passing `-f "awsbatch" "not advanced"` all test cases marked with `@pytest.mark.awsbatch` and
not marked with `@pytest.mark.advanced` are executed.

It is a good practice to mark test cases with a series of markers that allow to identify the feature under test.

