import unittest

import argparse

from pcluster import cfnconfig

config_file = "tests/pcluster/config_efs"
test_cluster_template = "unittest"
args = argparse.Namespace()
args.config_file = config_file
args.cluster_template = test_cluster_template


def create():
    """Empty function to simulate the create function in pcluster."""
    return


def update():
    """Empty function to simulate the update function in pcluster."""
    return


class TestEFSConfigParser(unittest.TestCase):
    """Unit testing module for parsing EFS related options."""

    def test_efs_create(self):
        """Unit tests for parsing EFS related options when pcluster create is called."""
        global args
        args.func = create
        config = cfnconfig.ParallelClusterConfig(args)
        efs_options = [opt.strip() for opt in config.parameters["EFSOptions"].split(",")]
        self.assertEqual(efs_options[0], "efs_shared", msg="Unexpected shared_dir")
        self.assertEqual(efs_options[1], "fs-12345", msg="Unexpected efs_fs_id")
        self.assertEqual(efs_options[2], "maxIO", msg="Unexpected performance_mode")
        self.assertEqual(efs_options[3], "key1", msg="Unexpected efs_kms_key_id")
        self.assertEqual(efs_options[4], "1020", msg="Unexpected provisioned_throughput")
        self.assertEqual(efs_options[5], "true", msg="Unexpected encrypted")
        self.assertEqual(efs_options[6], "provisioned", msg="Unexpected throughput_mode")
        self.assertEqual(
            len(efs_options),
            8,
            "Unexpected number of EFS parameters: %s "
            "\nExpected 8 parameters, 7 configurable parameters"
            "and 1 parameter reserved for passing mount point state to stack" % len(efs_options),
        )

    def test_efs_update(self):
        """Unit tests for parsing EFS related options when pcluster update is called."""
        global args
        args.func = update
        config = cfnconfig.ParallelClusterConfig(args)
        efs_options = [opt.strip() for opt in config.parameters["EFSOptions"].split(",")]
        self.assertEqual(efs_options[0], "efs_shared", msg="Unexpected shared_dir")
        self.assertEqual(efs_options[1], "fs-12345", msg="Unexpected efs_fs_id")
        self.assertEqual(efs_options[2], "maxIO", msg="Unexpected performance_mode")
        self.assertEqual(efs_options[3], "key1", msg="Unexpected efs_kms_key_id")
        self.assertEqual(efs_options[4], "1020", msg="Unexpected provisioned_throughput")
        self.assertEqual(efs_options[5], "true", msg="Unexpected encrypted")
        self.assertEqual(efs_options[6], "provisioned", msg="Unexpected throughput_mode")
        self.assertEqual(
            len(efs_options),
            8,
            "Unexpected number of EFS parameters: %s "
            "\nExpected 8 parameters, 7 configurable parameters"
            "and 1 parameter reserved for passing mount point state to stack" % len(efs_options),
        )


if __name__ == "__main__":
    unittest.main()
