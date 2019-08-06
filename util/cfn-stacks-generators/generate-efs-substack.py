import argparse

from troposphere import And, Condition, Equals, If, Not, NoValue, Output, Parameter, Ref, Select, Template
from troposphere.efs import FileSystem, MountTarget


def main(args):
    t = Template()

    # [0 shared_dir, 1 efs_fs_id, 2 performance_mode, 3 efs_kms_key_id,
    # 4 provisioned_throughput, 5 encrypted, 6 throughput_mode, 7 exists_valid_mt]
    efs_options = t.add_parameter(
        Parameter(
            "EFSOptions",
            Type="CommaDelimitedList",
            Description="Comma separated list of efs related options, " "8 parameters in total",
        )
    )
    compute_security_group = t.add_parameter(
        Parameter("ComputeSecurityGroup", Type="String", Description="SecurityGroup for Mount Target")
    )
    subnet_id = t.add_parameter(Parameter("SubnetId", Type="String", Description="SubnetId for Mount Target"))
    create_efs = t.add_condition(
        "CreateEFS",
        And(Not(Equals(Select(str(0), Ref(efs_options)), "NONE")), Equals(Select(str(1), Ref(efs_options)), "NONE")),
    )
    create_mt = t.add_condition(
        "CreateMT",
        And(Not(Equals(Select(str(0), Ref(efs_options)), "NONE")), Equals(Select(str(7), Ref(efs_options)), "NONE")),
    )
    use_performance_mode = t.add_condition("UsePerformanceMode", Not(Equals(Select(str(2), Ref(efs_options)), "NONE")))
    use_efs_encryption = t.add_condition("UseEFSEncryption", Equals(Select(str(5), Ref(efs_options)), "true"))
    use_efs_kms_key = t.add_condition(
        "UseEFSKMSKey", And(Condition(use_efs_encryption), Not(Equals(Select(str(3), Ref(efs_options)), "NONE")))
    )
    use_throughput_mode = t.add_condition("UseThroughputMode", Not(Equals(Select(str(6), Ref(efs_options)), "NONE")))
    use_provisioned = t.add_condition("UseProvisioned", Equals(Select(str(6), Ref(efs_options)), "provisioned"))
    use_provisioned_throughput = t.add_condition(
        "UseProvisionedThroughput",
        And(Condition(use_provisioned), Not(Equals(Select(str(4), Ref(efs_options)), "NONE"))),
    )

    fs = t.add_resource(
        FileSystem(
            "EFSFS",
            PerformanceMode=If(use_performance_mode, Select(str(2), Ref(efs_options)), NoValue),
            ProvisionedThroughputInMibps=If(use_provisioned_throughput, Select(str(4), Ref(efs_options)), NoValue),
            ThroughputMode=If(use_throughput_mode, Select(str(6), Ref(efs_options)), NoValue),
            Encrypted=If(use_efs_encryption, Select(str(5), Ref(efs_options)), NoValue),
            KmsKeyId=If(use_efs_kms_key, Select(str(3), Ref(efs_options)), NoValue),
            Condition=create_efs,
        )
    )

    mt = t.add_resource(
        MountTarget(
            "EFSMT",
            FileSystemId=If(create_efs, Ref(fs), Select(str(1), Ref(efs_options))),
            SecurityGroups=[Ref(compute_security_group)],
            SubnetId=Ref(subnet_id),
            Condition=create_mt,
        )
    )

    t.add_output(
        Output(
            "FileSystemId",
            Description="ID of the FileSystem",
            Value=If(create_efs, Ref(fs), Select("1", Ref(efs_options))),
        )
    )

    # Specify output file path
    json_file_path = args.target_path
    output_file = open(json_file_path, "w")
    output_file.write(t.to_json())
    output_file.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Take in generator related parameters")
    parser.add_argument(
        "--target-path", type=str, help="The target path for generated substack template", required=True
    )
    args = parser.parse_args()
    main(args)
