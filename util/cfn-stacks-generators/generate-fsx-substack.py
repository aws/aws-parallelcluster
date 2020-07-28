import argparse
from troposphere import And, Equals, If, Not, NoValue, Output, Parameter, Ref, Select, Template
from troposphere.fsx import FileSystem, LustreConfiguration


def main(args):
    t = Template()

    # ================= Parameters =================
    #      0            1           2              3                    4                  5           6
    # [shared_dir,fsx_fs_id,storage_capacity,fsx_kms_key_id,imported_file_chunk_size,export_path,import_path,
    #              7
    # weekly_maintenance_start_time]
    fsx_options = t.add_parameter(
        Parameter(
            "FSXOptions",
            Type="CommaDelimitedList",
            Description="Comma separated list of fsx related options, 8 parameters in total, [shared_dir,fsx_fs_id,"
            "storage_capacity,fsx_kms_key_id,imported_file_chunk_size,export_path,import_path,"
            "weekly_maintenance_start_time]",
        )
    )

    compute_security_group = t.add_parameter(
        Parameter("ComputeSecurityGroup", Type="String", Description="SecurityGroup for FSx filesystem")
    )

    subnet_id = t.add_parameter(Parameter("SubnetId", Type="String", Description="SubnetId for FSx filesystem"))

    # ================= Conditions =================
    create_fsx = t.add_condition(
        "CreateFSX",
        And(Not(Equals(Select(str(0), Ref(fsx_options)), "NONE")), Equals(Select(str(1), Ref(fsx_options)), "NONE")),
    )

    use_storage_capacity = t.add_condition("UseStorageCap", Not(Equals(Select(str(2), Ref(fsx_options)), "NONE")))
    use_fsx_kms_key = t.add_condition("UseFSXKMSKey", Not(Equals(Select(str(3), Ref(fsx_options)), "NONE")))
    use_imported_file_chunk_size = t.add_condition(
        "UseImportedFileChunkSize", Not(Equals(Select(str(4), Ref(fsx_options)), "NONE"))
    )
    use_export_path = t.add_condition("UseExportPath", Not(Equals(Select(str(5), Ref(fsx_options)), "NONE")))
    use_import_path = t.add_condition("UseImportPath", Not(Equals(Select(str(6), Ref(fsx_options)), "NONE")))
    use_weekly_mainenance_start_time = t.add_condition(
        "UseWeeklyMaintenanceStartTime", Not(Equals(Select(str(7), Ref(fsx_options)), "NONE"))
    )

    # ================= Resources =================
    fs = t.add_resource(
        FileSystem(
            "FileSystem",
            FileSystemType="LUSTRE",
            SubnetIds=[Ref(subnet_id)],
            SecurityGroupIds=[Ref(compute_security_group)],
            KmsKeyId=If(use_fsx_kms_key, Select(str(3), Ref(fsx_options)), NoValue),
            StorageCapacity=If(use_storage_capacity, Select(str(2), Ref(fsx_options)), NoValue),
            LustreConfiguration=LustreConfiguration(
                ImportedFileChunkSize=If(use_imported_file_chunk_size, Select(str(4), Ref(fsx_options)), NoValue),
                ExportPath=If(use_export_path, Select(str(5), Ref(fsx_options)), NoValue),
                ImportPath=If(use_import_path, Select(str(6), Ref(fsx_options)), NoValue),
                WeeklyMaintenanceStartTime=If(
                    use_weekly_mainenance_start_time, Select(str(7), Ref(fsx_options)), NoValue
                ),
            ),
            Condition=create_fsx,
        )
    )

    # ================= Outputs =================
    t.add_output(
        Output(
            "FileSystemId",
            Description="ID of the FileSystem",
            Value=If(create_fsx, Ref(fs), Select("1", Ref(fsx_options))),
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
