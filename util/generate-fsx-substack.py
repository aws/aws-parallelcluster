import argparse

import troposphere.ec2 as ec2
from troposphere import And, Condition, Equals, If, Not, NoValue, Output, Parameter, Ref, Select, Template


def main(args):
    t = Template()

    # [0 shared_dir, 1 efs_fs_id, 2 performance_mode, 3 efs_kms_key_id,
    # 4 provisioned_throughput, 5 encrypted, 6 throughput_mode, 7 exists_valid_mt]
    fsx_options = t.add_parameter(
        Parameter(
            "FSXOptions",
            Type="CommaDelimitedList",
            Description="Comma separated list of efs related options, 4 parameters in total",
        )
    )
    compute_security_group = t.add_parameter(
        Parameter("ComputeSecurityGroup", Type="String", Description="SecurityGroup for FSx filesystem")
    )
    subnet_id = t.add_parameter(Parameter("SubnetId", Type="String", Description="SubnetId for FSx filesystem"))
    create_fsx = t.add_condition(
        "CreateFSX",
        And(Not(Equals(Select(str(0), Ref(fsx_options)), "NONE")), Equals(Select(str(1), Ref(fsx_options)), "NONE")),
    )
    use_storage_capacity = t.add_condition("UseStorageCap", Not(Equals(Select(str(2), Ref(fsx_options)), "NONE")))
    use_fsx_kms_key = t.add_condition("UseFSXKMSKey", Not(Equals(Select(str(3), Ref(fsx_options)), "NONE")))

    # Follow similar template when official FSx CFN resource is released
    # fs = t.add_resource(
    #     FSXFileSystem(
    #         "FSXFS",
    #         FileSystemType="LUSTRE",
    #         StorageCapacity=If(use_storage_capacity, Select(str(2), Ref(fsx_options)), 3600),
    #         SubnetIds=Ref(subnet_id),
    #         SecurityGroupIds=Ref(compute_security_group),
    #         KmsKeyId=If(use_fsx_kms_key, Select(str(3), Ref(fsx_options)), NoValue),
    #         Condition=create_fsx,
    #     )
    # )
    #
    # t.add_output(
    #     Output(
    #         "FileSystemId",
    #         Description="ID of the FileSystem",
    #         Value=If(create_fsx, Ref(fs), Select("1", Ref(fsx_options))),
    #     )
    # )

    t.add_resource(
        ec2.Volume(
            "fakeVolume",
            AvailabilityZone="us-east-2a",
            VolumeType="gp2",
            Size="20",
            SnapshotId=NoValue,
            Iops=NoValue,
            Encrypted=NoValue,
            KmsKeyId=NoValue,
        )
    )

    t.add_output(Output("FileSystemId", Description="ID of the FileSystem", Value=Select("1", Ref(fsx_options))))

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
