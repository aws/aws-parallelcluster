from network_template_builder import Gateways, NetworkTemplateBuilder, SubnetConfig, VPCConfig


def generate_public_template(path):
    """
    Generate a template for a network configuration with one public subnet.

    The generated template will obligatory ask for the CIDR of the subnet and the vpc-id. If the vpc has already an
    internet gateway, you must pass it as a parameter. You can optionally specify the availability zone if you need a
    specific one.
    :param path: the path in which write the file
    """
    public_subnet = SubnetConfig(
        name="Public", map_public_ip_on_launch=False, has_nat_gateway=False, default_gateway=Gateways.INTERNET_GATEWAY
    )
    existing_vpc = VPCConfig(subnets=[public_subnet])
    template = NetworkTemplateBuilder(vpc_configuration=existing_vpc, existing_vpc=True).build()
    _write_json_to_file(template, path)


def generate_public_private_template(path):
    """
    Generate a template for a network configuration with one public subnet and one private subnet with NAT.

    The generated template will obligatory ask for both CIDR of the public subnet and the private one. It will also ask
    for the vpc-id. If the vpc has already an internet gateway, you must pass it as a parameter. You can optionally
    specify the availability zone if you need a specific one.
    :param path: the path in which write the file
    """
    public_subnet = SubnetConfig(
        name="Public", map_public_ip_on_launch=True, has_nat_gateway=True, default_gateway=Gateways.INTERNET_GATEWAY
    )
    private_subnet = SubnetConfig(
        name="Private", map_public_ip_on_launch=False, has_nat_gateway=False, default_gateway=Gateways.NAT_GATEWAY
    )
    existing_vpc = VPCConfig(subnets=[public_subnet, private_subnet])
    template = NetworkTemplateBuilder(vpc_configuration=existing_vpc, existing_vpc=True).build()
    _write_json_to_file(template, path)


def _write_json_to_file(template, path):
    with open(path, "w+") as file:
        file.write(template.to_json())


if __name__ == "__main__":
    generate_public_private_template("public-private.cfn.json")
    generate_public_template("public.cfn.json")
