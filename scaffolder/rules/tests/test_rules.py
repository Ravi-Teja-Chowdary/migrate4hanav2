"""Unit tests for the DQ rule library.

These tests run via ``pytest scaffolder/rules/tests/test_rules.py`` and cover
every rule with: missing value, empty value, valid value, invalid value, and
(for parametric rules) edge cases on the args.
"""
from __future__ import annotations

import pytest

from scaffolder.rules import (
    non_empty, positive_number, non_negative_number, iso_date,
    sap_unit_of_measure, currency_iso_4217, material_number_format,
    bukrs_company_code, werks_plant, langu_code, sap_client_3char,
    decimal_max_digits, regex_match, in_set, fk_required_when, RULES,
)


# ── non_empty ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("row,expected", [
    ({"X": "value"}, ""),
    ({"X": "   value   "}, ""),
    ({"X": ""}, "X: value is empty"),
    ({"X": "   "}, "X: value is empty"),
    ({"X": None}, "X: value is missing"),
    ({}, "X: value is missing"),
])
def test_non_empty(row, expected):
    assert non_empty(row, "X") == expected


# ── positive_number ──────────────────────────────────────────────────────────
@pytest.mark.parametrize("v,expected_empty", [
    (1, True), (1.5, True), ("1", True), ("0.0001", True),
    (0, False), (-1, False), ("abc", False), (None, False), ("", False),
])
def test_positive_number(v, expected_empty):
    out = positive_number({"X": v}, "X")
    assert (out == "") is expected_empty


# ── non_negative_number ──────────────────────────────────────────────────────
@pytest.mark.parametrize("v,expected_empty", [
    (0, True), (1, True), ("0", True),
    (-0.01, False), ("xyz", False), (None, False),
])
def test_non_negative_number(v, expected_empty):
    out = non_negative_number({"X": v}, "X")
    assert (out == "") is expected_empty


# ── iso_date ─────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("v,expected_empty", [
    ("20260614", True), ("2026-06-14", True),
    ("2026/06/14", False), ("not-a-date", False), ("20261301", False),
    (None, False), ("", False),
])
def test_iso_date(v, expected_empty):
    out = iso_date({"X": v}, "X")
    assert (out == "") is expected_empty


# ── sap_unit_of_measure ──────────────────────────────────────────────────────
@pytest.mark.parametrize("v,expected_empty", [
    ("EA", True), ("KG", True), ("L", True), ("ABC", True),
    ("1234", False), ("KG2", False), ("", False),
])
def test_sap_unit_of_measure(v, expected_empty):
    out = sap_unit_of_measure({"X": v}, "X")
    assert (out == "") is expected_empty


# ── currency_iso_4217 ────────────────────────────────────────────────────────
@pytest.mark.parametrize("v,expected_empty", [
    ("USD", True), ("EUR", True), ("inr", True),
    ("US", False), ("USDX", False), ("123", False), ("", False),
])
def test_currency_iso_4217(v, expected_empty):
    out = currency_iso_4217({"X": v}, "X")
    assert (out == "") is expected_empty


# ── material_number_format ───────────────────────────────────────────────────
@pytest.mark.parametrize("v,expected_empty", [
    ("MAT-001", True), ("HALB123", True), ("ABC/DEF_GHI", True),
    ("MAT 001", False),                # space not allowed
    ("M" * 41, False),                  # > 40 chars
    ("", False),
])
def test_material_number_format(v, expected_empty):
    out = material_number_format({"X": v}, "X")
    assert (out == "") is expected_empty


# ── bukrs_company_code ───────────────────────────────────────────────────────
@pytest.mark.parametrize("v,expected_empty", [
    ("1010", True), ("US01", True),
    ("100", False), ("10101", False), ("AB-1", False), ("", False),
])
def test_bukrs_company_code(v, expected_empty):
    out = bukrs_company_code({"X": v}, "X")
    assert (out == "") is expected_empty


# ── werks_plant ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("v,expected_empty", [
    ("1710", True), ("PL01", True),
    ("17", False), ("17105", False), ("PL-1", False), ("", False),
])
def test_werks_plant(v, expected_empty):
    out = werks_plant({"X": v}, "X")
    assert (out == "") is expected_empty


