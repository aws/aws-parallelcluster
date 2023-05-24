from abc import ABC, abstractmethod


class _LaunchTemplateBuilder(ABC):
    """Abstract class with methods with the common logic for launch template builders."""

    def get_block_device_mappings(self, root_volume, root_volume_device_name):
        """Return a list of block device mappings."""
        block_device_mappings = []
        for _, (device_name_index, virtual_name_index) in enumerate(zip(list(map(chr, range(97, 121))), range(0, 24))):
            device_name = "/dev/xvdb{0}".format(device_name_index)
            virtual_name = "ephemeral{0}".format(virtual_name_index)
            block_device_mappings.append(self._block_device_mapping_for_virt(device_name, virtual_name))

        block_device_mappings.append(self._block_device_mapping_for_ebs(root_volume_device_name, root_volume))
        return block_device_mappings

    def get_instance_market_options(self, queue, compute_resource):
        """Return the instance market options for spot instances."""
        instance_market_options = None
        if queue.is_spot():
            instance_market_options = self._instance_market_option(
                market_type="spot",
                spot_instance_type="one-time",
                instance_interruption_behavior="terminate",
                max_price=None if compute_resource.spot_price is None else str(compute_resource.spot_price),
            )
        return instance_market_options

    def get_capacity_reservation(self, queue, compute_resource):
        """Return the capacity reservation if a target is defined at the queue or compute resource level."""
        capacity_reservation = None
        cr_target = compute_resource.capacity_reservation_target or queue.capacity_reservation_target
        if cr_target:
            capacity_reservation = self._capacity_reservation(cr_target)
        return capacity_reservation

    @abstractmethod
    def _block_device_mapping_for_virt(self, device_name, virtual_name):
        pass

    @abstractmethod
    def _block_device_mapping_for_ebs(self, device_name, volume):
        pass

    @abstractmethod
    def _instance_market_option(self, market_type, spot_instance_type, instance_interruption_behavior, max_price):
        pass

    @abstractmethod
    def _capacity_reservation(self, cr_target):
        pass
