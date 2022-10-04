"""
BSD 3-Clause License

Copyright (c) 2021, Netskope OSS
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its
   contributors may be used to endorse or promote products derived from
   this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""

"""ArcSight Plugin."""


import collections
import socket
import time
import datetime
import datetime as dt

from .arcsight_constants import (
    SEVERITY_MAP,
    AUDIT_SEVERITY_MAP,
    SEVERITY_UNKNOWN,
)

from .arcsight_exceptions import (
    CEFTypeError,
)

from netskope.integrations.cls.utils.sanitizer import *
from netskope.integrations.cls.utils.converter import *


class CEFGenerator(object):
    """CEF Generator class."""

    def __init__(self, mapping, delimiter, cef_version, logger):
        """Init method."""
        self.logger = logger
        self.cef_version = cef_version  # Version of CEF being used
        self.mapping = mapping  # Mapping file content
        self.extension = collections.namedtuple(
            "Extension", ("key_name", "sanitizer")
        )
        self.extension_converter = collections.namedtuple(
            "Extension", ("key_name", "converter")
        )
        self._prefix_field_str_sanitizer = str_sanitizer(
            "[^\r\n]*", escape_chars=delimiter
        )
        self._prefix_field_float_sanitizer = float_sanitizer()
        self._equals_escaper = escaper("=")
        self._severity_sanitizer = str_sanitizer(
            "Unknown|Low|Medium|High|Info|Very-High"
        )
        self.valid_extensions = self._valid_extensions()
        self.extension_converters = self._type_converter()
        self.delimiter = delimiter

    def _type_converter(self):
        """To Parse the CEF transformation mapping and creates the dict for data type converters.

        Returns:
            Dict object having details of all the available CEF fields and its type converters
        """
        converters = type_converter()
        converters["Epoch"] = self.epoch_convertor()
        converters["DateTime"] = self.datetime_converter()

        # Parse the transformation mapping and create key-converter dict
        try:
            field_converters = {}
            mapping = self.mapping["taxonomy"]

            for data_type, data_mapping in mapping.items():
                if data_type == "json":	
                    continue
                for subtype, subtype_mapping in data_mapping.items():
                    for key, value in subtype_mapping.items():
                        for field, field_mapping in value.items():
                            field_converters[field] = self.extension_converter(
                                key_name=field,
                                converter=converters[
                                    field_mapping.get(
                                        "transformation", "String"
                                    )
                                ],
                            )
            return field_converters
        except Exception as err:
            self.logger.error(
                "Error occurred while parsing CEF transformation field. Error: {}".format(
                    str(err)
                )
            )
            raise

    def _valid_extensions(self):
        """To Parse the given transformation mapping and creates the dict for each provided values with its sanitizers.

        Returns:
            Dict object having details of all the available CEF fields and its sanitizers
        """
        sanitizers = get_sanitizers()
        sanitizers["Epoch"] = self.epoch_sanitizer()
        sanitizers["DateTime"] = self.datetime_sanitizer()

        # Parse the transformation mapping and create key-sanitizer dict
        try:
            field_sanitizers = {}
            mapping = self.mapping["taxonomy"]

            for data_type, data_mapping in mapping.items():
                if data_type == "json":	
                    continue
                for subtype, subtype_mapping in data_mapping.items():
                    for key, value in subtype_mapping.items():
                        for field, field_mapping in value.items():
                            field_sanitizers[field] = self.extension(
                                key_name=field,
                                sanitizer=sanitizers[
                                    field_mapping.get(
                                        "transformation", "String"
                                    )
                                ],
                            )
            return field_sanitizers
        except Exception as err:
            self.logger.error(
                "Error occurred while parsing CEF transformation field. Error: {}".format(
                    str(err)
                )
            )
            raise

    def epoch_sanitizer(self):
        """Wrap function for ensuring the given value is epoch.

        Raises:
            CEFTypeError in case of value other than epoch

        Returns:
            Function to sanitize the given epoch value
        """

        def sanitize(n, debug_name):
            if not isinstance(n, str):
                raise CEFTypeError(
                    "{}: Expected Epoch Time as String, got {}".format(
                        debug_name, type(n)
                    )
                )
            else:
                return n

        return sanitize

    def datetime_sanitizer(self):
        """Wrap function for ensuring the given value is a valid date time instance.

        Raises:
            CEFTypeError in case of value other than datetime

        Returns:
            Function to sanitize the given datetime value
        """

        def sanitize(t, debug_name):
            if not isinstance(t, dt.datetime):
                raise CEFTypeError(
                    "{}: Expected datetime, got {}".format(debug_name, type(t))
                )
            else:
                return t.strftime("%b %d %Y %H:%M:%S")

        return sanitize

    def datetime_converter(self):
        """Wrap function for converting given value to datetime object.

        Raises:
            CEFTypeError in case when value is not datetime compatible

        Returns:
            Function to convert type of given value to datetime
        """

        def convert(val, debug_name):
            try:
                return datetime.datetime.fromtimestamp(val)
            except Exception as err:
                raise CEFTypeError(
                    "{}: Error occurred while converting to datetime: {}".format(
                        debug_name, err
                    )
                )

        return convert

    def epoch_convertor(self):
        """Wrap function for converting given value to millisecond precise epoch time.

        Raises:
            CEFTypeError in case when value is not epoch compatible

        Returns:
            Function to convert type of given value to millisecond precise epoch time
        """

        def convert(val, debug_name):
            try:
                val = str(val)
                if len(val) < 13:
                    val = val + "0" * (13 - len(val))
                return val
            except Exception:
                raise CEFTypeError(
                    "{}: Error occurred while converting to millisecond precise epoch time".format(
                        debug_name
                    )
                )

        return convert

    def get_header_value(self, header, headers):
        """To Fetch sanitized value of header from given configured headers dict.

        Args:
            header: The header for which sanitized value is to be fetched
            headers: Configured headers

        Returns:
            Sanitized value
        """
        if header == "Severity":
            return self._severity_sanitizer(headers[header], header)
        return self._prefix_field_str_sanitizer(headers[header], header)

    def log_invalid_header(
        self, possible_headers, headers, data_type, subtype
    ):
        """Issues log in case of invalid header found in mappings.

        Args:
            possible_headers: Possible CEF headers
            headers: Configured headers
            data_type: Data type for which CEF event is being generated
            subtype: Subtype of data type for which CEF event is being generated
        """
        for configured_header in list(headers.keys()):
            if configured_header not in possible_headers:
                self.logger.error(
                    '[{}][{}]: Found invalid header configured in arcsight mapping file: "{}". Header '
                    "field will be ignored.".format(
                        data_type, subtype, configured_header
                    )
                )

    def webtx_timestamp(self, raw_data):
        date = raw_data.get("date", None)
        time = raw_data.get("time", None)
        if date and time:
            return str(
                int(
                    datetime.datetime.strptime(
                        f"{date} {time}", "%Y-%m-%d %H:%M:%S"
                    ).timestamp()
                    * 1000
                )
            )
        return None

    def get_cef_event(
        self,
        raw_data,
        headers,
        extensions,
        data_type,
        subtype,
        log_source_identifier,
    ):
        """To Produce a CEF compliant message from the arguments.

        Args:
            data_type: type of data being transformed (alert/event)
            subtype: subtype of data being transformed
            headers: Headers of CEF event
            extensions (dict): key-value pairs for event metadata.
            log_source_identifier: prefix for the logs sent
        """
        extension_strs = {}
        for name, value in extensions.items():

            # First convert the incoming value from Netskope to appropriate data type
            try:
                value = self.extension_converters[name].converter(value, name)
            except KeyError:
                self.logger.error(
                    '[{}][{}]: An error occurred while generating CEF data for field: "{}". Could not '
                    'find the field in the "valid_extensions". Field will be ignored'.format(
                        data_type, subtype, name
                    )
                )
                continue
            except Exception as err:
                self.logger.error(
                    '[{}][{}]: An error occurred while generating CEF data for field: "{}". Error: {}. '
                    "Field will be ignored".format(
                        data_type, subtype, name, str(err)
                    )
                )
                continue

            # Validate and sanitise (if required) the incoming value from Netskope before mapping it CEF
            try:
                sanitized_value = self.valid_extensions[name].sanitizer(
                    value, name
                )
                if isinstance(sanitized_value, str):
                    sanitized_value = self._equals_escaper(sanitized_value)

                extension_strs[
                    self.valid_extensions[name].key_name
                ] = sanitized_value
            except KeyError:
                self.logger.error(
                    '[{}][{}]: An error occurred while generating CEF data for field: "{}". Could not '
                    'find the field in the "valid_extensions". Field will be ignored'.format(
                        data_type, subtype, name
                    )
                )
            except Exception as err:
                self.logger.error(
                    '[{}][{}]: An error occurred while generating CEF data for field: "{}". Error: {}. '
                    "Field will be ignored".format(
                        data_type, subtype, name, str(err)
                    )
                )

        possible_headers = [
            "Device Vendor",
            "Device Product",
            "Device Version",
            "Device Event Class ID",
            "Name",
            "Severity",
        ]

        self.log_invalid_header(possible_headers, headers, data_type, subtype)

        hostname = log_source_identifier

        # Append the CEF version
        cef_components = [
            "{} {} CEF:{}".format(
                time.strftime("%b %d %H:%M:%S", time.localtime(time.time())),
                hostname,
                self.cef_version,
            )
        ]

        # Append other headers if available
        for header in possible_headers:
            if header in headers:
                try:
                    if header == "Severity":
                        if subtype in ["audit"]:
                            headers[header] = AUDIT_SEVERITY_MAP.get(
                                str(headers[header]).lower(), SEVERITY_UNKNOWN
                            )
                        else:
                            headers[header] = SEVERITY_MAP.get(
                                str(headers[header]).lower(), SEVERITY_UNKNOWN
                            )
                    cef_components.append(
                        self.get_header_value(header, headers)
                    )
                except Exception as err:
                    self.logger.error(
                        '[{}][{}]: An error occurred while generating CEF data for header field: "{}". Error: {}. '
                        "Field will be ignored".format(
                            data_type, subtype, header, str(err)
                        )
                    )

        if data_type == "webtx":
            date = self.webtx_timestamp(raw_data)
            if date:
                extension_strs["rt"] = date

        extensions_str = " ".join(
            sorted("{}={}".format(k, v) for k, v in extension_strs.items())
        )

        # Append extension string
        cef_components.append(extensions_str)

        # Join every CEF component with given delimiter
        return self.delimiter.join(cef_components)
