# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError
import odoo.addons.decimal_precision as dp
from datetime import datetime
import pandas
from pandas import ExcelWriter
from pandas import ExcelFile
# import os

import logging
_logger = logging.getLogger(__name__)


class internal_requisition(models.Model):
    _name = "purchase.internal.requisition"
    _inherit = ['mail.thread', 'ir.needaction_mixin']
    _description = "Internal Requisition"

    ir_dept_id = fields.Many2one(
        'purchase.department', 'Department', required=True)
    ir_dept_code = fields.Char('Department Code', readonly=True, store=True)
    ir_dept_head_id = fields.Char('Department Head', readonly=True, store=True)
    ir_req_date = fields.Datetime(
        string='Date', required=True, index=True, default=fields.Datetime.now)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('sent', 'IRF Sent'),
        ('to approve', 'WH Manager'),
        ('purchase', 'Approved'),
        ('done', 'Approved & Locked'),
        ('cancel', 'Cancelled')
    ], string='Status', readonly=True, index=True, copy=False, default='draft', track_visibility='onchange')
    name = fields.Char('Reference', required=True,
                       index=True, copy=False, default='New')
    item_ids = fields.One2many(
        'purchase.internal.requisition.item', 'ir_item_id')
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
        department = self.env["purchase.department"].search(
            [['id', '=', vals['ir_dept_id']]])

        vals['ir_dept_code'] = department.dep_code
        vals['ir_dept_head_id'] = department.dep_head_id.name

        if vals.get('name', 'New') == 'New':
            vals['name'] = self.env['ir.sequence'].next_by_code(
                'purchase.internal.requisition') or '/'
        return super(internal_requisition, self).create(vals)

    @api.multi
    def button_confirm(self):
        for order in self:
            if order.state in ['draft', 'sent']:
                self.write({'state': 'to approve',
                            'date_approve': fields.Date.context_today(self)})
                self.notifyUserInGroup(
                    "stock.group_stock_manager")
        return {}

    @api.multi
    def button_approve(self, force=False):
        self.write(
            {'state': 'purchase', 'date_approve': fields.Date.context_today(self)})
        self.filtered(
            lambda p: p.company_id.po_lock == 'lock').write({'state': 'done'})
        for item in self.item_ids:
            if item.product_qty > item.qty_available:
                raise UserError(str(item.item_id.name)+' is out of stock, remaining stock is:'+str(item.qty_available))
        self._init_stock_move()
        self.notifyInitiator("Stock Manager")
        return {}

    def _init_stock_move(self):
        sp_types = self.env['stock.picking.type'].search(
            [('code', '=', 'internal')])
        # Initiate a stock pick
        for prod in self.item_ids:
            move = self.env['stock.move'].create({
                'name': str(prod.item_id.name),
                'location_id': self.ir_dept_id.location.location_id.id,
                'location_dest_id': self.ir_dept_id.location.id,
                'product_id': prod.item_id.id,
                'product_uom': prod.item_id.uom_id.id,
                'product_uom_qty': prod.product_qty,
                'picking_type_id': sp_types[0].id,
            })
            picking = self.env['stock.picking'].create({
                'state': 'draft',
                'location_id': self.ir_dept_id.location.location_id.id,
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

    @api.multi
    def button_cancel(self):
        self.write({'state': 'cancel'})
        self.notifyInitiatorCancel(self.env.user.name)
        return {}

    @api.multi
    def button_draft(self):
        self.write({'state': 'draft'})
        return {}

    @api.multi
    def load_duplicate_prod(self):
        _logger.error("=====start=====")
        products = self.env['product.template'].search([('active','=',True)])
        _logger.error('# active products: '+str(len(products)))
        count = 0
        for prod in products:
            duplicate = self.env['product.template'].search([('active','=',True),('name','=ilike',prod.name)])
            
            if len(duplicate)>1:
                has_order = False
                dup_pid = {}
                for p in duplicate:                    
                    order = self.env['purchase.order.line'].search([('product_id','=',p.id)])
                    dup_pid[p.id]=len(order)
                _logger.error(prod.name)
                _logger.error(dup_pid)
                _logger.error(max(dup_pid, key=dup_pid.get))
                max_pid = max(dup_pid, key=dup_pid.get)
                for p in duplicate:
                    if p.id != max_pid:
                        p.write({'active': False})
                        count +=1
                _logger.error("========================================")
        _logger.error("|Total archived: "+str(count))
        _logger.error("=====end=====")

    @api.multi
    def load_file_prod(self):
        template = self.env['product.template'].search([('active','=',True)])
        prod = self.env['product.product'].search([('active','=',True)])
        _logger.error('|# Template: '+str(len(template)))
        _logger.error('|# Prod: '+str(len(prod)))
        # _logger.error(os.getcwd())
        
        dff = pandas.read_excel('inventory_items.xlsx', sheet_name='Worksheet')
        df = pandas.DataFrame(dff, columns= ['Item name','Initial cost']).fillna(0)
        listOfProd = [(ItemsInFile(row['Item name'],row['Initial cost'])) for index, row in df.iterrows()] #convert to list of ItemsInFile class 
        new_prod = {}
        uom = self.env['product.uom'].search([('name','=ilike','NA')])# look for a 'NA' UoM
        if uom:
            for p in listOfProd:
                template = self.env['product.template'].search([('active','=',True),('name','=ilike',p.name)])
                if len(template)>0:
                    for i in range(len(template)):
                        _logger.error('|'+template[i].name+' |Sales Price: '+str(template[i].lst_price))
                        template[i].write({'lst_price':p.price})
                        _logger.error('|'+template[i].name+' |Sales Price: '+str(template[i].lst_price))
                        
                else:
                    product = self.env['product.template'].create({
                        'name':p.name,
                        'type':'product',
                        'lst_price':p.price,
                        'active':True,
                        'uom_id':uom[0].id,
                        'uom_po_id':uom[0].id
                    })
                    new_prod[p.name] = p.price

                prod = self.env['product.product'].search([('active','=',True),('name','=ilike',p.name)])
                if len(prod)>0:
                    for i in range(len(prod)):                    
                        prod[i].write({'lst_price':p.price})
                else:
                    product = self.env['product.product'].create({
                        'name':p.name,
                        'type':'product',
                        'lst_price':p.price,
                        'active':True,
                        'uom_id':uom[0].id,
                        'uom_po_id':uom[0].id
                    })
                
            for p in new_prod:
                _logger.error(p)
                        



    # deal with notification
    @api.multi
    def notifyUserInGroup(self, group_ext_id):
        group = self.env.ref(group_ext_id)
        for user in group.users:
            self.sendToManager(user.login, self[0].name, user.name)
        return True

    @api.multi
    def sendToManager(self, recipient, po, name):
        url = self.env['ir.config_parameter'].get_param('web.base.url')
        mail_pool = self.env['mail.mail']
        values = {}
        values.update({'subject': 'Internal Requisition Order #' +
                       po + ' waiting your approval'})
        values.update({'email_from': "odoomail.service@gmail.com"})
        values.update({'email_to': recipient})
        values.update({'body_html':
                       'To Manager ' + name + ',<br>'
                       + 'IRF No. ' + po + ' has been created and requires your approval. You can find the details to approve here. '+url})

        self.env['mail.mail'].create(values).send()
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
        self.sendToInitiatorCancel(user.login, self[0].name, user.name, approver)
        return True

    @api.multi
    def sendToInitiator(self, recipient, po, name, approver):
        url = self.env['ir.config_parameter'].get_param('web.base.url')
        mail_pool = self.env['mail.mail']
        values = {}
        values.update({'subject': 'Internal Requisition order #' +
                       po + ' approved'})
        values.update({'email_from': "odoomail.service@gmail.com"})
        values.update({'email_to': recipient})
        values.update({'body_html':
                       'To ' + name + ',<br>'
                       + 'IRF No. ' + po + ' has been Approved by ' + str(approver)+'. You can find the details: '+url})

        self.env['mail.mail'].create(values).send()
        return True
        
    @api.multi
    def sendToInitiatorCancel(self, recipient, po, name, approver):
        url = self.env['ir.config_parameter'].get_param('web.base.url')
        mail_pool = self.env['mail.mail']
        values = {}
        values.update({'subject': 'Internal Requisition order #' +
                       po + ' cancelled'})
        values.update({'email_from': "odoomail.service@gmail.com"})
        values.update({'email_to': recipient})
        values.update({'body_html':
                       'To ' + name + ',<br>'
                       + 'IRF No. ' + po + ' has been cancelled by ' + str(approver)+'. You can find the details: '+url})

        self.env['mail.mail'].create(values).send()
        return True


class purchase_internal_requisition_items(models.Model):
    _name = "purchase.internal.requisition.item"
    ir_item_id = fields.Many2one('purchase.internal.requisition')
    item_id = fields.Many2one('product.product', string='Item')
    qty_available = fields.Float('Available Quantity',
                                 store=True,
                                 )
    product_qty = fields.Float(string='Quantity To Order', digits=dp.get_precision(
        'Product Unit of Measure'), required=True)
    comment = fields.Text("Comment")

    @api.onchange('item_id')
    def _get_qty(self):
        self.qty_available = self.compute_remain_qty(self.ir_item_id)
        return {}

    def compute_remain_qty(self, item):
        stock_qty_obj = self.env['stock.quant']
        stock_qty_lines = stock_qty_obj.search([('product_id', '=', self.item_id.id), (
            'location_id', '=', self.ir_item_id.ir_dept_id.location.location_id.id)])
        total_qty = 0
        for quant in stock_qty_lines:
            total_qty += quant.qty
        return total_qty

class ItemsInFile:
    def __init__(self, name, price):
       self.name = name
       self.price = price
     