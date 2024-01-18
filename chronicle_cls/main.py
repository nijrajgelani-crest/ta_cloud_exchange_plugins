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

"""Chronicle plugin."""


import time
import datetime
import requests
import json
import re
import urllib
from typing import List
from jsonpath import jsonpath

from google.oauth2 import service_account
from google.auth.transport import requests as gRequest
from netskope.common.utils import AlertsHelper, add_user_agent
from netskope.integrations.cls.plugin_base import (
    PluginBase,
    ValidationResult,
    PushResult,
)
from .utils.chronicle_client import (
    ChronicleClient,
)
from .utils.chronicle_helper import (
    get_chronicle_mappings,
)
from .utils.chronicle_udm_generator import (  # NOQA: E501
    UDMGenerator,
)
from .utils.chronicle_exceptions import (
    MappingValidationError,
    EmptyExtensionError,
    FieldNotFoundError,
)
from .utils.chronicle_validator import (
    ChronicleValidator,
)
from .utils.chronicle_constants import (
    SCOPES, DUMMY_DATA, DEFAULT_URL
)


class ChroniclePlugin(PluginBase):
    """The Chronicle plugin implementation class."""

    def validate(self, configuration: dict) -> ValidationResult:
        """Validate the configuration parameters dict."""
        chronicle_validator = ChronicleValidator(self.logger)

        if (
            "service_account_key" not in configuration
            or type(configuration["service_account_key"]) != str
            or not configuration["service_account_key"].strip()
        ):
            self.logger.error(
                "Chronicle Plugin: Validation error occurred. Error: "
                "Invalid Service Account Key found in the configuration parameters."
            )
            return ValidationResult(
                success=False, message="Invalid Service Account Key provided."
            )

        # validating api key
        if (
            "customer_id" not in configuration
            or not configuration["customer_id"].strip()
            or type(configuration["customer_id"]) != str
        ):
            self.logger.error(
                "Plugin Chronicle: Validation error occurred. Error: \
                Invalid Customer ID found in the configuration parameters."
            )
            return ValidationResult(
                success=False, message="Invalid Customer ID provided."
            )

        if (
            "region" not in configuration
            or not configuration["region"].strip()
            or type(configuration["region"]) != str
            or configuration["region"].strip() not in ["usa", "europe", "asia", "custom"]
        ):
            self.logger.error(
                "Plugin Chronicle: Validation error occurred. Error: \
                Invalid Region found in the configuration parameters."
            )
            return ValidationResult(
                success=False, message="Invalid Region provided."
            )

        try:
            self._validate_auth(configuration)
        except Exception as ex:
            self.logger.error(
                re.sub(
                    r"key=(.*?) ",
                    "key=******** ",
                    f"Chronicle Plugin: Validation error occurred. "
                    f"Could not validate authentication credentials. Error: {repr(ex)}.",
                )
            )
            return ValidationResult(
                success=False,
                message="Error while connecting to Chronicle. "
                "Please check Service Account Key.",
            )

        # validating mapping file
        mappings = self.mappings.get("jsonData", None)
        try:
            mappings = json.loads(mappings)
        except json.decoder.JSONDecodeError as err:
            self.logger.error(
                f"Chronicle Plugin: error occurred decoding of json file: {err}"
            )
            return ValidationResult(
                success=False,
                message=f"Invalid Chronicle attribute mapping provided. {err}",
            )
        if type(
            mappings
        ) != dict or not chronicle_validator.validate_chronicle_map(mappings):
            self.logger.error(
                "Chronicle Plugin: Validation error occurred. Error: "
                "Invalid Chronicle attribute mapping found in the configuration parameters."
            )
            return ValidationResult(
                success=False,
                message="Invalid Chronicle attribute mapping provided.",
            )
            
        try:   
            if (not self._check_dummy_post(configuration)
            and configuration.get("region","") != "custom"):
                self.logger.error(
                    "Chronicle Plugin: Validation error occurred. Error: "
                    "Invalid credentials"
                )
                return ValidationResult(
                    success=False,
                    message="Invalid credentials or region.",
                )           
        except requests.ConnectionError as ex:
            self.logger.error(
                f"Chronicle Plugin: Connection Error. Check custom URL. "
                f"Exception: {repr(ex)}.",
            )
            return ValidationResult(
                success=False,
                message="Connection Error, "
                "please check custom URL and logs",
            )
        except Exception as ex:
            self.logger.error(
                f"Chronicle Plugin: Exception occurred. "
                f"Exception: {repr(ex)}.",
            )
            return ValidationResult(
                success=False,
                message="Error occurred with Chronicle server. "
                "Please check logs",
            )
            
        try: 
            
            flag, url_path_value = self.udm_events_url_check(configuration)
            toast_message = f"Please enter the URL without {url_path_value} ."
            if(not flag):
                self.logger.error(
                    "Chronicle Plugin: Validation error occurred. Error: "
                    f"URL path has {url_path_value} in it."
                )
                return ValidationResult(
                    success=False,
                    message=toast_message,
                )
              
            if (configuration.get("region","") == "custom"
            and (not self._check_dummy_post(configuration)
            or configuration.get("custom_region","") == "")):
                self.logger.error(
                    "Chronicle Plugin: Validation error occurred. Error: "
                    "Invalid Chronicle custom URL"
                )
                return ValidationResult(
                    success=False,
                    message="Invalid Chronicle custom URL.",
                )
        except requests.ConnectionError as ex:
            self.logger.error(
                f"Chronicle Plugin: Connection Error. "
                f"Exception: {repr(ex)}.",
            )
            return ValidationResult(
                success=False,
                message="Connection Error, "
                "please check custom region URL and logs",
            )
            
        except Exception as ex:
            self.logger.error(
                f"Chronicle Plugin: Exception occurred. "
                f"Exception: {repr(ex)}.",
            )
            return ValidationResult(
                success=False,
                message="Error occurred with Chronicle server. "
                "Please check logs",
            )
       
        return ValidationResult(success=True, message="Validation successful.")

    def udm_events_url_check(self, configuration):
        BASE_URL = configuration.get("custom_region", "").strip()               
        parsed = urllib.parse.urlparse(BASE_URL.strip())
        if not (parsed.scheme in ["http", "https"]
            and parsed.netloc != ""):
            return True, ""
        if (parsed.path.strip() == "/" or parsed.path == ""):
            return True, parsed.path.strip()
        else:
            return False, parsed.path.strip()
    
    def _validate_auth(self, configuration: dict) -> ValidationResult:
        """Validate API key by making REST API call."""
        try:
            credentials = (
                service_account.Credentials.from_service_account_info(
                    json.loads(configuration["service_account_key"]),
                    scopes=SCOPES,
                )
            )
        except Exception as ex:
            raise
        
    def _check_dummy_post(self, configuration: dict): 

        try:
            credentials = (
                service_account.Credentials.from_service_account_info(
                    json.loads(configuration["service_account_key"]),
                    scopes=SCOPES,
                )
            )
            self.http_session = gRequest.AuthorizedSession(credentials)
            
            if configuration.get("region", "") == "custom":
                BASE_URL = configuration.get("custom_region", "").strip()               
            else:   
                BASE_URL = DEFAULT_URL[configuration.get("region", "usa")]
                
            if (not self._url_valid(BASE_URL)
            and configuration.get("region","") == "custom"):
                return False
            
            url = f"{BASE_URL}/v2/udmevents:batchCreate"      
            payload = {
                "customer_id": configuration["customer_id"].strip(),
                "events": DUMMY_DATA,
            }
            response = self.http_session.request(
                "POST",
                url,
                json=payload,
            )
            
            if response.status_code == 200:
                return True
            else:
                return False
            
        except Exception:
            raise
        
    def _url_valid(self, base_url):
        parsed = urllib.parse.urlparse(base_url.strip())
        if (parsed.scheme in ["http", "https"]
            and parsed.netloc != ""):
            return True
        else:
            return False

    def push(self, transformed_data, data_type, subtype) -> PushResult:
        """Push the transformed_data to the 3rd party platform.

        Args:
            transformed_data (list): The transformed data to be ingested.
            data_type (str): The type of data to be ingested (alert/event)
            subtype (str): The subtype of data to be ingested \
            (DLP, anomaly etc. in case of alerts)

        Returns:
            PushResult: Result indicating ingesting outcome and message
        """
        try:
            chronicle_client = ChronicleClient(self.configuration, self.logger)
            chronicle_client.ingest(transformed_data)
        except Exception as e:
            self.logger.error(
                f"Error occurred while ingesting data to Chronicle Plugin."
                f" Error: {e}"
            )
            raise

    def get_mapping_value_from_json_path(self, data, json_path):
        """To Fetch the value from given JSON object using given JSON path.

        Args:
            data: JSON object from which the value is to be fetched
            json_path: JSON path indicating the path of the value in given JSON

        Returns:
            fetched value.
        """
        return jsonpath(data, json_path)

    def get_mapping_value_from_field(self, data, field):
        """To Fetch the value from given field.

        Args:
            data: JSON object from which the value is to be fetched
            field: Field whose value is to be fetched

        Returns:
            fetched value.
        """
        return (
            data[field]
            if data[field] or isinstance(data[field], int)
            else "null"
        )

    def get_subtype_mapping(self, mappings, subtype):
        """To Retrieve subtype mappings case insensitively.

        Args:
            mappings: Mapping JSON from which subtypes are to be retrieved
            subtype: Subtype (e.g. DLP for alerts) for which the mapping is
            to be fetched

        Returns:
            Fetched mapping JSON object
        """
        mappings = {k.lower(): v for k, v in mappings.items()}
        if subtype.lower() in mappings:
            return mappings[subtype.lower()]
        else:
            return mappings[subtype.upper()]

    def get_headers(self, header_mappings, data, data_type, subtype):
        """To Create a dictionary of UDM headers from given header mappings.

        Args:
            subtype: Subtype for which the headers are being transformed
            data_type: Data type for which the headers are being transformed
            header_mappings: UDM header mapping with Netskope fields
            data: The alert/event for which the UDM header is being generated

        Returns:
            header dict
        """
        headers = {}
        helper = AlertsHelper()
        tenant = helper.get_tenant_cls(self.source)
        mapping_variables = {"$tenant_name": tenant.name}

        try:
            headers[
                "metadata.event_timestamp"
            ] = datetime.datetime.utcfromtimestamp(
                data.get("timestamp", time.time())
            ).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
        except Exception:
            raise

        missing_fields = []
        # Iterate over mapped headers
        for udm_header, header_mapping in header_mappings.items():
            try:
                headers[udm_header] = self.get_field_value_from_data(
                    header_mapping, data, data_type, subtype, False
                )

                # Handle variable mappings
                if (
                    isinstance(headers[udm_header], str)
                    and headers[udm_header].lower() in mapping_variables
                ):
                    headers[udm_header] = mapping_variables[
                        headers[udm_header].lower()
                    ]
            except FieldNotFoundError as err:
                missing_fields.append(str(err))

        return headers

    def get_extensions(self, extension_mappings, data, data_type, subtype):
        """Fetch extensions from given mappings.

        Args:
            subtype: Subtype for which the headers are being transformed
            data_type: Data type for which the headers are being transformed
            extension_mappings: Mapping of extensions
            data: The data to be transformed

        Returns:
            extensions (dict)
        """
        extension = {}
        missing_fields = []

        # Iterate over mapped extensions
        for udm_extension, extension_mapping in extension_mappings.items():
            try:
                extension[udm_extension] = self.get_field_value_from_data(
                    extension_mapping,
                    data,
                    data_type,
                    subtype,
                    is_json_path="is_json_path" in extension_mapping,
                )
            except FieldNotFoundError as err:
                missing_fields.append(str(err))

        return extension

    def get_field_value_from_data(
        self, extension_mapping, data, data_type, subtype, is_json_path=False
    ):
        """To Fetch the value of extension based on "mapping" and "default".

        Args:
            extension_mapping: Dict containing "mapping" and "default" fields
            data: Data instance retrieved from Netskope
            subtype: Subtype for which the extension are being transformed
            data_type: Data type for which the headers are being transformed
            is_json_path: Whether the mapped value is JSON path or direct
            field name

        Returns:
            Fetched values of extension

        ---------------------------------------------------------------------
             Mapping          |    Response    |    Retrieved Value
        ----------------------|                |
        default  |  Mapping   |                |
        ---------------------------------------------------------------------
           P     |     P      |        P       |           Mapped
           P     |     P      |        NP      |           Default
           P     |     NP     |        P       |           Default
           NP    |     P      |        P       |           Mapped
           P     |     NP     |        NP      |           Default
           NP    |     P      |        NP      |           -
           NP    |     NP     |        P       |           - (Not possible)
           NP    |     NP     |        NP      |           - (Not possible)
        -----------------------------------------------------------------------
        """
        if (
            "mapping_field" in extension_mapping
            and extension_mapping["mapping_field"]
        ):
            if is_json_path:
                # If mapping field specified by JSON path is present in data,
                #  map that field, else skip by raising
                # exception:
                value = self.get_mapping_value_from_json_path(
                    data, extension_mapping["mapping_field"]
                )
                if value:
                    return ",".join([str(val) for val in value])
                else:
                    raise FieldNotFoundError(
                        extension_mapping["mapping_field"]
                    )
            else:
                # TODO: Add merging feild logic
                # If mapping is present in data, map that field,
                # else skip by raising exception
                field_list = extension_mapping["mapping_field"].split("-")
                if len(field_list) == 1:
                    if (
                        extension_mapping["mapping_field"] in data
                    ):  # case #1 and case #4
                        return self.get_mapping_value_from_field(
                            data, extension_mapping["mapping_field"]
                        )
                    elif "default_value" in extension_mapping:
                        # If mapped value is not found in response and default
                        #  is mapped, map the default value (case #2)
                        return extension_mapping["default_value"]
                    else:  # case #6
                        raise FieldNotFoundError(
                            extension_mapping["mapping_field"]
                        )
                out_list = []
                for field in field_list:
                    field = field.strip(" ")
                    field = field.strip("[]")
                    if field == "NULL":
                        out_list.append("NULL")
                    elif field in data:  # case #1 and case #4
                        out_list.append(
                            self.get_mapping_value_from_field(data, field)
                        )
                    elif "default_value" in extension_mapping:
                        # If mapped value is not found in response and default
                        # is mapped, map the default value (case #2)
                        return extension_mapping["default_value"]
                    else:  # case #6
                        raise FieldNotFoundError(
                            extension_mapping["mapping_field"]
                        )
                return " - ".join(out_list)
        else:
            # If mapping is not present, 'default_value' must be there
            # because of validation (case #3 and case #5)
            return extension_mapping["default_value"]

    def map_json_data(self, mappings, data, data_type, subtype):
        """Filter the raw data and returns the filtered data.

        :param mappings: List of fields to be pushed
        :param data: Data to be mapped (retrieved from Netskope)
        :param logger: Logger object for logging purpose
        :return: Mapped data based on fields given in mapping file
        """
        
        if mappings == []:
            return data

        mapped_dict = {}
        for key in mappings:
            if key in data:
                mapped_dict[key] = data[key]
        
        return mapped_dict

    def transform(self, raw_data, data_type, subtype) -> List:
        """Transform the raw data into target platform supported data formats.

        Args:
            raw_data (list): The raw data to be tranformed.
            data_type (str): The type of data to be ingested (alert/event)
            subtype (str): The subtype of data to be ingested
            (DLP, anomaly etc. in case of alerts)

        Raises:
            NotImplementedError: If the method is not implemented.

        Returns:
            List: list of transformed data.
        """
        if not self.configuration.get("transformData", True):
            if data_type not in ["alerts", "events"]:
                return raw_data

            try:
                udm_version, chronicle_mappings = get_chronicle_mappings(
                    self.mappings, "json"
                )
            except KeyError as err:
                self.logger.error(
                    "Error in chronicle mapping file. Error: {}".format(str(err))
                )
                raise
            except MappingValidationError as err:
                self.logger.error(str(err))
                raise
            except Exception as err:
                self.logger.error(
                    "An error occurred while mapping data using given json mappings. Error: {}".format(
                        str(err)
                    )
                )
                raise

            try:
                subtype_mapping = self.get_subtype_mapping(
                    chronicle_mappings["json"][data_type], subtype
                )
            except Exception:
                self.logger.error(
                    'Error occurred while retrieving mappings for datatype: "{}" (subtype "{}"). '
                    "Transformation will be skipped.".format(
                        data_type, subtype
                    )
                )
                raise

            transformed_data = []

            for data in raw_data:
                transformed_data.append(
                    self.map_json_data(subtype_mapping, data, data_type, subtype)
                )

            return transformed_data
                

        else:
            try:
                udm_version, chronicle_mappings = get_chronicle_mappings(
                    self.mappings, data_type
                )
            except KeyError as err:
                self.logger.error(
                    "Error in chronicle mapping file. Error: {}.".format(str(err))
                )
                raise
            except MappingValidationError as err:
                self.logger.error(str(err))
                raise
            except Exception as err:
                self.logger.error(
                    f"An error occurred while mapping data using given json "
                    f"mappings. Error: {str(err)}."
                )
                raise

            transformed_data = []
            udm_generator = UDMGenerator(
                self.mappings,
                udm_version,
                self.logger,
            )
            # First retrieve the mapping of subtype being transformed
            try:
                subtype_mapping = self.get_subtype_mapping(
                    chronicle_mappings[data_type], subtype
                )
            except Exception as err:
                self.logger.error(
                    f"Error occurred while retrieving mappings for subtype"
                    f" '{subtype}'. Transformation of current record will be"
                    f" skipped. Exception: {err}"
                )
                raise

            for data in raw_data:
                # Generating the UDM header
                try:
                    header = self.get_headers(
                        subtype_mapping["header"], data, data_type, subtype
                    )
                except Exception as err:
                    self.logger.error(
                        f"[{data_type}][{subtype}]: Error occurred while creating "
                        f"UDM header: {str(err)}. Transformation of "
                        f"current record will be skipped."
                    )
                    continue

                try:
                    extension = self.get_extensions(
                        subtype_mapping["extension"], data, data_type, subtype
                    )
                except Exception as err:
                    self.logger.error(
                        f"[{data_type}][{subtype}]: Error occurred while creating"
                        f" UDM extension: {str(err)}."
                        f" Transformation of the current record will be skipped."
                    )
                    continue

                try:
                    transformed_data.append(
                        udm_generator.get_udm_event(
                            data, header, extension, data_type, subtype
                        )
                    )
                    # pass
                except EmptyExtensionError:
                    self.logger.error(
                        "[{}][{}]: Got empty extension during transformation."
                        "Transformation of current record will be skipped.".format(
                            data_type, subtype
                        )
                    )
                except Exception as err:
                    self.logger.error(
                        "[{}][{}]: An error occurred during transformation."
                        " Error: {}.".format(data_type, subtype, str(err))
                    )
            return transformed_data
