# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError
import odoo.addons.decimal_precision as dp
from datetime import datetime

import logging
_logger = logging.getLogger(__name__)

class document_action(models.Model):
    _name = 'document.action'
    _description = "Store action done on each document(Purchase order and ERF)"
    name = fields.Char('Reference', required=True,
                       index=True, copy=False, default='New')
    model = fields.Char('model')
    action = fields.Char('Action')
    approver = fields.Char('Approver')
    document = fields.Char('Document')
    role = fields.Char('Role')
    date_approved = fields.Date('Action Date', readonly=1, index=True, copy=False)
