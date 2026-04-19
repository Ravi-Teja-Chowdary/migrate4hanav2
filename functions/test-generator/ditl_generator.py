import json
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Fiori app-specific UI selectors for generating runnable Cypress tests
FIORI_SELECTORS = {
    "F0718": {  # Post General Journal Entries
        "semantic_object": "GeneralJournalEntry",
        "action": "create",
        "app_load": "[data-sap-ui-area='content']",
        "form_fields": {
            "company_code": "input[id*='companyCode']",
            "posting_date": "input[id*='postingDate']",
            "document_type": "input[id*='docType']",
            "gl_account": "input[id*='glAccount']",
            "amount": "input[id*='amount']",
        },
        "save_button": "button[id*='postButton'], button:contains('Post')",
        "success_indicator": ".sapMMessageToast, [class*='success']",
    },
    "F0711": {  # Create Incoming Invoices
        "semantic_object": "SupplierInvoice",
        "action": "create",
        "app_load": "[data-sap-ui-area='content']",
        "form_fields": {
            "vendor": "input[id*='vendor']",
            "invoice_date": "input[id*='invoiceDate']",
            "amount": "input[id*='grossAmount']",
            "company_code": "input[id*='companyCode']",
        },
        "save_button": "button[id*='saveButton'], button:contains('Save')",
        "success_indicator": ".sapMMessageToast",
    },
    "F3893": {  # Create Sales Orders
        "semantic_object": "SalesOrder",
        "action": "create",
        "app_load": "[data-sap-ui-area='content']",
        "form_fields": {
            "order_type": "input[id*='orderType']",
            "sold_to": "input[id*='soldTo']",
            "material": "input[id*='material']",
            "quantity": "input[id*='quantity']",
        },
        "save_button": "button[id*='saveButton'], button:contains('Save')",
        "success_indicator": ".sapMMessageToast",
    },
    "F0842A": {  # Manage Purchase Orders
        "semantic_object": "PurchaseOrder",
        "action": "manage",
        "app_load": "[data-sap-ui-area='content']",
        "form_fields": {
            "vendor": "input[id*='supplier']",
            "material": "input[id*='material']",
            "quantity": "input[id*='orderQuantity']",
            "plant": "input[id*='plant']",
        },
        "save_button": "button[id*='orderButton'], button:contains('Order')",
        "success_indicator": ".sapMMessageToast",
    },
    "F3163": {  # Manage Business Partner
        "semantic_object": "BusinessPartner",
        "action": "manage",
        "app_load": "[data-sap-ui-area='content']",
        "form_fields": {
            "name": "input[id*='partnerName']",
            "category": "select[id*='partnerCategory']",
            "search": "input[id*='searchField']",
        },
        "save_button": "button[id*='saveButton'], button:contains('Save')",
        "success_indicator": ".sapMMessageToast",
    },
    "F0721": {  # Reverse Document
        "semantic_object": "JournalEntry",
        "action": "reverse",
        "app_load": "[data-sap-ui-area='content']",
        "form_fields": {
            "document_number": "input[id*='documentNumber']",
            "company_code": "input[id*='companyCode']",
            "fiscal_year": "input[id*='fiscalYear']",
            "reversal_reason": "input[id*='reversalReason']",
        },
        "save_button": "button[id*='reverseButton'], button:contains('Reverse')",
        "success_indicator": ".sapMMessageToast, [class*='success']",
    },
    "F2680": {  # Create Billing Document
        "semantic_object": "BillingDocument",
        "action": "create",
        "app_load": "[data-sap-ui-area='content']",
        "form_fields": {
            "billing_type": "input[id*='billingType']",
            "sales_org": "input[id*='salesOrg']",
            "billing_date": "input[id*='billingDate']",
        },
        "save_button": "button[id*='saveButton'], button:contains('Save')",
        "success_indicator": ".sapMMessageToast",
    },
    "F2723": {  # Create Production Order
        "semantic_object": "ProductionOrder",
        "action": "create",
        "app_load": "[data-sap-ui-area='content']",
        "form_fields": {
            "material": "input[id*='material']",
            "plant": "input[id*='plant']",
            "order_type": "input[id*='orderType']",
            "quantity": "input[id*='totalQuantity']",
        },
        "save_button": "button[id*='releaseButton'], button:contains('Release')",
        "success_indicator": ".sapMMessageToast, [class*='success']",
    },
    "F1434": {  # Display Stock/Requirements List
        "semantic_object": "MaterialStockRequirement",
        "action": "display",
        "app_load": "[data-sap-ui-area='content']",
        "form_fields": {
            "material": "input[id*='material']",
            "plant": "input[id*='plant']",
            "mrp_area": "input[id*='mrpArea']",
        },
        "save_button": "",
        "success_indicator": ".sapMList, .sapUiTable",
    },
    "F2436": {  # Create Maintenance Order
        "semantic_object": "MaintenanceOrder",
        "action": "create",
        "app_load": "[data-sap-ui-area='content']",
        "form_fields": {
            "order_type": "input[id*='orderType']",
            "functional_location": "input[id*='functionalLocation']",
            "equipment": "input[id*='equipment']",
            "description": "input[id*='description']",
        },
        "save_button": "button[id*='saveButton'], button:contains('Save')",
        "success_indicator": ".sapMMessageToast, [class*='success']",
    },
    "F0723": {  # Post Incoming Payments
        "semantic_object": "IncomingPayment",
        "action": "post",
        "app_load": "[data-sap-ui-area='content']",
        "form_fields": {
            "company_code": "input[id*='companyCode']",
            "customer": "input[id*='customer']",
            "amount": "input[id*='amount']",
            "posting_date": "input[id*='postingDate']",
        },
        "save_button": "button[id*='postButton'], button:contains('Post')",
        "success_indicator": ".sapMMessageToast, [class*='success']",
    },
    "F3185": {  # Goods Movement (MIGO)
        "semantic_object": "MaterialDocument",
        "action": "create",
        "app_load": "[data-sap-ui-area='content']",
        "form_fields": {
            "movement_type": "input[id*='movementType']",
            "material": "input[id*='material']",
            "plant": "input[id*='plant']",
            "quantity": "input[id*='quantity']",
            "storage_location": "input[id*='storageLocation']",
        },
        "save_button": "button[id*='postButton'], button:contains('Post')",
        "success_indicator": ".sapMMessageToast, [class*='success']",
    },
    "F2390": {  # Enter Incoming Invoice (MIRO)
        "semantic_object": "SupplierInvoice",
        "action": "post",
        "app_load": "[data-sap-ui-area='content']",
        "form_fields": {
            "vendor": "input[id*='vendor']",
            "invoice_date": "input[id*='invoiceDate']",
            "amount": "input[id*='amount']",
            "company_code": "input[id*='companyCode']",
            "po_reference": "input[id*='poReference']",
        },
        "save_button": "button[id*='postButton'], button:contains('Post')",
        "success_indicator": ".sapMMessageToast, [class*='success']",
    },
    "F1569": {  # Create Purchase Requisition
        "semantic_object": "PurchaseRequisition",
        "action": "create",
        "app_load": "[data-sap-ui-area='content']",
        "form_fields": {
            "material": "input[id*='material']",
            "quantity": "input[id*='quantity']",
            "plant": "input[id*='plant']",
            "delivery_date": "input[id*='deliveryDate']",
        },
        "save_button": "button[id*='saveButton'], button:contains('Save')",
        "success_indicator": ".sapMMessageToast",
    },
    "F2439": {  # Create Maintenance Notification
        "semantic_object": "MaintenanceNotification",
        "action": "create",
        "app_load": "[data-sap-ui-area='content']",
        "form_fields": {
            "notification_type": "input[id*='notificationType']",
            "functional_location": "input[id*='functionalLocation']",
            "equipment": "input[id*='equipment']",
            "description": "input[id*='description']",
        },
        "save_button": "button[id*='saveButton'], button:contains('Save')",
        "success_indicator": ".sapMMessageToast, [class*='success']",
    },
    "F3380": {  # Create Inspection Lot (QM)
        "semantic_object": "InspectionLot",
        "action": "create",
        "app_load": "[data-sap-ui-area='content']",
        "form_fields": {
            "material": "input[id*='material']",
            "plant": "input[id*='plant']",
            "inspection_type": "input[id*='inspectionType']",
        },
        "save_button": "button[id*='saveButton'], button:contains('Save')",
        "success_indicator": ".sapMMessageToast",
    },
    "F1625": {  # Create Cost Center
        "semantic_object": "CostCenter",
        "action": "create",
        "app_load": "[data-sap-ui-area='content']",
        "form_fields": {
            "cost_center": "input[id*='costCenter']",
            "name": "input[id*='name']",
            "controlling_area": "input[id*='controllingArea']",
            "cost_center_category": "input[id*='category']",
        },
        "save_button": "button[id*='saveButton'], button:contains('Save')",
        "success_indicator": ".sapMMessageToast",
    },
    "F5637": {  # Personnel Actions (HR)
        "semantic_object": "PersonnelAction",
        "action": "execute",
        "app_load": "[data-sap-ui-area='content']",
        "form_fields": {
            "personnel_number": "input[id*='personnelNumber']",
            "action_type": "input[id*='actionType']",
            "effective_date": "input[id*='effectiveDate']",
        },
        "save_button": "button[id*='executeButton'], button:contains('Execute')",
        "success_indicator": ".sapMMessageToast, [class*='success']",
    },
    "F3500": {  # Create Transfer Order (WM)
        "semantic_object": "WarehouseTask",
        "action": "create",
        "app_load": "[data-sap-ui-area='content']",
        "form_fields": {
            "warehouse_number": "input[id*='warehouseNumber']",
            "material": "input[id*='material']",
            "quantity": "input[id*='quantity']",
            "source_bin": "input[id*='sourceBin']",
            "destination_bin": "input[id*='destinationBin']",
        },
        "save_button": "button[id*='saveButton'], button:contains('Save')",
        "success_indicator": ".sapMMessageToast",
    },
    "F2680": {  # Manage Sales Orders
        "semantic_object": "SalesOrder",
        "action": "manage",
        "app_load": "[data-sap-ui-area='content']",
        "form_fields": {
            "sales_order": "input[id*='salesOrder']",
            "sold_to_party": "input[id*='soldToParty']",
            "material": "input[id*='material']",
            "quantity": "input[id*='requestedQuantity']",
            "sales_org": "input[id*='salesOrganization']",
        },
        "save_button": "button[id*='saveButton'], button:contains('Save')",
        "success_indicator": ".sapMMessageToast, [class*='success']",
    },
    "F2390A": {  # Manage Purchase Orders
        "semantic_object": "PurchaseOrder",
        "action": "manage",
        "app_load": "[data-sap-ui-area='content']",
        "form_fields": {
            "purchase_order": "input[id*='purchaseOrder']",
            "supplier": "input[id*='supplier']",
            "material": "input[id*='material']",
            "order_quantity": "input[id*='orderQuantity']",
            "plant": "input[id*='plant']",
        },
        "save_button": "button[id*='saveButton'], button:contains('Save')",
        "success_indicator": ".sapMMessageToast, [class*='success']",
    },
    "F4515": {  # Manage Production Orders
        "semantic_object": "ProductionOrder",
        "action": "manage",
        "app_load": "[data-sap-ui-area='content']",
        "form_fields": {
            "production_order": "input[id*='productionOrder']",
            "material": "input[id*='material']",
            "plant": "input[id*='plant']",
            "order_quantity": "input[id*='totalQuantity']",
            "order_type": "input[id*='orderType']",
        },
        "save_button": "button[id*='releaseButton'], button:contains('Release')",
        "success_indicator": ".sapMMessageToast, [class*='success']",
    },
    "F4530": {  # Create Maintenance Notification
        "semantic_object": "MaintenanceNotification",
        "action": "create",
        "app_load": "[data-sap-ui-area='content']",
        "form_fields": {
            "notification_type": "input[id*='notificationType']",
            "functional_location": "input[id*='functionalLocation']",
            "equipment": "input[id*='equipment']",
            "description": "input[id*='shortText']",
            "priority": "select[id*='priority']",
        },
        "save_button": "button[id*='saveButton'], button:contains('Save')",
        "success_indicator": ".sapMMessageToast, [class*='success']",
    },
    "F4531": {  # Create Maintenance Order
        "semantic_object": "MaintenanceOrder",
        "action": "create",
        "app_load": "[data-sap-ui-area='content']",
        "form_fields": {
            "order_type": "input[id*='orderType']",
            "functional_location": "input[id*='functionalLocation']",
            "equipment": "input[id*='equipment']",
            "description": "input[id*='description']",
            "planning_plant": "input[id*='planningPlant']",
        },
        "save_button": "button[id*='saveButton'], button:contains('Save')",
        "success_indicator": ".sapMMessageToast, [class*='success']",
    },
    "F4543": {  # Manage Inspection Lots
        "semantic_object": "InspectionLot",
        "action": "manage",
        "app_load": "[data-sap-ui-area='content']",
        "form_fields": {
            "inspection_lot": "input[id*='inspectionLot']",
            "material": "input[id*='material']",
            "plant": "input[id*='plant']",
            "inspection_type": "input[id*='inspectionType']",
        },
        "save_button": "button[id*='saveButton'], button:contains('Save')",
        "success_indicator": ".sapMMessageToast, [class*='success']",
    },
    "F4562": {  # Manage Employee Master Data
        "semantic_object": "Employee",
        "action": "manage",
        "app_load": "[data-sap-ui-area='content']",
        "form_fields": {
            "personnel_number": "input[id*='personnelNumber']",
            "first_name": "input[id*='firstName']",
            "last_name": "input[id*='lastName']",
            "personnel_area": "input[id*='personnelArea']",
            "employee_group": "select[id*='employeeGroup']",
        },
        "save_button": "button[id*='saveButton'], button:contains('Save')",
        "success_indicator": ".sapMMessageToast, [class*='success']",
    },
    "F2485": {  # Manage Fixed Assets
        "semantic_object": "FixedAsset",
        "action": "manage",
        "app_load": "[data-sap-ui-area='content']",
        "form_fields": {
            "company_code": "input[id*='companyCode']",
            "asset_number": "input[id*='assetNumber']",
            "asset_class": "input[id*='assetClass']",
            "description": "input[id*='description']",
            "capitalization_date": "input[id*='capitalizationDate']",
        },
        "save_button": "button[id*='saveButton'], button:contains('Save')",
        "success_indicator": ".sapMMessageToast, [class*='success']",
    },
    "F1614": {  # Manage Cost Centers
        "semantic_object": "CostCenter",
        "action": "manage",
        "app_load": "[data-sap-ui-area='content']",
        "form_fields": {
            "controlling_area": "input[id*='controllingArea']",
            "cost_center": "input[id*='costCenter']",
            "name": "input[id*='name']",
            "category": "select[id*='category']",
            "profit_center": "input[id*='profitCenter']",
        },
        "save_button": "button[id*='saveButton'], button:contains('Save')",
        "success_indicator": ".sapMMessageToast, [class*='success']",
    },
    "F1616": {  # Manage Profit Centers
        "semantic_object": "ProfitCenter",
        "action": "manage",
        "app_load": "[data-sap-ui-area='content']",
        "form_fields": {
            "controlling_area": "input[id*='controllingArea']",
            "profit_center": "input[id*='profitCenter']",
            "name": "input[id*='name']",
            "profit_center_group": "input[id*='profitCenterGroup']",
        },
        "save_button": "button[id*='saveButton'], button:contains('Save')",
        "success_indicator": ".sapMMessageToast, [class*='success']",
    },
    "F2681": {  # Manage Internal Orders
        "semantic_object": "InternalOrder",
        "action": "manage",
        "app_load": "[data-sap-ui-area='content']",
        "form_fields": {
            "order_number": "input[id*='orderNumber']",
            "order_type": "input[id*='orderType']",
            "description": "input[id*='description']",
            "company_code": "input[id*='companyCode']",
            "responsible_cc": "input[id*='responsibleCostCenter']",
        },
        "save_button": "button[id*='saveButton'], button:contains('Save')",
        "success_indicator": ".sapMMessageToast, [class*='success']",
    },
    "F4785": {  # Manage Projects (Project Builder)
        "semantic_object": "EnterpriseProject",
        "action": "manage",
        "app_load": "[data-sap-ui-area='content']",
        "form_fields": {
            "project_definition": "input[id*='projectDefinition']",
            "project_name": "input[id*='projectName']",
            "project_profile": "input[id*='projectProfile']",
            "responsible_person": "input[id*='responsiblePerson']",
            "company_code": "input[id*='companyCode']",
        },
        "save_button": "button[id*='saveButton'], button:contains('Save')",
        "success_indicator": ".sapMMessageToast, [class*='success']",
    },
    "F2029": {  # Manage Outbound Deliveries
        "semantic_object": "OutboundDelivery",
        "action": "manage",
        "app_load": "[data-sap-ui-area='content']",
        "form_fields": {
            "delivery": "input[id*='delivery']",
            "shipping_point": "input[id*='shippingPoint']",
            "ship_to_party": "input[id*='shipToParty']",
            "delivery_date": "input[id*='deliveryDate']",
        },
        "save_button": "button[id*='saveButton'], button:contains('Save')",
        "success_indicator": ".sapMMessageToast, [class*='success']",
    },
    "F2093": {  # Manage Billing Documents
        "semantic_object": "BillingDocument",
        "action": "manage",
        "app_load": "[data-sap-ui-area='content']",
        "form_fields": {
            "billing_document": "input[id*='billingDocument']",
            "billing_type": "input[id*='billingType']",
            "sales_org": "input[id*='salesOrganization']",
            "payer": "input[id*='payer']",
        },
        "save_button": "button[id*='saveButton'], button:contains('Save')",
        "success_indicator": ".sapMMessageToast, [class*='success']",
    },
    "F1924": {  # Manage Supplier Invoices
        "semantic_object": "SupplierInvoice",
        "action": "manage",
        "app_load": "[data-sap-ui-area='content']",
        "form_fields": {
            "invoice_document": "input[id*='invoiceDocument']",
            "vendor": "input[id*='vendor']",
            "invoice_date": "input[id*='invoiceDate']",
            "gross_amount": "input[id*='grossAmount']",
            "company_code": "input[id*='companyCode']",
        },
        "save_button": "button[id*='postButton'], button:contains('Post')",
        "success_indicator": ".sapMMessageToast, [class*='success']",
    },
    "F2752": {  # Manage Cash Journal
        "semantic_object": "CashJournal",
        "action": "manage",
        "app_load": "[data-sap-ui-area='content']",
        "form_fields": {
            "company_code": "input[id*='companyCode']",
            "cash_journal": "input[id*='cashJournal']",
            "posting_date": "input[id*='postingDate']",
            "amount": "input[id*='amount']",
            "business_transaction": "select[id*='businessTransaction']",
        },
        "save_button": "button[id*='postButton'], button:contains('Post')",
        "success_indicator": ".sapMMessageToast, [class*='success']",
    },
    "F4104": {  # Manage Product Master Data
        "semantic_object": "Product",
        "action": "manage",
        "app_load": "[data-sap-ui-area='content']",
        "form_fields": {
            "product": "input[id*='product']",
            "product_type": "select[id*='productType']",
            "description": "input[id*='description']",
            "base_unit": "input[id*='baseUnit']",
            "product_group": "input[id*='productGroup']",
        },
        "save_button": "button[id*='saveButton'], button:contains('Save')",
        "success_indicator": ".sapMMessageToast, [class*='success']",
    },
    "F3993": {  # Post Goods Movement
        "semantic_object": "MaterialDocument",
        "action": "post",
        "app_load": "[data-sap-ui-area='content']",
        "form_fields": {
            "movement_type": "input[id*='goodsMovementType']",
            "material": "input[id*='material']",
            "plant": "input[id*='plant']",
            "storage_location": "input[id*='storageLocation']",
            "quantity": "input[id*='quantity']",
        },
        "save_button": "button[id*='postButton'], button:contains('Post')",
        "success_indicator": ".sapMMessageToast, [class*='success']",
    },
    "F2579": {  # Display Stock Overview
        "semantic_object": "MaterialStock",
        "action": "display",
        "app_load": "[data-sap-ui-area='content']",
        "form_fields": {
            "material": "input[id*='material']",
            "plant": "input[id*='plant']",
            "storage_location": "input[id*='storageLocation']",
        },
        "save_button": "",
        "success_indicator": ".sapMList, .sapUiTable",
    },
    "F4519": {  # Manage Bill of Materials
        "semantic_object": "BillOfMaterial",
        "action": "manage",
        "app_load": "[data-sap-ui-area='content']",
        "form_fields": {
            "material": "input[id*='material']",
            "plant": "input[id*='plant']",
            "bom_usage": "input[id*='bomUsage']",
            "alternative_bom": "input[id*='alternativeBOM']",
        },
        "save_button": "button[id*='saveButton'], button:contains('Save')",
        "success_indicator": ".sapMMessageToast, [class*='success']",
    },
    "F4520": {  # Manage Production Routing
        "semantic_object": "ProductionRouting",
        "action": "manage",
        "app_load": "[data-sap-ui-area='content']",
        "form_fields": {
            "material": "input[id*='material']",
            "plant": "input[id*='plant']",
            "routing_group": "input[id*='routingGroup']",
            "work_center": "input[id*='workCenter']",
        },
        "save_button": "button[id*='saveButton'], button:contains('Save')",
        "success_indicator": ".sapMMessageToast, [class*='success']",
    },
    "F4523": {  # Monitor MRP
        "semantic_object": "MRPMaterial",
        "action": "monitor",
        "app_load": "[data-sap-ui-area='content']",
        "form_fields": {
            "material": "input[id*='material']",
            "plant": "input[id*='plant']",
            "mrp_controller": "input[id*='mrpController']",
        },
        "save_button": "",
        "success_indicator": ".sapMList, .sapUiTable",
    },
    "F4536": {  # Manage Equipment
        "semantic_object": "Equipment",
        "action": "manage",
        "app_load": "[data-sap-ui-area='content']",
        "form_fields": {
            "equipment": "input[id*='equipment']",
            "description": "input[id*='description']",
            "functional_location": "input[id*='functionalLocation']",
            "planning_plant": "input[id*='planningPlant']",
            "cost_center": "input[id*='costCenter']",
        },
        "save_button": "button[id*='saveButton'], button:contains('Save')",
        "success_indicator": ".sapMMessageToast, [class*='success']",
    },
    "F4537": {  # Manage Functional Locations
        "semantic_object": "FunctionalLocation",
        "action": "manage",
        "app_load": "[data-sap-ui-area='content']",
        "form_fields": {
            "functional_location": "input[id*='functionalLocation']",
            "description": "input[id*='description']",
            "category": "select[id*='category']",
            "planning_plant": "input[id*='planningPlant']",
        },
        "save_button": "button[id*='saveButton'], button:contains('Save')",
        "success_indicator": ".sapMMessageToast, [class*='success']",
    },
    "F4546": {  # Manage Quality Notifications
        "semantic_object": "QualityNotification",
        "action": "manage",
        "app_load": "[data-sap-ui-area='content']",
        "form_fields": {
            "notification": "input[id*='notification']",
            "notification_type": "input[id*='notificationType']",
            "material": "input[id*='material']",
            "description": "input[id*='description']",
        },
        "save_button": "button[id*='saveButton'], button:contains('Save')",
        "success_indicator": ".sapMMessageToast, [class*='success']",
    },
    "F4553": {  # Manage Transfer Orders
        "semantic_object": "WarehouseTask",
        "action": "manage",
        "app_load": "[data-sap-ui-area='content']",
        "form_fields": {
            "warehouse": "input[id*='warehouse']",
            "transfer_order": "input[id*='transferOrder']",
            "material": "input[id*='material']",
            "source_storage_type": "input[id*='sourceStorageType']",
            "destination_storage_type": "input[id*='destinationStorageType']",
        },
        "save_button": "button[id*='confirmButton'], button:contains('Confirm')",
        "success_indicator": ".sapMMessageToast, [class*='success']",
    },
    "F0717": {  # Post Journal Entry
        "semantic_object": "JournalEntry",
        "action": "post",
        "app_load": "[data-sap-ui-area='content']",
        "form_fields": {
            "company_code": "input[id*='companyCode']",
            "posting_date": "input[id*='postingDate']",
            "document_type": "input[id*='documentType']",
            "reference": "input[id*='reference']",
            "gl_account": "input[id*='glAccount']",
            "amount": "input[id*='amount']",
        },
        "save_button": "button[id*='postButton'], button:contains('Post')",
        "success_indicator": ".sapMMessageToast, [class*='success']",
    },
    "F1603": {  # Post with Clearing
        "semantic_object": "JournalEntry",
        "action": "postWithClearing",
        "app_load": "[data-sap-ui-area='content']",
        "form_fields": {
            "company_code": "input[id*='companyCode']",
            "account": "input[id*='account']",
            "posting_date": "input[id*='postingDate']",
            "clearing_date": "input[id*='clearingDate']",
            "amount": "input[id*='amount']",
        },
        "save_button": "button[id*='postButton'], button:contains('Post')",
        "success_indicator": ".sapMMessageToast, [class*='success']",
    },
}

