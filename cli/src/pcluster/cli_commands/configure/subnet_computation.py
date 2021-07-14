# Copyright 2018 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance with
# the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.

from ipaddress import ip_address, ip_network, summarize_address_range


def unicode(ip_addr):
    return "{0}".format(ip_addr)


def get_subnet_cidr(vpc_cidr, occupied_cidr, min_subnet_size):
    """
    Decide the parallelcluster subnet size of the compute fleet.

    :param vpc_cidr: the vpc_cidr in which the suitable subnet should be
    :param occupied_cidr: a list of cidr of the already occupied subnets in the vpc
    :param min_subnet_size: the minimum size of the subnet
    :return:
    """
    default_target_size = 4000
    target_size = max(default_target_size, 2 * min_subnet_size)
    cidr = evaluate_cidr(vpc_cidr, occupied_cidr, target_size)
    while cidr is None:
        if target_size < min_subnet_size:
            return None
        target_size = target_size // 2
        cidr = evaluate_cidr(vpc_cidr, occupied_cidr, target_size)
    return cidr


def evaluate_cidr(vpc_cidr, occupied_cidrs, target_size):
    """
    Decide the first smallest suitable CIDR for a subnet with size >= target_size.

    In order to find a space in between all the subnets we have, we first start by making all the occupied subnets size
    bigger or equal to the one we are targeting. In order to do that, if a subnet is smaller than target_size, we will
    find the bigger one to which she is part of.

    After that, we will sort the subnet by cidr and than look for space between the end of one subnet and the beginning
    of the other, not forgetting to also look for space in the begin and end.
    :param vpc_cidr: the vpc_cidr in which the suitable subnet should be
    :param occupied_cidrs: a list of cidr of the already occupied subnets in the vpc
    :param target_size: the minimum target size of the subnet
    :return: the suitable CIDR if found, else None
    """
    subnet_size, subnet_bitmask = _evaluate_subnet_size(target_size)
    vpc_begin_address_decimal, vpc_end_address_decimal = _get_cidr_limits_as_decimal(vpc_cidr)

    # if we do not have enough space
    if vpc_end_address_decimal - vpc_begin_address_decimal + 1 < subnet_size:
        return None

    # if we have space and no occupied cidr
    if not occupied_cidrs:
        return _decimal_ip_limits_to_cidr(vpc_begin_address_decimal, vpc_begin_address_decimal + subnet_size)

    lower_limit_index = 0
    upper_limit_index = 1

    # Get subnets limits
    occupied_cidrs = _align_subnet_cidrs(occupied_cidrs, subnet_bitmask)
    subnets_limits = [_get_cidr_limits_as_decimal(subnet) for subnet in occupied_cidrs]
    subnets_limits.sort(key=lambda x: x[upper_limit_index])

    #  Looking at space between occupied cidrs
    resulting_cidr = None

    subnets_limits.append((vpc_end_address_decimal, vpc_end_address_decimal))
    for index, subnet_limit in enumerate(subnets_limits):
        current_lower_limit = subnet_limit[lower_limit_index]
        # In the first case, vpc_begin_address is free, whereas upper_limit_index is not
        previous_upper_limit = (
            subnets_limits[index - 1][upper_limit_index] if index > 0 else vpc_begin_address_decimal - 1
        )
        if current_lower_limit - previous_upper_limit > subnet_size:
            resulting_cidr = _decimal_ip_limits_to_cidr(previous_upper_limit + 1, previous_upper_limit + subnet_size)
            break

    return resulting_cidr


def _align_subnet_cidrs(occupied_cidr, target_bitmask):
    """Transform the subnet cidr that are smaller than the minimum bitmask to bigger ones."""
    correct_cidrs = set()
    for subnet_cidr in occupied_cidr:
        if _get_bitmask(subnet_cidr) > target_bitmask:
            correct_cidrs.add(expand_cidr(subnet_cidr, target_bitmask))
        else:
            correct_cidrs.add(subnet_cidr)
    return list(correct_cidrs)


def _get_bitmask(cidr):
    return int(cidr.split("/")[1])


def _evaluate_subnet_size(target_size):
    aws_reserved_ip = 6
    min_bitmask = 28
    subnet_bitmask = min(32 - ((next_power_of_2(target_size + aws_reserved_ip) - 1).bit_length()), min_bitmask)
    subnet_size = 2 ** (32 - subnet_bitmask)
    return subnet_size, subnet_bitmask


def _decimal_ip_limits_to_cidr(begin, end):
    """Given begin and end ip (as decimals number), return the CIDR that begins with begin ip and ends with end ip."""
    return str(next(summarize_address_range(ip_address(begin), ip_address(end))))


def _get_cidr_limits_as_decimal(cidr):
    """
    Given a cidr, return the begin ip and the end ip as decimal.

    For example, given the cidr 10.0.0.0/24, it will return 167772160, which is 10.0.0.0 and 167772416,
    which is 10.0.1.0
    :param: cidr the cidr to convert
    :return: a tuple (decimal begin address, decimal end address)
    """
    address = ip_network(unicode(cidr))
    return _ip_to_decimal(str(address[0])), _ip_to_decimal(str(address[-1]))


def _ip_to_decimal(ip_addr):
    """Transform an ip into its decimal representation."""
    return int(ip_address(unicode(ip_addr)))


def expand_cidr(cidr, new_size):
    """
    Given a cidr, it upgrade is netmask to new_size.

    :param cidr: the list of cidr to promote
    :param new_size: the minimum bitmask required
    """
    ip_addr = ip_network(unicode(cidr))
    return str(ip_addr.supernet(new_prefix=new_size))


def next_power_of_2(number):
    """Given a number returns the following power of 2 of that number."""
    return 1 if number == 0 else 2 ** (number - 1).bit_length()
