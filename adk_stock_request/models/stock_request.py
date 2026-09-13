from odoo import models, fields, api, _
from odoo.exceptions import UserError

class AdkStockRequestOrder(models.Model):
    _name = 'adk.stock.request.order'
    _description = 'Demande de Stock ADK'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string="Référence", required=True, readonly=True, default='Nouveau', copy=False, tracking=True)
    expected_date = fields.Datetime(string="Date prévue", default=fields.Datetime.now, required=True, tracking=True)
    request_date = fields.Datetime(string="Date de la demande", default=fields.Datetime.now, tracking=True)
    shipping_policy = fields.Selection([
        ('direct', 'Expédier chaque article dès qu’il est disponible'),
        ('one', 'Expédier tous les articles en même temps')
    ], string="Politique d'expédition", default='direct', required=True, tracking=True)

    demandeur_id = fields.Many2one('res.users', string="Demandeur", default=lambda self: self.env.user, required=True, tracking=True)
    description = fields.Text(string="Description")
    warehouse_id = fields.Many2one('stock.warehouse', string="Entrepôt", required=True, tracking=True)
    location_id = fields.Many2one('stock.location', string="Emplacement Destination", required=True, tracking=True)
    route_id = fields.Many2one('stock.route', string="Route", tracking=True)
    procurement_group_id = fields.Many2one('procurement.group', string="Groupe d'approvisionnement", copy=False, readonly=True)
    
    state = fields.Selection([
        ('draft', 'Brouillon'),
        ('submitted', 'Soumis'),
        ('in_progress', 'En cours'),
        ('done', 'Terminé'),
        ('cancelled', 'Annulé'),
    ], string="État", default='draft', tracking=True)

    line_ids = fields.One2many('adk.stock.request.line', 'order_id', string="Lignes", copy=True)
    picking_ids = fields.One2many('stock.picking', 'adk_request_id', string="Transferts")
    picking_count = fields.Integer(compute='_compute_picking_count', string="Transferts", compute_sudo=True)
    sortie_picking_id = fields.Many2one('stock.picking', compute='_compute_pickings', string="Transfert SORTIE", compute_sudo=True, copy=False)
    reception_picking_id = fields.Many2one('stock.picking', compute='_compute_pickings', string="Transfert RÉCEPTION", compute_sudo=True, copy=False)
    sortie_picking_count = fields.Integer(compute='_compute_picking_count', string="Transferts SORTIE", compute_sudo=True)
    reception_picking_count = fields.Integer(compute='_compute_picking_count', string="Transferts RÉCEPTION", compute_sudo=True)
    sortie_status = fields.Selection([
        ('done', 'Terminé'),
        ('pret', 'Prêt'),
        ('en_attente', "En attente d'approvisionnement"),
    ], compute='_compute_pickings_state', string="État SORTIE", compute_sudo=True)
    reception_status = fields.Selection([
        ('done', 'Terminé'),
        ('pret', 'Prêt'),
        ('en_attente', 'En attente de la sortie'),
    ], compute='_compute_pickings_state', string="État RÉCEPTION", compute_sudo=True)
    company_id = fields.Many2one('res.company', string="Société", default=lambda self: self.env.company, required=True, tracking=True)
    line_count = fields.Integer(compute='_compute_line_stats', string="Nb. lignes", compute_sudo=True, store=True)
    total_qty_requested = fields.Float(compute='_compute_line_stats', string="Qté totale demandée", compute_sudo=True, store=True)
    total_qty_done = fields.Float(compute='_compute_line_stats', string="Qté totale traitée", compute_sudo=True, store=True)
    progress = fields.Float(compute='_compute_line_stats', string="Avancement (%)", compute_sudo=True, store=True)
    is_late = fields.Boolean(compute='_compute_is_late', string="En retard", compute_sudo=True, store=True)

    @api.depends('picking_ids')
    def _compute_picking_count(self):
        for record in self:
            record.picking_count = len(record.picking_ids)
            record.sortie_picking_count = len(
                record.picking_ids.filtered(lambda p: p.picking_type_id.code != 'incoming' and 'SORTIE' in (p.origin or '')))
            record.reception_picking_count = len(
                record.picking_ids.filtered(lambda p: p.picking_type_id.code == 'incoming' and 'RÉCEPTION' in (p.origin or '')))

    @api.depends('picking_ids')
    def _compute_pickings(self):
        for record in self:
            pickings = record.picking_ids
            # SORTIE : transfert interne (code 'internal') de l'entrepôt source.
            # RÉCEPTION : opération 'Réceptions' (code 'incoming') de l'entrepôt de réception.
            record.sortie_picking_id = pickings.filtered(
                lambda p: p.picking_type_id.code != 'incoming' and 'SORTIE' in (p.origin or ''))[:1]
            record.reception_picking_id = pickings.filtered(
                lambda p: p.picking_type_id.code == 'incoming' and 'RÉCEPTION' in (p.origin or ''))[:1]

    @api.depends('sortie_picking_id.state', 'reception_picking_id.state')
    def _compute_pickings_state(self):
        # Même règle qu'au niveau ligne : le statut se lit directement sur l'état du
        # transfert (assigned = Prêt), et la RÉCEPTION ne passe "Prêt" que lorsque la
        # SORTIE est Terminée.
        for record in self:
            sortie = record.sortie_picking_id
            reception = record.reception_picking_id
            if sortie:
                if sortie.state == 'done':
                    record.sortie_status = 'done'
                elif sortie.state == 'assigned':
                    record.sortie_status = 'pret'
                else:
                    record.sortie_status = 'en_attente'
            else:
                record.sortie_status = False
            if reception:
                if reception.state == 'done':
                    record.reception_status = 'done'
                elif sortie and sortie.state == 'done':
                    record.reception_status = 'pret'
                else:
                    record.reception_status = 'en_attente'
            else:
                record.reception_status = False

    @api.depends('line_ids.qty', 'line_ids.qty_done')
    def _compute_line_stats(self):
        for record in self:
            record.line_count = len(record.line_ids)
            record.total_qty_requested = sum(record.line_ids.mapped('qty'))
            record.total_qty_done = sum(record.line_ids.mapped('qty_done'))
            record.progress = (record.total_qty_done / record.total_qty_requested * 100) if record.total_qty_requested else 0.0

    @api.depends('expected_date', 'state')
    def _compute_is_late(self):
        now = fields.Datetime.now()
        for record in self:
            record.is_late = bool(
                record.expected_date and record.expected_date < now
                and record.state not in ('done', 'cancelled')
            )

    @api.constrains('picking_ids')
    def _check_transfers_are_isolated(self):
        for record in self:
            pickings = record.picking_ids
            if not pickings:
                continue
            sorties = pickings.filtered(lambda p: 'SORTIE' in (p.origin or ''))
            receptions = pickings.filtered(lambda p: 'RÉCEPTION' in (p.origin or ''))
            if len(sorties) > 1 or len(receptions) > 1:
                raise UserError(_(
                    "Chaque demande de stock possède exactement 2 transferts : une SORTIE "
                    "et une RÉCEPTION. Les transferts des demandes ne doivent jamais se mélanger."
                ))
            if len(pickings) != len(sorties) + len(receptions):
                raise UserError(_(
                    "Les transferts d'une demande de stock ne peuvent contenir que la SORTIE "
                    "et la RÉCEPTION de cette demande, sans mélange avec d'autres demandes."
                ))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                vals['name'] = self.env['ir.sequence'].next_by_code('adk.stock.request.order') or 'Nouveau'
        return super().create(vals_list)

    def action_submit(self):
        self.state = 'submitted'

    def action_reset_to_draft(self):
        """Bouton 'Réinitialiser' : Soumis / En cours / Annulé -> Brouillon pour
        permettre de repartir sur une base propre. Un transfert encore en brouillon,
        confirmé, réservé ou déjà Annulé ne bloque pas la remise en brouillon.

        Dès qu'une SORTIE ou RÉCEPTION est réellement effectuée (transfert validé),
        la demande ne peut plus être réinitialisée : seul le retour des articles
        reste possible."""
        for record in self:
            if record.state == 'done':
                raise UserError(_(
                    "Les transferts SORTIE et RÉCEPTION ont été effectués. Cette demande "
                    "ne peut plus être corrigée : seul le retour des articles est possible."
                ))
            validated = record.picking_ids.filtered(lambda p: p.state == 'done')
            if validated:
                raise UserError(_(
                    "Un transfert (SORTIE ou RÉCEPTION) a déjà été validé (effectué). La "
                    "demande ne peut plus être réinitialisée : seul le retour des articles est possible."
                ))
            # Manager requis dès que des transferts ont existé pour cette demande
            # (approuvée puis éventuellement annulée) : pas seulement quand elle est
            # encore "En cours".
            needs_manager = record.state == 'in_progress' or (record.state == 'cancelled' and record.picking_ids)
            if needs_manager and not self.env.user.has_group('adk_stock_request.group_adk_stock_request_manager'):
                raise UserError(_("Seul un Manager Demande Stock peut réinitialiser une demande déjà approuvée."))
            if record.state == 'draft':
                raise UserError(_("La demande est déjà en brouillon."))
        for record in self:
            record.picking_ids.filtered(lambda p: p.state != 'done').unlink()
            for old_group in record.procurement_group_id:
                record.procurement_group_id = False
                try:
                    old_group.sudo().unlink()
                except Exception:
                    pass
            record.write({'state': 'draft'})

    def action_cancel(self):
        """Bouton 'Annuler' : Brouillon / Soumis / En cours -> Annulé.

        - Depuis Brouillon ou Soumis : aucun transfert n'existe encore, l'annulation
          est immédiate et ouverte à tout utilisateur habilité sur ses propres demandes.
        - Depuis En cours : les transferts SORTIE/RÉCEPTION existent déjà (même non
          validés) ; seul un Manager peut annuler, et seulement si aucun des deux n'a
          encore été validé. Les transferts non validés sont alors annulés (pas
          supprimés), pour garder une trace consultable dans l'Inventaire.
        - Depuis Terminé : annulation impossible, la demande est déjà réalisée."""
        for record in self:
            if record.state == 'done':
                raise UserError(_(
                    "Les transferts SORTIE et RÉCEPTION ont déjà été effectués. Cette "
                    "demande ne peut plus être annulée."
                ))
            if record.state == 'cancelled':
                raise UserError(_("Cette demande est déjà annulée."))
            validated = record.picking_ids.filtered(lambda p: p.state == 'done')
            if validated:
                raise UserError(_(
                    "Un transfert (SORTIE ou RÉCEPTION) a déjà été validé (effectué). "
                    "Cette demande ne peut plus être annulée."
                ))
            if record.state == 'in_progress' and not self.env.user.has_group('adk_stock_request.group_adk_stock_request_manager'):
                raise UserError(_("Seul un Manager Demande Stock peut annuler une demande déjà approuvée."))
        for record in self:
            open_pickings = record.picking_ids.filtered(lambda p: p.state != 'done')
            if open_pickings:
                open_pickings.action_cancel()
            record.write({'state': 'cancelled'})

    def action_confirm(self):
        self.ensure_one()
        if not self.env.user.has_group('adk_stock_request.group_adk_stock_request_manager'):
            raise UserError(_("Seul un Manager Demande Stock peut approuver cette demande."))
        if not self.line_ids:
            raise UserError(_("Veuillez ajouter des lignes de demande."))
        
        if self.picking_ids:
            raise UserError(_(
                "Les transferts SORTIE et RÉCEPTION existent déjà pour cette demande. "
                "Une demande de stock ne génère jamais plus de 2 transferts."
            ))
        
        if not self.procurement_group_id:
            group = self.env['procurement.group'].create({'name': self.name})
            self.procurement_group_id = group.id

        # La SORTIE utilise le type « Transfert interne » de l'entrepôt source :
        # seuls les transferts SORTIE doivent apparaître dans cette opération.
        picking_type_out = self.warehouse_id.int_type_id
        if not picking_type_out:
            raise UserError(_("Aucun type de transfert interne pour l'entrepôt source %s.") % self.warehouse_id.name)

        # La RÉCEPTION utilise l'opération « Réceptions » de l'entrepôt de
        # réception (celui de l'emplacement de destination choisi).
        reception_wh = self.location_id.warehouse_id or self.warehouse_id
        picking_type_in = reception_wh.in_type_id
        if not picking_type_in:
            raise UserError(_("Aucun type de réception pour l'entrepôt de réception %s.") % reception_wh.name)

        transit_location = self.env.ref('stock.stock_location_inter_wh', raise_if_not_found=False)

        picking_out = self.env['stock.picking'].create({
            'picking_type_id': picking_type_out.id,
            'location_id': self.warehouse_id.lot_stock_id.id,
            'location_dest_id': (transit_location or self.location_id).id,
            'origin': self.name + ' - SORTIE',
            'group_id': self.procurement_group_id.id,
            'adk_request_id': self.id,
        })

        picking_in = self.env['stock.picking'].create({
            'picking_type_id': picking_type_in.id,
            'location_id': (transit_location or self.location_id).id,
            'location_dest_id': self.location_id.id,
            'origin': self.name + ' - RÉCEPTION',
            'group_id': self.procurement_group_id.id,
            'adk_request_id': self.id,
        })

        for line in self.line_ids:
            self.env['stock.move'].create({
                'name': _("Sortie: %s") % self.name,
                'product_id': line.product_id.id,
                'product_uom_qty': line.qty,
                'product_uom': line.product_uom_id.id,
                'picking_id': picking_out.id,
                'location_id': picking_out.location_id.id,
                'location_dest_id': picking_out.location_dest_id.id,
                'group_id': self.procurement_group_id.id,
            })
            self.env['stock.move'].create({
                'name': _("Réception: %s") % self.name,
                'product_id': line.product_id.id,
                'product_uom_qty': line.qty,
                'product_uom': line.product_uom_id.id,
                'picking_id': picking_in.id,
                'location_id': picking_in.location_id.id,
                'location_dest_id': picking_in.location_dest_id.id,
                'group_id': self.procurement_group_id.id,
            })

        picking_out.action_confirm()
        picking_out.action_assign()
        picking_in.action_confirm()
        
        self.state = 'in_progress'

    def action_view_picking(self):
        return {
            'name': _('Transferts'),
            'type': 'ir.actions.act_window',
            'res_model': 'stock.picking',
            'view_mode': 'list,form',
            'domain': [('adk_request_id', '=', self.id)],
            'context': {'default_adk_request_id': self.id}
        }

    def _open_transfer(self, label):
        self.ensure_one()
        incoming = (label == 'RÉCEPTION')
        pickings = self.picking_ids.filtered(
            lambda p: (p.picking_type_id.code == 'incoming') == incoming and label in (p.origin or ''))
        return {
            'name': _('Transfert %s') % label,
            'type': 'ir.actions.act_window',
            'res_model': 'stock.picking',
            'view_mode': 'list,form',
            'domain': [('id', 'in', pickings.ids)],
        }

    def action_view_sortie(self):
        return self._open_transfer('SORTIE')

    def action_view_reception(self):
        return self._open_transfer('RÉCEPTION')

    def action_view_lines(self):
        return {
            'name': _('Lignes d\'articles'),
            'type': 'ir.actions.act_window',
            'res_model': 'adk.stock.request.line',
            'view_mode': 'list,form',
            'domain': [('order_id', '=', self.id)],
            'context': {'default_order_id': self.id},
        }

