# Copyright (c) 2025, Karani Geoffrey and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from upeoxpense.utils.periods import period_bounds
import datetime as dt


class Budget(Document):
	def validate(self):
		if self.amount <= 0:
			frappe.throw('Budget amount must be > 0')


	def before_save(self):
		ref = dt.date.fromisoformat(self.start_date) if self.start_date else dt.date.today()
		s,e = period_bounds(self.period_type, ref)
		self.current_period_start, self.current_period_end = s, e