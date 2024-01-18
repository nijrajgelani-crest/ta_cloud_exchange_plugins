"""Cloudtrail Plugin Helper."""


from jsonschema import validate
from .cloudtrail_exceptions import (
    MappingValidationError,
)
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError


def validate_extension(instance):
    """Define JSON schema for validating mapped cloudtrail extension fields.

    Args:
        instance: JSON instance to be validated
    """
    schema = {"type": "object", "minProperties": 0}

    validate(instance=instance, schema=schema)


def validate_header_extension_subdict(instance):
    """Validate sub dict of extension having fields "mapping" and "default".

    Args:
        instance: JSON instance to be validated
    """
    # If both are empty
    if (
        "mapping_field" in instance
        and "default_value" in instance
        and (
            not instance["mapping_field"] and not instance["default_value"]
        )
    ):
        raise JsonSchemaValidationError(
            'Both "mapping" and "default" can not be empty'
        )

    # If only one is there and it is empty, that's not valid
    if (
        "mapping_field" in instance
        and "default_value" not in instance
        and (not instance["mapping_field"])
    ):
        raise JsonSchemaValidationError(
            '"mapping" field can not be empty as no "default" is provided'
        )

    # If only one is there and it is empty, that's not valid
    if (
        "default_value" in instance
        and "mapping_field" not in instance
        and (not instance["default_value"])
    ):
        raise JsonSchemaValidationError(
            '"default" field can not be empty as no "mapping" is provided'
        )


def validate_header(instance):
    """Define JSON schema for validating mapped cloudtrail header fields.

    Args:
        instance: JSON instance to be validated
    """
    properties_schema = {
        "default_value": {"type": "string"},
        "mapping_field": {"type": "string"},
        "transformation": {"type": "string"},
    }

    one_of_sub_schema = [
        # both empty are not allowed. So schema will be: one of (one of (both), both)
        {
            "oneOf": [
                {"required": ["mapping_field"]},
                {"required": ["default_value"]},
            ]
        },
        {
            "allOf": [
                {"required": ["mapping_field"]},
                {"required": ["default_value"]},
            ]
        },
    ]

    header_sub_schema = {
        "type": "object",
        "properties": properties_schema,
        "minProperties": 0,
        "maxProperties": 3,
        "oneOf": one_of_sub_schema,
    }

    schema = {
        "type": "object",
        "properties": {
            "Device Product": header_sub_schema,
            "Device Vendor": header_sub_schema,
            "Device Version": header_sub_schema,
            "Device Event Class ID": header_sub_schema,
            "Name": header_sub_schema,
            "Severity": header_sub_schema,
        },
    }

    validate(instance=instance, schema=schema)

    # After validating schema, validate the "mapping" and "default" fields for each header fields
    for field in instance:
        validate_header_extension_subdict(instance[field])


def validate_extension_field(instance):
    """Define JSON schema for validating each extension fields.

    Args:
        instance: JSON instance to be validated
    """
    schema = {
        "type": "object",
        "properties": {
            "mapping_field": {"type": "string"},
            "default_value": {"type": "string"},
            "transformation": {"type": "string"},
            "is_json_path": {"type": "boolean"},
        },
        "minProperties": 0,
        "maxProperties": 4,
        "oneOf": [  # both empty are not allowed. So schema will be: one of (one of (both), both)
            {
                "oneOf": [
                    {"required": ["mapping_field"]},
                    {"required": ["default_value"]},
                ]
            },
            {
                "allOf": [
                    {"required": ["mapping_field"]},
                    {"required": ["default_value"]},
                ]
            },
        ],
    }

    validate(instance=instance, schema=schema)
    validate_header_extension_subdict(instance)


def get_cloudtrail_mappings(mappings, data_type):
    """Read mapping json and return the dict of mappings to be applied to raw_data.

    Args:
        data_type (str): Data type (alert/event) for which the
        mappings are to be fetched
        mappings: Attribute mapping json string

    Returns:
        mapping delimiter, cef_version, elastic_mappings
    """
    data_type_specific_mapping = mappings["taxonomy"][data_type]

    # Validate the extension for each mapped subtype
    for subtype, subtype_map in data_type_specific_mapping.items():
        subtype_extension = subtype_map["extension"]
        try:
            validate_extension(subtype_extension)
        except JsonSchemaValidationError as err:
            raise MappingValidationError(
                'Error occurred while validating extension for type "{}". '
                "Error: {}".format(subtype, err)
            )

        # Validate each extension
        for cef_field, ext_dict in subtype_extension.items():
            try:
                validate_extension_field(ext_dict)
            except JsonSchemaValidationError as err:
                raise MappingValidationError(
                    'Error occurred while validating cloudtrail extension '
                    'field "{}" for type "{}". '
                    'Error: {}'.format(
                        cef_field, subtype, err
                    )
                )

    return mappings["taxonomy"]


def extract_subtypes(mappings, data_type):
    """Extract subtypes of given data types.

    Args:
        data_type (str): Data type (alert/event) for which the
        mappings are to be fetched
        mappings: Attribute mapping json string

    Returns:
        extracted sub types
    """
    taxonomy = mappings["taxonomy"][data_type]
    return [subtype for subtype in taxonomy]
