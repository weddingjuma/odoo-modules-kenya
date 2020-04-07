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
    
    @api.depends('product_qty', 'price_unit', 'taxes_id')
    def _compute_amount(self):
        for line in self:
            taxes = line.taxes_id.compute_all(line.price_unit, line.order_id.currency_id, line.qty_received if line.qty_received else line.product_qty, product=line.product_id, partner=line.order_id.partner_id)
            line.update({
                'price_tax': taxes['total_included'] - taxes['total_excluded'],
                'price_total': taxes['total_included'],
                'price_subtotal': taxes['total_excluded'],
            })
            _logger.error('=================Total: '+str(line.qty_received if line.qty_received else line.product_qty))

class StockMove(models.Model):
    _inherit = 'stock.picking'

    currency_id = fields.Many2one(related='company_id.currency_id', store=True, string='Currency', readonly=True)




