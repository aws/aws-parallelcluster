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
            Description="Availability Zone the cluster will launch into. " "THIS IS REQUIRED",
        )
    )
    raid_options = t.add_parameter(
        Parameter(
            "RAIDOptions",
            Type="CommaDelimitedList",
            Description="Comma separated list of RAID related options, "
            "8 parameters in total, "
            "["
            "0 shared_dir,"
            "1 raid_type,"
            "2 num_of_vols,"
            "3 vol_type,"
            "4 vol_size,"
            "5 vol_IOPS,"
            "6 encrypted, "
            "7 ebs_kms_key]",
        )
    )
    use_vol = [None] * number_of_vol
    v = [None] * number_of_vol

    for i in range(number_of_vol):
        if i == 0:
            use_vol[i] = t.add_condition("UseVol%s" % (i + 1), Not(Equals(Select("0", Ref(raid_options)), "NONE")))
        else:
            use_vol[i] = t.add_condition(
                "UseVol%s" % (i + 1),
                And(Not(Equals(Select("2", Ref(raid_options)), str(i))), Condition(use_vol[i - 1])),
            )

        use_ebs_iops = t.add_condition("Vol%s_UseEBSPIOPS" % (i + 1), Equals(Select("3", Ref(raid_options)), "io1"))
        use_volume_size = t.add_condition(
            "Vol%s_UseVolumeSize" % (i + 1), Not(Equals(Select("4", Ref(raid_options)), "NONE"))
        )
        use_volume_type = t.add_condition(
            "Vol%s_UseVolumeType" % (i + 1), Not(Equals(Select("3", Ref(raid_options)), "NONE"))
        )
        use_ebs_encryption = t.add_condition(
            "Vol%s_UseEBSEncryption" % (i + 1), Equals(Select("6", Ref(raid_options)), "true")
        )
        use_ebs_kms_key = t.add_condition(
            "Vol%s_UseEBSKMSKey" % (i + 1),
            And(Condition(use_ebs_encryption), Not(Equals(Select("7", Ref(raid_options)), "NONE"))),
        )
        v[i] = t.add_resource(
            ec2.Volume(
                "Volume%s" % (i + 1),
                AvailabilityZone=Ref(availability_zone),
                VolumeType=If(use_volume_type, Select("3", Ref(raid_options)), "gp2"),
                Size=If(use_volume_size, Select("4", Ref(raid_options)), 20),
                Iops=If(use_ebs_iops, Select("5", Ref(raid_options)), NoValue),
                Encrypted=If(use_ebs_encryption, Select("6", Ref(raid_options)), NoValue),
                KmsKeyId=If(use_ebs_kms_key, Select("7", Ref(raid_options)), NoValue),
                Condition=use_vol[i],
            )
        )

    outputs = [None] * number_of_vol
    vol_to_return = [None] * number_of_vol
    for i in range(number_of_vol):
        vol_to_return[i] = Ref(v[i])
        if i == 0:
            outputs[i] = If(use_vol[i], vol_to_return[i], "NONE")
        else:
            outputs[i] = If(use_vol[i], Join(",", vol_to_return[: (i + 1)]), outputs[i - 1])

    t.add_output(
        Output("Volumeids", Description="Volume IDs of the resulted RAID EBS volumes", Value=outputs[number_of_vol - 1])
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
