from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError
from datetime import datetime

import logging
_logger = logging.getLogger(__name__)

class stock_consume(models.Model):
    _name = "stock.consume"
    _inherit = ['mail.thread', 'ir.needaction_mixin']
    _description = "Stock Consumption from department store"

    ir_dept_id = fields.Many2one(
        'purchase.department', 'Department', required=True)
    ir_dept_head_id = fields.Char('Department Head', readonly=True, store=True)
    ir_consumed_date = fields.Datetime(
        string='Date', required=True, index=True, default=fields.Datetime.now)
    consumer = fields.Char('Client reference', required=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('sent', 'Sent'),
        ('hod', 'HOD'),
        ('approved', 'Approved'),
        ('done', 'Approved & Locked'),
        ('cancel', 'Cancelled')
    ], string='Status', readonly=True, index=True, copy=False, default='draft', track_visibility='onchange')
    name = fields.Char('Reference', required=True,
                       index=True, copy=False, default='New')
    item_ids = fields.One2many(
        'stock.consume.item', 'ir_item_id', required=True)
    notes = fields.Text('Terms and Conditions')
    company_id = fields.Many2one(
        'res.company', 'Company', default=lambda self: self.env.user.company_id.id, index=1)
    date_approve = fields.Date(
        'Approval Date', readonly=1, index=True, copy=False)

    @api.onchange('ir_dept_id')
    def _populate_dep_code(self):
        self.ir_dept_head_id = self.ir_dept_id.dep_head_id.name
        return {}
    
    @api.model
    def create(self, vals):

        if vals['item_ids']:
            for item in vals['item_ids']:
                if item[2]:
                    item_id = self.env['product.product'].search(
                        [('id', '=', item[2]['item_id'])])
                    if item[2]['consumed_qty'] <= 0:
                        raise ValidationError(
                            'Please set quantity on -> ' + str(item_id.name)+' !')
                    else:
                        department = self.env["purchase.department"].search(
                            [['id', '=', vals['ir_dept_id']]])
                        vals['ir_dept_head_id'] = department.dep_head_id.name

                        if vals.get('name', 'New') == 'New':
                            vals['name'] = self.env['ir.sequence'].next_by_code(
                                'stock.consume') or '/'
                            return super(stock_consume, self).create(vals)
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
        self.write({'state': 'approved',
                    'date_approve': fields.Date.context_today(self)})
        self.notifyInitiator("HOD")
        return True

    @api.multi
    def button_cancel(self):
        self.write({'state': 'cancel'})
        self.notifyInitiatorCancel(self.env.user.name)
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
        values.update({'subject': 'Stock Consumption #' +
                       po + ' approved'})
        values.update({'email_from': "odoomail.service@gmail.com"})
        values.update({'email_to': recipient})
        values.update({'body_html':
                       'To ' + name + ',<br>'
                       + 'Consumption No. ' + po + ' has been Approved by ' + str(approver)+'. You can find the details: '+url})

        self.env['mail.mail'].create(values).send()
        return True

    @api.multi
    def sendToManager(self, recipient, po, name):
        url = self.env['ir.config_parameter'].get_param('web.base.url')
        mail_pool = self.env['mail.mail']
        values = {}
        values.update({'subject': 'Stock Consumption #' +
                       po + ' waiting your approval'})
        values.update({'email_from': "odoomail.service@gmail.com"})
        values.update({'email_to': recipient})
        values.update({'body_html':
                       'To Manager ' + name + ',<br>'
                       + 'Consumption No. ' + po + ' has been created and requires your approval. You can find the details to approve here. '+url})

        self.env['mail.mail'].create(values).send()
        return True

    @api.multi
    def notifyHod(self, department, irf):
        user = self.env["res.users"].search(
            [['id', '=', department.dep_head_id.id]])
        self.sendToManager(user.login, irf, user.name)
        return True

    # End notification

class stock_consume_item(models.Model):
    _name = "stock.consume.item"
    _inherit = ['mail.thread', 'ir.needaction_mixin']
    _description = "Stock items consumed from department store"

    ir_item_id = fields.Many2one('stock.consume')
    item_id = fields.Many2one('product.product', string='Item')
    consumed_qty = fields.Float('Consumed Quantity', store=True)