from assertpy import assert_that

from pcluster.configure.subnet_computation import evaluate_cidr, get_subnet_cidr


def test_empty_vpc():
    assert_that(evaluate_cidr(vpc_cidr="10.0.0.0/16", occupied_cidrs=[], target_size=250)).is_equal_to("10.0.0.0/24")
    assert_that(evaluate_cidr(vpc_cidr="10.0.0.0/8", occupied_cidrs=[], target_size=250)).is_equal_to("10.0.0.0/24")
    assert_that(evaluate_cidr(vpc_cidr="10.2.0.0/16", occupied_cidrs=[], target_size=250)).is_equal_to("10.2.0.0/24")
    assert_that(evaluate_cidr(vpc_cidr="10.2.0.0/25", occupied_cidrs=[], target_size=500)).is_none()
    assert_that(evaluate_cidr(vpc_cidr="10.2.0.0/25", occupied_cidrs=[], target_size=100)).is_equal_to("10.2.0.0/25")


def test_fully_booked_vpc():
    assert_that(evaluate_cidr(vpc_cidr="10.0.0.0/16", occupied_cidrs=["10.0.0.0/16"], target_size=1)).is_none()
    assert_that(
        evaluate_cidr(vpc_cidr="10.0.0.0/16", occupied_cidrs=["10.0.0.0/17", "10.0.128.0/17"], target_size=1)
    ).is_none()
    assert_that(
        evaluate_cidr(
            vpc_cidr="10.0.0.0/16", occupied_cidrs=["10.0.0.0/18", "10.0.64.0/18", "10.0.128.0/18"], target_size=16385
        )
    ).is_none()
    assert_that(
        evaluate_cidr(vpc_cidr="10.0.0.0/16", occupied_cidrs=["10.0.0.0/18", "10.0.128.0/17"], target_size=16385)
    ).is_none()


# testing _expand_cidrs function
def test_target_size_bigger_than_allocated_subnets():
    assert_that(
        evaluate_cidr(vpc_cidr="10.0.0.0/16", occupied_cidrs=["10.0.1.0/24", "10.0.3.0/24"], target_size=500)
    ).is_equal_to("10.0.4.0/23")
    assert_that(
        evaluate_cidr(vpc_cidr="10.0.0.0/16", occupied_cidrs=["10.0.1.0/24", "10.0.4.0/24"], target_size=500)
    ).is_equal_to("10.0.2.0/23")
    assert_that(
        evaluate_cidr(vpc_cidr="10.0.0.0/16", occupied_cidrs=["10.0.1.0/24", "10.0.4.0/24"], target_size=1000)
    ).is_equal_to("10.0.8.0/22")


def test_target_size_smaller_than_allocated_subnets():
    assert_that(
        evaluate_cidr(vpc_cidr="10.0.0.0/16", occupied_cidrs=["10.0.1.0/24", "10.0.3.0/24"], target_size=250)
    ).is_equal_to("10.0.0.0/24")
    assert_that(
        evaluate_cidr(vpc_cidr="10.0.0.0/16", occupied_cidrs=["10.0.1.0/24", "10.0.2.0/24"], target_size=250)
    ).is_equal_to("10.0.0.0/24")
    assert_that(
        evaluate_cidr(vpc_cidr="10.0.0.0/16", occupied_cidrs=["10.0.3.0/24", "10.0.2.0/24"], target_size=250)
    ).is_equal_to("10.0.0.0/24")
    assert_that(
        evaluate_cidr(vpc_cidr="10.0.0.0/16", occupied_cidrs=["10.0.4.0/24", "10.0.2.0/24"], target_size=250)
    ).is_equal_to("10.0.0.0/24")
    assert_that(
        evaluate_cidr(vpc_cidr="10.0.0.0/16", occupied_cidrs=["10.0.4.0/24", "10.0.2.0/24"], target_size=120)
    ).is_equal_to("10.0.0.0/25")
    assert_that(
        evaluate_cidr(vpc_cidr="10.0.0.0/16", occupied_cidrs=["10.0.1.0/24", "10.0.0.0/24"], target_size=120)
    ).is_equal_to("10.0.2.0/25")


def test_get_subnet_cidr():
    assert_that(
        get_subnet_cidr(
            vpc_cidr="10.0.0.0/16",
            occupied_cidr=["10.0.0.0/18", "10.0.64.0/18", "10.0.128.0/18"],
            min_subnet_size=17000,
        )
    ).is_none()
    assert_that(
        get_subnet_cidr(
            vpc_cidr="10.0.0.0/16", occupied_cidr=["10.0.0.0/18", "10.0.64.0/18", "10.0.128.0/18"], min_subnet_size=100
        )
    ).is_equal_to("10.0.192.0/20")
    assert_that(
        get_subnet_cidr(
            vpc_cidr="10.0.0.0/16",
            occupied_cidr=["10.0.0.0/19", "10.0.32.0/20", "10.0.48.0/21", "10.0.64.0/18", "10.0.128.0/17"],
            min_subnet_size=100,
        )
    ).is_equal_to("10.0.56.0/21")
    assert_that(get_subnet_cidr("10.0.0.0/16", ["10.0.0.0/24"], 256)).is_equal_to("10.0.16.0/20")
