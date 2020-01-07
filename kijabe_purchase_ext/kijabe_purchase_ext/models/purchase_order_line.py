# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError

import logging
_logger = logging.getLogger(__name__)

class purchase_order_line(models.Model):
    _inherit = 'purchase.order.line'

    x_details = fields.Char('Details',compute='conc_name_uom', store=True)
    
    @api.depends('name','product_uom')
    def conc_name_uom(self):
        for line in self:
            line.x_details = (line.name or '')+' /'+(line.product_uom.name or '')