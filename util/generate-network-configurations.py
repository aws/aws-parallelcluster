from troposphere import Template, Parameter, Ref, Output
from troposphere.ec2 import (
    Subnet, InternetGateway, RouteTable, VPCGatewayAttachment, Route, SubnetRouteTableAssociation
)


class NetworkHandler:

    def __init__(self):
        self.template = Template()

    def __add_parameter(self, name, description, expected_input):
        return self.template.add_parameter(Parameter(name, Description=description, Type=expected_input))

    def __add_output(self, name, description, value):
        return self.template.add_output(Output(name, Description=description, Value=value))

    def __write_template(self, path):
        with open(path, "w+") as file:
            file.write(self.template.to_json())

    def create_public(self, path):
        vpc = self.__add_parameter(name="vpcID", description="String containing the vpc id", expected_input="String")
        subnet_cidr = self.__add_parameter(
            name="SubnetCidr",
            description="CIDR describing the size of the subnet",
            expected_input="String",
        )
        availability_zone = self.__add_parameter(
            name="AvailabilityZone",
            description="The zone in which you want to create your subnet(s)",
            expected_input="String",
        )
        master_subnet = self.template.add_resource(
            Subnet(
                "MasterSubnet",
                CidrBlock=Ref(subnet_cidr),
                VpcId=Ref(vpc),
                AvailabilityZone=Ref(availability_zone),
                Tags=[{"Key": "Name", "Value": "Pcluster Master Subnet"}]
            )
        )
        internet_gateway = self.template.add_resource(
            InternetGateway("InternetGateway", Tags=[{"Key": "Name", "Value": "Pcluster internet gateway"}])
        )
        gatewayAttachment = self.template.add_resource(
            VPCGatewayAttachment(
                'AttachGateway',
                VpcId=Ref(vpc),
                InternetGatewayId=Ref(internet_gateway)
            )
        )
        route_table = self.template.add_resource(
            RouteTable(
                "RouteTable",
                VpcId=Ref(vpc),
                Tags=[{"Key": "Name", "Value": "Pcluster route table"}]
            )
        )
        route = self.template.add_resource(
            Route(
                "Route",
                DependsOn="AttachGateway",
                GatewayId=Ref("InternetGateway"),
                DestinationCidrBlock="0.0.0.0/0",
                RouteTableId=Ref(route_table),
            )
        )
        subnetRouteTableAssociation = self.template.add_resource(
            SubnetRouteTableAssociation(
                'SubnetRouteTableAssociation',
                SubnetId=Ref(master_subnet),
                RouteTableId=Ref(route_table),
            )
        )
        self.__add_output(name="VpcId", description="The VPC id of the network", value=Ref(vpc))
        self.__add_output(name="MasterSubnetId", description="The master subnet id", value=Ref(master_subnet))
        self.__write_template(path)


if __name__ == '__main__':
    generator = NetworkHandler()
    generator.create_public("public.json")
