import inspect

from assertpy import assert_that, soft_assertions
from marshmallow import Schema

import pcluster.schemas.cluster_schema
import pcluster.schemas.common_schema
import pcluster.schemas.imagebuilder_schema


def _validate_list_has_update_key(section):
    """Validate that the schema's lists have an update_key defined."""
    for _, field_obj in section.declared_fields.items():
        is_list = hasattr(field_obj, "many") and field_obj.many
        if is_list:
            update_key = field_obj.metadata.get("update_key", None)
            assert_that(update_key).is_not_none()


def _is_schema(module):
    """Get the Schema subclasses defined in the module.

    :param module: the module where the schemas are defined
    """

    def predicate(class_object):
        return (
            inspect.isclass(class_object)
            and class_object.__module__ == module.__name__
            and issubclass(class_object, Schema)
        )

    return predicate


def _validate_module_schemas(module):
    """Validate the schema subclasses defined in the module.

    This validator checks that if the schema has list field, it has an update_key defined. Note that since we check
    every schema in the module, we don't just need to check the lists at the top level (if there are nested fields,
    the check on the list will be done when the field's schema is validated.

    :param module: the module with the schemas to validate
    """
    for _, class_object in inspect.getmembers(module, _is_schema(module)):
        _validate_list_has_update_key(class_object())


def test_schemas():
    with soft_assertions():
        _validate_module_schemas(pcluster.schemas.cluster_schema)
        _validate_module_schemas(pcluster.schemas.imagebuilder_schema)
        _validate_module_schemas(pcluster.schemas.common_schema)
