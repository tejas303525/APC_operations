# Copyright (c) 2026, APC and contributors

from frappe.tests.utils import FrappeTestCase

from apc_operations.inventory.qc_spec import has_spec_limit, optional_spec_float


class TestQcSpec(FrappeTestCase):
    def test_optional_spec_float_empty_is_none(self):
        for value in (None, ""):
            self.assertIsNone(optional_spec_float(value))

    def test_optional_spec_float_zero_is_valid(self):
        self.assertEqual(optional_spec_float(0), 0.0)

    def test_has_spec_limit(self):
        self.assertFalse(has_spec_limit(None))
        self.assertFalse(has_spec_limit(""))
        self.assertTrue(has_spec_limit(0))
        self.assertTrue(has_spec_limit(1.5))
