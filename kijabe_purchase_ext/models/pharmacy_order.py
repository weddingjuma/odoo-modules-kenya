from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError
from datetime import datetime
import odoo.addons.decimal_precision as dp

import logging
_logger = logging.getLogger(__name__)

class pharmacy_order(models.Model):
    _name = "pharmacy.order"
    _inherit = ['mail.thread', 'ir.needaction_mixin']
    _description = "Pharmacy Stock orders from departments"

    ir_dept_id = fields.Many2one(
        'purchase.department', 'Department', required=True)
    ir_dept_code = fields.Char('Department Code', readonly=True, store=True)
    ir_dept_head_id = fields.Char('Department Head', readonly=True, store=True)
    ir_req_date = fields.Datetime(
        string='Date', required=True, index=True, default=fields.Datetime.now)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('sent', 'Sent'),
        ('hod', 'HOD'),
        ('pharmacy', 'Pharmacy'),
        ('approved','Approved'),
        ('done', 'Approved & Locked'),
        ('cancel', 'Cancelled')
    ], string='Status', readonly=True, index=True, copy=False, default='draft', track_visibility='onchange')
    name = fields.Char('Reference', required=True,
                       index=True, copy=False, default='New')
    item_ids = fields.One2many(
        'pharmacy.order.item', 'ir_item_id', required=True)
    notes = fields.Text('Terms and Conditions')
    company_id = fields.Many2one(
        'res.company', 'Company', default=lambda self: self.env.user.company_id.id, index=1)
    date_approve = fields.Date(
        'Approval Date', readonly=1, index=True, copy=False)

    @api.onchange('ir_dept_id')
    def _populate_dep_code(self):
        self.ir_dept_code = self.ir_dept_id.dep_code
        self.ir_dept_head_id = self.ir_dept_id.dep_head_id.name
        return {}
    
    @api.model
    def create(self, vals):
        if vals['item_ids']:
            for item in vals['item_ids']:
                if item[2]:
                    item_id = self.env['product.product'].search(
                        [('id', '=', item[2]['item_id'])])
                    if item[2]['product_qty'] <= 0:
                        raise ValidationError(
                            'Please set ordered quantity on -> ' + str(item_id.name)+' !')
                    else:
                        department = self.env["purchase.department"].search(
                            [['id', '=', vals['ir_dept_id']]])

                        vals['ir_dept_code'] = department.dep_code
                        vals['ir_dept_head_id'] = department.dep_head_id.name

                        if vals.get('name', 'New') == 'New':
                            vals['name'] = self.env['ir.sequence'].next_by_code(
                                'pharmacy.order') or '/'
                            return super(pharmacy_order, self).create(vals)
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
        self.write({'state': 'pharmacy',
                    'date_approve': fields.Date.context_today(self)})
        self.notifyUserInGroup(
            "kijabe_purchase_ext.pharmacy")
        return True
        
    @api.multi
    def pharmacist_approval(self):        
        self.write(
            {'state': 'approved', 'date_approve': fields.Date.context_today(self)})
        self.filtered(
            lambda p: p.company_id.po_lock == 'lock').write({'state': 'done'})
        for item in self.item_ids:
            if item.product_qty > item.qty_available:
                raise UserError(str(
                    item.item_id.name)+' is out of stock, remaining stock is:'+str(item.qty_available))
        self._init_stock_move()
        self.notifyInitiator("Pharmacist")
        return {}
    
    def _init_stock_move(self):
        sp_types = self.env['stock.picking.type'].search(
            [('code', '=', 'internal')])
        pharmacy_location = self.env['stock.location'].search([('name', '=', 'Pharmacy')])
        # Initiate a stock pick
        for prod in self.item_ids:
            move = self.env['stock.move'].create({
                'name': str(prod.item_id.name),
                'location_id': pharmacy_location.id,
                'location_dest_id': self.ir_dept_id.location.id,
                'product_id': prod.item_id.id,
                'product_uom': prod.item_id.uom_id.id,
                'product_uom_qty': prod.product_qty,
                'picking_type_id': sp_types[0].id,
            })
            picking = self.env['stock.picking'].create({
                'state': 'draft',
                'location_id': pharmacy_location.id,
                'location_dest_id': self.ir_dept_id.location.id,
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
                {'qty_done': prod.product_qty})
            picking.do_new_transfer()

        return {}

    # deal with notification
    @api.multi
    def notifyUserInGroup(self, group_ext_id):
        group = self.env.ref(group_ext_id)
        for user in group.users:
            self.sendToManager(user.login, self[0].name, user.name)
        return True

    @api.multi
    def notifyInitiator(self, approver):
        user = self.env["res.users"].search(
            [['id', '=', self[0].create_uid.id]])
        self.sendToInitiator(user.login, self[0].name, user.name, approver)
        return True

    @api.multi
    def notifyInitiatorCancel(self, approver):
        user = self.env["res.users"].search(
            [['id', '=', self[0].create_uid.id]])
        self.sendToInitiatorCancel(
            user.login, self[0].name, user.name, approver)
        return True

    @api.multi
    def sendToInitiator(self, recipient, reference, name, approver):
        url = self.env['ir.config_parameter'].get_param('web.base.url')
        mail_pool = self.env['mail.mail']
        values = {}
        values.update({'subject': 'Pharmacy order #' +
                       reference + ' approved'})
        values.update({'email_from': "odoomail.service@gmail.com"})
        values.update({'email_to': recipient})
        values.update({'body_html':
                       'To ' + name + ',<br>'
                       + 'Pharmacy No. ' + reference + ' has been Approved by ' + str(approver)+'. You can find the details: '+url})

        self.env['mail.mail'].create(values).send()
        return True

    @api.multi
    def sendToManager(self, recipient, reference, name):
        url = self.env['ir.config_parameter'].get_param('web.base.url')
        mail_pool = self.env['mail.mail']
        values = {}
        values.update({'subject': 'Pharmacy Order #' +
                       reference + ' waiting your approval'})
        values.update({'email_from': "odoomail.service@gmail.com"})
        values.update({'email_to': recipient})
        values.update({'body_html':
                       'To Manager ' + name + ',<br>'
                       + 'Pharmacy Order No. ' + reference + ' has been created and requires your approval. You can find the details to approve here. '+url})

        self.env['mail.mail'].create(values).send()
        return True

    @api.multi
    def sendToInitiatorCancel(self, recipient, reference, name, approver):
        url = self.env['ir.config_parameter'].get_param('web.base.url')
        mail_pool = self.env['mail.mail']
        values = {}
        values.update({'subject': 'Pharmacy order #' +
                       reference + ' cancelled'})
        values.update({'email_from': "odoomail.service@gmail.com"})
        values.update({'email_to': recipient})
        values.update({'body_html':
                       'To ' + name + ',<br>'
                       + 'Pharmacy order No. ' + reference + ' has been cancelled by ' + str(approver)+'. You can find the details: '+url})

        self.env['mail.mail'].create(values).send()
        return True

    @api.multi
    def notifyHod(self, department, reference):
        user = self.env["res.users"].search(
            [['id', '=', department.dep_head_id.id]])
        self.sendToManager(user.login, reference, user.name)
        return True

    # End notification


class pharmacy_order_item(models.Model):
    _name = "pharmacy.order.item"
    ir_item_id = fields.Many2one('pharmacy.order')
    
    item_id = fields.Many2one('product.product', string='Item', domain=lambda self:self._get_pharmacy_categ()) # Get only product of pharmacy category
    qty_available = fields.Float('Available Quantity',
                                 store=True,
                                 )
    product_qty = fields.Float(string='Quantity To Order', digits=dp.get_precision(
        'Product Unit of Measure'), required=True)
    comment = fields.Text("Comment")

    def _get_pharmacy_categ(self):
        return [('categ_id', 'child_of', self.env['product.category'].search([('name', '=', 'Pharmacy')]).id)]

    @api.onchange('item_id')
    def _get_qty(self):
        self.qty_available = self.compute_remain_qty(self.ir_item_id)
        return {}

    def compute_remain_qty(self, item):
        stock_qty_obj = self.env['stock.quant']
        stock_location = self.env['stock.location'].search([('name', '=', 'Pharmacy')])
        stock_qty_lines = stock_qty_obj.search([('product_id', '=', self.item_id.id), (
            'location_id', '=', stock_location.id)])# Get the product qty on hand in Pharmacy location only
        total_qty = 0
        for quant in stock_qty_lines:
            total_qty += quant.qty
        return total_qty