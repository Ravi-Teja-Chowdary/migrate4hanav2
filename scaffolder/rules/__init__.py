"""
Migrate4HANA scaffolder DQ rule library.

Each rule is a pure function with a uniform signature:

    def <rule_name>(row: dict, field: str, **kwargs) -> str

It returns an empty string on pass, or a human-readable error message on fail.
The generator emits ``rule_fn(row, field, **rule_args)`` calls in the spine's
``validate()`` hook. A non-empty return triggers a DEAD_LETTER_DQ result.

Adding a new rule = adding one file in this package. No spine regeneration is
needed: rules are imported at runtime, so a rule fix patches every spine that
references it at once. The corresponding unit test goes in tests/test_rules.py.
"""

from .non_empty import non_empty
from .positive_number import positive_number
from .non_negative_number import non_negative_number
from .iso_date import iso_date
from .sap_unit_of_measure import sap_unit_of_measure
from .currency_iso_4217 import currency_iso_4217
from .material_number_format import material_number_format
from .bukrs_company_code import bukrs_company_code
from .werks_plant import werks_plant
from .langu_code import langu_code
from .sap_client_3char import sap_client_3char
from .decimal_max_digits import decimal_max_digits
from .regex_match import regex_match
from .in_set import in_set
from .fk_required_when import fk_required_when


# Authoritative registry — keep alphabetical for deterministic codegen.
RULES = {
    "bukrs_company_code":     bukrs_company_code,
    "currency_iso_4217":      currency_iso_4217,
    "decimal_max_digits":     decimal_max_digits,
    "fk_required_when":       fk_required_when,
    "in_set":                 in_set,
    "iso_date":               iso_date,
    "langu_code":             langu_code,
    "material_number_format": material_number_format,
    "non_empty":              non_empty,
    "non_negative_number":    non_negative_number,
    "positive_number":        positive_number,
    "regex_match":            regex_match,
    "sap_client_3char":       sap_client_3char,
    "sap_unit_of_measure":    sap_unit_of_measure,
    "werks_plant":            werks_plant,
}