class AdkStockRequestLine(models.Model):
    _name = 'adk.stock.request.line'
    _description = 'Ligne de demande'

    order_id = fields.Many2one('adk.stock.request.order', ondelete='cascade')
    request_date = fields.Datetime(related='order_id.request_date', string="Date de la demande", store=True, readonly=True)
    state = fields.Selection(related='order_id.state', string="État de la demande", store=True, readonly=True)
    warehouse_id = fields.Many2one(related='order_id.warehouse_id', string="Entrepôt", store=True, readonly=True)

    product_id = fields.Many2one('product.product', string="Article", required=True)
    product_uom_id = fields.Many2one('uom.uom', string="Unité", related='product_id.uom_id', readonly=True)
    route_id = fields.Many2one('stock.route', string="Route", related='order_id.route_id', store=True, readonly=True)
    qty = fields.Float(string="Quantité demandée", default=1.0, required=True)
    qty_done = fields.Float(compute="_compute_qty_status", compute_sudo=True)
    status = fields.Selection([('draft', 'En cours'), ('done', 'Terminé')], compute="_compute_qty_status", compute_sudo=True)

    sortie_picking_id = fields.Many2one('stock.picking', compute='_compute_pickings', string="Transfert SORTIE", compute_sudo=True, store=True)
    reception_picking_id = fields.Many2one('stock.picking', compute='_compute_pickings', string="Transfert RÉCEPTION", compute_sudo=True, store=True)
    available_qty = fields.Float(compute='_compute_available_qty', string="Disponible en stock", compute_sudo=True)
    sortie_qty_done = fields.Float(compute='_compute_sortie_qty_done', string="Qté sortie", compute_sudo=True, store=True)
    reception_qty_done = fields.Float(compute='_compute_reception_qty_done', string="Qté réceptionnée", compute_sudo=True, store=True)
    sortie_status = fields.Selection([
        ('done', 'Terminé'),
        ('pret', 'Prêt'),
        ('en_attente', "En attente d'approvisionnement"),
    ], compute='_compute_pickings_status', string="État SORTIE", compute_sudo=True, search='_search_sortie_status')
    reception_status = fields.Selection([
        ('done', 'Terminé'),
        ('pret', 'Prêt'),
        ('en_attente', 'En attente de la sortie'),
    ], compute='_compute_pickings_status', string="État RÉCEPTION", compute_sudo=True, search='_search_reception_status')

    @api.depends('order_id.picking_ids')
    def _compute_pickings(self):
        for line in self:
            pickings = line.order_id.picking_ids
            line.sortie_picking_id = pickings.filtered(
                lambda p: p.picking_type_id.code != 'incoming' and 'SORTIE' in (p.origin or ''))[:1]
            line.reception_picking_id = pickings.filtered(
                lambda p: p.picking_type_id.code == 'incoming' and 'RÉCEPTION' in (p.origin or ''))[:1]

    @api.depends('sortie_picking_id', 'reception_picking_id', 'product_id')
    def _compute_available_qty(self):
        for line in self:
            sortie = line.sortie_picking_id
            available = 0.0
            if line.product_id and sortie and sortie.location_id:
                available = self.env['stock.quant']._get_available_quantity(
                    line.product_id, sortie.location_id, strict=True)
            line.available_qty = available

    @api.depends('sortie_picking_id.move_ids.state', 'sortie_picking_id.move_ids.product_id', 'sortie_picking_id.move_ids.quantity', 'product_id')
    def _compute_sortie_qty_done(self):
        for line in self:
            sortie = line.sortie_picking_id
            if sortie:
                done_s = sortie.move_ids.filtered(lambda m: m.product_id == line.product_id and m.state == 'done')
                line.sortie_qty_done = sum(done_s.mapped('quantity'))
            else:
                line.sortie_qty_done = 0.0

    @api.depends('reception_picking_id.move_ids.state', 'reception_picking_id.move_ids.product_id', 'reception_picking_id.move_ids.quantity', 'product_id')
    def _compute_reception_qty_done(self):
        for line in self:
            reception = line.reception_picking_id
            if reception:
                done_r = reception.move_ids.filtered(lambda m: m.product_id == line.product_id and m.state == 'done')
                line.reception_qty_done = sum(done_r.mapped('quantity'))
            else:
                line.reception_qty_done = 0.0

    @api.depends('sortie_picking_id.state', 'reception_picking_id.state', 'qty')
    def _compute_pickings_status(self):
        # SORTIE "Prêt" = le transfert a pu réserver la quantité en stock (état Odoo
        # natif 'assigned'). On se base sur l'état réel du mouvement, pas sur un calcul
        # de quantité disponible à part : ce dernier n'est pas notifié quand le stock
        # change ailleurs et peut afficher un statut périmé.
        # RÉCEPTION ne peut jamais être "Prêt" avant que la SORTIE ne soit Terminée :
        # les deux ne sont jamais avancés en même temps.
        for line in self:
            sortie = line.sortie_picking_id
            reception = line.reception_picking_id
            line.sortie_status = False
            line.reception_status = False
            if sortie:
                if sortie.state == 'done':
                    line.sortie_status = 'done'
                elif sortie.state == 'assigned':
                    line.sortie_status = 'pret'
                else:
                    line.sortie_status = 'en_attente'
            if reception:
                if reception.state == 'done':
                    line.reception_status = 'done'
                elif sortie and sortie.state == 'done':
                    line.reception_status = 'pret'
                else:
                    line.reception_status = 'en_attente'

    def _search_status(self, operator, value, attr):
        if operator not in ('=', '!='):
            raise NotImplementedError(_("Opérateur '%s' non géré pour cet état.") % operator)
        match = (operator == '=')
        lines = self.search([])
        return [('id', 'in', lines.filtered(lambda l: (getattr(l, attr) == value) == match).ids)]

    def _search_sortie_status(self, operator, value):
        return self._search_status(operator, value, 'sortie_status')

    def _search_reception_status(self, operator, value):
        return self._search_status(operator, value, 'reception_status')

    @api.depends('reception_qty_done', 'qty')
    def _compute_qty_status(self):
        # NB : on se base uniquement sur le transfert de RÉCEPTION (reception_qty_done),
        # jamais sur "toutes les pickings dont la destination == emplacement final" :
        # quand l'emplacement de transit inter-entrepôt n'existe pas dans la base, le
        # transfert de SORTIE retombe lui aussi sur cet emplacement final, et les deux
        # mouvements (SORTIE + RÉCEPTION) étaient alors comptés ensemble -> avancement à
        # 200 % au lieu de 100 %.
        for line in self:
            done = line.reception_qty_done
            line.qty_done = done
            line.status = 'done' if line.qty > 0 and done >= line.qty else 'draft'

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    adk_request_id = fields.Many2one('adk.stock.request.order', string="Source ADK", ondelete='set null')

    def button_validate(self):
        # Contrainte de validation séquentielle
        for picking in self:
            if picking.adk_request_id and picking.picking_type_id.code == 'incoming' and 'RÉCEPTION' in (picking.origin or ''):
                picking_out = picking.adk_request_id.picking_ids.filtered(
                    lambda p: p.picking_type_id.code != 'incoming' and 'SORTIE' in (p.origin or ''))
                if picking_out and any(p.state != 'done' for p in picking_out):
                    raise UserError(_("Impossible de valider la RÉCEPTION tant que le transfert de SORTIE n'est pas terminé."))
        
        res = super().button_validate()
        
        for picking in self:
            request = picking.adk_request_id
            if request:
                if all(p.state == 'done' for p in request.picking_ids):
                    request.state = 'done'
                else:
                    request.state = 'in_progress'
        return res
