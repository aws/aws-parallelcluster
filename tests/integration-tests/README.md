# AWS ParallelCluster Integration Testing Framework

The framework used to implement and run integration tests for AWS ParallelCluster is made of two main components:
* **Integration Tests Orchestrator**: is a cli that allows to submit the integration tests. It takes care of setting
up the test environment, it orchestrates parallel tests execution and generates the final tests reports.
* **Integration Tests Framework**: the actual testing framework, based on pytest, which defines a series of
fixtures and markers that allows to parametrize tests execution across several dimensions, to easily manage clusters
lifecycle and re-usage and to perform cleanup on failures. It also offers a set of utility functions
that implement features which are common to all tests such as remote command execution and ParallelCluster
config generation.

![integtests_small](https://user-images.githubusercontent.com/12721611/61521900-868c0500-aa11-11e9-9a98-de58eaa18752.png)

## Run Integration Tests

To run the integration tests you have to use Python 3.7.

Before executing integration tests it is required to install all the python dependencies required by the framework.
In order to do that simply run the following command:
```bash
pip install -r tests/integration-tests/requirements.txt
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

### Tests Outputs & Reports

The following options can be used to control test outputs and reports:
* `--output-dir path/to/dir`: specifies the base dir where test outputs and logs will be saved.
Defaults to tests_outputs.
* `--reports {html,junitxml,json,cw}`: allows to select what tests reports to generate.
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
    ├── $region_i: directory containing tests reports for a single region
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

By specifying the option `--reports cw`, the results of the tests run will be published as a series of CloudWatch
metrics. You can use the options `--cw-region` (default `us-east-1`) and `--cw-namespace`
(default `ParallelCluster/IntegrationTests`) to specify what region and what metric namespace
you want to use for the published metrics.

### Specify Tests Dimensions
The following options can be used to control the parametrization of test cases:
* `-r REGIONS [REGIONS ...], --regions REGIONS [REGIONS ...]`: AWS region where tests are executed.
* `-i INSTANCES [INSTANCES ...], --instances INSTANCES [INSTANCES ...]`: AWS instances under test.
* `-o OSS [OSS ...], --oss OSS [OSS ...]`: OSs under test.
* `-s SCHEDULERS [SCHEDULERS ...], --schedulers SCHEDULERS [SCHEDULERS ...]`: Schedulers under test.

Note that each test case can specify a subset of dimensions it is allowed to run against (for example
a test case written specifically for the awsbatch scheduler should only be executed against the awsbatch scheduler).
This means that the final parametrization of the tests is given by an intersection of the input dimensions and
the tests specific dimensions so that all constraints are verified.

### Parallelize Tests Execution
The following options can be used to control tests parallelism:
* `--sequential`: by default the tests orchestrator executes a separate parallel process for each region under test.
By specifying this option all tests are executed sequentially in a single process.
* `-n PARALLELISM, --parallelism PARALLELISM`: allows to specify the degree of parallelism for each process. It is
useful to limit the number of clusters that are created concurrently in a specific region so that AWS account limits
can be guaranteed.

### Retry On Failures
When passing the `--retry-on-failures` flag failed tests are retried once more after a delay of 60 seconds.

### Run Tests For Specific Features
The `-f FEATURES [FEATURES ...], --features FEATURES [FEATURES ...]` option allows to limit the number of test
cases to execute by only running those that are meant to verify a specific feature or subset of features.

To execute a subset of features simply pass with the `-f` option a list of markers that identify the test cases
to run. For example when passing `-f "awsbatch" "not advanced"` all test cases marked with `@pytest.mark.awsbatch` and
not marked with `@pytest.mark.advanced` are executed.

It is a good practice to mark test cases with a series of markers that allow to identify the feature under test.
Every test is marked by default with a marker matching its filename with the `test_` prefix or `_test` suffix removed.

### Custom Templates, Packages and AMI

To use custom templates or packages URLs or to run tests against a given custom AMI
use the following options:
* `--custom-node-url`: URL to a custom node package.
* `--custom-cookbook-url`: URL to a custom cookbook package.
* `--createami-custom-cookbook-url`: URL to a custom cookbook package for the createami command.
* `--custom-template-url`: URL to a custom cfn template.
* `--custom-awsbatch-template-url`: URL to a custom awsbatch cfn template.
* `--custom-awsbatchcli-url`: URL to a custom awsbatch cli package.
* `--custom-ami`: custom AMI to use for all tests. Note that this custom AMI will be used
  for all tests, no matter the region.

The configuration for the custom templates and packages are automatically injected into
all cluster configs when these are rendered. In case any of these parameters is already set
in the cluster config then the value in the config is used.

### Re-use clusters and vpc clusters

When developing integration tests, it can be helpful to re-use a cluster between tests. 
This is easily accomplished with the use of the `--vpc-stack` and `--cluster` flags. 

If you're starting from scratch, run the test with the `--no-delete` flag. 
This preserves any stacks created for the test:

```bash
python -m test_runner \
  ...
  --no-delete
```

Then when you have a vpc stack and cluster, reference them when starting a test:

```bash
python -m test_runner \
  ...
  --vpc-stack "integ-tests-vpc-ncw7zrccsau8uh6k"
  --cluster "efa-demo"
  --no-delete
```

Keep in mind, the cluster you pass can have different `scheduler`, `os` or other features 
than what is specified in the test. This can break the tests in unexpected ways. Be mindful.

### Benchmark and performance tests

Performance tests are disabled by default due to the high resource utilization involved with their execution.
In order to run performance tests you can use the following options:
* `--benchmarks`: run benchmarks tests. This disables the execution of all tests defined under the tests directory.
* `--benchmarks-target-capacity`: set the target capacity for benchmarks tests (default: 200).
* `--benchmarks-max-time`: set the max waiting time in minutes for benchmarks tests (default: 30).

The same filters by dimensions and features can be applied to this kind of tests.

The output produced by the performance tests is stored under the following directory tree:
```
tests_outputs
└── $timestamp..out
    └── benchmarks: directory storing all cluster configs used by test
            ├── test_scaling_speed.py-test_scaling_speed[c5.xlarge-eu-west-1-centos7-slurm].png
            └── ...
```

## Cross Account Integration Tests
If you want to distribute integration tests across multiple accounts you can make use of the `--credential` flag. 
This is useful to overcome restrictions related to account limits and be compliant with a multi-region, multi-account 
setup.

When the `--credential` flag is specified and STS assume-role call is made in order to fetch temporary credentials to 
be used to run tests in a specific region. 

The `--credential` flag is in the form `<region>,<endpoint_url>,<ARN>,<external_id>` and needs to be specified for each 
region you want to use with an STS assumed role (that usually means for every region you want to have in a separate 
account).

 * `region` is the region you want to test with an assumed STS role (which is in the target account where you want to 
 launch the integration tests)
 * `endpoint_url` is the STS endpoint url of the main account to be called in order to assume the delegation role
 * `ARN` is the ARN of the delegation role in the optin region account to be assumed by the main account
 * `external_id` is the external ID of the delegation role  

By default, the delegation role lifetime last for one hour. Mind that if you are planning to launch tests that last 
more than one hour.

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

### Define Parametrized Test Cases

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

If you don't need to reference the parametrized arguments in your test case you can simply replace the
function arguments with this annotation: `@pytest.mark.usefixtures("region", "os", "instance", "scheduler")`

```python
@pytest.mark.regions(["us-east-1", "eu-west-1", "cn-north-1", "us-gov-west-1"])
@pytest.mark.instances(["c5.xlarge", "t2.large"])
@pytest.mark.dimensions("*", "*", "alinux", "awsbatch")
@pytest.mark.usefixtures("region", "os", "instance", "scheduler")
def test_case_2():
```

If you want to add another level of parametrization which only applies to a single or a subset of
test cases then you can do it in the following way:

```python
@pytest.mark.usefixtures("region", "os", "instance", "scheduler")
@pytest.mark.parametrized("cluster_max_size", [5, 10])
def test_case_2(cluster_max_size):
```

### Restrict Test Cases Dimensions

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
@pytest.mark.skip_dimensions("*", "c4.xlarge", "centos7", "sge")
def test_case_2(region, instance, os, scheduler):
```
is allowed to run only if:
* region is not `["us-east-1", "eu-west-1"]`
* the triplet (instance, os, scheduler) is not `("c5.xlarge", "alinux", "awsbatch")` or
`("c4.xlarge", "centos7", "sge")`

#### Default Invalid Dimensions

It is possible that some combination of dimensions are not allowed because for example a specific instance is not
available in a given AWS region.

To define such exceptions it is possible to extend the list `UNSUPPORTED_DIMENSIONS` in conftest_markers.py file.
By default all tuples specified in that list will be added as `skip_dimensions` marker to all tests.

### Manage Tests Data

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

### Parametrized Clusters Configurations

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
you can simply render the parametrized cluster config which is defined in the file
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
master_subnet_id = {{ public_subnet_id }}
compute_subnet_id = {{ private_subnet_id }}
```

The following placeholders are automatically injected by the `pcluster_config_reader` fixture and are
available in the `pcluster.config.ini` files:
* Test dimensions for the specific parametrized test case: `{{ region }}`, `{{ instance }}`, `{{ os }}`,
`{{ scheduler }}`
* EC2 key name specified at tests submission time by the user: `{{ key_name }}`
* VPC related parameters: `{{ vpc_id }}`, `{{ public_subnet_id }}`, `{{ private_subnet_id }}`

Additional parameters can be specified when calling the fixture to retrieve the rendered configuration
as shown in the example above.

### VPC Configuration

A VPC and the related subnets are automatically configured at the start of the integration tests for each region under
test. These resources are shared across all the tests and deleted when all tests are completed.

The idea is to create a single VPC per region and have multiple subnets that allow to test different networking setups.
At the moment two subnets are generated (a private one and a public one) with the current configuration:

```python
public_subnet = SubnetConfig(
    name="PublicSubnet",
    cidr="10.0.0.0/24",
    map_public_ip_on_launch=True,
    has_nat_gateway=True,
    default_gateway=Gateways.INTERNET_GATEWAY,
)
private_subnet = SubnetConfig(
    name="PrivateSubnet",
    cidr="10.0.1.0/24",
    map_public_ip_on_launch=False,
    has_nat_gateway=False,
    default_gateway=Gateways.NAT_GATEWAY,
)
vpc = VPCConfig(
    name="vpc",
    cidr="10.0.0.0/16",
    enable_dns_support=True,
    enable_dns_hostnames=True,
    has_internet_gateway=True,
    subnets = [private_subnet, public_subnet],
)
```

Behind the scenes a CloudFormation template is dynamically generated by the `NetworkTemplateBuilder`
(leveraging a tool called [Troposphere](https://github.com/cloudtools/troposphere)) and a VPC is created in each region
under test by the `vpc_stacks` autouse session fixture.

Parameters related to the generated VPC and Subnets are automatically exported to the Jinja template engine and
in particular are available when using the `pcluster_config_reader` fixture, as shown above. The only thing to do
is to use them when defining the cluster config for the specific test case:

```INI
...
[vpc parallelcluster-vpc]
vpc_id = {{ vpc_id }}
master_subnet_id = {{ public_subnet_id }}
compute_subnet_id = {{ private_subnet_id }}
```

### Create/Destroy Clusters

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

### Execute Remote Commands

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

### Logging

A default logger is configured to write both to the stdout and to the log file dedicated to the specific test
process. When running in `--sequential` mode a single log file is created otherwise a
separate logfile is generated for each region.

### Create CloudFormation Templates

If additional AWS resources are needed by the integration tests you can use a session scoped fixture,
`cfn_stacks_factory`, which takes care of automatically manage creation and deletion of CFN stacks that live
for the entire duration of the tests. Deletion of all stacks is automatically performed when all tests
are completed. If you want to reduce the lifetime of a specific resource you can either create a separate similar
fixture with a reduced scope or you can directly use the CfnStacksFactory object (note: fixtures are always better to
handle resources cleanup.)

An example is given by this piece of code that handles the creation of a test VPC:
```python
@pytest.fixture(autouse=True)
def vpc(cfn_stacks_factory):
    # ... lines removed
    template = NetworkTemplateBuilder(vpc_config).build()
    stack = CfnStack(name="integ-tests-vpc-" + random_alphanumeric(), region=region, template=template.to_json())
    cfn_stacks_factory.create_stack(stack)
    return stack
```

### Benchmark and performance tests

Benchmark and performance tests follow the same rules described above for a normal integration test.
The only differences are the following:
- the tests are defined under the `benchmarks/` directory
- they are not executed by default with the rest of the integration tests
- they write their output to a specific benchmarks directory created in the output dir

### Troubleshooting and fixes

* `IdentityFile` option in `ssh/config` will trigger a `str has no attribute extend` bug in the `fabric` package. 
Please remove `IdentityFile` option from `ssh/config` before running the testing framework
