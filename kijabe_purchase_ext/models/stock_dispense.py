# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError
from datetime import datetime

import logging
_logger = logging.getLogger(__name__)


class stock_dispense(models.Model):
    _name = "stock.dispense"
    _inherit = ['mail.thread', 'ir.needaction_mixin']
    _description = "Stock Dispensed from department store"

    ir_dept_id = fields.Many2one(
        'purchase.department', 'Department', required=True)
    ir_dept_head_id = fields.Char('Department Head', readonly=True, store=True,required=True)
    ir_dispensed_date = fields.Datetime(
        string='Date', required=True, index=True, default=fields.Datetime.now)
    patient_id = fields.Char('Patient ID')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('sent', 'Sent'),
        ('hod', 'HOD'),
        ('approved', 'Approved'),
        ('cancel', 'Cancelled')
    ], string='Status', readonly=True, index=True, copy=False, default='draft', track_visibility='onchange')
    name = fields.Char('Reference', required=True,
                       index=True, copy=False, default='New')
    item_ids = fields.One2many(
        'stock.dispense.item', 'ir_item_id', required=True)
    notes = fields.Text('Terms and Conditions')
    company_id = fields.Many2one(
        'res.company', 'Company', default=lambda self: self.env.user.company_id.id, index=1)
    date_approve = fields.Date(
        'Approval Date', readonly=1, index=True, copy=False)
    is_patient = fields.Boolean('Is for Patient?')
    is_department = fields.Boolean('Is for department?')
    disp_department = fields.Many2one('purchase.department', 'Department dispensed on')

    @api.multi
    def group_by_location(self):
        department = self.env["purchase.department"].search([['dep_head_id', '=', self.env.user.id]])
        if len(department)>0:
            return {
                'type': 'ir.actions.act_window',
                'name': 'Stock balances for '+department[0].name,
                'view_type': 'form',
                'view_mode': 'tree,form',
                'res_model': 'stock.quant',
                'domain': [('location_id','=',department[0].location.id)],
                'views': [(False, 'tree'), (False, 'form')],
                'target': 'current',
                'context': None,
            }
        else :
            raise ValidationError(
                        'You do not have permission to view this stock level, This is available only for HODs!')

    @api.onchange('ir_dept_id')
    def _populate_dep_code(self):
        self.ir_dept_head_id = self.ir_dept_id.dep_head_id.name
        self.item_ids = []
        return {}

    @api.model
    def create(self, vals):
        department = self.env["purchase.department"].search(
            [['id', '=', vals['ir_dept_id']]])
        vals['ir_dept_head_id'] = department.dep_head_id.name

        if vals['item_ids']:
            for item in vals['item_ids']:
                if item[2] and item[2]['item_id']:
                    stock_quant = self.env["stock.quant"].search(
                        [('product_id', '=', item[2]['item_id']), ('location_id', '=', department.location.id)])
                    item_id = self.env['product.product'].search(
                        [('id', '=', item[2]['item_id'])])
                    if len(stock_quant) > 0 and len(item_id) > 0:
                        if item[2]['dispensed_qty'] <= 0:
                            raise ValidationError(
                                'Dispensed Qty on "' + item_id.name+'" should be more than zero !')
                        elif item[2]['available_qty'] <= 0:
                            raise ValidationError(
                                item_id.name+' not available in ' + department.location.name + ' Stock')
                        elif item[2]['dispensed_qty'] > item[2]['available_qty']:
                            raise ValidationError(
                                'Dispensed Qty is more than available for -> ' + item_id.name)
                        else:
                            if vals.get('name', 'New') == 'New':
                                vals['name'] = self.env['ir.sequence'].next_by_code(
                                    'stock.dispense') or '/'
                                return super(stock_dispense, self).create(vals)
                    else:
                        raise ValidationError(
                            item_id.name +' Not available in ' + department.location.name + ' Store')
                else:
                    raise ValidationError(
                        'Empty item name, Kindly check your list of items!')
        else:
            raise ValidationError('No item found!')
            return {}

    @api.multi
    def button_confirm(self):
        for order in self:
            if order.state in ['draft', 'sent']:
                self.write(
                    {'state': 'hod', 'date_approve': fields.Date.context_today(self)})
            self.notifyHod(self.ir_dept_id, self.name)
        return {}

    @api.one
    def hod_approval(self):
        self._init_stock_move()
        self.write({'state': 'approved',
                    'date_approve': fields.Date.context_today(self)})
        self.notifyInitiator("HOD")
        return True

    @api.multi
    def button_cancel(self):
        self.write({'state': 'cancel'})
        self.notifyInitiatorCancel(self.env.user.name)
        return {}

    def _init_stock_move(self):
        sp_types = self.env['stock.picking.type'].search(
            [('code', '=', 'internal'), ('active', '=', True)])
        destination = self.env['stock.location'].search(
            [('name', '=', self.ir_dept_id.location.name), ('usage', '=', 'inventory'), ('active', '=', True)])

        # Initiate a stock pick
        if destination:
            for prod in self.item_ids:
                move = self.env['stock.move'].create({
                    'name': str(prod.item_id.name),
                    'location_id': self.ir_dept_id.location.id,
                    'location_dest_id': destination.id,
                    'product_id': prod.item_id.id,
                    'product_uom': prod.item_id.uom_id.id,
                    'product_uom_qty': prod.dispensed_qty,
                    'picking_type_id': sp_types[0].id,
                })
                picking = self.env['stock.picking'].create({
                    'state': 'draft',
                    'location_id': self.ir_dept_id.location.id,
                    'location_dest_id': destination.id,
                    'origin': self.name,
                    'move_type': 'direct',
                    'picking_type_id': sp_types[0].id,
                    'picking_type_code': sp_types[0].code,
                    'quant_reserved_exist': False,
                    'min_date': datetime.today(),
                    'priority': '1',
                    'company_id': prod.item_id.company_id.id,
                })
                picking.move_lines = move
                picking.action_confirm()
                picking.force_assign()
                picking.pack_operation_product_ids.write(
                    {'qty_done': prod.dispensed_qty})
                picking.do_new_transfer()
        else:
            raise ValidationError('Virtual dispensing location for "'+ self.ir_dept_id.location.name +'" not found, Please contact the system adminstrator.')
        return {}

    # Start Notification
    @api.multi
    def notifyInitiator(self, approver):
        user = self.env["res.users"].search(
            [['id', '=', self[0].create_uid.id]])
        self.sendToInitiator(user.login, self[0].name, user.name, approver)
        return True

    @api.multi
    def sendToInitiator(self, recipient, po, name, approver):
        url = self.env['ir.config_parameter'].get_param('web.base.url')
        mail_pool = self.env['mail.mail']
        values = {}
        values.update({'subject': 'Stock Dispensing # ' +
                       po + ' approved'})
        values.update({'email_from': "odoomail.service@gmail.com"})
        values.update({'email_to': recipient})
        values.update({'body_html':
                       'To ' + name + ',<br>'
                       + 'Dispensing No. ' + po + ' has been Approved by ' + str(approver)+'. You can find the details: '+url})

        self.env['mail.mail'].create(values).send()
        return True

    @api.multi
    def sendToManager(self, recipient, po, name):
        url = self.env['ir.config_parameter'].get_param('web.base.url')
        mail_pool = self.env['mail.mail']
        values = {}
        values.update({'subject': 'Stock Dispensing # ' +
                       po + ' waiting your approval'})
        values.update({'email_from': "odoomail.service@gmail.com"})
        values.update({'email_to': recipient})
        values.update({'body_html':
                       'To Manager ' + name + ',<br>'
                       + 'Dispensing No. ' + po + ' has been created and requires your approval. You can find the details to approve here. '+url})

        self.env['mail.mail'].create(values).send()
        return True

    @api.multi
    def notifyHod(self, department, irf):
        user = self.env["res.users"].search(
            [['id', '=', department.dep_head_id.id]])
        self.sendToManager(user.login, irf, user.name)
        return True

    # End notification


class stock_dispense_item(models.Model):
    _name = "stock.dispense.item"
    _inherit = ['mail.thread', 'ir.needaction_mixin']
    _description = "Stock items dispensed from department store"

    ir_item_id = fields.Many2one('stock.dispense')
    item_id = fields.Many2one('product.product', string='Item Dispensed')
    available_qty = fields.Float('Balance in Stock', store=True)
    dispensed_qty = fields.Float('Issued Quantity', store=True)

    @api.onchange('item_id')
    def _get_qty(self):
        self.available_qty = self.compute_remain_qty()
        return {}

    def compute_remain_qty(self):
        stock_qty_obj = self.env['stock.quant']
        stock_qty_lines = stock_qty_obj.search([('product_id', '=', self.item_id.id), (
            'location_id', '=', self.ir_item_id.ir_dept_id.location.id)]) # Get Department location
        total_qty = 0
        for quant in stock_qty_lines:
            total_qty += quant.qty
        return total_qty
