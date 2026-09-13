{
    'name': 'ADK Demande de Stock Officiel',
    'version': '18.0.9.0',
    'category': 'Demande de Stock',
    'summary': 'Gestion complète des flux de stock ADK avec traçabilité, tableau de bord et rapports intégrés',
    'description': """
ADK Demande de Stock
=====================
Module 100% natif Odoo 18 (stock, mail, uom) pour la gestion des demandes
de mouvement de stock internes, enrichi par ADK avec :

* Un tableau de bord (kanban) avec indicateurs clés
* Des vues d'analyse graphique et pivot
* Un rapport PDF imprimable de la demande de stock
* Une traçabilité complète (chatter, activités, suivi des champs)
""",
    'author': 'KAMBEU HENANG ANGE DUVAL',
    'company': 'ADK',
    'email': 'duvalkambeu61@gmail.com',
    'depends': ['stock', 'mail', 'uom'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'report/stock_request_report.xml',
        # CORRECTION ICI : Ajout de la virgule manquante à la fin de la ligne
        'report/stock_request_report_templates.xml',
        'views/stock_request_analysis_views.xml',
        'views/stock_request_dashboard_views.xml',
        'views/stock_request_article_dashboard_views.xml',
        'views/stock_request_views.xml',
        'views/stock_request_menus.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
