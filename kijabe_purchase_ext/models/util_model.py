# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError
import odoo.addons.decimal_precision as dp
from datetime import datetime
# import pandas
# from pandas import ExcelWriter
# from pandas import ExcelFile
# csv file import
import xmlrpclib
import csv

import logging
_logger = logging.getLogger(__name__)

class util_model(models.Model):
    _name = "util.model"

    @api.multi
    def stock_transfer(self):
        source = self.env['stock.location'].search([('id', '=', '165')])
        destination = self.env['stock.location'].search([('name', '=', 'Stock'),('id','=','31')])

        quant = self.env['stock.quant'].search([('location_id','=',source.id)])
        for q in quant:
            products = self.env['product.product'].search([('id','=',q.product_id.id)])
            self._init_stock_move(products, source, destination)
        return {}

    def _init_stock_move(self,prod,source,destination):
        sp_types = self.env['stock.picking.type'].search([('code', '=', 'internal')])
        # Initiate a stock pick
        onhand= self.env['stock.quant'].search([('product_id','=',prod.id),('location_id','=',source.id)])

        move = self.env['stock.move'].create({
                'name': str(prod.name),
                'location_id': source.id,
                'location_dest_id': destination.id,
                'product_id': prod.id,
                'product_uom': prod.uom_id.id,
                'product_uom_qty': onhand.qty,
                'picking_type_id': sp_types[0].id,
        })
        picking = self.env['stock.picking'].create({
                'state': 'draft',
                'location_id': source.id,
                'location_dest_id': destination.id,
                'origin': prod.name,
                'move_type': 'direct',
                'picking_type_id': sp_types[0].id,
                'picking_type_code': sp_types[0].code,
                'quant_reserved_exist': False,
                'min_date': datetime.today(),
                'priority': '1',
                'company_id': prod.company_id.id,
        })
        picking.move_lines = move
        picking.action_confirm()
        picking.force_assign()
        picking.pack_operation_product_ids.write({'qty_done': onhand.qty})
        picking.do_new_transfer()
        return {}

    @api.multi
    def load_drugs(self):
        url = self.env['ir.config_parameter'].get_param('web.base.url')
        username = "jeanpaul.mupagasi@cureinternational.org"
        pwd = 'Welcome123'
        dbname = "cure_kenya"
        sock_common = xmlrpclib.ServerProxy(url+"/xmlrpc/common")
        uid = sock_common.login(dbname, username, pwd)
        sock = xmlrpclib.ServerProxy(url+"/xmlrpc/object")
        reader = csv.reader(open('odoo.csv', 'rb'),
                            delimiter='|', quotechar='"')
        for row in reader:
                uom = self.env['product.uom'].search([('name', '=', row[1])],limit=1)
                categ = self.env['product.category'].search([('name', '=', 'Pharmacy')]) 
                name = self.env['product.template'].search(
                    [('name', '=', row[0])])
                if name:
                    _logger.error(
                        "====="+row[0]+" Duplicated")
                else:
                    if uom:
                        product_template = {
                            'name': row[0],
                            'uom_id': uom.id,
                            'uom_po_id': uom.id,
                            'list_price': row[2],
                            'standard_price': row[2],
                            'categ_id': categ.id,
                            'type': 'product'}
                        template_id = sock.execute(
                            dbname, uid, pwd, 'product.template', 'create', product_template)
                    else:
                        _logger.error(
                            "====="+row[0] + " UoM not found: "+str(row[1]))
        return {}

    # # Check duplicate products and archive if it doen't belong to a purchase order
    # @api.multi
    # def load_duplicate_prod(self):
    #     _logger.error("=====start=====")
    #     products = self.env['product.template'].search([('active', '=', True)])
    #     _logger.error('# active products: '+str(len(products)))
    #     count = 0
    #     for prod in products:
    #         duplicate = self.env['product.template'].search(
    #             [('active', '=', True), ('name', '=ilike', prod.name)])

    #         if len(duplicate) > 1:
    #             has_order = False
    #             dup_pid = {}
    #             for p in duplicate:
    #                 order = self.env['purchase.order.line'].search(
    #                     [('product_id', '=', p.id)])
    #                 dup_pid[p.id] = len(order)
    #             _logger.error(prod.name)
    #             _logger.error(dup_pid)
    #             _logger.error(max(dup_pid, key=dup_pid.get))
    #             max_pid = max(dup_pid, key=dup_pid.get)
    #             for p in duplicate:
    #                 if p.id != max_pid:
    #                     p.write({'active': False})
    #                     count += 1
    #             _logger.error("========================================")
    #     _logger.error("|Total archived: "+str(count))
    #     _logger.error("=====end=====")

    # # load products from a file
    # @api.multi
    # def load_file_prod(self):
    #     template = self.env['product.template'].search([('active', '=', True)])
    #     prod = self.env['product.product'].search([('active', '=', True)])
    #     _logger.error('|# Template: '+str(len(template)))
    #     _logger.error('|# Prod: '+str(len(prod)))
    #     # _logger.error(os.getcwd())

    #     dff = pandas.read_excel('inventory_items.xlsx', sheet_name='Worksheet')
    #     df = pandas.DataFrame(
    #         dff, columns=['Item name', 'Initial cost', 'unit of measure']).fillna(0)
    #     listOfProd = [(ItemsInFile(row['Item name'], row['Initial cost']), row['unit of measure'])
    #                   for index, row in df.iterrows()]  # convert to list of ItemsInFile class
    #     new_prod = {}
    #     uom = self.env['product.uom'].search(
    #         [('name', '=ilike', 'NA')])  # look for a 'NA' UoM
    #     if uom:
    #         for p in listOfProd:
    #             template = self.env['product.template'].search(
    #                 [('active', '=', True), ('name', '=ilike', p.name)])
    #             if len(template) > 0:
    #                 for i in range(len(template)):
    #                     _logger.error(
    #                         '|'+template[i].name+' |Sales Price: '+str(template[i].lst_price))
    #                     template[i].write({'lst_price': p.price})
    #                     _logger.error(
    #                         '|'+template[i].name+' |Sales Price: '+str(template[i].lst_price))

    #             else:
    #                 product = self.env['product.template'].create({
    #                     'name': p.name,
    #                     'type': 'product',
    #                     'lst_price': p.price,
    #                     'active': True,
    #                     'uom_id': uom[0].id,
    #                     'uom_po_id': uom[0].id
    #                 })
    #                 new_prod[p.name] = p.price

    #             prod = self.env['product.product'].search(
    #                 [('active', '=', True), ('name', '=ilike', p.name)])
    #             if len(prod) > 0:
    #                 for i in range(len(prod)):
    #                     prod[i].write({'lst_price': p.price})
    #             else:
    #                 product = self.env['product.product'].create({
    #                     'name': p.name,
    #                     'type': 'product',
    #                     'lst_price': p.price,
    #                     'active': True,
    #                     'uom_id': uom[0].id,
    #                     'uom_po_id': uom[0].id
    #                 })

    #         for p in new_prod:
    #             _logger.error(p)

    # # load products uom from a file
    # @api.multi
    # def load_uom_prod(self):
    #     template = self.env['product.template'].search([('active', '=', True)])
    #     prod = self.env['product.product'].search([('active', '=', True)])
    #     _logger.error('|# Template: '+str(len(template)))
    #     _logger.error('|# Prod: '+str(len(prod)))
        
    #     dff = pandas.read_excel('products_uom.xlsx', sheet_name='products with litres UOM')
    #     df = pandas.DataFrame(
    #         dff, columns=['Item name', 'Initial cost', 'unit of measure']).fillna(0)
    #     listOfProd = [(ItemsInFile(row['Item name'], row['Initial cost'], row['unit of measure']))
    #                   for index, row in df.iterrows()]  # convert to list of ItemsInFile class
    #     new_prod = {}

    #     for p in listOfProd:
    #         template = self.env['product.template'].search(
    #             [('active', '=', True), ('name', '=ilike', p.name)])
    #         uom = self.env['product.uom'].search(
    #             [('name', '=ilike', p.uom)])  # look for a UoM
    #         if len(uom)<=0:
    #             _logger.error("uom :"+str(p.uom))
    #             _logger.error("uom size :"+str(len(uom)))
    #         if len(uom) > 0:
    #             if len(template) > 0:
    #                 for i in range(len(template)):
    #                     _logger.error(template[i].name)
    #                     template[i].write(
    #                         {'uom_id': uom[0].id, 'uom_po_id': uom[0].id})
    #                     new_prod[p.name] = uom[0].name
                        

    #             prod = self.env['product.product'].search(
    #                 [('active', '=', True), ('name', '=ilike', p.name)])
    #             if len(prod) > 0:
    #                 for i in range(len(prod)):
    #                     prod[i].write(
    #                         {'uom_id': uom[0].id, 'uom_po_id': uom[0].id})
    #                     new_prod[p.name] = uom[0].name

    #         else:
    #             _logger.error(str(p.uom) + ' Not found!')

    #     for p in new_prod:
    #         _logger.error(p)

class ItemsInFile:
    def __init__(self, name, price, uom):
        self.name = name
        self.price = price
        self.uom = uom
    