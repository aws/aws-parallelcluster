import argparse
import troposphere.ec2 as ec2
from troposphere import And, Condition, Equals, If, Join, Not, NoValue, Output, Parameter, Ref, Select, Template


def main(args):
    number_of_vol = 5

    t = Template()
    availability_zone = t.add_parameter(
        Parameter(
            "AvailabilityZone",
            Type="String",
            Description="Availability Zone the cluster will launch into. THIS IS REQUIRED",
        )
    )
    volume_size = t.add_parameter(
        Parameter(
            "VolumeSize", Type="CommaDelimitedList", Description="Size of EBS volume in GB, if creating a new one"
        )
    )
    volume_type = t.add_parameter(
        Parameter(
            "VolumeType", Type="CommaDelimitedList", Description="Type of volume to create either new or from snapshot"
        )
    )
    volume_iops = t.add_parameter(
        Parameter(
            "VolumeIOPS",
            Type="CommaDelimitedList",
            Description="Number of IOPS for volume type io1. Not used for other volume types.",
        )
    )
    ebs_encryption = t.add_parameter(
        Parameter(
            "EBSEncryption",
            Type="CommaDelimitedList",
            Description="Boolean flag to use EBS encryption for /shared volume. " "(Not to be used for snapshots)",
        )
    )
    ebs_kms_id = t.add_parameter(
        Parameter(
            "EBSKMSKeyId",
            Type="CommaDelimitedList",
            Description="KMS ARN for customer created master key, will be used for EBS encryption",
        )
    )
    ebs_volume_id = t.add_parameter(
        Parameter("EBSVolumeId", Type="CommaDelimitedList", Description="Existing EBS volume Id")
    )
    ebs_snapshot_id = t.add_parameter(
        Parameter(
            "EBSSnapshotId",
            Type="CommaDelimitedList",
            Description="Id of EBS snapshot if using snapshot as source for volume",
        )
    )
    ebs_vol_num = t.add_parameter(
        Parameter(
            "NumberOfEBSVol",
            Type="Number",
            Description="Number of EBS Volumes the user requested, up to %s" % number_of_vol,
        )
    )

    use_vol = [None] * number_of_vol
    use_existing_ebs_volume = [None] * number_of_vol
    v = [None] * number_of_vol

    for i in range(number_of_vol):
        if i == 0:
            create_vol = t.add_condition(
                "Vol%s_CreateEBSVolume" % (i + 1), Equals(Select(str(i), Ref(ebs_volume_id)), "NONE")
            )
        elif i == 1:
            use_vol[i] = t.add_condition("UseVol%s" % (i + 1), Not(Equals(Ref(ebs_vol_num), str(i))))
            create_vol = t.add_condition(
                "Vol%s_CreateEBSVolume" % (i + 1),
                And(Condition(use_vol[i]), Equals(Select(str(i), Ref(ebs_volume_id)), "NONE")),
            )
        else:
            use_vol[i] = t.add_condition(
                "UseVol%s" % (i + 1), And(Not(Equals(Ref(ebs_vol_num), str(i))), Condition(use_vol[i - 1]))
            )
            create_vol = t.add_condition(
                "Vol%s_CreateEBSVolume" % (i + 1),
                And(Condition(use_vol[i]), Equals(Select(str(i), Ref(ebs_volume_id)), "NONE")),
            )

        use_ebs_iops = t.add_condition("Vol%s_UseEBSPIOPS" % (i + 1), Equals(Select(str(i), Ref(volume_type)), "io1"))
        use_vol_size = t.add_condition(
            "Vol%s_UseVolumeSize" % (i + 1), Not(Equals(Select(str(i), Ref(volume_size)), "NONE"))
        )
        use_vol_type = t.add_condition(
            "Vol%s_UseVolumeType" % (i + 1), Not(Equals(Select(str(i), Ref(volume_type)), "NONE"))
        )
        use_ebs_encryption = t.add_condition(
            "Vol%s_UseEBSEncryption" % (i + 1), Equals(Select(str(i), Ref(ebs_encryption)), "true")
        )
        use_ebs_kms_key = t.add_condition(
            "Vol%s_UseEBSKMSKey" % (i + 1),
            And(Condition(use_ebs_encryption), Not(Equals(Select(str(i), Ref(ebs_kms_id)), "NONE"))),
        )
        use_ebs_snapshot = t.add_condition(
            "Vol%s_UseEBSSnapshot" % (i + 1), Not(Equals(Select(str(i), Ref(ebs_snapshot_id)), "NONE"))
        )
        use_existing_ebs_volume[i] = t.add_condition(
            "Vol%s_UseExistingEBSVolume" % (i + 1), Not(Equals(Select(str(i), Ref(ebs_volume_id)), "NONE"))
        )
        v[i] = t.add_resource(
            ec2.Volume(
                "Volume%s" % (i + 1),
                AvailabilityZone=Ref(availability_zone),
                VolumeType=If(use_vol_type, Select(str(i), Ref(volume_type)), "gp2"),
                Size=If(use_vol_size, Select(str(i), Ref(volume_size)), "20"),
                SnapshotId=If(use_ebs_snapshot, Select(str(i), Ref(ebs_snapshot_id)), NoValue),
                Iops=If(use_ebs_iops, Select(str(i), Ref(volume_iops)), NoValue),
                Encrypted=If(use_ebs_encryption, Select(str(i), Ref(ebs_encryption)), NoValue),
                KmsKeyId=If(use_ebs_kms_key, Select(str(i), Ref(ebs_kms_id)), NoValue),
                Condition=create_vol,
            )
        )

    outputs = [None] * number_of_vol
    vol_to_return = [None] * number_of_vol
    for i in range(number_of_vol):
        vol_to_return[i] = If(use_existing_ebs_volume[i], Select(str(i), Ref(ebs_volume_id)), Ref(v[i]))
        if i == 0:
            outputs[i] = vol_to_return[i]
        else:
            outputs[i] = If(use_vol[i], Join(",", vol_to_return[: (i + 1)]), outputs[i - 1])

    t.add_output(
        Output("Volumeids", Description="Volume IDs of the resulted EBS volumes", Value=outputs[number_of_vol - 1])
    )

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