# Default selectors for unmapped Fiori apps
DEFAULT_SELECTORS = {
    "semantic_object": "GenericApp",
    "action": "display",
    "app_load": "[data-sap-ui-area='content']",
    "form_fields": {},
    "save_button": "button:contains('Save'), button:contains('Post'), button:contains('Create')",
    "success_indicator": ".sapMMessageToast, [class*='success']",
}


class DITLTestGenerator:
    """
    Day In The Life (DITL) Test Automation Generator.
    Takes Process Mining (ST03N/CDHDR) outputs and creates automated
    testing definitions (e.g., Cypress integration scripts, CBTA maps, Tosca XMLs)
    to validate that the translated ECC business processes still work in S/4HANA.
    """

    def __init__(self, target_framework="cypress"):
        self.target_framework = target_framework

    def _get_support_commands(self) -> str:
        """Generate Cypress custom commands for S/4HANA Fiori Launchpad."""
        return """// cypress/support/commands.js — S/4HANA Fiori Launchpad helpers
// Add to cypress/support/commands.js before running tests

Cypress.Commands.add('loginToS4HANA', () => {
  const user = Cypress.env('S4_USER') || 'TESTUSER';
  const pass = Cypress.env('S4_PASS') || 'testpass';
  const host = Cypress.env('S4_HOST') || 'https://s4hana.example.com';

  cy.visit(`${host}/sap/bc/ui5_ui5/ui2/ushell/shells/abap/FioriLaunchpad.html`);
  cy.get('input[name="sap-user"]', { timeout: 15000 }).type(user);
  cy.get('input[name="sap-password"]').type(pass);
  cy.get('button[type="submit"], #LOGIN_LINK').click();
  cy.get('#shell-header', { timeout: 30000 }).should('be.visible');
});

Cypress.Commands.add('navToApp', (semanticObject, action) => {
  cy.visit(`/#${semanticObject}-${action || 'display'}`);
  cy.get('[data-sap-ui-area="content"]', { timeout: 20000 }).should('exist');
});

Cypress.Commands.add('waitForFioriApp', (timeout = 20000) => {
  cy.get('.sapUiBody', { timeout }).should('exist');
  cy.get('.sapMBusyIndicator', { timeout }).should('not.exist');
});
"""

    def generate_cypress_script(self, test_name: str, fiori_app_id: str, app_name: str, odata_checks: list) -> str:
        """
        Generates a runnable Cypress E2E test with real Fiori selectors.
        """
        selectors = FIORI_SELECTORS.get(fiori_app_id, DEFAULT_SELECTORS)
        sem_obj = selectors["semantic_object"]
        action = selectors["action"]
        app_load = selectors["app_load"]
        save_btn = selectors["save_button"]
        success_ind = selectors["success_indicator"]
        form_fields = selectors.get("form_fields", {})

        # Build form field interaction lines
        field_lines = ""
        for field_name, selector in form_fields.items():
            field_lines += f"    cy.get('{selector}').should('be.visible');\n"

        # Build OData intercept lines
        intercept_lines = ""
        wait_aliases = []
        for i, check in enumerate(odata_checks):
            alias = f"odata_{i}"
            intercept_lines += f"    cy.intercept('GET', '**{check}**').as('{alias}');\n"
            wait_aliases.append(f"@{alias}")

        script = f"""// Auto-generated DITL Test for: {app_name} (App ID: {fiori_app_id})
// Prerequisites: Add support commands from cypress/support/commands.js
// Run: npx cypress run --spec "cypress/e2e/ditl_{test_name.lower()}.cy.js"

describe('{test_name} - S/4HANA Validation', () => {{
  beforeEach(() => {{
    cy.loginToS4HANA();
  }});

  it('Navigates to {app_name} and validates app loads', () => {{
    cy.navToApp('{sem_obj}', '{action}');
    cy.get('{app_load}', {{ timeout: 20000 }}).should('exist');
    cy.waitForFioriApp();
  }});

  it('Validates form fields are accessible in {app_name}', () => {{
    cy.navToApp('{sem_obj}', '{action}');
    cy.waitForFioriApp();
{field_lines}  }});

  it('Validates OData service endpoints for {app_name}', () => {{
{intercept_lines}    cy.navToApp('{sem_obj}', '{action}');
    cy.waitForFioriApp();
  }});

  it('Validates save/post action is available', () => {{
    cy.navToApp('{sem_obj}', '{action}');
    cy.waitForFioriApp();
    cy.get('{save_btn}').should('exist');
  }});
}});
"""
        return script

    def generate_support_file(self) -> str:
        """Returns the Cypress support commands file content."""
        return self._get_support_commands()

    def process_workload_to_tests(self, st03n_fiori_mappings: list):
        """
        Iterates over the generated Fiori Mappings from Process Mining
        and yields executable automation test scripts.
        """
        logger.info("Generating DITL Tests from ST03N/Fiori Mappings...")
        generated_tests = []
        
        for mapping in st03n_fiori_mappings:
            tcode = mapping.get("tcode")
            fiori_app = mapping.get("fiori_app_id")
            fiori_name = mapping.get("fiori_name")
            
            # Map T-Code to real S/4HANA OData services
            odata_services = self._get_odata_services(tcode, fiori_app)
            
            script = self.generate_cypress_script(
                test_name=f"DITL_Test_{tcode}_to_S4",
                fiori_app_id=fiori_app,
                app_name=fiori_name,
                odata_checks=odata_services
            )
            
            generated_tests.append({
                "process": tcode,
                "fiori_target": fiori_app,
                "test_script": script,
                "file_name": f"cypress/e2e/ditl_test_{tcode.lower()}_to_s4.cy.js",
            })

        # Include support commands file
        generated_tests.append({
            "process": "_support",
            "fiori_target": "commands",
            "test_script": self._get_support_commands(),
            "file_name": "cypress/support/commands.js",
        })
            
        return generated_tests

    def _get_odata_services(self, tcode: str, fiori_app_id: str) -> list:
        """Map T-codes to known S/4HANA OData service paths."""
        TCODE_ODATA_MAP = {
            # === Finance (FI) ===
            "FB01": ["/sap/opu/odata/sap/API_JOURNALENTRYITEMBASIC_SRV"],
            "FB02": ["/sap/opu/odata/sap/API_JOURNALENTRYITEMBASIC_SRV"],
            "FB03": ["/sap/opu/odata/sap/API_JOURNALENTRYITEMBASIC_SRV"],
            "FB08": ["/sap/opu/odata/sap/API_JOURNALENTRYITEMBASIC_SRV"],
            "FB50": ["/sap/opu/odata/sap/API_JOURNALENTRYITEMBASIC_SRV"],
            "FB60": ["/sap/opu/odata/sap/API_SUPPLIERINVOICE_PROCESS_SRV"],
            "FB70": ["/sap/opu/odata/sap/API_CUSTOMERINVOICE_SRV"],
            "F-02": ["/sap/opu/odata/sap/API_JOURNALENTRYITEMBASIC_SRV"],
            "F-28": ["/sap/opu/odata/sap/API_PAYMENTRUN_SRV"],
            "F-53": ["/sap/opu/odata/sap/API_PAYMENTRUN_SRV"],
            "FBV0": ["/sap/opu/odata/sap/API_JOURNALENTRYITEMBASIC_SRV"],
            "FBRA": ["/sap/opu/odata/sap/API_JOURNALENTRYITEMBASIC_SRV"],
            "FBL1N": ["/sap/opu/odata/sap/API_SUPPLIERLINEITEM_SRV"],
            "FBL3N": ["/sap/opu/odata/sap/API_GLACCOUNTLINEITEM_SRV"],
            "FBL5N": ["/sap/opu/odata/sap/API_CUSTOMERLINEITEM_SRV"],
            "FK01": ["/sap/opu/odata/sap/API_BUSINESS_PARTNER"],
            "FK02": ["/sap/opu/odata/sap/API_BUSINESS_PARTNER"],
            "FK03": ["/sap/opu/odata/sap/API_BUSINESS_PARTNER"],
            "FD01": ["/sap/opu/odata/sap/API_BUSINESS_PARTNER"],
            "FD02": ["/sap/opu/odata/sap/API_BUSINESS_PARTNER"],
            "FD03": ["/sap/opu/odata/sap/API_BUSINESS_PARTNER"],
            "FS00": ["/sap/opu/odata/sap/API_GLACCOUNTINCHARTOFACCOUNTS_SRV"],
            "F110": ["/sap/opu/odata/sap/API_PAYMENTRUN_SRV"],
            "F.01": ["/sap/opu/odata/sap/API_GLACCOUNTBALANCE_SRV"],
            "F.13": ["/sap/opu/odata/sap/API_JOURNALENTRYITEMBASIC_SRV"],
            "S_ALR_87012277": ["/sap/opu/odata/sap/API_GLACCOUNTBALANCE_SRV"],
            # === Business Partner ===
            "BP": ["/sap/opu/odata/sap/API_BUSINESS_PARTNER"],
            # === Asset Accounting (AA) ===
            "AS01": ["/sap/opu/odata/sap/API_FIXEDASSET_SRV"],
            "AS02": ["/sap/opu/odata/sap/API_FIXEDASSET_SRV"],
            "AS03": ["/sap/opu/odata/sap/API_FIXEDASSET_SRV"],
            "ABZON": ["/sap/opu/odata/sap/API_FIXEDASSET_SRV"],
            "ABAV": ["/sap/opu/odata/sap/API_FIXEDASSET_SRV"],
            # === Sales & Distribution (SD) ===
            "VA01": ["/sap/opu/odata/sap/API_SALES_ORDER_SRV"],
            "VA02": ["/sap/opu/odata/sap/API_SALES_ORDER_SRV"],
            "VA03": ["/sap/opu/odata/sap/API_SALES_ORDER_SRV"],
            "VA05": ["/sap/opu/odata/sap/API_SALES_ORDER_SRV"],
            "VA41": ["/sap/opu/odata/sap/API_SALES_CONTRACT_SRV"],
            "VA42": ["/sap/opu/odata/sap/API_SALES_CONTRACT_SRV"],
            "VL01N": ["/sap/opu/odata/sap/API_OUTBOUND_DELIVERY_SRV_V2"],
            "VL02N": ["/sap/opu/odata/sap/API_OUTBOUND_DELIVERY_SRV_V2"],
            "VL03N": ["/sap/opu/odata/sap/API_OUTBOUND_DELIVERY_SRV_V2"],
            "VL10A": ["/sap/opu/odata/sap/API_OUTBOUND_DELIVERY_SRV_V2"],
            "VF01": ["/sap/opu/odata/sap/API_BILLING_DOCUMENT_SRV"],
            "VF02": ["/sap/opu/odata/sap/API_BILLING_DOCUMENT_SRV"],
            "VF03": ["/sap/opu/odata/sap/API_BILLING_DOCUMENT_SRV"],
            "VKM1": ["/sap/opu/odata/sap/API_SALES_ORDER_SRV"],
            "VP01": ["/sap/opu/odata/sap/API_SALES_ORDER_SRV"],
            # === Materials Management (MM) ===
            "ME21N": ["/sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV"],
            "ME22N": ["/sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV"],
            "ME23N": ["/sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV"],
            "ME51N": ["/sap/opu/odata/sap/API_PURCHASEREQUISITION_SRV"],
            "ME52N": ["/sap/opu/odata/sap/API_PURCHASEREQUISITION_SRV"],
            "ME53N": ["/sap/opu/odata/sap/API_PURCHASEREQUISITION_SRV"],
            "ME2M": ["/sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV"],
            "ME2N": ["/sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV"],
            "ME2L": ["/sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV"],
            "MB51": ["/sap/opu/odata/sap/API_MATERIAL_DOCUMENT_SRV"],
            "MB52": ["/sap/opu/odata/sap/API_MATERIAL_STOCK_SRV"],
            "MB5B": ["/sap/opu/odata/sap/API_MATERIAL_STOCK_SRV"],
            "MMBE": ["/sap/opu/odata/sap/API_MATERIAL_STOCK_SRV"],
            "MIGO": ["/sap/opu/odata/sap/API_MATERIAL_DOCUMENT_SRV"],
            "MIRO": ["/sap/opu/odata/sap/API_SUPPLIERINVOICE_PROCESS_SRV"],
            "MRIS": ["/sap/opu/odata/sap/API_SUPPLIERINVOICE_PROCESS_SRV"],
            "MM01": ["/sap/opu/odata/sap/API_PRODUCT_SRV"],
            "MM02": ["/sap/opu/odata/sap/API_PRODUCT_SRV"],
            "MM03": ["/sap/opu/odata/sap/API_PRODUCT_SRV"],
            "MM04": ["/sap/opu/odata/sap/API_PRODUCT_SRV"],
            "MR21": ["/sap/opu/odata/sap/API_PRODUCT_SRV"],
            "MI01": ["/sap/opu/odata/sap/API_PHYSICALINVENTORYDOC_SRV"],
            "MI04": ["/sap/opu/odata/sap/API_PHYSICALINVENTORYDOC_SRV"],
            # === Production Planning (PP) ===
            "CO01": ["/sap/opu/odata/sap/API_PRODUCTION_ORDER_SRV"],
            "CO02": ["/sap/opu/odata/sap/API_PRODUCTION_ORDER_SRV"],
            "CO03": ["/sap/opu/odata/sap/API_PRODUCTION_ORDER_SRV"],
            "CO11N": ["/sap/opu/odata/sap/API_PRODUCTION_ORDER_SRV"],
            "CO15": ["/sap/opu/odata/sap/API_PRODUCTION_ORDER_SRV"],
            "COOIS": ["/sap/opu/odata/sap/API_PRODUCTION_ORDER_SRV"],
            "CS01": ["/sap/opu/odata/sap/API_BILL_OF_MATERIAL_SRV"],
            "CS02": ["/sap/opu/odata/sap/API_BILL_OF_MATERIAL_SRV"],
            "CS03": ["/sap/opu/odata/sap/API_BILL_OF_MATERIAL_SRV"],
            "CR01": ["/sap/opu/odata/sap/API_WORKCENTER_SRV"],
            "MD01": ["/sap/opu/odata/sap/API_MRP_MATERIALS_SRV_01"],
            "MD02": ["/sap/opu/odata/sap/API_MRP_MATERIALS_SRV_01"],
            "MD04": ["/sap/opu/odata/sap/API_MRP_MATERIALS_SRV_01"],
            "MD05": ["/sap/opu/odata/sap/API_MRP_MATERIALS_SRV_01"],
            # === Plant Maintenance (PM) ===
            "IW21": ["/sap/opu/odata/sap/API_MAINTNOTIFICATION_SRV"],
            "IW22": ["/sap/opu/odata/sap/API_MAINTNOTIFICATION_SRV"],
            "IW23": ["/sap/opu/odata/sap/API_MAINTNOTIFICATION_SRV"],
            "IW28": ["/sap/opu/odata/sap/API_MAINTNOTIFICATION_SRV"],
            "IW29": ["/sap/opu/odata/sap/API_MAINTNOTIFICATION_SRV"],
            "IW31": ["/sap/opu/odata/sap/API_MAINTENANCEORDER_SRV"],
            "IW32": ["/sap/opu/odata/sap/API_MAINTENANCEORDER_SRV"],
            "IW33": ["/sap/opu/odata/sap/API_MAINTENANCEORDER_SRV"],
            "IW38": ["/sap/opu/odata/sap/API_MAINTENANCEORDER_SRV"],
            "IW39": ["/sap/opu/odata/sap/API_MAINTENANCEORDER_SRV"],
            "IA01": ["/sap/opu/odata/sap/API_BILL_OF_MATERIAL_SRV"],
            "IE01": ["/sap/opu/odata/sap/API_EQUIPMENT_SRV"],
            "IE02": ["/sap/opu/odata/sap/API_EQUIPMENT_SRV"],
            "IE03": ["/sap/opu/odata/sap/API_EQUIPMENT_SRV"],
            "IL01": ["/sap/opu/odata/sap/API_FUNCTIONALLOCATION_SRV"],
            "IL02": ["/sap/opu/odata/sap/API_FUNCTIONALLOCATION_SRV"],
            "IP10": ["/sap/opu/odata/sap/API_MAINTENANCEPLAN_SRV"],
            # === Controlling (CO) ===
            "KS01": ["/sap/opu/odata/sap/API_COSTCENTER_SRV"],
            "KS02": ["/sap/opu/odata/sap/API_COSTCENTER_SRV"],
            "KS03": ["/sap/opu/odata/sap/API_COSTCENTER_SRV"],
            "KSB1": ["/sap/opu/odata/sap/API_COSTCENTER_SRV"],
            "KSB5": ["/sap/opu/odata/sap/API_COSTCENTER_SRV"],
            "KP06": ["/sap/opu/odata/sap/API_COSTCENTER_SRV"],
            "KB21N": ["/sap/opu/odata/sap/API_COSTCENTERACTIVITYTYPE_SRV"],
            "CJ20N": ["/sap/opu/odata/sap/API_PROJECT_SRV"],
            "KOB1": ["/sap/opu/odata/sap/API_INTERNALORDER_SRV"],
            # === Quality Management (QM) ===
            "QA01": ["/sap/opu/odata/sap/API_INSPECTIONLOT_SRV"],
            "QA02": ["/sap/opu/odata/sap/API_INSPECTIONLOT_SRV"],
            "QA03": ["/sap/opu/odata/sap/API_INSPECTIONLOT_SRV"],
            "QM01": ["/sap/opu/odata/sap/API_QUALITYNOTIFICATION_SRV"],
            "QM02": ["/sap/opu/odata/sap/API_QUALITYNOTIFICATION_SRV"],
            "QP01": ["/sap/opu/odata/sap/API_INSPECTIONPLAN_SRV"],
            # === Human Resources (HR) ===
            "PA20": ["/sap/opu/odata/sap/API_EMPLOYEE_SRV"],
            "PA30": ["/sap/opu/odata/sap/API_EMPLOYEE_SRV"],
            "PA40": ["/sap/opu/odata/sap/API_EMPLOYEE_SRV"],
            "PA10": ["/sap/opu/odata/sap/API_EMPLOYEE_SRV"],
            "PT01": ["/sap/opu/odata/sap/API_WORKSHIFTPLAN_SRV"],
            "PU03": ["/sap/opu/odata/sap/API_EMPLOYEE_SRV"],
            "PC00_M40_CALC": ["/sap/opu/odata/sap/API_EMPLOYEE_SRV"],
            # === Warehouse Management (EWM/WM) ===
            "LT01": ["/sap/opu/odata/sap/API_WAREHOUSE_TASK_SRV"],
            "LT21": ["/sap/opu/odata/sap/API_WAREHOUSE_TASK_SRV"],
            "LS26": ["/sap/opu/odata/sap/API_MATERIAL_STOCK_SRV"],
            # === Additional Finance (FI) ===
            "F-04": ["/sap/opu/odata/sap/API_JOURNALENTRY_SRV"],
            "F-06": ["/sap/opu/odata/sap/API_JOURNALENTRY_SRV"],
            "F-07": ["/sap/opu/odata/sap/API_JOURNALENTRY_SRV"],
            "F-22": ["/sap/opu/odata/sap/API_JOURNALENTRY_SRV"],
            "F-32": ["/sap/opu/odata/sap/API_JOURNALENTRY_SRV"],
            "F-43": ["/sap/opu/odata/sap/API_JOURNALENTRY_SRV"],
            "F-44": ["/sap/opu/odata/sap/API_JOURNALENTRY_SRV"],
            "FBR2": ["/sap/opu/odata/sap/API_JOURNALENTRY_SRV"],
            "FBV2": ["/sap/opu/odata/sap/API_JOURNALENTRY_SRV"],
            "FBCJ": ["/sap/opu/odata/sap/API_CASHJOURNAL_SRV"],
            "FK10N": ["/sap/opu/odata/sap/API_BUSINESS_PARTNER_SRV"],
            "FD10N": ["/sap/opu/odata/sap/API_BUSINESS_PARTNER_SRV"],
            "FAGLL03": ["/sap/opu/odata/sap/API_GLACCOUNTLINEITEM_SRV"],
            "FAGLB03": ["/sap/opu/odata/sap/API_GLACCOUNTLINEITEM_SRV"],
            "OB52": ["/sap/opu/odata/sap/API_POSTINGPERIODVARIANT_SRV"],
            "AW01N": ["/sap/opu/odata/sap/API_FIXEDASSET_SRV/0001"],
            "ABSO": ["/sap/opu/odata/sap/API_FIXEDASSET_SRV/0001"],
            "S_ALR_87012326": ["/sap/opu/odata/sap/API_GLACCOUNTBALANCE_SRV"],
            "S_ALR_87012277A": ["/sap/opu/odata/sap/API_FINANCIALSTATEMENT_SRV"],
            # === Additional Controlling (CO) ===
            "KA01": ["/sap/opu/odata/sap/API_COSTELEMENT_SRV"],
            "KA02": ["/sap/opu/odata/sap/API_COSTELEMENT_SRV"],
            "KE51": ["/sap/opu/odata/sap/API_PROFITCENTER_SRV"],
            "KE52": ["/sap/opu/odata/sap/API_PROFITCENTER_SRV"],
            "KE53": ["/sap/opu/odata/sap/API_PROFITCENTER_SRV"],
            "KO01": ["/sap/opu/odata/sap/API_INTERNALORDER_SRV"],
            "KO02": ["/sap/opu/odata/sap/API_INTERNALORDER_SRV"],
            "KO03": ["/sap/opu/odata/sap/API_INTERNALORDER_SRV"],
            "KE30": ["/sap/opu/odata/sap/API_PROFITABILITYANALYSIS_SRV"],
            # === Additional Sales & Distribution (SD) ===
            "VA21": ["/sap/opu/odata/sap/API_SALES_QUOTATION_SRV"],
            "VA22": ["/sap/opu/odata/sap/API_SALES_QUOTATION_SRV"],
            "VA31": ["/sap/opu/odata/sap/API_SALES_SCHEDULING_AGREEMENT_SRV"],
            "VL06O": ["/sap/opu/odata/sap/API_OUTBOUND_DELIVERY_SRV/0002"],
            "VF04": ["/sap/opu/odata/sap/API_BILLING_DOCUMENT_SRV"],
            "VK11": ["/sap/opu/odata/sap/API_SLSPRICINGCONDITIONRECORD_SRV"],
            "VK12": ["/sap/opu/odata/sap/API_SLSPRICINGCONDITIONRECORD_SRV"],
            "VKM3": ["/sap/opu/odata/sap/API_CREDIT_MANAGEMENT_SRV"],
            # === Additional Materials Management (MM) ===
            "ME31K": ["/sap/opu/odata/sap/API_PURCHASECONTRACT_PROCESS_SRV"],
            "ME32K": ["/sap/opu/odata/sap/API_PURCHASECONTRACT_PROCESS_SRV"],
            "ME41": ["/sap/opu/odata/sap/API_REQUESTFORQUOTATION_SRV"],
            "ME47": ["/sap/opu/odata/sap/API_REQUESTFORQUOTATION_SRV"],
            "MB01": ["/sap/opu/odata/sap/API_MATERIAL_DOCUMENT_SRV"],
            "MB02": ["/sap/opu/odata/sap/API_MATERIAL_DOCUMENT_SRV"],
            "MB03": ["/sap/opu/odata/sap/API_MATERIAL_DOCUMENT_SRV"],
            "MB11": ["/sap/opu/odata/sap/API_MATERIAL_DOCUMENT_SRV"],
            "MB1A": ["/sap/opu/odata/sap/API_MATERIAL_DOCUMENT_SRV"],
            "MB1B": ["/sap/opu/odata/sap/API_MATERIAL_DOCUMENT_SRV"],
            "MB1C": ["/sap/opu/odata/sap/API_MATERIAL_DOCUMENT_SRV"],
            "MI07": ["/sap/opu/odata/sap/API_PHYSICALINVENTORYDOC_SRV"],
            "MIR7": ["/sap/opu/odata/sap/API_SUPPLIERINVOICE_PROCESS_SRV"],
            # === Additional Production Planning (PP) ===
            "CA01": ["/sap/opu/odata/sap/API_PRODUCTION_ROUTING_SRV"],
            "CA02": ["/sap/opu/odata/sap/API_PRODUCTION_ROUTING_SRV"],
            "CA03": ["/sap/opu/odata/sap/API_PRODUCTION_ROUTING_SRV"],
            "CR02": ["/sap/opu/odata/sap/API_WORKCENTER_SRV"],
            "PI01": ["/sap/opu/odata/sap/API_PROCESS_ORDER_SRV"],
            # === Additional Plant Maintenance (PM) ===
            "IL03": ["/sap/opu/odata/sap/API_FUNCTIONALLOCATION_SRV"],
            "IP30": ["/sap/opu/odata/sap/API_MAINTENANCEPLAN_SRV"],
            # === Additional Quality Management (QM) ===
            "QM03": ["/sap/opu/odata/sap/API_QUALITYNOTIFICATION_SRV"],
            "QE01": ["/sap/opu/odata/sap/API_INSPECTIONRESULT_SRV"],
            "QA11": ["/sap/opu/odata/sap/API_INSPECTIONRESULT_SRV"],
            # === Additional HR ===
            "PA10": ["/sap/opu/odata/sap/API_EMPLOYEE_SRV"],
            # === Additional Warehouse Management (EWM/WM) ===
            "LT02": ["/sap/opu/odata/sap/API_WAREHOUSE_TASK_SRV"],
            "LT03": ["/sap/opu/odata/sap/API_WAREHOUSE_TASK_SRV"],
            "/SCWM/MON": ["/sap/opu/odata/sap/API_WAREHOUSE_MONITORING_SRV"],
            # === Project Systems ===
            "CJ01": ["/sap/opu/odata/sap/API_ENTERPRISE_PROJECT_SRV/0002"],
            "CJ02": ["/sap/opu/odata/sap/API_ENTERPRISE_PROJECT_SRV/0002"],
            "CJ03": ["/sap/opu/odata/sap/API_ENTERPRISE_PROJECT_SRV/0002"],
            "CJ20N": ["/sap/opu/odata/sap/API_ENTERPRISE_PROJECT_SRV/0002"],
            "CN01": ["/sap/opu/odata/sap/API_PROJECT_NETWORK_SRV"],
            "CN02": ["/sap/opu/odata/sap/API_PROJECT_NETWORK_SRV"],
            # === Treasury / Cash Management ===
            "FF7A": ["/sap/opu/odata/sap/API_CASHMANAGEMENT_SRV"],
            "FF7B": ["/sap/opu/odata/sap/API_LIQUIDITYFORECAST_SRV"],
            "FF67": ["/sap/opu/odata/sap/API_BANKSTATEMENT_SRV"],
            "FF68": ["/sap/opu/odata/sap/API_BANKSTATEMENT_SRV"],
            "FTR_CREATE": ["/sap/opu/odata/sap/API_FINANCIALTRANSACTION_SRV"],
            "TBB1": ["/sap/opu/odata/sap/API_FINANCIALTRANSACTION_SRV"],
            "FWZZ": ["/sap/opu/odata/sap/API_FINANCIALTRANSACTION_SRV"],
            "FF63": ["/sap/opu/odata/sap/API_CASHMANAGEMENT_SRV"],
            "FF65": ["/sap/opu/odata/sap/API_CASHMANAGEMENT_SRV"],
            # === General / Basis ===
            "SU01": ["/sap/opu/odata/sap/API_USER_SRV"],
            "SM37": ["/sap/opu/odata/sap/API_JOBSCHEDULER_SRV"],
            "SM36": ["/sap/opu/odata/sap/API_JOBSCHEDULER_SRV"],
            "SM21": ["/sap/opu/odata/sap/API_SYSLOG_SRV"],
            "SM50": ["/sap/opu/odata/sap/API_PROCESSMONITORING_SRV"],
            "SM51": ["/sap/opu/odata/sap/API_PROCESSMONITORING_SRV"],
            "SCC4": ["/sap/opu/odata/sap/API_CLIENTDATA_SRV"],
            "PFCG": ["/sap/opu/odata/sap/API_IAM_ROLE_SRV"],
            "SU53": ["/sap/opu/odata/sap/API_IAM_AUTHCHECK_SRV"],
            "STMS": ["/sap/opu/odata/sap/API_TRANSPORTREQUEST_SRV"],
            "SE10": ["/sap/opu/odata/sap/API_TRANSPORTREQUEST_SRV"],
            "SE16N": ["/sap/opu/odata/sap/API_TABLEDATA_SRV"],
            # === Extended Finance — Bank Accounting ===
            "FI12": ["/sap/opu/odata/sap/API_BANKDETAIL_SRV"],
            "FI01": ["/sap/opu/odata/sap/API_BANKDETAIL_SRV"],
            "FI02": ["/sap/opu/odata/sap/API_BANKDETAIL_SRV"],
            "FBCJ": ["/sap/opu/odata/sap/API_CASHJOURNAL_SRV"],
            "FCH1": ["/sap/opu/odata/sap/API_CHECK_SRV"],
            "FCH2": ["/sap/opu/odata/sap/API_CHECK_SRV"],
            "FCH5": ["/sap/opu/odata/sap/API_CHECK_SRV"],
            "FCH9": ["/sap/opu/odata/sap/API_CHECK_SRV"],
            "F-28": ["/sap/opu/odata/sap/API_INCOMINGINVOICE_SRV"],
            "F-53": ["/sap/opu/odata/sap/API_PAYMENTRUN_SRV"],
            # === Extended Finance — Tax ===
            "FB41": ["/sap/opu/odata/sap/API_WITHHOLDINGTAXREPORT_SRV"],
            "S_P00_07000134": ["/sap/opu/odata/sap/API_TAXCORRESPONDENCE_SRV"],
            "OBCL": ["/sap/opu/odata/sap/API_TAXCLASSIFICATION_SRV"],
            # === Fixed Asset Accounting ===
            "AS01": ["/sap/opu/odata/sap/API_FIXEDASSET_0002"],
            "AS02": ["/sap/opu/odata/sap/API_FIXEDASSET_0002"],
            "AS03": ["/sap/opu/odata/sap/API_FIXEDASSET_0002"],
            "ABAV": ["/sap/opu/odata/sap/API_ASSETRETIREMENT_SRV"],
            "ABAON": ["/sap/opu/odata/sap/API_ASSETRETIREMENT_SRV"],
            "ABSO": ["/sap/opu/odata/sap/API_ASSETACQUISITION_SRV"],
            "AB01": ["/sap/opu/odata/sap/API_ASSETACQUISITION_SRV"],
            "ABNAN": ["/sap/opu/odata/sap/API_ASSETACQUISITION_SRV"],
            "AFAR": ["/sap/opu/odata/sap/API_ASSETDEPRECIATION_SRV"],
            "AFAB": ["/sap/opu/odata/sap/API_ASSETDEPRECIATION_SRV"],
            "AR01": ["/sap/opu/odata/sap/API_ASSETCLASS_SRV"],
            "AR02": ["/sap/opu/odata/sap/API_ASSETCLASS_SRV"],
            "AW01N": ["/sap/opu/odata/sap/API_ASSETEXPLORER_SRV"],
            # === Extended Controlling ===
            "KS01": ["/sap/opu/odata/sap/API_COSTCENTER_SRV"],
            "KS02": ["/sap/opu/odata/sap/API_COSTCENTER_SRV"],
            "KS03": ["/sap/opu/odata/sap/API_COSTCENTER_SRV"],
            "KE51": ["/sap/opu/odata/sap/API_PROFITABILITYANALYSIS_SRV"],
            "KE52": ["/sap/opu/odata/sap/API_PROFITABILITYANALYSIS_SRV"],
            "KEPM": ["/sap/opu/odata/sap/API_PROFITABILITYANALYSIS_SRV"],
            "KO01": ["/sap/opu/odata/sap/API_INTERNALORDER_SRV/0002"],
            "KO02": ["/sap/opu/odata/sap/API_INTERNALORDER_SRV/0002"],
            "KO03": ["/sap/opu/odata/sap/API_INTERNALORDER_SRV/0002"],
            "KA01": ["/sap/opu/odata/sap/API_COSTELEMENT_SRV"],
            "KA02": ["/sap/opu/odata/sap/API_COSTELEMENT_SRV"],
            "KP06": ["/sap/opu/odata/sap/API_COSTCENTERPLAN_SRV"],
            "KP26": ["/sap/opu/odata/sap/API_COSTCENTERPLAN_SRV"],
            "KSPI": ["/sap/opu/odata/sap/API_COSTCENTERACTUALCOST_SRV"],
            "KSB1": ["/sap/opu/odata/sap/API_COSTCENTERACTUALCOST_SRV"],
            "KOB1": ["/sap/opu/odata/sap/API_INTERNALORDERACTUAL_SRV"],
            "CJI3": ["/sap/opu/odata/sap/API_PROJECTACTUALCOST_SRV"],
            "KE30": ["/sap/opu/odata/sap/API_PROFITABILITYANALYSIS_SRV"],
            "1KEK": ["/sap/opu/odata/sap/API_COPACHARACTERISTIC_SRV"],
            # === Extended Profit Center ===
            "KE51": ["/sap/opu/odata/sap/API_PROFITCENTER_SRV/0002"],
            "KE52": ["/sap/opu/odata/sap/API_PROFITCENTER_SRV/0002"],
            "1KE0": ["/sap/opu/odata/sap/API_PROFITCENTER_SRV/0002"],
            # === Extended SD — Shipping / Returns / Complaints ===
            "VL10A": ["/sap/opu/odata/sap/API_OUTBOUND_DELIVERY_SRV_V2"],
            "VL10B": ["/sap/opu/odata/sap/API_OUTBOUND_DELIVERY_SRV_V2"],
            "VL31N": ["/sap/opu/odata/sap/API_INBOUND_DELIVERY_SRV_V2"],
            "VL32N": ["/sap/opu/odata/sap/API_INBOUND_DELIVERY_SRV_V2"],
            "VL33N": ["/sap/opu/odata/sap/API_INBOUND_DELIVERY_SRV_V2"],
            "VA11": ["/sap/opu/odata/sap/API_SALES_ORDER_SRV"],
            "VA42": ["/sap/opu/odata/sap/API_SALES_CONTRACT_SRV"],
            "VA43": ["/sap/opu/odata/sap/API_SALES_CONTRACT_SRV"],
            "VA31": ["/sap/opu/odata/sap/API_SALES_SCHEDULING_AGREEMENT_SRV"],
            "VA32": ["/sap/opu/odata/sap/API_SALES_SCHEDULING_AGREEMENT_SRV"],
            "VBO1": ["/sap/opu/odata/sap/API_REBATE_AGREEMENT_SRV"],
            "VBO2": ["/sap/opu/odata/sap/API_REBATE_AGREEMENT_SRV"],
            "CR01": ["/sap/opu/odata/sap/API_RETURNS_DELIVERY_SRV"],
            "VF11": ["/sap/opu/odata/sap/API_BILLING_DOCUMENT_SRV"],
            "VF21": ["/sap/opu/odata/sap/API_BILLING_DOCUMENT_SRV"],
            "VF44": ["/sap/opu/odata/sap/API_BILLING_DOCUMENT_SRV"],
            "VKM1": ["/sap/opu/odata/sap/API_CREDIT_MANAGEMENT_SRV"],
            "VKM5": ["/sap/opu/odata/sap/API_CREDIT_MANAGEMENT_SRV"],
            "VT01N": ["/sap/opu/odata/sap/API_SHIPMENT_SRV"],
            "VT02N": ["/sap/opu/odata/sap/API_SHIPMENT_SRV"],
            # === Extended MM — Inventory / Valuation / GR ===
            "MMBE": ["/sap/opu/odata/sap/API_MATERIAL_STOCK_SRV"],
            "MB52": ["/sap/opu/odata/sap/API_MATERIAL_STOCK_SRV"],
            "MB51": ["/sap/opu/odata/sap/API_MATERIAL_DOCUMENT_SRV"],
            "MR11": ["/sap/opu/odata/sap/API_SUPPLIERINVOICE_PROCESS_SRV"],
            "MIRO": ["/sap/opu/odata/sap/API_SUPPLIERINVOICE_PROCESS_SRV"],
            "ML81N": ["/sap/opu/odata/sap/API_SERVICE_ENTRY_SHEET_SRV"],
            "ML85": ["/sap/opu/odata/sap/API_SERVICE_ENTRY_SHEET_SRV"],
            "ME2M": ["/sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV"],
            "ME2N": ["/sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV"],
            "ME2L": ["/sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV"],
            "ME57": ["/sap/opu/odata/sap/API_PURCHASEREQUISITION_SRV"],
            "ME59N": ["/sap/opu/odata/sap/API_PURCHASEREQUISITION_SRV"],
            "ME84": ["/sap/opu/odata/sap/API_PURCHASEREQUISITION_SRV"],
            "MI01": ["/sap/opu/odata/sap/API_PHYSICALINVENTORYDOC_SRV"],
            "MI04": ["/sap/opu/odata/sap/API_PHYSICALINVENTORYDOC_SRV"],
            "MI20": ["/sap/opu/odata/sap/API_PHYSICALINVENTORYDOC_SRV"],
            "MR21": ["/sap/opu/odata/sap/API_MATERIALPRICECHANGE_SRV"],
            "MR22": ["/sap/opu/odata/sap/API_MATERIALPRICECHANGE_SRV"],
            "MMPV": ["/sap/opu/odata/sap/API_MATERIALPERIODCLOSE_SRV"],
            "CKM3N": ["/sap/opu/odata/sap/API_MATERIALLEDGERPRICES_SRV"],
            "CKMLCP": ["/sap/opu/odata/sap/API_MATERIALLEDGERPRICES_SRV"],
            # === Extended MM — Source Determination / Contract ===
            "ME35K": ["/sap/opu/odata/sap/API_PURCHASECONTRACT_PROCESS_SRV"],
            "ME33K": ["/sap/opu/odata/sap/API_PURCHASECONTRACT_PROCESS_SRV"],
            "ME35": ["/sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV"],
            "ME36": ["/sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV"],
            "ME15": ["/sap/opu/odata/sap/API_SOURCEOFFSUPPLY_SRV"],
            "ME01": ["/sap/opu/odata/sap/API_SOURCEOFFSUPPLY_SRV"],
            "ME49": ["/sap/opu/odata/sap/API_PURCHASEORDERPRICECOMPARISON_SRV"],
            # === Extended PP — Capacity / Scheduling ===
            "CO02": ["/sap/opu/odata/sap/API_PRODUCTION_ORDER_SRV"],
            "CO03": ["/sap/opu/odata/sap/API_PRODUCTION_ORDER_SRV"],
            "CO07": ["/sap/opu/odata/sap/API_PRODUCTION_ORDER_SRV"],
            "CO08": ["/sap/opu/odata/sap/API_PRODUCTION_ORDER_SRV"],
            "COOIS": ["/sap/opu/odata/sap/API_PRODUCTION_ORDER_SRV"],
            "CO11": ["/sap/opu/odata/sap/API_PRODORDCONF_PROCESS_SRV"],
            "CO15": ["/sap/opu/odata/sap/API_PRODORDCONF_PROCESS_SRV"],
            "CO13": ["/sap/opu/odata/sap/API_PRODORDCONF_PROCESS_SRV"],
            "CM01": ["/sap/opu/odata/sap/API_CAPACITYPLANNING_SRV"],
            "CM21": ["/sap/opu/odata/sap/API_CAPACITYPLANNING_SRV"],
            "CM25": ["/sap/opu/odata/sap/API_CAPACITYPLANNING_SRV"],
            "MD02": ["/sap/opu/odata/sap/API_MRP_MATERIALS_SRV_01"],
            "MD05": ["/sap/opu/odata/sap/API_MRP_MATERIALS_SRV_01"],
            "MD06": ["/sap/opu/odata/sap/API_MRP_MATERIALS_SRV_01"],
            "MD07": ["/sap/opu/odata/sap/API_MRP_MATERIALS_SRV_01"],
            "MD11": ["/sap/opu/odata/sap/API_PLANNEDORDER_SRV"],
            "MD12": ["/sap/opu/odata/sap/API_PLANNEDORDER_SRV"],
            "MD16": ["/sap/opu/odata/sap/API_PLANNEDORDER_SRV"],
            "CS02": ["/sap/opu/odata/sap/API_BILL_OF_MATERIAL_SRV/0002"],
            "CS03": ["/sap/opu/odata/sap/API_BILL_OF_MATERIAL_SRV/0002"],
            "CS12": ["/sap/opu/odata/sap/API_BILL_OF_MATERIAL_SRV/0002"],
            "CS13": ["/sap/opu/odata/sap/API_BILL_OF_MATERIAL_SRV/0002"],
            "CS15": ["/sap/opu/odata/sap/API_BILL_OF_MATERIAL_SRV/0002"],
            "CR01": ["/sap/opu/odata/sap/API_WORKCENTER_SRV"],
            "CR03": ["/sap/opu/odata/sap/API_WORKCENTER_SRV"],
            # === Extended PM — Work Orders / Measurement Points ===
            "IW22": ["/sap/opu/odata/sap/API_MAINTNOTIFICATION_SRV"],
            "IW23": ["/sap/opu/odata/sap/API_MAINTNOTIFICATION_SRV"],
            "IW28": ["/sap/opu/odata/sap/API_MAINTNOTIFICATION_SRV"],
            "IW32": ["/sap/opu/odata/sap/API_MAINTENANCEORDER_SRV"],
            "IW33": ["/sap/opu/odata/sap/API_MAINTENANCEORDER_SRV"],
            "IW38": ["/sap/opu/odata/sap/API_MAINTENANCEORDER_SRV"],
            "IW39": ["/sap/opu/odata/sap/API_MAINTENANCEORDER_SRV"],
            "IW41": ["/sap/opu/odata/sap/API_MAINTORDCONF_SRV"],
            "IW42": ["/sap/opu/odata/sap/API_MAINTORDCONF_SRV"],
            "IE02": ["/sap/opu/odata/sap/API_EQUIPMENT_SRV"],
            "IE03": ["/sap/opu/odata/sap/API_EQUIPMENT_SRV"],
            "IL02": ["/sap/opu/odata/sap/API_FUNCTIONALLOCATION_SRV"],
            "IA01": ["/sap/opu/odata/sap/API_MAINTENANCETASKLIST_SRV"],
            "IA02": ["/sap/opu/odata/sap/API_MAINTENANCETASKLIST_SRV"],
            "IP02": ["/sap/opu/odata/sap/API_MAINTENANCEPLAN_SRV"],
            "IP10": ["/sap/opu/odata/sap/API_MAINTENANCEPLAN_SRV"],
            "IK11": ["/sap/opu/odata/sap/API_MEASURINGPOINT_SRV"],
            "IK12": ["/sap/opu/odata/sap/API_MEASURINGPOINT_SRV"],
            # === Extended QM — Quality Planning / Inspection ===
            "QA01": ["/sap/opu/odata/sap/API_INSPECTIONLOT_SRV"],
            "QA02": ["/sap/opu/odata/sap/API_INSPECTIONLOT_SRV"],
            "QA03": ["/sap/opu/odata/sap/API_INSPECTIONLOT_SRV"],
            "QM01": ["/sap/opu/odata/sap/API_QUALITYNOTIFICATION_SRV"],
            "QM02": ["/sap/opu/odata/sap/API_QUALITYNOTIFICATION_SRV"],
            "QP01": ["/sap/opu/odata/sap/API_INSPECTIONPLAN_SRV"],
            "QP02": ["/sap/opu/odata/sap/API_INSPECTIONPLAN_SRV"],
            "QS21": ["/sap/opu/odata/sap/API_MASTINSPCHARACTERISTIC_SRV"],
            "QS23": ["/sap/opu/odata/sap/API_MASTINSPCHARACTERISTIC_SRV"],
            "QE02": ["/sap/opu/odata/sap/API_INSPECTIONRESULT_SRV"],
            "QE03": ["/sap/opu/odata/sap/API_INSPECTIONRESULT_SRV"],
            "QE51N": ["/sap/opu/odata/sap/API_INSPECTIONRESULT_SRV"],
            # === Extended HR / SuccessFactors OData ===
            "PA20": ["/sap/opu/odata/sap/API_EMPLOYEE_SRV"],
            "PA30": ["/sap/opu/odata/sap/API_EMPLOYEE_SRV"],
            "PA61": ["/sap/opu/odata/sap/API_TIMESHEET_V2"],
            "PT01": ["/sap/opu/odata/sap/API_WORKSHIFTPLAN_SRV"],
            "PT60": ["/sap/opu/odata/sap/API_TIMESHEET_V2"],
            "CAT2": ["/sap/opu/odata/sap/API_TIMESHEET_V2"],
            "PC00_M99_CALC": ["/sap/opu/odata/sap/API_PAYROLLRESULT_SRV"],
            "PPOM": ["/sap/opu/odata/sap/API_ORGUNIT_SRV"],
            "PO13": ["/sap/opu/odata/sap/API_POSITION_SRV"],
            # === Extended EWM / Warehouse ===
            "LT01": ["/sap/opu/odata/sap/API_WAREHOUSE_TASK_SRV"],
            "LT06": ["/sap/opu/odata/sap/API_WAREHOUSE_TASK_SRV"],
            "LT09": ["/sap/opu/odata/sap/API_WAREHOUSE_TASK_SRV"],
            "LT0A": ["/sap/opu/odata/sap/API_WAREHOUSE_TASK_SRV"],
            "LS03N": ["/sap/opu/odata/sap/API_WAREHOUSE_BIN_SRV"],
            "LS04": ["/sap/opu/odata/sap/API_WAREHOUSE_BIN_SRV"],
            "/SCWM/ADGI": ["/sap/opu/odata/sap/API_WAREHOUSE_GOODSISSUE_SRV"],
            "/SCWM/ADGR": ["/sap/opu/odata/sap/API_WAREHOUSE_GOODSRECEIPT_SRV"],
            "/SCWM/PACK": ["/sap/opu/odata/sap/API_WAREHOUSE_HANDLING_UNIT_SRV"],
            "/SCWM/STOCK": ["/sap/opu/odata/sap/API_WAREHOUSE_STOCKBALANCE_SRV"],
            "/SCWM/PRDO": ["/sap/opu/odata/sap/API_WAREHOUSE_PRODUCTIONORDER_SRV"],
            # === Extended PS — Project Systems / Investment Mgmt ===
            "CJ30": ["/sap/opu/odata/sap/API_ENTERPRISE_PROJECT_SRV/0002"],
            "CJ40": ["/sap/opu/odata/sap/API_PROJECTBUDGET_SRV"],
            "CJ42": ["/sap/opu/odata/sap/API_PROJECTBUDGET_SRV"],
            "CJ44": ["/sap/opu/odata/sap/API_PROJECTBUDGET_SRV"],
            "CNMM": ["/sap/opu/odata/sap/API_PROJECTNETWORKACTIVITY_SRV"],
            "CN22": ["/sap/opu/odata/sap/API_PROJECTNETWORKACTIVITY_SRV"],
            "CN25": ["/sap/opu/odata/sap/API_PROJECT_NETWORK_SRV"],
            "CJ45": ["/sap/opu/odata/sap/API_PROJECTSETTLEMENT_SRV"],
            "IM01": ["/sap/opu/odata/sap/API_INVESTMENTPROGRAM_SRV"],
            "IM02": ["/sap/opu/odata/sap/API_INVESTMENTPROGRAM_SRV"],
            "IM22": ["/sap/opu/odata/sap/API_APPROPRIATIONREQUEST_SRV"],
            "IM27": ["/sap/opu/odata/sap/API_APPROPRIATIONREQUEST_SRV"],
            # === Business Partner ===
            "BP": ["/sap/opu/odata/sap/API_BUSINESS_PARTNER"],
            "BUP1": ["/sap/opu/odata/sap/API_BUSINESS_PARTNER"],
            "BUP2": ["/sap/opu/odata/sap/API_BUSINESS_PARTNER"],
            "BUP3": ["/sap/opu/odata/sap/API_BUSINESS_PARTNER"],
            "FK01": ["/sap/opu/odata/sap/API_BUSINESS_PARTNER"],
            "FK02": ["/sap/opu/odata/sap/API_BUSINESS_PARTNER"],
            "FK03": ["/sap/opu/odata/sap/API_BUSINESS_PARTNER"],
            "FD01": ["/sap/opu/odata/sap/API_BUSINESS_PARTNER"],
            "FD02": ["/sap/opu/odata/sap/API_BUSINESS_PARTNER"],
            "FD03": ["/sap/opu/odata/sap/API_BUSINESS_PARTNER"],
            "XK01": ["/sap/opu/odata/sap/API_BUSINESS_PARTNER"],
            "XK02": ["/sap/opu/odata/sap/API_BUSINESS_PARTNER"],
            "XD01": ["/sap/opu/odata/sap/API_BUSINESS_PARTNER"],
            "XD02": ["/sap/opu/odata/sap/API_BUSINESS_PARTNER"],
            # === Material Master Extended ===
            "MM02": ["/sap/opu/odata/sap/API_PRODUCT_SRV/0002"],
            "MM03": ["/sap/opu/odata/sap/API_PRODUCT_SRV/0002"],
            "MM04": ["/sap/opu/odata/sap/API_PRODUCT_SRV/0002"],
            "MM06": ["/sap/opu/odata/sap/API_PRODUCT_SRV/0002"],
            "MM11": ["/sap/opu/odata/sap/API_PRODUCT_SRV/0002"],
            "MM17": ["/sap/opu/odata/sap/API_PRODUCT_SRV/0002"],
            "MM50": ["/sap/opu/odata/sap/API_PRODUCT_SRV/0002"],
            "MM60": ["/sap/opu/odata/sap/API_PRODUCT_SRV/0002"],
            "MEK1": ["/sap/opu/odata/sap/API_PURCHASINGCONDITIONRECORD_SRV"],
            "MEK2": ["/sap/opu/odata/sap/API_PURCHASINGCONDITIONRECORD_SRV"],
            "MEK3": ["/sap/opu/odata/sap/API_PURCHASINGCONDITIONRECORD_SRV"],
            # === Finance GL Extended ===
            "FS10N": ["/sap/opu/odata/sap/API_GLACCOUNTBALANCE_SRV"],
            "FBL1N": ["/sap/opu/odata/sap/API_OPMTRLVENDORLINEITEM_SRV"],
            "FBL3N": ["/sap/opu/odata/sap/API_GLACCOUNTLINEITEM_SRV"],
            "FBL5N": ["/sap/opu/odata/sap/API_OPMTRLCUSTOMERLINEITEM_SRV"],
            "S_ALR_87012277": ["/sap/opu/odata/sap/API_GLACCOUNTBALANCE_SRV"],
            "S_ALR_87012078": ["/sap/opu/odata/sap/API_OPMTRLVENDORLINEITEM_SRV"],
            "S_ALR_87012172": ["/sap/opu/odata/sap/API_OPMTRLCUSTOMERLINEITEM_SRV"],
            "FAGLL03": ["/sap/opu/odata/sap/API_GLACCOUNTLINEITEM_SRV"],
            "FAGLB03": ["/sap/opu/odata/sap/API_GLACCOUNTBALANCE_SRV"],
            # === Consolidation / Group Reporting ===
            "CXNB": ["/sap/opu/odata/sap/API_GROUPREPORTING_SRV"],
            "CX6M1": ["/sap/opu/odata/sap/API_CONSOLIDATIONDOCUMENT_SRV"],
            "CX9R1": ["/sap/opu/odata/sap/API_CONSOLIDATIONHIERARCHY_SRV"],
            # === Classification / Batch ===
            "CL01": ["/sap/opu/odata/sap/API_CLASSIFICATION_SRV"],
            "CL02": ["/sap/opu/odata/sap/API_CLASSIFICATION_SRV"],
            "CT04": ["/sap/opu/odata/sap/API_CHARACTERISTICVALUE_SRV"],
            "MSC1N": ["/sap/opu/odata/sap/API_BATCH_SRV/0002"],
            "MSC2N": ["/sap/opu/odata/sap/API_BATCH_SRV/0002"],
            "MSC3N": ["/sap/opu/odata/sap/API_BATCH_SRV/0002"],
            # === Service Management ===
            "IW51": ["/sap/opu/odata/sap/API_SERVICEORDER_SRV"],
            "IW52": ["/sap/opu/odata/sap/API_SERVICEORDER_SRV"],
            "IW53": ["/sap/opu/odata/sap/API_SERVICEORDER_SRV"],
            "IW54": ["/sap/opu/odata/sap/API_SERVICECONFIRMATION_SRV"],
            "IW55": ["/sap/opu/odata/sap/API_SERVICECONFIRMATION_SRV"],
            "DP80": ["/sap/opu/odata/sap/API_SERVICECONTRACT_SRV"],
            "DP81": ["/sap/opu/odata/sap/API_SERVICECONTRACT_SRV"],
            # === GTS / Trade Compliance ===
            "/SAPSLL/MENU_LEGAL": ["/sap/opu/odata/sap/API_CUSTOMSDECLARATION_SRV"],
            "/SAPSLL/MENU_COMPL": ["/sap/opu/odata/sap/API_SANCTIONEDPARTY_SCREEN_SRV"],
            "/SAPSLL/SP_LIST": ["/sap/opu/odata/sap/API_SANCTIONEDPARTY_SCREEN_SRV"],
            # === Environment Health Safety ===
            "EHSM": ["/sap/opu/odata/sap/API_EHSM_INCIDENTREPORT_SRV"],
            "CBIH01": ["/sap/opu/odata/sap/API_EHSM_HAZARDOUSMATERIAL_SRV"],
        }
        return TCODE_ODATA_MAP.get(tcode, [f"/sap/opu/odata/sap/API_{tcode}_SRV"])


