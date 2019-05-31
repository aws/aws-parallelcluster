from troposphere import Template, Parameter, Ref, Output, Equals, Not, GetAtt, If
from troposphere.ec2 import (
    Subnet,
    InternetGateway,
    RouteTable,
    VPCGatewayAttachment,
    Route,
    SubnetRouteTableAssociation,
    NatGateway,
    EIP,
)


class NetworkHandler:
    def __init__(self):
        self.template = Template()

    @staticmethod
    def __add_name(resource_name):
        return [{"Key": "Name", "Value": f"Pcluster {resource_name}"}]

    def __add_parameter(self, name, description, expected_input):
        return self.template.add_parameter(Parameter(name, Description=description, Type=expected_input))

    def __add_output(self, name, description, value):
        return self.template.add_output(Output(name, Description=description, Value=value))

    def __write_template(self, path):
        with open(path, "w+") as file:
            file.write(self.template.to_yaml())

    def __create_gateway(self, vpc, gateway_attachment_name):
        internet_gateway = self.template.add_resource(
            InternetGateway("InternetGateway", Tags=NetworkHandler.__add_name("Internet Gateway"))
        )
        self.template.add_resource(
            VPCGatewayAttachment(gateway_attachment_name, VpcId=Ref(vpc), InternetGatewayId=Ref(internet_gateway))
        )
        return internet_gateway

    def __create_route_table_with_ig(self, vpc, internet_gateway, gateway_attachment_name, subnet):
        route_table = self.template.add_resource(
            RouteTable("RouteTable", VpcId=Ref(vpc), Tags=NetworkHandler.__add_name("Public Route Table"))
        )
        self.template.add_resource(
            Route(
                "Route",
                DependsOn=gateway_attachment_name,
                GatewayId=Ref(internet_gateway),
                DestinationCidrBlock="0.0.0.0/0",
                RouteTableId=Ref(route_table),
            )
        )
        self.template.add_resource(
            SubnetRouteTableAssociation(
                "SubnetRouteTableAssociation", SubnetId=Ref(subnet), RouteTableId=Ref(route_table)
            )
        )
        return route_table

    def __create_nat(self, compute_subnet, condition, master_subnet, vpc):
        nat_eip = self.template.add_resource(EIP("NatEip", Domain=Ref(vpc), Condition=condition))
        nat = self.template.add_resource(
            NatGateway(
                "Nat",
                AllocationId=GetAtt(nat_eip, "AllocationId"),
                SubnetId=Ref(master_subnet),
                Condition=condition,
                Tags=[{"Key": "Name", "Value": "NAT"}],
            )
        )
        private_route_table = self.template.add_resource(
            RouteTable(
                "PrivateRouteTable",
                VpcId=Ref(vpc),
                Tags=[{"Key": "Name", "Value": "Private Route Table"}],
                Condition=condition,
            )
        )
        self.template.add_resource(
            Route(
                "NatRoute",
                RouteTableId=Ref(private_route_table),
                DestinationCidrBlock="0.0.0.0/0",
                NatGatewayId=Ref(nat),
                Condition=condition,
            )
        )
        self.template.add_resource(
            SubnetRouteTableAssociation(
                "SubnetRouteTableAssociation2",
                SubnetId=Ref(compute_subnet),
                RouteTableId=Ref(private_route_table),
                Condition=condition,
            )
        )

    def create(self, path):
        vpc = self.__add_parameter(name="VpcId", description="The vpc id", expected_input="String")

        # Parameters
        master_subnet_cidr = self.__add_parameter(
            name="MasterSubnetCidr",
            description="CIDR describing the size of the master subnet",
            expected_input="String",
        )
        compute_subnet_cidr = self.__add_parameter(
            name="ComputeSubnetCidr",
            description="(Optional) CIDR describing the size of the compute subnet",
            expected_input="String",
        )
        availability_zone = self.__add_parameter(
            name="AvailabilityZone",
            description="(Optional) The zone in which you want to create your subnet(s)",
            expected_input="String",
        )

        # Conditions
        is_compute_cidr_set = self.template.add_condition("IsComputeCIDRSet", Not(Equals(Ref(compute_subnet_cidr), "")))

        # Always created Resources
        master_subnet = self.template.add_resource(
            Subnet(
                "MasterSubnet",
                CidrBlock=Ref(master_subnet_cidr),
                VpcId=Ref(vpc),
                AvailabilityZone=Ref(availability_zone),
                Tags=NetworkHandler.__add_name("Master Subnet"),
            )
        )
        gateway_attachment_name = "GateAttach"
        internet_gateway = self.__create_gateway(vpc, gateway_attachment_name)
        self.__create_route_table_with_ig(vpc, internet_gateway, gateway_attachment_name, master_subnet)

        # Optional Resources
        compute_subnet = self.template.add_resource(
            Subnet(
                "ComputeSubnet",
                CidrBlock=Ref(compute_subnet_cidr),
                VpcId=Ref(vpc),
                AvailabilityZone=GetAtt(master_subnet, "AvailabilityZone"),
                Tags=NetworkHandler.__add_name("Compute Subnet"),
                Condition=is_compute_cidr_set,
            )
        )
        self.__create_nat(compute_subnet, is_compute_cidr_set, master_subnet, vpc)

        # Outputs
        self.__add_output(name="VpcId", description="The VPC id of the network", value=Ref(vpc))
        self.__add_output(name="MasterSubnetId", description="The master subnet id", value=Ref(master_subnet))
        self.__add_output(
            name="ComputeSubnetId",
            description="The compute subnet id",
            value=If(is_compute_cidr_set, Ref(compute_subnet), "None"),
        )
        self.__write_template(path)


if __name__ == "__main__":
    generator = NetworkHandler()
    generator.create("public.yaml")
