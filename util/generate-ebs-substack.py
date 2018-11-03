import troposphere.ec2 as ec2
from troposphere import Parameter, Condition, Ref, Template, Select, If, Equals, And, Not, NoValue, Join, Output

numberOfVol = 5


t = Template()
AvailabilityZone = t.add_parameter(Parameter("AvailabilityZone",
                                             Type="String",
                                             Description="Availability Zone the cluster will launch into. THIS IS REQUIRED"))
VolumeSize = t.add_parameter(Parameter("VolumeSize",
                                       Type="CommaDelimitedList",
                                       Description = "Size of EBS volume in GB, if creating a new one"))
VolumeType = t.add_parameter(Parameter("VolumeType",
                                       Type="CommaDelimitedList",
                                       Description="Type of volume to create either new or from snapshot"))
VolumeIOPS = t.add_parameter(Parameter("VolumeIOPS",
                                       Type="CommaDelimitedList",
                                       Description= "Number of IOPS for volume type io1. Not used for other volume types."))
EBSEncryption = t.add_parameter(Parameter("EBSEncryption",
                                          Type="CommaDelimitedList",
                                          Description="Boolean flag to use EBS encryption for /shared volume. "
                                                      "(Not to be used for snapshots)"))
EBSKMSKeyId = t.add_parameter(Parameter("EBSKMSKeyId",
                                        Type="CommaDelimitedList",
                                        Description="KMS ARN for customer created master key, will be used for EBS encryption"))
EBSVolumeId = t.add_parameter(Parameter("EBSVolumeId",
                                        Type="CommaDelimitedList",
                                        Description="Existing EBS volume Id"))
EBSSnapshotId = t.add_parameter(Parameter("EBSSnapshotId",
                                          Type="CommaDelimitedList",
                                          Description="Id of EBS snapshot if using snapshot as source for volume"))
EBSVolumeNum = t.add_parameter(Parameter("NumberOfEBSVol",
                                         Type="Number",
                                         Description= "Number of EBS Volumes the user requested, up to %s" %numberOfVol))

UseVol = [None]*numberOfVol
UseExistingEBSVolume = [None]*numberOfVol
v = [None]*numberOfVol

for i in range(numberOfVol):
    if i == 0:
        CreateVol = t.add_condition("Vol%s_CreateEBSVolume" % (i + 1),
                                    Equals(Select(str(i), Ref(EBSVolumeId)), "NONE"))
    elif i == 1:
        UseVol[i] = t.add_condition("UseVol%s" % (i + 1), Not(Equals(Ref(EBSVolumeNum), str(i))))
        CreateVol = t.add_condition("Vol%s_CreateEBSVolume" % (i + 1),
                                    And(Condition(UseVol[i]), Equals(Select(str(i), Ref(EBSVolumeId)), "NONE")))
    else:
        UseVol[i] = t.add_condition("UseVol%s" % (i + 1), And(Not(Equals(Ref(EBSVolumeNum), str(i))), Condition(UseVol[i-1])))
        CreateVol = t.add_condition("Vol%s_CreateEBSVolume" % (i + 1),
                                    And(Condition(UseVol[i]), Equals(Select(str(i), Ref(EBSVolumeId)), "NONE")))

    UseEBSPIOPS = t.add_condition("Vol%s_UseEBSPIOPS" % (i + 1),
                                  Equals(Select(str(i), Ref(VolumeType)), "io1"))
    UseVolumeSize = t.add_condition("Vol%s_UseVolumeSize" % (i + 1),
                                    Not(Equals(Select(str(i), Ref(VolumeSize)), "NONE")))
    UseVolumeType = t.add_condition("Vol%s_UseVolumeType" % (i + 1),
                                    Not(Equals(Select(str(i), Ref(VolumeType)), "NONE")))
    UseEBSEncryption = t.add_condition("Vol%s_UseEBSEncryption" % (i + 1),
                                       Equals(Select(str(i), Ref(EBSEncryption)), "true"))
    UseEBSKMSKey = t.add_condition("Vol%s_UseEBSKMSKey" % (i + 1),
                                   And(Condition(UseEBSEncryption), Not(Equals(Select(str(i), Ref(EBSKMSKeyId)), "NONE"))))
    UseEBSSnapshot = t.add_condition("Vol%s_UseEBSSnapshot" % (i + 1),
                                     Not(Equals(Select(str(i), Ref(EBSSnapshotId)), "NONE")))
    UseExistingEBSVolume[i] = t.add_condition("Vol%s_UseExistingEBSVolume" % (i + 1),
                                              Not(Equals(Select(str(i), Ref(EBSVolumeId)), "NONE")))
    v[i] = t.add_resource(ec2.Volume("Volume%s" % (i + 1),
                                     AvailabilityZone=Ref(AvailabilityZone),
                                     VolumeType=If(UseVolumeType, Select(str(i), Ref(VolumeType)), "gp2"),
                                     Size=If(UseEBSSnapshot, NoValue, If(UseVolumeSize, Select(str(i), Ref(VolumeSize)), "20")),
                                     SnapshotId=If(UseEBSSnapshot, Select(str(i), Ref(EBSSnapshotId)), NoValue),
                                     Iops=If(UseEBSPIOPS, Select(str(i), Ref(VolumeIOPS)), NoValue),
                                     Encrypted=If(UseEBSEncryption, Select(str(i), Ref(EBSEncryption)), NoValue),
                                     KmsKeyId=If(UseEBSKMSKey, Select(str(i), Ref(EBSKMSKeyId)), NoValue),
                                     Condition=CreateVol
                                     ))

outputs = [None]*numberOfVol
volToReturn = [None]*numberOfVol
for i in range(numberOfVol):
    volToReturn[i] = If(UseExistingEBSVolume[i], Select(str(i), Ref(EBSVolumeId)), Ref(v[i]))
    if i == 0:
        outputs[i] = volToReturn[i]
    else:
        outputs[i] = If(UseVol[i], Join(",", volToReturn[:(i+1)]), outputs[i-1])

t.add_output(Output("Volumeids",
                    Description= "Volume IDs of the resulted EBS volumes",
                    Value=outputs[numberOfVol-1]))

jsonFilePath = "targetPath"
outputfile = open(jsonFilePath, "w")
outputfile.write(t.to_json())
outputfile.close()