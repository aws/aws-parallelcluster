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
* tests reports are generated in html, junitxml and json formats

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
Every test is marked by default with a marker matching its filename with the `test_` prefix or `_test` suffix removed.

## Write Integration Tests

All integration tests are defined in the `integration-tests/tests` directory.

When executing the test_runner, tests are automatically discovered by following the default pytest discovery rules:
* search for `test_*.py` or `*_test.py` files, imported by their test package name.
* from those files, collect test items:
  * `test_` prefixed test functions or methods outside of class
  * `test_` prefixed test functions or methods inside `Test` prefixed test classes (without an `__init__` method)

Test cases are organized in separate files where the file name is `test_$feature_under_test`. For example test
cases specific to awsbatch scheduler can be defined in a file named `test_awsbatch.py`.
If a single feature contains several tests it is possible to split them across several files and group them in a
common directory. Directories can be used also to group test belonging to the same category. For instance all tests
related to storage options could be grouped in the following fashion:
```
tests_outputs
└──  tests
    └── storage
         ├── test_ebs.py
         ├── test_raid.py
         └── test_efs.py
```

*The testing framework is heavily based on [pytest](https://docs.pytest.org/en/latest/contents.html) and it makes use of
some specific pytest concepts such as [fixtures](https://doc.pytest.org/en/latest/fixture.html). To better understand
the implementation details behind the testing framework, it is highly recommended to have a quick look at the basic
pytest key concepts first. This is not required in case you only want to add new test cases and not modify the framework
itself.*

#### Define Parametrized Test Cases

Here is how to define a simple parametrized test case:
```python
def test_case_1(region, instance, os, scheduler):
```
This test case will be automatically parametrized and executed for all combination of input dimensions.
For example, given as input dimensions `--regions "eu-west-1" --instances "c4.xlarge" --oss "alinux"
"ubuntu1604" --scheduler "sge" "slurm"`, the following tests will run:
```
test_case_1[eu-west-1-c4.xlarge-alinux-sge]
test_case_1[eu-west-1-c4.xlarge-ubuntu1604-sge]
test_case_1[eu-west-1-c4.xlarge-alinux-slurm]
test_case_1[eu-west-1-c4.xlarge-ubuntu1604-slurm]
```

#### Restrict Test Cases Dimensions

It is possible to restrict the dimensions each test is compatible with by using some custom markers.
The available markers are the following:
```python
@pytest.mark.instances(instances_list): run test only against the listed instances
@pytest.mark.regions(regions_list): run test only against the listed regions
@pytest.mark.oss(os_list): run test only against the listed oss
@pytest.mark.schedulers(schedulers_list): run test only against the listed schedulers
@pytest.mark.dimensions(region, instance, os, scheduler): run test only against the listed dimensions
@pytest.mark.skip_instances(instances_list): skip test for the listed instances
@pytest.mark.skip_regions(regions_list): skip test for the listed regions
@pytest.mark.skip_oss(os_list): skip test for the listed oss
@pytest.mark.skip_schedulers(schedulers_list): skip test for the listed schedulers
@pytest.mark.skip_dimensions(region, instance, os, scheduler): skip test for the listed dimensions
```

For example, given the following test definition:
```python
@pytest.mark.regions(["us-east-1", "eu-west-1", "cn-north-1", "us-gov-west-1"])
@pytest.mark.instances(["c5.xlarge", "t2.large"])
@pytest.mark.dimensions("*", "*", "alinux", "awsbatch")
def test_case_1(region, instance, os, scheduler):
```
The test is allowed to run against the following subset of dimensions:
* region has to be one of `["us-east-1", "eu-west-1", "cn-north-1", "us-gov-west-1"]`
* instance has to be one of `"c5.xlarge", "t2.large"`
* os has to be `alinux`
* scheduler has to be `awsbatch`

While the following test case:
```python
@pytest.mark.skip_regions(["us-east-1", "eu-west-1"])
@pytest.mark.skip_dimensions("*", "c5.xlarge", "alinux", "awsbatch")
@pytest.mark.skip_dimensions("*", "c5.xlarge", "alinux", "awsbatch")
def test_feature_2(region, instance, os, scheduler):
```
is allowed to run only if:
* region is not `["us-east-1", "eu-west-1"]`
* the triplet (instance, os, scheduler) is not `("c5.xlarge", "alinux", "awsbatch")` or
`("c5.xlarge", "alinux", "awsbatch")`

**DEFAULT INVALID DIMENSIONS**

It is possible that some combination of dimensions are not allowed because for example a specific instance is not
available in a given AWS region.

To define such exceptions it is possible to extend the list `UNSUPPORTED_DIMENSIONS` in conftest_markers.py file.
By default all tuples specified in that list will be added as `skip_dimensions` marker to all tests.

#### Manage Tests Data

Tests data and resources are organized in the following directories:
```
integration-tests
└── tests
   ├── $test_file_i.py: contains resources for test cases defined in file $test_file_i.py
   │   └── $test_case_i: contains resources for test case $test_case_i
   │       ├── data_file
   │       ├── pcluster.config.ini
   │       └── test_script.sh
   └── data: contains common resources to share across all tests
       └── shared_dir_1
           └── shared_file_1
```

[pytest-datadir](https://github.com/gabrielcnr/pytest-datadir) is a pytest plugin that is used for manipulating test
data directories and files.

A fixture `test_datadir` is built on top of it and can be used to the inject the `datadir` with resources for the
specific test function.

For example in the following test, defined in the file `test_feature.py`:
```python
def test_case_1(region, instance, os, scheduler, test_datadir):
```
the argument `test_datadir` is initialized at each test run with the a path to a temporary directory that contains
a copy of the contents of `integration-tests/tests/test_feature/test_case_1`.
This way the test case can freely modify the contents of that dir at each run without compromising other tests
executions.

The fixture `shared_datadir` can be used similarly to access the shared resources directory.

#### Parametrized Clusters Configurations

Similarly to parametrized test cases, also cluster configurations can be parametrized or even better written with
[Jinja2](http://jinja.pocoo.org/docs/2.10/) templating syntax.

The cluster configuration needed for a given test case needs to reside in the test specific `test_datadir`
and it needs to be in a file named pcluster.config.ini.

Test cases can then inject a fixture called `pcluster_config_reader` which allows to automatically read and render
the configuration defined for a specific test case and have it automatically parametrized with the default
test dimensions and additional test options (such as the value assigned to `key_name`).

For example in the following test, defined in the file `test_feature.py`:
```python
def test_case_1(region, instance, os, scheduler, pcluster_config_reader):
    cluster_config = pcluster_config_reader(vpc_id="id-xxx", master_subnet_id="id-xxx", compute_subnet_id="id-xxx")
```
I can simply render the parametrized cluster config which is defined in the file
`integration-tests/tests/test_feature/test_case_1/pcluster.config.ini`

Here is an example of the parametrized pcluster config:
```INI
[global]
cluster_template = awsbatch

[aws]
aws_region_name = {{ region }}

[cluster awsbatch]
base_os = {{ os }}
key_name = {{ key_name }}
vpc_settings = parallelcluster-vpc
scheduler = awsbatch
compute_instance_type = {{ instance }}
min_vcpus = 2
desired_vcpus = 2
max_vcpus = 24

[vpc parallelcluster-vpc]
vpc_id = {{ vpc_id }}
master_subnet_id = {{ master_subnet_id }}
compute_subnet_id = {{ compute_subnet_id }}
```

The placeholders `{{ region }}`, `{{ instance }}`, `{{ os }}`, `{{ scheduler }}`, `{{ key_name }}`
are automatically injected by the `pcluster_config_reader` fixture.
Additional parameters can be specified when calling the fixture to retrieve the rendered configuration
as shown in the example above.

#### Create/Destroy Clusters

Cluster lifecycle management is fully managed by the testing framework and is exposed through the fixture
`clusters_factory`.

Here is an example of how to use it:
```python
def test_case_1(region, instance, os, scheduler, pcluster_config_reader, clusters_factory):
    cluster_config = pcluster_config_reader(vpc_id="aaa", master_subnet_id="bbb", compute_subnet_id="ccc")
    cluster = clusters_factory(cluster_config)
```

The factory can be used as shown above to create one or multiple clusters that will be automatically
destroyed when the test completes or in case of unexpected errors.

`cluster_factory` fixture also takes care of dumping a copy of the configuration used to create each cluster
in the tests output directory.

The object returned by clusters_factory is a `Cluster` instance that contains all the necessary cluster information,
included the CloudFormation stack outputs.

#### Execute Remote Commands

To execute remote commands or scripts on the Master instance of the cluster under test, the `RemoteCommandExecutor`
class can be used. It simply requires a valid `Cluster` object to be initialized and it offers some utility
methods to execute remote commands and scripts as shown in the example below:

```python
import logging
from remote_command_executor import RemoteCommandExecutor
def test_case_1(region, instance, os, scheduler, pcluster_config_reader, clusters_factory, test_datadir):
    cluster_config = pcluster_config_reader(vpc_id="aaa", master_subnet_id="bbb", compute_subnet_id="ccc")
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    result = remote_command_executor.run_remote_command("env")
    logging.info(result.stdout)
    result = remote_command_executor.run_remote_command(["echo", "test"])
    logging.info(result.stdout)
    result = remote_command_executor.run_remote_script(
        str(test_datadir / "test_script.sh"), args=["1", "2"], additional_files=[str(test_datadir / "data_file")]
    )
    logging.info(result.stdout)
```

and here is the structure of the datadir if the test case is defined in the `test_feature.py` file:
```
integration-tests
└── tests
    └──  test_feature
        └── test_case_1
            ├── data_file
            ├── pcluster.config.ini
            └── test_script.sh

```

#### Logging

A default logger is configured to write both to the stdout and to the log file dedicated to the specific test
process. When running in `--sequential` mode a single log file is created otherwise a
separate logfile is generated for each region.