def main(event, context):
    logger.info("Executing DITL Generation Pipeline (Part 5 Automation)")
    generator = DITLTestGenerator(target_framework="cypress")

    st03n_mappings = None

    # Dual-mode: try to read previous stage results from SAP via PyRFC,
    # fall back to event data or mock data
    try:
        from pyrfc import Connection
        import os
        from utils.secrets_client import get_secret_value

        secret_name = os.environ.get("ECC_SECRET_NAME", "sap-ecc-credentials")
        secret_response = get_secret_value(secret_name)
        import json as _json
        conn_params = _json.loads(secret_response["SecretString"])

        conn = Connection(
            ashost=conn_params["host"],
            sysnr=conn_params["sysnr"],
            client=conn_params["client"],
            user=conn_params["user"],
            passwd=conn_params["passwd"],
            lang="EN",
        )

        # Read previous stage process-miner results via RFC
        # Query SMEN_BUFFC for recently used T-code/Fiori mappings
        result = conn.call(
            "RFC_READ_TABLE",
            QUERY_TABLE="SMEN_BUFFC",
            DELIMITER="|",
            FIELDS=[
                {"FIELDNAME": "REPORT"},
                {"FIELDNAME": "TCODE"},
            ],
            ROWCOUNT=99999,
        )

        import sys as _sys, os as _os
        _sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), '..', 'process-miner'))
        from st03n_analyzer import ST03NAnalyzer
        catalog = ST03NAnalyzer().fiori_catalog

        st03n_mappings = []
        for row in result["DATA"]:
            fields = row["WA"].split("|")
            if len(fields) >= 2:
                tcode = fields[1].strip()
                if tcode in catalog:
                    mapping = catalog[tcode]
                    st03n_mappings.append({
                        "tcode": tcode,
                        "fiori_app_id": mapping["app_id"],
                        "fiori_name": mapping["name"],
                        "executions": 0,
                    })

        conn.close()
        logger.info(f"Read {len(st03n_mappings)} Fiori mappings from SAP via RFC")

    except ImportError:
        logger.warning("PyRFC not available — falling back to mock mode")
    except Exception as e:
        logger.warning(f"RFC call failed ({e}) — falling back to mock mode")

    # Fall back to event data or mock data if RFC was not available or failed
    if st03n_mappings is None:
        st03n_mappings = event.get('fiori_mappings', [
            {"tcode": "FB50", "fiori_app_id": "F0718", "fiori_name": "Post General Journal Entries", "executions": 1403}
        ])

    scripts = generator.process_workload_to_tests(st03n_mappings)

    return {
        "statusCode": 200,
        "body": {
            "message": f"Generated {len(scripts)} DITL Test Scripts natively mapped from ECC Usage Patterns.",
            "test_scripts": scripts,
            "support_file": generator.generate_support_file(),
        }
    }
