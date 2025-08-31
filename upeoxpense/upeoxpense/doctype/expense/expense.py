# Copyright (c) 2025, Karani Geoffrey and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class Expense(Document):
	def validate(self):
		if self.amount <= 0:
			frappe.throw('Amount must be > 0')