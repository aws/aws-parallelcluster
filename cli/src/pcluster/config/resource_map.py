# Copyright 2019 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.


class ResourceMap(object):
    """
    Generic data structure that remembers the internal position of each element during the updates.

    Items can be added or removed to/from a ResourceMap without changing the position of the other items; in other words
    each element can be modified without affecting others.
    """

    class ResourceArray(object):
        """
        Represents a set of available resources for a single resource type.

        For instance, this class can represent the available EBS volume resources that can be attached to a head node.
        """

        def __init__(self, resources):
            """
            Create a Resource Array with the provided resources.

            :param resources: The initial resources to store
            """
            self.__resources = resources

        def store(self, values):
            """
            Store a new array of values into the resources array corresponding to the provided key.

            The values are assigned to the available resources according to the following rules:

                - resources containing values not present in the input array are released (i.e. set to None)
                - resources containing values present in the input array stay untouched (i.e. keep their value)
                - values in the input array not present in resources are added to the resources array based on their
                  order, taking the first empty slot for each value

            Accordingly with these rules, if no values (or an empty array) are provided, all resources will be released.
            If instead more values are provided than available resources, an Exception about insufficient resources
            capacity will be thrown.

            :param values: The new resources values
            """
            # First purge removed values from internal resources
            self.__resources = [value if value in values else None for value in self.__resources]

            # Then add only new values
            for value in list(filter(lambda l: l not in self.__resources, values)):
                # Assign first free slot to the label
                for i in range(len(self.__resources)):
                    if not self.__resources[i]:
                        self.__resources[i] = value
                        break
                else:
                    raise Exception("No more resources available for value {0}".format(value))

        def resources(self):
            """Return the resources values in this array."""
            return self.__resources

    def __init__(self, initial_data=None):
        """
        Create a ResourceMap.

        A ResourceMap can be constructed from scratch (like in the case of a new configuration file) or starting from a
        dictionary representing the resources structure, like the one that can be obtained by calling the resources()
        method.

        :param initial_data: A dict containing the initial data for the structure, or None if a new empty ResourceMap is
        being created
        """
        self.__resource_arrays = {}
        if initial_data:
            for key, resources in initial_data.items():
                self.__resource_arrays[key] = ResourceMap.ResourceArray(resources)

    def resources(self, key=None):
        """
        Return the resources array corresponding to the provided key.

        If no key is provided, it returns a dict containing all the Resource arrays. The purpose of this method is to
        return a serializable structure that can be stored somewhere (ex. in a CloudFormation template) and deserialized
        back into a ResourceMap by passing it to ResourceMap's constructor.

        :param key: The key of the resources array to be returned, or None if the all structure is needed.
        :return: The requested resources array or a dict with all the resources arrays
        """
        if not key:
            resources_map = {}
            for key, resource_array in self.__resource_arrays.items():
                resources_map[key] = resource_array.resources()
            return resources_map
        else:
            resource_array = self.__resource_arrays.get(key)
            return resource_array.resources() if resource_array else None

    def store(self, key, values):
        """
        Store the provided values in the resources array corresponding to the specified key.

        Values will be stored in the resources array according to the rules specified in ResourceArray.store() method.

        :param key: The key of the resources array
        :param values: The values to store.
        """
        self.__resource_arrays.get(key).store(values)

    def alloc(self, key, num_resources):
        """
        Allocate a resources array with a specified number of empty resources for the provided key.

        Using a new ResourceMap sections resources must be allocated with this method before being used to store values.
        This is to ensure that the right number of resources will be always created, since the store() method accepts
        any number of values from 0 to num_resources.

        :param key: The key to assign to the new resources array
        :param num_resources: The number of resources to create
        """
        self.__resource_arrays[key] = ResourceMap.ResourceArray([None] * num_resources)