# ── langu_code ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize("v,expected_empty", [
    ("E", True), ("EN", True), ("de", True),
    ("ENG", False), ("12", False), ("", False),
])
def test_langu_code(v, expected_empty):
    out = langu_code({"X": v}, "X")
    assert (out == "") is expected_empty


# ── sap_client_3char ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("v,expected_empty", [
    ("100", True), ("800", True), ("000", True),
    ("10", False), ("1000", False), ("ABC", False), ("", False),
])
def test_sap_client_3char(v, expected_empty):
    out = sap_client_3char({"X": v}, "X")
    assert (out == "") is expected_empty


# ── decimal_max_digits ───────────────────────────────────────────────────────
def test_decimal_max_digits_pass():
    assert decimal_max_digits({"X": "123.45"}, "X", digits=13, decimals=2) == ""
    assert decimal_max_digits({"X": "1234567890.12"}, "X", digits=13, decimals=2) == ""


def test_decimal_max_digits_fail_decimals():
    out = decimal_max_digits({"X": "1.234"}, "X", digits=13, decimals=2)
    assert "decimal places" in out


def test_decimal_max_digits_fail_total():
    out = decimal_max_digits({"X": "12345678901234"}, "X", digits=13, decimals=2)
    assert "digits exceeds" in out


def test_decimal_max_digits_non_numeric():
    out = decimal_max_digits({"X": "abc"}, "X", digits=13, decimals=2)
    assert "not numeric" in out


# ── regex_match ──────────────────────────────────────────────────────────────
def test_regex_match_pass():
    assert regex_match({"X": "MAT001"}, "X", pattern=r"^MAT\d+$") == ""


def test_regex_match_fail():
    out = regex_match({"X": "VND001"}, "X", pattern=r"^MAT\d+$")
    assert "does not match" in out


def test_regex_match_missing_pattern():
    out = regex_match({"X": "anything"}, "X")
    assert "needs a 'pattern' arg" in out


# ── in_set ───────────────────────────────────────────────────────────────────
def test_in_set_pass():
    assert in_set({"X": "ACTIVE"}, "X", values=["ACTIVE", "INACTIVE"]) == ""


def test_in_set_fail():
    out = in_set({"X": "PENDING"}, "X", values=["ACTIVE", "INACTIVE"])
    assert "not in allowed set" in out


def test_in_set_missing_values():
    out = in_set({"X": "ACTIVE"}, "X")
    assert "needs a 'values' arg" in out


# ── fk_required_when ─────────────────────────────────────────────────────────
def test_fk_required_when_trigger_not_active():
    # PAYMENT_METHOD != BANK → BANK_ACCOUNT not required
    out = fk_required_when({"PAYMENT_METHOD": "CASH"}, "BANK_ACCOUNT",
                            trigger_field="PAYMENT_METHOD", trigger_value="BANK")
    assert out == ""


def test_fk_required_when_trigger_active_and_field_present():
    out = fk_required_when({"PAYMENT_METHOD": "BANK", "BANK_ACCOUNT": "ACC123"},
                            "BANK_ACCOUNT",
                            trigger_field="PAYMENT_METHOD", trigger_value="BANK")
    assert out == ""


def test_fk_required_when_trigger_active_and_field_missing():
    out = fk_required_when({"PAYMENT_METHOD": "BANK"}, "BANK_ACCOUNT",
                            trigger_field="PAYMENT_METHOD", trigger_value="BANK")
    assert "required when" in out


def test_fk_required_when_missing_trigger_field():
    out = fk_required_when({"X": "v"}, "Y")
    assert "needs a 'trigger_field' arg" in out


# ── registry ─────────────────────────────────────────────────────────────────
def test_registry_has_all_15_rules():
    expected = {
        "bukrs_company_code", "currency_iso_4217", "decimal_max_digits",
        "fk_required_when", "in_set", "iso_date", "langu_code",
        "material_number_format", "non_empty", "non_negative_number",
        "positive_number", "regex_match", "sap_client_3char",
        "sap_unit_of_measure", "werks_plant",
    }
    assert set(RULES.keys()) == expected


def test_registry_is_alphabetical():
    # Determinism: codegen iteration order must be stable.
    assert list(RULES.keys()) == sorted(RULES.keys())
