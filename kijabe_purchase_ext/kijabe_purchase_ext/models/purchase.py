# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError

import logging
_logger = logging.getLogger(__name__)
''' 
This class inherit purchase.order model
Main feature:
1) Adding new fields and modifying fields display name
2) After confim button clicked, send email notification to Procurement manager requesting approval and 
   procurement manager approve the LPO, send notification to Finance manager requesting approval and the initiator,
   Finanace manager approve the LPO, check for double validation process, and send to ED for approval 
   if the amount exceed the amount set in double validation, otherwise approve the LPO by Finance and notify the initiator.
'''


class purchase(models.Model):
    _inherit = 'purchase.order'
    
    # Add new field
    x_dept_id = fields.Many2one(
        'purchase.department', 'Department')
    x_division = fields.Char('Division',
                             readonly=True,
                             store=True)
    x_dept_code = fields.Char('Dept Code',
                              readonly=True,
                              store=True
                              )
    x_div_code = fields.Char('Division Code',
                              readonly=True,
                              store=True
                              )
    # Modify existing fields display name
    partner_id = fields.Many2one(string=u'Supplier')
    partner_ref = fields.Char(string=u'Supplier Code')
    state = fields.Selection([
        ('draft', 'RFQ'),
        ('sent', 'RFQ Sent'),
        ('p_m_approve', 'To Procurement'),
        ('o_m_approve', 'To Operations'),
        ('f_m_approve', 'To Finance'),
        ('ceo_approve', 'To ED'),
        ('purchase', 'Purchase Order'),
        ('done', 'Locked'),
        ('cancel', 'Cancelled')
    ], string='Status', readonly=True, index=True, copy=False, default='draft', track_visibility='onchange')
    irf_ids = fields.Many2one("purchase.internal.requisition", "IRF Reference")

    @api.onchange('x_dept_id')
    def _populate_div(self):
        self.x_division = self.x_dept_id.dep_id.name
        self.x_div_code = self.x_dept_id.dep_id.div_code
        self.x_dept_code = self.x_dept_id.dep_code

        return {}

    @api.model
    def create(self, vals):
        division = self.env["purchase.division"].search(
            [['department_ids', '=', vals['x_dept_id']]])
        department = self.env["purchase.department"].search([['id', '=', vals['x_dept_id']]])
        
        vals['x_dept_code'] = department.dep_code
        vals['x_division'] = division.name
        vals['x_div_code'] = division.div_code

        return super(purchase, self).create(vals)

    @api.one
    def executive_director_approval(self):
        super(purchase, self).button_approve()
        self.notifyInitiator("Executive Director")
        return True

    @api.one
    def financial_manager_approval(self):
        for order in self:
            if order.state != 'f_m_approve':
                continue
            order._add_supplier_to_product()
            # Deal with double validation process
            if order.company_id.po_double_validation == 'one_step'\
                    or (order.company_id.po_double_validation == 'two_step'
                        and order.amount_total < self.env.user.company_id.currency_id.compute(order.company_id.po_double_validation_amount, order.currency_id))\
                    or order.user_has_groups('kijabe_purchase_ext.purchase_director_id'):
                order.button_approve()
                self.notifyInitiator("Financial Manager")
            else:
                order.write({'state': 'ceo_approve',
                             'date_approve': fields.Date.context_today(self)})
                self.notifyUserInGroup(
                    "kijabe_purchase_ext.purchase_director_id")

        return True

    @api.one
    def operations_manager_approval(self):
        self.write({'state': 'f_m_approve',
                    'date_approve': fields.Date.context_today(self)})
        self.notifyUserInGroup("kijabe_purchase_ext.purchase_finance_id")
        return True

    @api.one
    def procurement_manager_approval(self):
        self.write({'state': 'o_m_approve',
                    'date_approve': fields.Date.context_today(self)})
        self.notifyUserInGroup("kijabe_purchase_ext.purchase_operation_id")
        return True

    @api.multi
    def button_confirm(self):
        for order in self:
            if order.state in ['draft', 'sent']:
                self.write({'state': 'p_m_approve',
                            'date_approve': fields.Date.context_today(self)})
                self.notifyUserInGroup(
                    "kijabe_purchase_ext.purchase_leader_procurement_id")
        return True

    @api.multi
    def notifyUserInGroup(self, group_ext_id):
        group = self.env.ref(group_ext_id)
        for user in group.users:
            _logger.error("Notify User `%s` In Group `%s`" %
                          (str(user.login), group.name))
            self.sendToManager(user.login, self[0].name, user.name)
        return True

    @api.multi
    def notifyInitiator(self, approver):
        user = self.env["res.users"].search(
            [['id', '=', self[0].create_uid.id]])
        self.sendToInitiator(user.login, self[0].name, user.name, approver)
        return True

    @api.multi
    def sendToManager(self, recipient, po, name):
        url = self.env['ir.config_parameter'].get_param('web.base.url')
        mail_pool = self.env['mail.mail']
        values = {}
        values.update({'subject': 'Purchase Order #' +
                       po + ' waiting your approval'})
        values.update({'email_from': "odoomail.service@gmail.com"})
        values.update({'email_to': recipient})
        values.update({'body_html':
                       'To Manager ' + name + ',<br>'
                       + 'LPO No. ' + po + ' has been created and requires your approval. You can find the details to approve here. '+url})

        self.env['mail.mail'].create(values).send()
        return True

    @api.multi
    def sendToInitiator(self, recipient, po, name, approver):
        url = self.env['ir.config_parameter'].get_param('web.base.url')
        mail_pool = self.env['mail.mail']
        values = {}
        values.update({'subject': 'Purchase order #' +
                       po + ' approved'})
        values.update({'email_from': "odoomail.service@gmail.com"})
        values.update({'email_to': recipient})
        values.update({'body_html':
                       'To ' + name + ',<br>'
                       + 'LPO No. ' + po + ' has been Approved by ' + str(approver)+'. You can find the details: '+url})

        self.env['mail.mail'].create(values).send()
        return True
