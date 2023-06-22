# AWS ParallelCluster Integration Testing Framework

The framework used to implement and run integration tests for AWS ParallelCluster is made of two main components:
* **Integration Tests Orchestrator**: is a cli that allows to submit the integration tests. It takes care of setting
up the test environment, it orchestrates parallel tests execution and generates the final tests reports.
* **Integration Tests Framework**: the actual testing framework, based on pytest, which defines a series of
fixtures and markers that allow to parametrize tests execution across several dimensions, to easily manage clusters
lifecycle and re-usage and to perform cleanup on failures. It also offers a set of utility functions
that implement features which are common to all tests such as remote command execution and ParallelCluster
config generation.

![integtests_small](https://user-images.githubusercontent.com/12721611/61521900-868c0500-aa11-11e9-9a98-de58eaa18752.png)

## Run Integration Tests

### Requirements

To run the integration tests you have to use Python >= 3.7.

Before executing integration tests it is required to install all the Python dependencies required by the framework.
In order to do that simply run the following commands:
```bash
cd tests/integration-tests
pip install -r requirements.txt
```

After that you can run the CLI by simply executing the following
```
python -m test_runner --help
```

### The test_runner CLI

The test_runner CLI is the main entry point to be used in order to run tests. Here is the output of the helper function
that lists all the available options:

```
python -m test_runner --help
usage: test_runner.py [-h] --key-name KEY_NAME --key-path KEY_PATH [-n PARALLELISM] [--sequential] [--credential CREDENTIAL] [--use-default-iam-credentials] [--retry-on-failures] [--tests-root-dir TESTS_ROOT_DIR] [-c TESTS_CONFIG]
                      [-i [INSTANCES [INSTANCES ...]]] [-o [OSS [OSS ...]]] [-s [SCHEDULERS [SCHEDULERS ...]]] [-r [REGIONS [REGIONS ...]]] [-f FEATURES [FEATURES ...]] [--show-output]
                      [--reports {html,junitxml,json,cw} [{html,junitxml,json,cw} ...]] [--cw-region CW_REGION] [--cw-namespace CW_NAMESPACE] [--cw-timestamp-day-start] [--output-dir OUTPUT_DIR] [--custom-node-url CUSTOM_NODE_URL]
                      [--custom-cookbook-url CUSTOM_COOKBOOK_URL] [--createami-custom-cookbook-url CREATEAMI_CUSTOM_COOKBOOK_URL] [--createami-custom-node-url CREATEAMI_CUSTOM_NODE_URL] [--custom-awsbatchcli-url CUSTOM_AWSBATCHCLI_URL]
                      [--pre-install PRE_INSTALL] [--post-install POST_INSTALL] [--instance-types-data INSTANCE_TYPES_DATA] [--custom-ami CUSTOM_AMI] [--pcluster-git-ref PCLUSTER_GIT_REF] [--cookbook-git-ref COOKBOOK_GIT_REF]
                      [--node-git-ref NODE_GIT_REF] [--ami-owner AMI_OWNER] [--benchmarks] [--benchmarks-target-capacity BENCHMARKS_TARGET_CAPACITY] [--benchmarks-max-time BENCHMARKS_MAX_TIME]
                      [--api-definition-s3-uri API_DEFINITION_S3_URI] [--api-infrastructure-s3-uri API_INFRASTRUCTURE_S3_URI] [--api-uri API_URI] [--policies-uri POLICIES_URI] [--vpc-stack VPC_STACK] [--cluster CLUSTER] [--lambda-layer-source LAMBDA_LAYER_SOURCE]
                      [--no-delete] [--delete-logs-on-success] [--stackname-suffix STACKNAME_SUFFIX] [--dry-run] [--directory-stack-name DIRECTORY_STACK_NAME] [--ldaps-nlb-stack-name LDAPS_NLB_STACK_NAME] [--external-shared-storage-stack-name SHARED_STORAGE_STACK_NAME]

Run integration tests suite.

optional arguments:
  -h, --help            show this help message and exit
  --key-name KEY_NAME   Key to use for EC2 instances (default: None)
  --key-path KEY_PATH   Path to the key to use for SSH connections (default: None)
  -n PARALLELISM, --parallelism PARALLELISM
                        Tests parallelism for every region. (default: None)
  --sequential          Run tests in a single process. When not specified tests will spawn a process for each region under test. (default: False)
  --credential CREDENTIAL
                        STS credential to assume when running tests in a specific region.Credentials need to be in the format <region>,<endpoint>,<ARN>,<externalId> and can be specified multiple times. <region> represents the region
                        credentials are used for, <endpoint> is the sts endpoint to contact in order to assume credentials, <account-id> is the id of the account where the role to assume is defined, <externalId> is the id to use when
                        assuming the role. (e.g. ap-east-1,https://sts.us-east-1.amazonaws.com,arn:aws:iam::<account-id>:role/role-to-assume,externalId) (default: None)
  --use-default-iam-credentials
                        Use the default IAM creds to run pcluster CLI commands. Skips the creation of pcluster CLI IAM role. (default: False)
  --retry-on-failures   Retry once more the failed tests after a delay of 60 seconds. (default: False)
  --tests-root-dir TESTS_ROOT_DIR
                        Root dir where integration tests are defined (default: ./tests)

Test dimensions:
  -c TESTS_CONFIG, --tests-config TESTS_CONFIG
                        Config file that specifies the tests to run and the dimensions to enable for each test. Note that when a config file is used the following flags are ignored: instances, regions, oss, schedulers. Refer to the docs
                        for further details on the config format: https://github.com/aws/aws-parallelcluster/blob/develop/tests/integration-tests/README.md (default: None)
  -i [INSTANCES [INSTANCES ...]], --instances [INSTANCES [INSTANCES ...]]
                        AWS instances under test. Ignored when tests-config is used. (default: [])
  -o [OSS [OSS ...]], --oss [OSS [OSS ...]]
                        OSs under test. Ignored when tests-config is used. (default: [])
  -s [SCHEDULERS [SCHEDULERS ...]], --schedulers [SCHEDULERS [SCHEDULERS ...]]
                        Schedulers under test. Ignored when tests-config is used. (default: [])
  -r [REGIONS [REGIONS ...]], --regions [REGIONS [REGIONS ...]]
                        AWS regions where tests are executed. Ignored when tests-config is used. (default: [])
  -f FEATURES [FEATURES ...], --features FEATURES [FEATURES ...]
                        Run only tests for the listed features. Prepending the not keyword to the feature name causes the feature to be excluded. (default: )

Test reports:
  --show-output         Do not redirect tests stdout to file. Not recommended when running in multiple regions. (default: None)
  --reports {html,junitxml,json,cw} [{html,junitxml,json,cw} ...]
                        create tests report files. junitxml creates a junit-xml style report file. html creates an html style report file. json creates a summary with details for each dimensions. cw publishes tests metrics into
                        CloudWatch (default: [])
  --cw-region CW_REGION
                        Region where to publish CloudWatch metrics (default: us-east-1)
  --cw-namespace CW_NAMESPACE
                        CloudWatch namespace where to publish metrics (default: ParallelCluster/IntegrationTests)
  --cw-timestamp-day-start
                        CloudWatch metrics pushed with at timestamp equal to the start of the current day (midnight) (default: False)
  --output-dir OUTPUT_DIR
                        Directory where tests outputs are generated (default: tests_outputs)

Custom packages and templates:
  --custom-node-url CUSTOM_NODE_URL
                        URL to a custom node package. (default: None)
  --custom-cookbook-url CUSTOM_COOKBOOK_URL
                        URL to a custom cookbook package. (default: None)
  --createami-custom-cookbook-url CREATEAMI_CUSTOM_COOKBOOK_URL
                        URL to a custom cookbook package for the createami command. (default: None)
  --createami-custom-node-url CREATEAMI_CUSTOM_NODE_URL
                        URL to a custom node package for the createami command. (default: None)
  --custom-awsbatchcli-url CUSTOM_AWSBATCHCLI_URL
                        URL to a custom awsbatch cli package. (default: None)
  --pre-install PRE_INSTALL
                        URL to a pre install script (default: None)
  --post-install POST_INSTALL
                        URL to a post install script (default: None)
  --instance-types-data INSTANCE_TYPES_DATA
                        Additional information about instance types used in the tests. The format is a JSON map instance_type -> data, where data must respect the same structure returned by ec2 describe-instance-types (default: None)

AMI selection parameters:
  --custom-ami CUSTOM_AMI
                        custom AMI to use for all tests. (default: None)
  --pcluster-git-ref PCLUSTER_GIT_REF
                        Git ref of the custom cli package used to build the AMI. (default: None)
  --cookbook-git-ref COOKBOOK_GIT_REF
                        Git ref of the custom cookbook package used to build the AMI. (default: None)
  --node-git-ref NODE_GIT_REF
                        Git ref of the custom node package used to build the AMI. (default: None)
  --ami-owner AMI_OWNER
                        Override the owner value when fetching AMIs to use with cluster. By default pcluster uses amazon. (default: None)

Benchmarks:
  --benchmarks          Run benchmarks tests. Benchmarks tests will be run together with functionality tests. (default: False)

CloudFormation / Custom Resource options:
  --cluster-custom-resource-service-token CLUSTER_CUSTOM_RESOURCE_SERVICE_TOKEN
                        ServiceToken (ARN) Cluster CloudFormation custom resource provider (default: None)
  --resource-bucket RESOURCE_BUCKET
                        Name of bucket to use to to retrieve standard hosted resources like CloudFormation templates. {region} can be used to parametrize this value, and the bucket name will be formatted with the region where the test will be run (default: None)
  --lambda-layer-source LAMBDA_LAYER_SOURCE
                        S3 URI of lambda layer to copy instead of building. (default: None)

API options:
  --api-definition-s3-uri API_DEFINITION_S3_URI
                        URI of the OpenAPI spec of the ParallelCluster API (default: None)
  --api-infrastructure-s3-uri API_INFRASTRUCTURE_S3_URI
                        URI of the CloudFormation template for the ParallelCluster API (default: None)
  --api-uri API_URI     URI of an existing ParallelCluster API (default: None)
  --policies-uri POLICIES_URI
                        Use an existing policies URI instead of uploading one. (default: None)

Debugging/Development options:
  --vpc-stack VPC_STACK
                        Name of an existing vpc stack. (default: None)
  --cluster CLUSTER     Use an existing cluster instead of creating one. (default: None)
  --iam-user-role-stack-name
                        Name of an existing IAM user role stack. (default: None)
  --directory-stack-name
                        Name of CFN stack providing AD domain to be used for testing AD integration feature. (default: None)
  --ldaps-nlb-stack-name
                        Name of CFN stack providing NLB to enable use of LDAPS with a Simple AD directory when testing AD integration feature. (default: None)

  --no-delete           Don't delete stacks after tests are complete. (default: False)
  --delete-logs-on-success
                        delete CloudWatch logs when a test succeeds (default: False)
  --stackname-suffix STACKNAME_SUFFIX
                        set a suffix in the integration tests stack names (default: )
  --dry-run             Only show the list of tests that would run with specified options. (default: False)
  --directory-stack-name DIRECTORY_STACK_NAME
                        Name of CFN stack providing AD domain to be used for testing AD integration feature. (default: None)
  --ldaps-nlb-stack-name LDAPS_NLB_STACK_NAME
                        Name of CFN stack providing NLB to enable use of LDAPS with a Simple AD directory when testing AD integration feature. (default: None)
  --external-shared-storage-stack-name 
                        Name of an existing external shared storage stack. (default: None)
```

Here is an example of tests submission:
```bash
python -m test_runner \
    --key-name "ec2-key-name" \
    --key-path "~/.ssh/ec2-key.pem" \
    --tests-config configs/develop.yaml \
    --parallelism 8 \
    --retry-on-failures \
    --reports html junitxml json
```

Executing the command will run an integration testing suite with the following features:
* "ec2-key-name" is used to configure EC2 keys
* "~/.ssh/ec2-key.pem" is used to ssh into cluster instances and corresponds to the EC2 key ec2-key-name
* configs/develop.yaml is the configuration file containing the tests suite to run
* tests are executed in parallel in all regions and for each region 8 tests are executed concurrently
* in case of failures the failed tests are retried once more after a delay of 60 seconds
* tests reports are generated in html, junitxml and json formats

### Parametrize and select the tests to run

Each test contained in the suite can be parametrized, at submission time, across four different dimensions: regions,
instances, operating systems and schedulers. These dimensions allow to dynamically customize the combination of cluster
parameters that need to be validated by the scheduler. Some tests, due to the specific feature they are validating,
might not be compatible with the entire set of available dimensions.

In order to specify what tests to execute and the dimensions to select there are two different possibilities:
1. The recommended approach consists into passing to the `test_runner` a YAML configuration file that declares the tests
   suite and the dimensions to use for each test
2. The alternative approach is to use some of the CLI arguments to limit the dimensions and the features under test

#### The tests suite configuration file

When executing the `test_runner` CLI, the `--tests-config` argument can be used to specify a configuration file
containing the list of tests that need to be executed. The configuration file is a YAML document, with optionally Jinja
templating directives, that needs to comply with the following schema:
https://github.com/aws/aws-parallelcluster/tree/develop/tests/integration-tests/framework/tests_configuration/config_schema.yaml

Here is an example of a tests suite definition file:
```
{%- import 'common.jinja2' as common -%}
---
test-suites:
  cfn-init:
    test_cfn_init.py::test_replace_compute_on_failure:
      dimensions:
        - regions: ["eu-central-1"]
          instances: {{ common.INSTANCES_DEFAULT_X86 }}
          oss: {{ common.OSS_ONE_PER_DISTRO }}
          schedulers: ["slurm", "awsbatch"]
  cli_commands:
    test_cli_commands.py::test_hit_cli_commands:
      dimensions:
        - regions: ["us-east-2"]
          instances: {{ common.INSTANCES_DEFAULT_X86 }}
          oss: ["ubuntu1804"]
          schedulers: ["slurm"]
    test_cli_commands.py::test_sit_cli_commands:
      dimensions:
        - regions: ["us-west-2"]
          instances: {{ common.INSTANCES_DEFAULT_X86 }}
          oss: ["centos7"]
          schedulers: ["slurm"]
  cloudwatch_logging:
    test_cloudwatch_logging.py::test_cloudwatch_logging:
      dimensions:
        # 1) run the test for all of the schedulers with alinux2
        - regions: ["ca-central-1"]
          instances: {{ common.INSTANCES_DEFAULT_X86 }}
          oss: ["alinux2"]
          schedulers: {{ common.SCHEDULERS_ALL }}
        # 2) run the test for all of the OSes with slurm
        - regions: ["ap-east-1"]
          instances: {{ common.INSTANCES_DEFAULT_X86 }}
          oss: {{ common.OSS_COMMERCIAL_X86 }}
          schedulers: ["slurm"]
        # 3) run the test for a single scheduler-OS combination on an ARM instance
        - regions: ["eu-west-1"]
          instances: {{ common.INSTANCES_DEFAULT_ARM }}
          oss: ["alinux2"]
          schedulers: ["slurm"]
```

As shown in the example above, the configuration file groups tests by the name of the package where these are defined.
For each test function, identified by the test module and the function name, an array of dimensions are specified in
order to define how this specific test is parametrized. Each element of the dimensions array generates a parametrization
of the selected test function which consist in the combination of all defined dimensions. For example the
cloudwatch_logging suite defined above will produce the following parametrization:

```
cloudwatch_logging/test_cloudwatch_logging.py::test_cloudwatch_logging[ap-east-1-c5.xlarge-alinux2-slurm]
cloudwatch_logging/test_cloudwatch_logging.py::test_cloudwatch_logging[ap-east-1-c5.xlarge-centos7-slurm]
cloudwatch_logging/test_cloudwatch_logging.py::test_cloudwatch_logging[ap-east-1-c5.xlarge-ubuntu1804-slurm]
cloudwatch_logging/test_cloudwatch_logging.py::test_cloudwatch_logging[ca-central-1-c5.xlarge-alinux2-awsbatch]
cloudwatch_logging/test_cloudwatch_logging.py::test_cloudwatch_logging[ca-central-1-c5.xlarge-alinux2-slurm]
cloudwatch_logging/test_cloudwatch_logging.py::test_cloudwatch_logging[eu-west-1-m6g.xlarge-alinux2-slurm]
```

Jinja directives can be used to simplify the declaration of the tests suites.

Some tox commands are offered in order to simplify the generation and validation of such configuration files:
* ` tox -e validate-test-configs` can be executed to validate all configuration files defined in the
  `tests/integration-tests/configs` directory. The directory or the specific file to validate can be also selected
  with the additional arguments: `--tests-configs-dir` and `--tests-config-file`
  (e.g. tox -e validate-test-configs -- --tests-config-file configs/develop.yaml)
* `tox -e generate-test-config my-config-file` can be used to automatically generate a configuration file pre-filled
  with the list of all available files. The config file is generated in the `tests/integration-tests/configs` directory.

#### AZ override
By default, the TestRunner will run the test in a random AZ between the ones available in the region.
There are cases where some resources (like `instance_type` or aws services) are not available in all AZ.
In these cases to successfully run the test it is necessary to override the AZ where the test must run.

To do so you can specify a ZoneId in the regions dimension. So for example if you set

```
      dimensions:
        - regions: ["euw1-az1", "eu-central-1"]
```

the test will be executed in
* `eu-west-1` using the AZ with ZoneId `euw1-az1` (ZoneId is consistent across accounts)
* `eu-central-1` using a random AZ available in the region

#### Using CLI options

The following options can be used to control the parametrization of test cases:
* `-r REGIONS [REGIONS ...], --regions REGIONS [REGIONS ...]`: AWS region where tests are executed.
* `-i INSTANCES [INSTANCES ...], --instances INSTANCES [INSTANCES ...]`: AWS instances under test.
* `-o OSS [OSS ...], --oss OSS [OSS ...]`: OSs under test.
* `-s SCHEDULERS [SCHEDULERS ...], --schedulers SCHEDULERS [SCHEDULERS ...]`: Schedulers under test.

Note that each test case can specify a subset of dimensions it is allowed to run against (for example
a test case written specifically for the awsbatch scheduler should only be executed against the awsbatch scheduler).
This means that the final parametrization of the tests is given by an intersection of the input dimensions and
the test-specific dimensions so that all constraints are verified.

The `-f FEATURES [FEATURES ...], --features FEATURES [FEATURES ...]` option allows to limit the number of test
cases to execute by only running those that are meant to verify a specific feature or subset of features.

To execute a subset of features simply pass with the `-f` option a list of markers that identify the test cases
to run. For example when passing `-f "awsbatch" "not advanced"` all test cases marked with `@pytest.mark.awsbatch` and
not marked with `@pytest.mark.advanced` are executed.

It is a good practice to mark test cases with a series of markers that allow to identify the feature under test.
Every test is marked by default with a marker matching its filename with the `test_` prefix or `_test` suffix removed.

Note: These options can be used also in combination with a tests suite configuration file

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
│         ├── $region_i.log: log outputs for a single region
│         └── ...
└── $timestamp.out: directory containing tests reports
    ├── $region_i: directory containing tests reports for a single region
    │         ├── clusters_configs: directory storing all cluster configs used by test
    │         │         ├── test_awsbatch.py::test_job_submission[c5.xlarge-eu-west-1-alinux2-awsbatch].config
    │         │         └── ...
    │         ├── pytest.out: stdout of pytest for the given region
    │         ├── results.html: html report for the given region
    │         ├── results.xml: junitxml report for the given region
    │         ├── collected_tests.txt: the list of collected parametrized tests that are executed in the specific region
    │         └── tests_config.yaml: the configuration file used to define the tests to run (if present)
    ├── test_report.json: global json report
    └── test_report.xml: global junitxml report
```

If tests are run sequentially by adding the `--sequential` option the result is the following:
```
tests_outputs
├── $timestamp..logs
│         └── all_regions.log: log outputs for all regions
└── $timestamp..out
    ├── clusters_configs: directory storing all cluster configs used by test
    │        ├── test_playground.py::test_factory.config
    │        └── ...
    ├── pytest.out: global pytest stdout
    ├── results.html: global html report
    ├── results.xml: same as test_report.xml
    ├── test_report.json: global json report
    ├── test_report.xml: global junitxml report
    ├── collected_tests.txt: the list of collected parametrized tests
    └── tests_config.yaml: the configuration file used to define the tests to run (if present)
```

By specifying the option `--reports cw`, the results of the tests run will be published as a series of CloudWatch
metrics. You can use the options `--cw-region` (default `us-east-1`) and `--cw-namespace`
(default `ParallelCluster/IntegrationTests`) to specify what region and what metric namespace
you want to use for the published metrics.

### Parallelize Tests Execution
The following options can be used to control tests parallelism:
* `--sequential`: by default the tests orchestrator executes a separate parallel process for each region under test.
By specifying this option all tests are executed sequentially in a single process.
* `-n PARALLELISM, --parallelism PARALLELISM`: allows to specify the degree of parallelism for each process. It is
useful to limit the number of clusters that are created concurrently in a specific region so that AWS account limits
can be guaranteed.

### Retry On Failures
When passing the `--retry-on-failures` flag failed tests are retried once more after a delay of 60 seconds.

### Custom Templates, Packages and AMI

To use custom templates or packages URLs or to run tests against a given custom AMI
use the following options:
* `--custom-node-url`: URL to a custom node package.
* `--custom-cookbook-url`: URL to a custom cookbook package.
* `--createami-custom-cookbook-url`: URL to a custom cookbook package for the createami command.
* `--custom-template-url`: URL to a custom cfn template.
* `--custom-awsbatchcli-url`: URL to a custom awsbatch cli package.
* `--custom-ami`: custom AMI to use for all tests. Note that this custom AMI will be used
  for all tests, no matter the region.
* `--custom-hit-template-url`: URL to a custom hit cfn template.

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

By default, the delegation role lifetime is one hour. Mind that if you are planning to launch tests that last
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
For example, given as input dimensions `--regions "eu-west-1" --instances "c4.xlarge" --oss "alinux2"
"ubuntu1804" --scheduler "awsbatch" "slurm"`, the following tests will run:
```
test_case_1[eu-west-1-c4.xlarge-alinux2-awsbatch]
test_case_1[eu-west-1-c4.xlarge-ubuntu1804-awsbatch]
test_case_1[eu-west-1-c4.xlarge-alinux2-slurm]
test_case_1[eu-west-1-c4.xlarge-ubuntu1804-slurm]
```

If you don't need to reference the parametrized arguments in your test case you can simply replace the
function arguments with this annotation: `@pytest.mark.usefixtures("region", "os", "instance", "scheduler")`

```python
@pytest.mark.regions(["us-east-1", "eu-west-1", "cn-north-1", "us-gov-west-1"])
@pytest.mark.instances(["c5.xlarge", "t2.large"])
@pytest.mark.dimensions("*", "*", "alinux2", "awsbatch")
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

Note: this does not apply when using a test configuration file to select and parametrize the tests to execute

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
@pytest.mark.dimensions("*", "*", "alinux2", "awsbatch")
def test_case_1(region, instance, os, scheduler):
```
The test is allowed to run against the following subset of dimensions:
* region has to be one of `["us-east-1", "eu-west-1", "cn-north-1", "us-gov-west-1"]`
* instance has to be one of `"c5.xlarge", "t2.large"`
* os has to be `alinux2`
* scheduler has to be `awsbatch`

While the following test case:
```python
@pytest.mark.skip_regions(["us-east-1", "eu-west-1"])
@pytest.mark.skip_dimensions("*", "c5.xlarge", "alinux2", "awsbatch")
@pytest.mark.skip_dimensions("*", "c4.xlarge", "centos7", "slurm")
def test_case_2(region, instance, os, scheduler):
```
is allowed to run only if:
* region is not `["us-east-1", "eu-west-1"]`
* the triplet (instance, os, scheduler) is not `("c5.xlarge", "alinux2", "awsbatch")` or
`("c4.xlarge", "centos7", "slurm")`

#### Default Invalid Dimensions

It is possible that some combination of dimensions are not allowed because for example a specific instance is not
available in a given AWS region.

To define such exceptions it is possible to extend the list `UNSUPPORTED_DIMENSIONS` in conftest_markers.py file.
By default, all tuples specified in that list will be added as `skip_dimensions` markers to all tests.

### Manage Tests Data

Tests data and resources are organized in the following directories:
```
integration-tests
└── tests
         ├── $test_file_i.py: contains resources for test cases defined in file $test_file_i.py
         │         └── $test_case_i: contains resources for test case $test_case_i
         │             ├── data_file
         │             ├── pcluster.config.yaml
         │             └── test_script.sh
         └── data: contains common resources to share across all tests
                └── shared_dir_1
                       └── shared_file_1
```

[pytest-datadir](https://github.com/gabrielcnr/pytest-datadir) is a pytest plugin that is used for manipulating test
data directories and files.

A fixture `test_datadir` is built on top of it and can be used to inject the `datadir` with resources for the
specific test function.

For example in the following test, defined in the file `test_feature.py`:
```python
def test_case_1(region, instance, os, scheduler, test_datadir):
```
the argument `test_datadir` is initialized at each test run with the path to a temporary directory that contains
a copy of the contents of `integration-tests/tests/test_feature/test_case_1`.
This way the test case can freely modify the contents of that dir at each run without compromising other tests
executions.

The fixture `shared_datadir` can be used similarly to access the shared resource directory.

### Parametrized Clusters Configurations

Similar to parametrized test cases, cluster configurations can be parametrized or even better written with
[Jinja2](http://jinja.pocoo.org/docs/2.10/) templating syntax.

The cluster configuration needed for a given test case needs to reside in the test specific `test_datadir`
and it needs to be in a file named pcluster.config.yaml.

Test cases can then inject a fixture called `pcluster_config_reader` which allows to automatically read and render
the configuration defined for a specific test case and have it automatically parametrized with the default
test dimensions and additional test options (such as the value assigned to `key_name`).

For example in the following test, defined in the file `test_feature.py`:
```python
def test_case_1(region, instance, os, scheduler, pcluster_config_reader):
    cluster_config = pcluster_config_reader(public_subnet_id="id-xxx", private_subnet_id="id-xxx")
```
you can simply render the parametrized cluster config which is defined in the file
`integration-tests/tests/test_feature/test_case_1/pcluster.config.yaml`

Here is an example of the parametrized pcluster config:
```YAML
Image:
  Os: {{ os }}
HeadNode:
  InstanceType: {{ instance }}
  Networking:
    SubnetId: {{ public_subnet_id }}
  Ssh:
    KeyName: {{ key_name }}
Scheduling:
  Scheduler: {{ scheduler }}
  <scheduler-specific>Queues:
    - Name: queue-0
      ComputeResources:
        - Name: compute-resource-0
          InstanceType: {{ instance }}
      Networking:
        SubnetIds:
          - {{ private_subnet_id }}
    - Name: queue-1
      ComputeResources:
        - Name: compute-resource-1
          InstanceType: {{ instance }}
      Networking:
        SubnetIds:
          - {{ public_subnet_ids[0] }}
          - {{ public_subnet_ids[1] }}
SharedStorage:
  - MountDir: /shared
    Name: name1
    StorageType: Ebs
```

The following placeholders are automatically injected by the `pcluster_config_reader` fixture and are
available in the `pcluster.config.yaml` files:
* Test dimensions for the specific parametrized test case: `{{ region }}`, `{{ instance }}`, `{{ os }}`,
`{{ scheduler }}`
* EC2 key name specified at tests submission time by the user: `{{ key_name }}`
* Networking related parameters: `{{ public_subnet_id }}`, `{{ public_subnet_ids }}`, 
`{{ private_subnet_id }}` and `{{ private_subnet_ids }}`, where `{{ public_subnet_ids }}` and `{{ private_subnet_ids }}`
 contain a list of subnets for which the relative index points to subnets in the same AZ, e.g. 
`{{ public_subnet_ids[2] }}` and `{{ private_subnet_ids[2] }}` will be in the same AZ   

Additional parameters can be specified when calling the fixture to retrieve the rendered configuration
as shown in the example above.

### VPC Configuration

A VPC and the related subnets are automatically configured at the start of the integration tests for each region under
test. These resources are shared across all the tests and deleted when all tests are completed.

The idea is to create a single VPC per region and have multiple subnets that allow to test different networking setups.
A pair of subnets (public/private) for each available AZ, plus a subnet with VPC endpoints and no internet access, 
are generated with the following configuration:

```python
# Subnets visual representation:
# http://www.davidc.net/sites/default/subnets/subnets.html?network=192.168.0.0&mask=16&division=7.70
for index, az_id in enumerate(az_ids):
  az_name = az_id_to_az_name_map.get(az_id)
  # Subnets visual representation:
  # http://www.davidc.net/sites/default/subnets/subnets.html?network=192.168.0.0&mask=16&division=7.70
  subnets.append(
    SubnetConfig(
      name=subnet_name(visibility="Public", az_id=az_id),
      cidr=CIDR_FOR_PUBLIC_SUBNETS[index],
      map_public_ip_on_launch=True,
      has_nat_gateway=True,
      availability_zone=az_name,
      default_gateway=Gateways.INTERNET_GATEWAY,
    )
  )
  subnets.append(
    SubnetConfig(
      name=subnet_name(visibility="Private", az_id=az_id),
      cidr=CIDR_FOR_PRIVATE_SUBNETS[index],
      map_public_ip_on_launch=False,
      has_nat_gateway=False,
      availability_zone=az_name,
      default_gateway=Gateways.NAT_GATEWAY,
    )
  )
  if index == 0:
    subnets.append(
        SubnetConfig(
            name=subnet_name(visibility="Private", flavor="Isolated"),
            cidr=CIDR_FOR_CUSTOM_SUBNETS[index],
            map_public_ip_on_launch=False,
            has_nat_gateway=False,
            availability_zone=default_az_name,
            default_gateway=Gateways.NONE,
        )
    )

vpc_config = VPCConfig(
  cidr="192.168.0.0/17",
  additional_cidr_blocks=["192.168.128.0/17"],
  subnets=subnets,
)
```

Behind the scenes a CloudFormation template is dynamically generated by the `NetworkTemplateBuilder`
(leveraging a tool called [Troposphere](https://github.com/cloudtools/troposphere)) and a VPC is created in each region
under test by the `vpc_stacks_shared` autouse session fixture.

Parameters related to the generated VPC and Subnets are automatically exported to the Jinja template engine and
in particular are available when using the `pcluster_config_reader` fixture, as shown above. The only thing to do
is to use them when defining the cluster config for the specific test case:

```YAML
HeadNode:
  Networking:
    SubnetId: {{ public_subnet_id }}
  ...
Scheduling:
  <scheduler-specific>Queues:
    - Name: queue-0
      Networking:
        SubnetIds:
          - {{ private_subnet_id }}
  ...
    - Name: queue-1
      Networking:
        SubnetIds:
          - {{ private_subnet_ids[0] }}
  ...          
    - Name: queue-2
      Networking:
        SubnetIds:
          - {{ public_subnet_ids[0] }}
  ...
```

### Create/Destroy Clusters

Cluster lifecycle management is fully managed by the testing framework and is exposed through the fixture
`clusters_factory`.

Here is an example of how to use it:
```python
def test_case_1(region, instance, os, scheduler, pcluster_config_reader, clusters_factory):
    cluster_config = pcluster_config_reader(public_subnet_id="bbb", private_subnet_id="ccc")
    cluster = clusters_factory(cluster_config)
```

The factory can be used as shown above to create one or multiple clusters that will be automatically
destroyed when the test completes or in case of unexpected errors.

`cluster_factory` fixture also takes care of dumping a copy of the configuration used to create each cluster
in the tests output directory.

The object returned by clusters_factory is a `Cluster` instance that contains all the necessary cluster information,
including the CloudFormation stack outputs.

### Execute Remote Commands

To execute remote commands or scripts on the head node of the cluster under test, the `RemoteCommandExecutor`
class can be used. It simply requires a valid `Cluster` object to be initialized. It offers some utility
methods to execute remote commands and scripts as shown in the example below:

```python
import logging
from remote_command_executor import RemoteCommandExecutor
def test_case_1(region, instance, os, scheduler, pcluster_config_reader, clusters_factory, test_datadir):
    cluster_config = pcluster_config_reader(public_subnet_id="bbb", private_subnet_id="ccc")
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
                        ├── pcluster.config.yaml
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

## Run Performance Tests with Integration Tests

Performance tests can run together with functionality tests, reusing clusters created by functionality test.

To run performance test for a specific integration test, the following changes are required:
1. Add `run_benchmarks` and `benchmarks` fixtures to the test:
```python
def test_feature(..., run_benchmarks, benchmarks):
    ...
```
2. Add `benchmarks` parameter to `pcluster_config_reader`. This addition lets the `pcluster_config_reader` know benchmarks are used, therefore add placement groups and set larger max count in the configuration file.
```python
def test_feature(..., run_benchmarks, benchmarks):
    ...
    cluster_config = pcluster_config_reader(benchmarks=benchmarks)
    ...
```
3. Decide the exact location in the test where the `run_benchmarks` should be called. The location is arbitrary. It can be the last line  of the test. Or if the test deletes/updates the cluster in the middle, you may want to call `run_benchmarks` before the deletes/updates.
```python
def test_feature(..., run_benchmarks, benchmarks):
    ...
    cluster_config = pcluster_config_reader(benchmarks=benchmarks)
    ...
    run_benchmarks(remote_command_executor, scheduler_commands)
    ...
```
3. You may add more keyword arguments to the `run_benchmarks` calls. The keyword arguments will be added to the dimensions of CloudWatch metrics.
```python
def test_feature(..., run_benchmarks):
    ...
    cluster_config = pcluster_config_reader(benchmarks=benchmarks)
    ...
    run_benchmarks(remote_command_executor, scheduler_commands, diretory_type="MicrosoftAD")
    ...
```
4. Decide if a larger head node instance type is needed and change the cluster configuration accordingly.
5. Specify what benchmarks to run in the tests suite definition file
```yaml
{%- import 'common.jinja2' as common -%}
---
test-suites:
  feature:
    test_feature.py::test_feature:
      dimensions:
        - regions: ["us-east-1"]
          instances: {{ common.INSTANCES_DEFAULT_X86 }}
          oss: ["centos7"]
          schedulers: ["slurm"]
        - regions: ["eu-west-1"]
          instances: {{ common.INSTANCES_DEFAULT_X86 }}
          oss: ["ubuntu2004"]
          schedulers: ["slurm"]
          benchmarks:
            - mpi_variants: ["openmpi"]
              num_instances: [100]
              osu_benchmarks:
                # Available collective benchmarks "osu_allgather", "osu_allreduce", "osu_alltoall", "osu_barrier", "osu_bcast", "osu_gather", "osu_reduce", "osu_reduce_scatter", "osu_scatter"
                collective: ["osu_allreduce", "osu_alltoall"]
                pt2pt: []
```
The definition above means the `osu_allreduce` and `osu_alltoall` will run in `eu-west-1`. You can extend the list under `benchmarks` or each parameters to get various combinations

6. Use `--benchmarks` option to run performance tests. Performance tests are disabled by default due to the high resource utilization involved with their execution.

In conclusion, the performance test will run for a test only if:
1. The test calls the `run_benchmark` fixture
2. Tests suite definition file contains benchmarks specification
3. `--benchmarks` option is used


## Expand Performance Tests
The current performance tests only support running OSU benchmarks. This section discusses how the current code is structured and how it facilitates adding more other performance test suites.
1. The `benchmarks` in the tests suite definition file is a list of arbitrary structure, which means other benchmarks definition can be added without any change to the code.
```yaml
{%- import 'common.jinja2' as common -%}
---
test-suites:
  feature:
    test_feature.py::test_feature:
      dimensions:
        - regions: ["eu-west-1"]
          instances: {{ common.INSTANCES_DEFAULT_X86 }}
          oss: ["ubuntu2004"]
          schedulers: ["slurm"]
          benchmarks:
            - mpi_variants: ["openmpi"]
              num_instances: [100]
              other_benchmarks:
                other_benchmarks_group: ["other_allreduce", "other_alltoall"]
```
2. The `run_benchmarks` fixture runs benchmarks for different `mpi_variants`, `num_instances` and pushes the result to CloudWatch with the correct namespace. The detailed execution of the OSU benchmarks is in `osu_common.py`, decoupled from the `run_benchmarks` fixture. So in the future, the `run_benchmarks` fixture will look like:
```python
@pytest.fixture()
def run_benchmarks(request, mpi_variants, test_datadir, instance, os, region, benchmarks):
  def _run_benchmarks(remote_command_executor, scheduler_commands, **kwargs):
    ...
    for mpi_variant, num_instances in product(benchmark.get("mpi_variants"), benchmark.get("num_instances")):
        metric_namespace = f"ParallelCluster/{function_name}"
        ...
        osu_benchmarks = benchmark.get("osu_benchmarks", [])
        if osu_benchmarks:
            metric_data_list = run_osu_benchmarks(...)
            for metric_data in metric_data_list:
                cloudwatch_client.put_metric_data(Namespace=metric_namespace, MetricData=metric_data)

        other_benchmarks = benchmark.get("other_benchmarks", [])
        if other_benchmarks:
            metric_data_list = run_other_benchmarks(...)
            for metric_data in metric_data_list:
                cloudwatch_client.put_metric_data(Namespace=metric_namespace, MetricData=metric_data)
```

### Troubleshooting and fixes

* `IdentityFile` option in `ssh/config` will trigger a `str has no attribute extend` bug in the `fabric` package.
Please remove `IdentityFile` option from `ssh/config` before running the testing framework

## Collect system analysis

In case of performance degradation detected in tests, to speed up the root cause analysis it is useful to have a
report of all the services, cron settings and information about the tested cluster. The function `run_system_analyzer` creates a subfolder
in `out_dir` called `system_analyzer`. Every run the function creates 2 files, one for the head node and one
for a compute node of the fleet. The generated file is a `tar.gz` archive containing a directory structure
which is comparable with `diff`. Moreover, the function also collects some network statistics which can be inspected to
get information about dropped packages and other meaningful network metrics.

The information collected are:
* System id: ubuntu, amzn or centos
* System version
* uname with kernel version
* Installed packages
* Services and timers active on the system
* Scheduled commands like cron, at, anacron
* The available MPI modules
* The configured network and the statistics associated to those network
* ami-id, instance-type and user data queried from the instance metadata service (IMDSv2)

### How to add system analysis to a test

In order to add the system analysis to a test do the following:
1. Import the function from utils.py (e.g. `from tests.common.utils import run_system_analyzer`)
2. Call the function after the cluster creation; can be useful to run it as the last step of the test.
If needed, it is possible to specify the partition from which to collect compute node info.
```python
def run_system_analyzer(cluster, scheduler_commands_factory, request, partition=None):
...
```
### How to compare system analysis

The nodeJS `diff2html` generates a html file from a diff which helps to compare the differences.
Compare result from different node type (head, compute) can create misleading results: it is suggested to compare the
same node type (e.g. head with head)
Below an example on how compare system analysis results :
```bash
npm install -g diff2html

# Get the archives
ls .
headnode-current-run.tar.gz
headnode-previous-run.tar.gz

# Extract the archives in 2 separated directory
mkdir current-run
mkdir previous-run
tar xzvf headnode-current-run.tar.gz -C current-run/
tar xzvf headnode-previous-run.tar.gz -C previous-run/

# Compare and generate the diff.html file
diff --exclude=network/ -u *-run/system-information | diff2html -s side -i stdin -o stdout > diff.html ;
```

Once generated the file can be inspected in the browser.
