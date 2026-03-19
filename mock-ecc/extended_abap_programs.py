"""
Migrate4HANA — Extended Sample ABAP Programs
==============================================
20+ realistic ABAP programs that exercise ALL 100 rules.

These programs are written exactly like real production code found
in Indian manufacturing companies running SAP ECC 6.0. Every bad
pattern is intentional — it's what our analyzer should catch.

Programs cover:
  - Finance (GL, AP, AR, Asset, Intercompany)
  - Materials (PO, GRN, Inventory, MRP)
  - Sales (Order, Billing, GST Invoice, E-way Bill)
  - Production (Production Order, BOM, Shop Floor)
  - HR (Payroll, PF/ESI, Attendance, Form 16)
  - Controlling (Cost Center, Profit Center, COPA)
  - Basis (IDoc monitor, RFC wrapper, Email sender)
  - Cross-module (Performance anti-patterns, Dynpro, OO ABAP)
"""

EXTENDED_ABAP_PROGRAMS = {

# ─────────────────────────────────────────────────────────────────
# FINANCE PROGRAMS
# ─────────────────────────────────────────────────────────────────

"ZFI_002_GL_BALANCE_REPORT": """*----------------------------------------------------------------------*
* Program: ZFI_002_GL_BALANCE_REPORT
* Description: GL Account Balance Sheet with drill-down
* Author: AMIT.SHARMA
* Date: 20160420
*----------------------------------------------------------------------*
REPORT ZFI_002_GL_BALANCE_REPORT.

TABLES: BKPF, BSEG, SKA1, GLT0, BSIS, BSAS, T001.

DATA: BEGIN OF lt_balances OCCURS 0,
        BUKRS TYPE BSEG-BUKRS,
        HKONT TYPE BSEG-HKONT,
        TXT50 TYPE SKAT-TXT50,
        DMBTR TYPE BSEG-DMBTR,
        SHKZG TYPE BSEG-SHKZG,
        GJAHR TYPE BKPF-GJAHR,
      END OF lt_balances.

DATA: lv_debit  TYPE BSEG-DMBTR,
      lv_credit TYPE BSEG-DMBTR,
      lv_saldo  TYPE BSEG-DMBTR,
      lv_count  TYPE i.

PARAMETERS: p_bukrs TYPE BKPF-BUKRS DEFAULT '1000',
            p_gjahr TYPE BKPF-GJAHR DEFAULT '2024'.

START-OF-SELECTION.

* First get totals from GLT0 (deprecated in S/4HANA!)
  SELECT * FROM GLT0
    INTO CORRESPONDING FIELDS OF TABLE lt_balances
    WHERE BUKRS = p_bukrs
    AND   RRCTY = '0'
    AND   GJAHR = p_gjahr.

* Then get open items from BSIS
  SELECT * FROM BSIS
    INTO CORRESPONDING FIELDS OF TABLE lt_balances
    WHERE BUKRS = p_bukrs
    AND   GJAHR = p_gjahr.

* Append cleared items from BSAS
  SELECT * FROM BSAS
    APPENDING CORRESPONDING FIELDS OF TABLE lt_balances
    WHERE BUKRS = p_bukrs
    AND   GJAHR = p_gjahr.

  SORT lt_balances BY HKONT.

  LOOP AT lt_balances.
    IF lt_balances-SHKZG = 'S'.
      ADD lt_balances-DMBTR TO lv_debit.
    ELSE.
      ADD lt_balances-DMBTR TO lv_credit.
    ENDIF.
    COMPUTE lv_saldo = lv_debit - lv_credit.
    ADD 1 TO lv_count.
  ENDLOOP.

  WRITE: / 'Company Code:', p_bukrs.
  WRITE: / 'Fiscal Year:', p_gjahr.
  WRITE: / 'Total Debit:', lv_debit.
  WRITE: / 'Total Credit:', lv_credit.
  WRITE: / 'Balance:', lv_saldo.
  WRITE: / 'Line items:', lv_count.

  CALL FUNCTION 'REUSE_ALV_LIST_DISPLAY'
    EXPORTING
      i_structure_name = 'BSEG'
    TABLES
      t_outtab         = lt_balances.
""",

"ZFI_003_VENDOR_AGING": """*----------------------------------------------------------------------*
* Program: ZFI_003_VENDOR_AGING
* Description: Vendor aging report (AP outstanding)
*----------------------------------------------------------------------*
REPORT ZFI_003_VENDOR_AGING.

TABLES: BSIK, BSAK, LFA1, LFB1.

DATA: lt_open TYPE STANDARD TABLE OF BSIK WITH HEADER LINE,
      lt_vendors TYPE STANDARD TABLE OF LFA1 OCCURS 100,
      ls_vendor TYPE LFA1,
      ls_lfb1 TYPE LFB1.

DATA: lv_days TYPE i,
      lv_total TYPE p DECIMALS 2.

SELECT-OPTIONS: s_bukrs FOR BSIK-BUKRS DEFAULT '1000',
                s_lifnr FOR BSIK-LIFNR.

START-OF-SELECTION.

  SELECT * FROM BSIK INTO TABLE lt_open
    WHERE BUKRS IN s_bukrs
    AND   LIFNR IN s_lifnr.

  SELECT * FROM LFA1 INTO TABLE lt_vendors
    WHERE LIFNR IN s_lifnr.

  LOOP AT lt_open.
    lv_days = sy-datum - lt_open-ZFBDT.

    SELECT SINGLE * FROM LFA1 INTO ls_vendor
      WHERE LIFNR = lt_open-LIFNR.

    SELECT SINGLE * FROM LFB1 INTO ls_lfb1
      WHERE LIFNR = lt_open-LIFNR
      AND   BUKRS = lt_open-BUKRS.

    MOVE lt_open-DMBTR TO lv_total.

    WRITE: / lt_open-LIFNR, ls_vendor-NAME1,
             lt_open-BELNR, lt_open-DMBTR, lv_days, 'days'.
  ENDLOOP.
""",

"ZFI_004_INTERCOMPANY_POST": """*----------------------------------------------------------------------*
* Program: ZFI_004_INTERCOMPANY_POST
* Description: Intercompany journal posting with BAPI
*----------------------------------------------------------------------*
REPORT ZFI_004_INTERCOMPANY_POST.

TABLES: BKPF, BSEG.

DATA: lt_docs     TYPE STANDARD TABLE OF BAPIACHE09,
      lt_currency TYPE STANDARD TABLE OF BAPIACCR09,
      lt_return   TYPE STANDARD TABLE OF BAPIRET2,
      ls_header   TYPE BAPIACHE09,
      lv_doc      TYPE BKPF-BELNR.

DATA: BEGIN OF lt_postings OCCURS 10,
        BUKRS_FROM TYPE BKPF-BUKRS,
        BUKRS_TO   TYPE BKPF-BUKRS,
        AMOUNT     TYPE BSEG-DMBTR,
        HKONT      TYPE BSEG-HKONT,
      END OF lt_postings.

* Read intercompany mapping
  EXEC SQL.
    SELECT * FROM ZTFI_INTERCO_MAP
    INTO :lt_postings
  ENDEXEC.

  LOOP AT lt_postings.
    CALL FUNCTION 'BAPI_ACC_DOCUMENT_POST'
      EXPORTING
        documentheader = ls_header
      TABLES
        accountgl      = lt_docs
        currencyamount = lt_currency
        return         = lt_return.

    COMMIT WORK AND WAIT.
  ENDLOOP.
""",

"ZFI_005_ASSET_DEPRECIATION": """*----------------------------------------------------------------------*
* Program: ZFI_005_ASSET_DEPRECIATION
* Description: Asset depreciation run with custom logic
*----------------------------------------------------------------------*
REPORT ZFI_005_ASSET_DEPRECIATION.

TABLES: ANLA, ANLB, ANLC, BKPF.

DATA: lt_assets TYPE STANDARD TABLE OF ANLA WITH HEADER LINE,
      lv_dep_amount TYPE ANLC-KANSW,
      lv_nbv TYPE p DECIMALS 2.

DATA: lt_result OCCURS 0 WITH HEADER LINE.

PARAMETERS: p_bukrs TYPE ANLA-BUKRS DEFAULT '1000',
            p_gjahr TYPE ANLA-AFASL DEFAULT '2024'.

  SELECT * FROM ANLA INTO TABLE lt_assets
    WHERE BUKRS = p_bukrs.

  SELECT SINGLE * FROM ANLC
    WHERE BUKRS = p_bukrs.

  LOOP AT lt_assets.
    COMPUTE lv_dep_amount = lt_assets-ANSWL * '0.15'.
    SUBTRACT lv_dep_amount FROM lv_nbv.
    MULTIPLY lv_nbv BY 1.

    WRITE: / lt_assets-ANLN1, lt_assets-TXT50,
             lv_dep_amount, lv_nbv.
  ENDLOOP.

  CALL FUNCTION 'REUSE_ALV_GRID_DISPLAY'
    EXPORTING
      i_structure_name = 'ANLA'
    TABLES
      t_outtab         = lt_assets.
""",

# ─────────────────────────────────────────────────────────────────
# MATERIALS MANAGEMENT PROGRAMS
# ─────────────────────────────────────────────────────────────────

"ZMM_002_STOCK_VALUATION": """*----------------------------------------------------------------------*
* Program: ZMM_002_STOCK_VALUATION
* Description: Stock valuation report with material ledger
*----------------------------------------------------------------------*
REPORT ZMM_002_STOCK_VALUATION.

TABLES: MARD, MBEW, MKPF, MSEG, MARA.

DATA: BEGIN OF lt_stock OCCURS 0,
        MATNR TYPE MARD-MATNR,
        WERKS TYPE MARD-WERKS,
        LGORT TYPE MARD-LGORT,
        LABST TYPE MARD-LABST,
        SALK3 TYPE MBEW-SALK3,
        STPRS TYPE MBEW-STPRS,
      END OF lt_stock.

DATA: lv_total_value TYPE p DECIMALS 2.

  SELECT MARD~MATNR MARD~WERKS MARD~LGORT MARD~LABST
         MBEW~SALK3 MBEW~STPRS
    INTO CORRESPONDING FIELDS OF TABLE lt_stock
    FROM MARD
    INNER JOIN MBEW ON MARD~MATNR = MBEW~MATNR
                   AND MARD~WERKS = MBEW~BWKEY
    WHERE MARD~WERKS = '1001'.

* Get material movements from MKPF/MSEG (deprecated!)
  DATA: lt_movements TYPE TABLE OF MSEG.
  SELECT * FROM MSEG INTO TABLE lt_movements
    WHERE WERKS = '1001'
    AND   BUDAT_MKPF >= '20240101'.

  DATA: lt_headers TYPE TABLE OF MKPF.
  SELECT * FROM MKPF INTO TABLE lt_headers
    FOR ALL ENTRIES IN lt_movements
    WHERE MBLNR = lt_movements-MBLNR.

  LOOP AT lt_stock.
    COMPUTE lv_total_value = lv_total_value + lt_stock-LABST * lt_stock-STPRS.
    WRITE: / lt_stock-MATNR, lt_stock-WERKS, lt_stock-LABST,
             lt_stock-STPRS, lt_stock-SALK3.
  ENDLOOP.

  WRITE: / 'Total Stock Value:', lv_total_value.
""",

"ZMM_003_GRN_WITH_QC": """*----------------------------------------------------------------------*
* Program: ZMM_003_GRN_WITH_QC
* Description: Goods Receipt with Quality Check integration
*----------------------------------------------------------------------*
REPORT ZMM_003_GRN_WITH_QC.

TABLES: EKKO, EKPO, MKPF, MSEG, LFA1.

DATA: lt_pos     TYPE STANDARD TABLE OF EKPO WITH HEADER LINE,
      ls_vendor  TYPE LFA1,
      lv_mblnr   TYPE MKPF-MBLNR,
      lv_answer   TYPE c.

  SELECT * FROM EKPO INTO TABLE lt_pos
    WHERE EBELN = '4500001234'
    AND   LOEKZ = ' '.

  LOOP AT lt_pos.
    SELECT SINGLE * FROM LFA1 INTO ls_vendor
      WHERE LIFNR = lt_pos-LIFNR.

    CALL FUNCTION 'BAPI_GOODSMVT_CREATE'
      EXPORTING
        goodsmvt_header = VALUE #( )
      TABLES
        goodsmvt_item   = lt_pos
        return          = lt_pos.

    CALL FUNCTION 'POPUP_TO_CONFIRM_STEP'
      EXPORTING
        textline1 = 'Post Goods Receipt?'
      IMPORTING
        answer    = lv_answer.
  ENDLOOP.
""",

"ZMM_004_PURCHASE_PRICE_HIST": """*----------------------------------------------------------------------*
* Program: ZMM_004_PURCHASE_PRICE_HIST
* Description: Purchase price history with vendor comparison
*----------------------------------------------------------------------*
REPORT ZMM_004_PURCHASE_PRICE_HIST.

TABLES: EKKO, EKPO, LFA1, KONV.

DATA: lt_prices LIKE EKPO OCCURS 100 WITH HEADER LINE.
DATA: lt_conditions TYPE TABLE OF KONV.

DATA: lv_total TYPE p DECIMALS 2,
      lv_lines TYPE i.

  SELECT * FROM EKPO INTO TABLE lt_prices
    WHERE WERKS = '1001'
    AND   AEDAT >= '20230101'.

* Get pricing conditions (KONV is deprecated in S/4!)
  SELECT * FROM KONV INTO TABLE lt_conditions
    FOR ALL ENTRIES IN lt_prices
    WHERE KNUMV = lt_prices-KNUMV.

  DESCRIBE TABLE lt_prices LINES lv_lines.

  LOOP AT lt_prices.
    CONCATENATE lt_prices-MATNR lt_prices-WERKS
      INTO DATA(lv_key) SEPARATED BY '-'.
    WRITE: / lt_prices-EBELN, lt_prices-MATNR,
             lt_prices-NETPR, lt_prices-WAERS.
  ENDLOOP.
""",

# ─────────────────────────────────────────────────────────────────
# SALES & DISTRIBUTION PROGRAMS
# ─────────────────────────────────────────────────────────────────

"ZSD_002_SALES_ORDER_CREATE": """*----------------------------------------------------------------------*
* Program: ZSD_002_SALES_ORDER_CREATE
* Description: Batch sales order creation from file upload
*----------------------------------------------------------------------*
REPORT ZSD_002_SALES_ORDER_CREATE.

TABLES: VBAK, VBAP, KNA1, KNVV.

DATA: lt_orders  TYPE STANDARD TABLE OF BAPISDHEAD,
      lt_items   TYPE STANDARD TABLE OF BAPISDITEM,
      lt_return  TYPE STANDARD TABLE OF BAPIRET2,
      lt_file    TYPE STANDARD TABLE OF STRING,
      lv_vbeln   TYPE VBAK-VBELN.

DATA: ls_customer TYPE KNA1,
      ls_sales    TYPE KNVV.

* Upload file from presentation server (GUI only!)
  CALL FUNCTION 'GUI_UPLOAD'
    EXPORTING
      filename = 'C:/SAP/orders.csv'
    TABLES
      data_tab = lt_file.

  LOOP AT lt_file INTO DATA(lv_line).
    SELECT SINGLE * FROM KNA1 INTO ls_customer
      WHERE KUNNR = lv_line+0(10).

    SELECT SINGLE * FROM KNVV INTO ls_sales
      WHERE KUNNR = lv_line+0(10)
      AND   VKORG = '1000'.

    CALL FUNCTION 'BAPI_SALESORDER_CREATEFROMDAT2'
      EXPORTING
        order_header_in = VALUE #( )
      TABLES
        return          = lt_return.

    READ TABLE lt_return INTO DATA(ls_ret) INDEX 1.
    IF ls_ret-TYPE = 'E'.
      WRITE: / 'Error:', ls_ret-MESSAGE.
    ENDIF.

    COMMIT WORK.
  ENDLOOP.
""",

"ZSD_003_EWAY_BILL_GEN": """*----------------------------------------------------------------------*
* Program: ZSD_003_EWAY_BILL_GEN
* Description: E-way Bill generation for India (GST compliance)
*----------------------------------------------------------------------*
REPORT ZSD_003_EWAY_BILL_GEN.

TABLES: VBRK, VBRP, KNA1, J_1IEXCHDR, LIKP.

DATA: BEGIN OF lt_invoices OCCURS 0,
        VBELN TYPE VBRK-VBELN,
        KUNAG TYPE VBRK-KUNAG,
        NETWR TYPE VBRK-NETWR,
        WAERS TYPE VBRK-WAERS,
        FKDAT TYPE VBRK-FKDAT,
      END OF lt_invoices.

DATA: lv_gstin     TYPE char15,
      lv_hsn       TYPE char8,
      lv_eway_num  TYPE char12,
      lv_igst      TYPE p DECIMALS 2,
      lv_cgst      TYPE p DECIMALS 2,
      lv_sgst      TYPE p DECIMALS 2.

* Get billing documents
  SELECT VBELN KUNAG NETWR WAERS FKDAT
    FROM VBRK
    INTO CORRESPONDING FIELDS OF TABLE lt_invoices
    WHERE BUKRS = '1000'
    AND   FKDAT >= '20240401'.

  LOOP AT lt_invoices.
*   Get customer GSTIN
    SELECT SINGLE * FROM KNA1
      INTO DATA(ls_kna1)
      WHERE KUNNR = lt_invoices-KUNAG.

*   Check old excise header (J_1IEXCHDR - completely obsolete post-GST!)
    SELECT SINGLE * FROM J_1IEXCHDR
      INTO DATA(ls_excise)
      WHERE BUKRS = '1000'.

*   Calculate GST: IGST for interstate, CGST+SGST for intrastate
    IF ls_kna1-REGIO <> 'MH'.  "Maharashtra
      lv_igst = lt_invoices-NETWR * 18 / 100.  "IGST 18%
    ELSE.
      lv_cgst = lt_invoices-NETWR * 9 / 100.   "CGST 9%
      lv_sgst = lt_invoices-NETWR * 9 / 100.   "SGST 9%
    ENDIF.

*   E-way bill required if value > 50,000
    IF lt_invoices-NETWR > 50000.
      WRITE: / 'EWAY BILL REQUIRED:', lt_invoices-VBELN,
               lt_invoices-NETWR, 'GSTIN:', lv_gstin.
    ENDIF.
  ENDLOOP.
""",

"ZSD_004_EXPORT_BILLING": """*----------------------------------------------------------------------*
* Program: ZSD_004_EXPORT_BILLING
* Description: Export billing with foreign currency and customs docs
*----------------------------------------------------------------------*
REPORT ZSD_004_EXPORT_BILLING.

TABLES: VBRK, VBRP, KNA1, KONV.

DATA: lt_billing TYPE TABLE OF VBRK,
      lt_items   TYPE TABLE OF VBRP,
      lt_cond    TYPE TABLE OF KONV,
      ls_cust    TYPE KNA1.

  SELECT * FROM VBRK INTO TABLE lt_billing
    WHERE VKORG = '2000'
    AND   FKDAT >= '20240101'.

  IF lt_billing IS NOT INITIAL.
    SELECT * FROM VBRP INTO TABLE lt_items
      FOR ALL ENTRIES IN lt_billing
      WHERE VBELN = lt_billing-VBELN.

*   KONV is deprecated in S/4HANA! → PRCD_ELEMENTS
    SELECT * FROM KONV INTO TABLE lt_cond
      FOR ALL ENTRIES IN lt_billing
      WHERE KNUMV = lt_billing-KNUMV.
  ENDIF.

  LOOP AT lt_billing INTO DATA(ls_bill).
    SELECT SINGLE * FROM KNA1 INTO ls_cust
      WHERE KUNNR = ls_bill-KUNAG.

    WRITE: / ls_bill-VBELN, ls_cust-NAME1,
             ls_bill-NETWR, ls_bill-WAERS.
  ENDLOOP.

* Download to Excel (GUI only — won't work in Fiori)
  CALL FUNCTION 'GUI_DOWNLOAD'
    EXPORTING
      filename = 'C:/Export/billing.csv'
    TABLES
      data_tab = lt_billing.
""",

# ─────────────────────────────────────────────────────────────────
# HR / PAYROLL PROGRAMS
# ─────────────────────────────────────────────────────────────────

"ZHR_002_PF_ESI_CALC": """*----------------------------------------------------------------------*
* Program: ZHR_002_PF_ESI_CALC
* Description: Provident Fund and ESI calculation for India
*----------------------------------------------------------------------*
REPORT ZHR_002_PF_ESI_CALC.

TABLES: PA0001, PA0008, PA0002.

INFOTYPES: 0001, 0008.

DATA: BEGIN OF lt_employees OCCURS 0,
        PERNR TYPE PA0001-PERNR,
        ENAME TYPE PA0001-ENAME,
        BASIC TYPE PA0008-ANSAL,
        PF_AMOUNT TYPE p DECIMALS 2,
        ESI_AMOUNT TYPE p DECIMALS 2,
        GRATUITY TYPE p DECIMALS 2,
      END OF lt_employees.

DATA: lv_pf_rate TYPE p DECIMALS 4 VALUE '0.12',
      lv_esi_rate TYPE p DECIMALS 4 VALUE '0.0075',
      lv_pf_ceiling TYPE p DECIMALS 2 VALUE 15000.

  SELECT PA0001~PERNR PA0001~ENAME PA0008~ANSAL AS BASIC
    INTO CORRESPONDING FIELDS OF TABLE lt_employees
    FROM PA0001
    INNER JOIN PA0008 ON PA0001~PERNR = PA0008~PERNR
    WHERE PA0001~ENDDA >= sy-datum
    AND   PA0001~BEGDA <= sy-datum
    AND   PA0008~ENDDA >= sy-datum.

  LOOP AT lt_employees.
    DATA(lv_monthly) = lt_employees-BASIC / 12.

*   PF: 12% of basic, capped at 15000
    IF lv_monthly > lv_pf_ceiling.
      COMPUTE lt_employees-PF_AMOUNT = lv_pf_ceiling * lv_pf_rate.
    ELSE.
      MULTIPLY lt_employees-PF_AMOUNT BY 1.
      lt_employees-PF_AMOUNT = lv_monthly * lv_pf_rate.
    ENDIF.

*   ESI: 0.75% if gross < 21000
    IF lv_monthly < 21000.
      COMPUTE lt_employees-ESI_AMOUNT = lv_monthly * lv_esi_rate.
    ENDIF.

*   Gratuity provision (15 days salary for each year)
    COMPUTE lt_employees-GRATUITY = ( lt_employees-BASIC / 26 ) * 15.

    MODIFY lt_employees.
  ENDLOOP.

  WRITE: / 'PF & ESI Calculation Report'.
  WRITE: / 'Employees processed:', LINES( lt_employees ).

  LOOP AT lt_employees.
    WRITE: / lt_employees-PERNR, lt_employees-ENAME,
             lt_employees-BASIC, lt_employees-PF_AMOUNT,
             lt_employees-ESI_AMOUNT.
  ENDLOOP.
""",

"ZHR_003_TDS_FORM16": """*----------------------------------------------------------------------*
* Program: ZHR_003_TDS_FORM16
* Description: TDS calculation and Form 16 generation
*----------------------------------------------------------------------*
REPORT ZHR_003_TDS_FORM16.

TABLES: PA0001, PA0008, PA0581.

DATA: lt_employees TYPE STANDARD TABLE OF PA0001 WITH HEADER LINE.
DATA: lv_taxable TYPE p DECIMALS 2,
      lv_tds     TYPE p DECIMALS 2,
      lv_section TYPE char10.

DATA: lv_pan TYPE char10.
* PAN validation: should be AAAAA0000A format
DATA: lv_pan_valid TYPE char1.

  SELECT * FROM PA0001 INTO TABLE lt_employees
    WHERE ENDDA >= sy-datum
    AND   BEGDA <= sy-datum.

  LOOP AT lt_employees.
*   TDS Section 192 — Salary income
    lv_section = '192'.

    SELECT SINGLE ANSAL INTO lv_taxable
      FROM PA0008
      WHERE PERNR = lt_employees-PERNR
      AND   ENDDA >= sy-datum.

*   Old tax regime TDS slabs
    IF lv_taxable <= 250000.
      lv_tds = 0.
    ELSEIF lv_taxable <= 500000.
      COMPUTE lv_tds = ( lv_taxable - 250000 ) * '0.05'.
    ELSEIF lv_taxable <= 1000000.
      COMPUTE lv_tds = 12500 + ( lv_taxable - 500000 ) * '0.20'.
    ELSE.
      COMPUTE lv_tds = 112500 + ( lv_taxable - 1000000 ) * '0.30'.
    ENDIF.

*   Generate Form 16 PDF via Smart Forms
    CALL FUNCTION 'SSF_FUNCTION_MODULE_NAME'
      EXPORTING
        formname = 'ZHR_FORM16'
      IMPORTING
        fm_name  = DATA(lv_fm_name).

    WRITE: / lt_employees-PERNR, lt_employees-ENAME,
             'Section', lv_section, 'TDS:', lv_tds,
             'Form 16 generated'.
  ENDLOOP.
""",

# ─────────────────────────────────────────────────────────────────
# PRODUCTION PROGRAMS
# ─────────────────────────────────────────────────────────────────

"ZPP_001_PROD_ORDER_STATUS": """*----------------------------------------------------------------------*
* Program: ZPP_001_PROD_ORDER_STATUS
* Description: Production order status with yield analysis
*----------------------------------------------------------------------*
REPORT ZPP_001_PROD_ORDER_STATUS.

TABLES: AUFK, AFKO, AFPO, MSEG, MKPF.

DATA: lt_orders  LIKE AUFK OCCURS 50 WITH HEADER LINE,
      lt_goods   TYPE TABLE OF MSEG,
      lt_headers TYPE TABLE OF MKPF.

DATA: lv_yield     TYPE p DECIMALS 2,
      lv_scrap     TYPE p DECIMALS 2,
      lv_total_qty TYPE p DECIMALS 2.

  SELECT * FROM AUFK INTO TABLE lt_orders
    WHERE WERKS = '1002'
    AND   AUTYP = '10'
    AND   ERDAT >= '20240101'.

* Get goods movements for these orders (MSEG is deprecated!)
  IF lt_orders[] IS NOT INITIAL.
    SELECT * FROM MSEG INTO TABLE lt_goods
      FOR ALL ENTRIES IN lt_orders
      WHERE AUFNR = lt_orders-AUFNR.

    SELECT * FROM MKPF INTO TABLE lt_headers
      FOR ALL ENTRIES IN lt_goods
      WHERE MBLNR = lt_goods-MBLNR.
  ENDIF.

  LOOP AT lt_orders.
    LOOP AT lt_goods INTO DATA(ls_mvt)
      WHERE AUFNR = lt_orders-AUFNR.
      IF ls_mvt-BWART = '101'.
        ADD ls_mvt-MENGE TO lv_total_qty.
      ELSEIF ls_mvt-BWART = '551'.
        ADD ls_mvt-MENGE TO lv_scrap.
      ENDIF.
    ENDLOOP.

    IF lv_total_qty > 0.
      COMPUTE lv_yield = ( lv_total_qty - lv_scrap ) / lv_total_qty * 100.
    ENDIF.

    WRITE: / lt_orders-AUFNR, lv_total_qty, lv_scrap, lv_yield, '%'.
    CLEAR: lv_total_qty, lv_scrap.
  ENDLOOP.
""",

"ZPP_002_BOM_COSTING": """*----------------------------------------------------------------------*
* Program: ZPP_002_BOM_COSTING
* Description: BOM explosion with cost rollup
*----------------------------------------------------------------------*
REPORT ZPP_002_BOM_COSTING.

TABLES: MAST, STKO, STPO, MBEW.

DATA: lt_bom     TYPE TABLE OF STPOX,
      lt_mat_val TYPE TABLE OF MBEW.

DATA: lv_cost TYPE p DECIMALS 2.

  CALL FUNCTION 'CS_BOM_EXPL_MAT_V2'
    EXPORTING
      capid = 'PP01'
      datefm = sy-datum
      mtnrv  = 'FG-1001'
      werks  = '1002'
    TABLES
      stb    = lt_bom.

* Get valuation prices (MBEW structure changed in S/4!)
  SELECT * FROM MBEW INTO TABLE lt_mat_val
    FOR ALL ENTRIES IN lt_bom
    WHERE MATNR = lt_bom-IDNRK
    AND   BWKEY = '1002'.

  LOOP AT lt_bom INTO DATA(ls_comp).
    READ TABLE lt_mat_val INTO DATA(ls_val)
      WITH KEY MATNR = ls_comp-IDNRK BINARY SEARCH.
    IF sy-subrc = 0.
      COMPUTE lv_cost = lv_cost + ls_comp-MENGE * ls_val-STPRS.
    ENDIF.
  ENDLOOP.

  WRITE: / 'Total BOM Cost:', lv_cost.
""",

# ─────────────────────────────────────────────────────────────────
# CONTROLLING PROGRAMS
# ─────────────────────────────────────────────────────────────────

"ZCO_001_COST_CENTER_REPORT": """*----------------------------------------------------------------------*
* Program: ZCO_001_COST_CENTER_REPORT
* Description: Cost center actual vs budget report
*----------------------------------------------------------------------*
REPORT ZCO_001_COST_CENTER_REPORT.

TABLES: CSKS, COSS, COSP, COEP, COBK.

DATA: BEGIN OF lt_costs OCCURS 0,
        KOSTL  TYPE CSKS-KOSTL,
        KSTAR  TYPE COEP-KSTAR,
        WTG001 TYPE COSP-WTG001,
        WTG002 TYPE COSP-WTG002,
      END OF lt_costs.

* Read CO totals (COSP/COSS both deprecated in S/4 → ACDOCA)
  SELECT KOSTL KSTAR WTG001 WTG002
    FROM COSP
    INTO CORRESPONDING FIELDS OF TABLE lt_costs
    WHERE KOKRS = '1000'
    AND   GJAHR = '2024'.

  DATA: lt_line_items TYPE TABLE OF COEP.
  SELECT * FROM COEP INTO TABLE lt_line_items
    WHERE KOKRS = '1000'
    AND   GJAHR = '2024'.

  DATA: lt_co_headers TYPE TABLE OF COBK.
  SELECT * FROM COBK INTO TABLE lt_co_headers
    WHERE KOKRS = '1000'
    AND   GJAHR = '2024'.

  LOOP AT lt_costs.
    WRITE: / lt_costs-KOSTL, lt_costs-KSTAR,
             'Actual:', lt_costs-WTG001,
             'Budget:', lt_costs-WTG002.
  ENDLOOP.
""",

"ZCO_002_COPA_ANALYSIS": """*----------------------------------------------------------------------*
* Program: ZCO_002_COPA_ANALYSIS
* Description: Profitability analysis — reads COPA tables
*----------------------------------------------------------------------*
REPORT ZCO_002_COPA_ANALYSIS.

TABLES: CE1BIS0, CE2BIS0.

DATA: lt_copa TYPE TABLE OF CE1BIS0.
DATA: lv_revenue TYPE p DECIMALS 2,
      lv_cogs    TYPE p DECIMALS 2,
      lv_margin  TYPE p DECIMALS 2.

* CE tables (CExxxxx) are merged into ACDOCA in S/4HANA!
  SELECT * FROM CE1BIS0 INTO TABLE lt_copa
    WHERE GJAHR = '2024'
    AND   BUKRS = '1000'.

  LOOP AT lt_copa INTO DATA(ls_copa).
    ADD ls_copa-VV010 TO lv_revenue.     "Revenue
    ADD ls_copa-VV020 TO lv_cogs.        "COGS
  ENDLOOP.

  COMPUTE lv_margin = lv_revenue - lv_cogs.

  WRITE: / 'Revenue:', lv_revenue.
  WRITE: / 'COGS:', lv_cogs.
  WRITE: / 'Margin:', lv_margin.
""",

# ─────────────────────────────────────────────────────────────────
# INDIA-SPECIFIC / GST PROGRAMS
# ─────────────────────────────────────────────────────────────────

"ZFI_006_GST_RETURN_GSTR1": """*----------------------------------------------------------------------*
* Program: ZFI_006_GST_RETURN_GSTR1
* Description: GSTR-1 return preparation (India GST compliance)
*----------------------------------------------------------------------*
REPORT ZFI_006_GST_RETURN_GSTR1.

TABLES: VBRK, VBRP, KNA1, J_1IEXCHDR, J_1IEXCDTL.

DATA: BEGIN OF lt_invoices OCCURS 0,
        VBELN     TYPE VBRK-VBELN,
        FKDAT     TYPE VBRK-FKDAT,
        KUNAG     TYPE VBRK-KUNAG,
        NETWR     TYPE VBRK-NETWR,
        GSTIN     TYPE char15,
        HSN_CODE  TYPE char8,
        SAC_CODE  TYPE char6,
        IGST      TYPE p DECIMALS 2,
        CGST      TYPE p DECIMALS 2,
        SGST      TYPE p DECIMALS 2,
        CESS      TYPE p DECIMALS 2,
        IRN       TYPE char64,
      END OF lt_invoices.

* Build GSTR-1 from billing docs
  SELECT VBELN FKDAT KUNAG NETWR
    FROM VBRK
    INTO CORRESPONDING FIELDS OF TABLE lt_invoices
    WHERE BUKRS = '1000'
    AND   FKDAT BETWEEN '20240401' AND '20240430'.

  LOOP AT lt_invoices.
*   Get customer GSTIN
    SELECT SINGLE STCD3 INTO lt_invoices-GSTIN
      FROM KNA1
      WHERE KUNNR = lt_invoices-KUNAG.

*   Old excise tables — completely obsolete!
    SELECT SINGLE * FROM J_1IEXCHDR
      WHERE LIFNR = lt_invoices-KUNAG.
    SELECT SINGLE * FROM J_1IEXCDTL
      WHERE LIFNR = lt_invoices-KUNAG.

*   HSN/SAC code lookup
    SELECT SINGLE HSN_CODE INTO lt_invoices-HSN_CODE
      FROM ZTMM_HSN_MASTER
      WHERE MATNR = lt_invoices-VBELN+0(10).

*   E-invoice IRN check
    IF lt_invoices-NETWR > 500.
      CONCATENATE 'IRN' lt_invoices-VBELN INTO lt_invoices-IRN.
      WRITE: / 'E-Invoice IRN generated:', lt_invoices-IRN.
    ENDIF.

    MODIFY lt_invoices.
  ENDLOOP.

  WRITE: / 'GSTR-1 Preparation Complete'.
  DESCRIBE TABLE lt_invoices LINES DATA(lv_count).
  WRITE: / 'Total invoices:', lv_count.
""",

"ZFI_007_TDS_QUARTERLY": """*----------------------------------------------------------------------*
* Program: ZFI_007_TDS_QUARTERLY
* Description: TDS quarterly return (Form 26Q / 24Q / 27Q)
*----------------------------------------------------------------------*
REPORT ZFI_007_TDS_QUARTERLY.

TABLES: BSEG, BKPF, LFA1, WITH_ITEM.

DATA: lt_tds_items TYPE STANDARD TABLE OF WITH_ITEM WITH HEADER LINE.
DATA: lv_tds_amount TYPE p DECIMALS 2,
      lv_section TYPE char10.

  SELECT * FROM WITH_ITEM INTO TABLE lt_tds_items
    WHERE BUKRS = '1000'
    AND   GJAHR = '2024'.

  LOOP AT lt_tds_items.
    CASE lt_tds_items-WITHT.
      WHEN 'C1'. lv_section = '194C'.  "Contractor
      WHEN 'J1'. lv_section = '194J'.  "Professional
      WHEN 'I1'. lv_section = '194I'.  "Rent
      WHEN 'A1'. lv_section = '194A'.  "Interest
      WHEN 'H1'. lv_section = '194H'.  "Commission
      WHEN 'Q1'. lv_section = '194Q'.  "Purchase > 50L
    ENDCASE.

    MOVE lt_tds_items-WT_QSSHB TO lv_tds_amount.

*   Get vendor PAN for TDS certificate
    SELECT SINGLE STCD1 INTO DATA(lv_pan)
      FROM LFA1
      WHERE LIFNR = lt_tds_items-LIFNR.

*   PAN validation
    IF lv_pan IS INITIAL OR strlen( lv_pan ) <> 10.
      WRITE: / 'WARNING: Invalid PAN for vendor', lt_tds_items-LIFNR.
    ENDIF.

    WRITE: / lt_tds_items-LIFNR, lv_section,
             lt_tds_items-WT_QSSHB, 'PAN:', lv_pan.
  ENDLOOP.

* Prepare Form 26Q data for TRACES upload
  WRITE: / 'Form 26Q preparation complete'.
  WRITE: / 'Upload to TRACES portal for filing'.
""",

# ─────────────────────────────────────────────────────────────────
# BASIS / CROSS-MODULE / PERFORMANCE ANTI-PATTERNS
# ─────────────────────────────────────────────────────────────────

"ZUTIL_001_IDOC_MONITOR": """*----------------------------------------------------------------------*
* Program: ZUTIL_001_IDOC_MONITOR
* Description: Custom IDoc monitoring dashboard
*----------------------------------------------------------------------*
REPORT ZUTIL_001_IDOC_MONITOR.

TABLES: EDIDC, EDIDS, EDID4.

DATA: lt_idocs TYPE STANDARD TABLE OF EDIDC WITH HEADER LINE.
DATA: lv_count TYPE i.

  SELECT * FROM EDIDC INTO TABLE lt_idocs
    WHERE CREDAT >= sy-datum - 7
    AND   STATUS IN ('51', '56', '61', '64').

  DESCRIBE TABLE lt_idocs LINES lv_count.

* Classic dynpro screen to show results
  CALL SCREEN 100.

  LOOP AT lt_idocs.
    WRITE: / lt_idocs-DOCNUM, lt_idocs-MESTYP,
             lt_idocs-STATUS, lt_idocs-CREDAT, lt_idocs-CRETIM.
  ENDLOOP.

* SAPscript text for error description
  LOOP AT lt_idocs WHERE STATUS = '51'.
    CALL FUNCTION 'READ_TEXT'
      EXPORTING
        id       = 'ST'
        language = 'E'
        name     = lt_idocs-DOCNUM
        object   = 'IDOC'.
  ENDLOOP.
""",

"ZUTIL_002_PERFORMANCE_BAD": """*----------------------------------------------------------------------*
* Program: ZUTIL_002_PERFORMANCE_BAD
* Description: Intentionally bad performance patterns
* (everything you should NOT do on HANA)
*----------------------------------------------------------------------*
REPORT ZUTIL_002_PERFORMANCE_BAD.

TABLES: MARA, MARC, MARD, MBEW, EKKO, EKPO, LFA1.

DATA: lt_materials TYPE STANDARD TABLE OF MARA WITH HEADER LINE.
DATA: lv_total TYPE p DECIMALS 2.

* Anti-pattern 1: SELECT * (fetches ALL columns — terrible on HANA column store)
  SELECT * FROM MARA INTO TABLE lt_materials.

* Anti-pattern 2: SELECT inside LOOP (N+1 query problem)
  LOOP AT lt_materials.
    SELECT SINGLE * FROM MARC
      WHERE MATNR = lt_materials-MATNR
      AND   WERKS = '1001'.

    SELECT SINGLE * FROM MBEW
      WHERE MATNR = lt_materials-MATNR
      AND   BWKEY = '1001'.

    SELECT SINGLE * FROM MARD
      WHERE MATNR = lt_materials-MATNR
      AND   WERKS = '1001'
      AND   LGORT = '0001'.
  ENDLOOP.

* Anti-pattern 3: SELECT...ENDSELECT (row-by-row processing)
  SELECT MATNR WERKS FROM MARC
    INTO DATA(ls_marc)
    WHERE WERKS = '1001'.
    WRITE: / ls_marc-MATNR.
  ENDSELECT.

* Anti-pattern 4: NATIVE SQL (forbidden in S/4 Cloud!)
  EXEC SQL.
    SELECT MANDT, MATNR, MTART FROM MARA
    WHERE MANDT = :sy-mandt
  ENDEXEC.

* Anti-pattern 5: CLIENT SPECIFIED (restricted in Cloud)
  SELECT * FROM MARA CLIENT SPECIFIED
    INTO TABLE lt_materials
    WHERE MANDT = sy-mandt.

* Anti-pattern 6: OCCURS with arbitrary number
  DATA: lt_bad_table TYPE TABLE OF MARA OCCURS 9999 WITH HEADER LINE.

* Anti-pattern 7: Nested loop without hash table
  DATA: lt_pos TYPE TABLE OF EKPO.
  SELECT * FROM EKPO INTO TABLE lt_pos WHERE WERKS = '1001'.

  LOOP AT lt_materials.
    LOOP AT lt_pos WHERE MATNR = lt_materials-MATNR.
      ADD lt_pos-NETPR TO lv_total.
    ENDLOOP.
  ENDLOOP.

* Anti-pattern 8: COUNT(*) just to check existence
  SELECT COUNT(*) FROM EKKO
    WHERE LIFNR = '0000001000'
    AND   BSART = 'NB'.

* Anti-pattern 9: UP TO 1 ROWS instead of SELECT SINGLE
  SELECT * FROM MARA UP TO 1 ROWS
    INTO lt_materials
    WHERE MTART = 'FERT'.
  ENDSELECT.
""",

"ZUTIL_003_OO_ABAP_LEGACY": """*----------------------------------------------------------------------*
* Program: ZUTIL_003_OO_ABAP_LEGACY
* Description: OO ABAP with legacy patterns that need modernization
*----------------------------------------------------------------------*
REPORT ZUTIL_003_OO_ABAP_LEGACY.

CLASS lcl_processor DEFINITION.
  PUBLIC SECTION.
    METHODS: process_data,
             get_customer IMPORTING iv_kunnr TYPE kunnr
                          RETURNING VALUE(rs_customer) TYPE kna1.
  PRIVATE SECTION.
    DATA: mt_customers TYPE TABLE OF KNA1.
ENDCLASS.

CLASS lcl_processor IMPLEMENTATION.
  METHOD process_data.
    DATA: lo_alv TYPE REF TO cl_gui_alv_grid.

*   Legacy: CREATE OBJECT instead of NEW
    CREATE OBJECT lo_alv TYPE cl_gui_alv_grid
      EXPORTING
        i_parent = cl_gui_container=>default_screen.

*   Legacy: MOVE-CORRESPONDING instead of CORRESPONDING #()
    DATA: ls_source TYPE KNA1,
          ls_target TYPE KNA1.
    MOVE-CORRESPONDING ls_source TO ls_target.

*   Legacy: CATCH SYSTEM-EXCEPTIONS instead of TRY/CATCH
    CATCH SYSTEM-EXCEPTIONS arithmetic_errors = 1
                             conversion_errors = 2.
      DATA(lv_result) = 100 / 0.
    ENDCATCH.

*   Legacy: REFRESH instead of CLEAR
    REFRESH mt_customers.

*   Legacy: DESCRIBE TABLE instead of lines()
    DATA: lv_lines TYPE i.
    DESCRIBE TABLE mt_customers LINES lv_lines.

  ENDMETHOD.

  METHOD get_customer.
*   Direct KNA1 access (should use BP in S/4HANA)
    SELECT SINGLE * FROM KNA1 INTO rs_customer
      WHERE KUNNR = iv_kunnr.
  ENDMETHOD.
ENDCLASS.

START-OF-SELECTION.
  DATA: lo_proc TYPE REF TO lcl_processor.
  CREATE OBJECT lo_proc.
  lo_proc->process_data( ).
""",

"ZUTIL_004_SMARTFORM_INVOICE": """*----------------------------------------------------------------------*
* Program: ZUTIL_004_SMARTFORM_INVOICE
* Description: Invoice print via Smart Forms + SAPscript
*----------------------------------------------------------------------*
REPORT ZUTIL_004_SMARTFORM_INVOICE.

TABLES: VBRK, VBRP, KNA1.

DATA: lv_fm_name   TYPE rs38l_fnam,
      lv_formname  TYPE tdsfname VALUE 'ZSD_INVOICE_SF',
      ls_header    TYPE VBRK,
      lt_items     TYPE TABLE OF VBRP.

  SELECT SINGLE * FROM VBRK INTO ls_header
    WHERE VBELN = '0090001234'.

  SELECT * FROM VBRP INTO TABLE lt_items
    WHERE VBELN = ls_header-VBELN.

* Get customer info (KNA1 — deprecated, should use BP)
  SELECT SINGLE * FROM KNA1 INTO DATA(ls_customer)
    WHERE KUNNR = ls_header-KUNAG.

* Smart Form rendering
  CALL FUNCTION 'SSF_FUNCTION_MODULE_NAME'
    EXPORTING
      formname = lv_formname
    IMPORTING
      fm_name  = lv_fm_name.

  CALL FUNCTION lv_fm_name
    EXPORTING
      is_header   = ls_header
    TABLES
      it_items    = lt_items.

* Also read SAPscript text
  CALL FUNCTION 'READ_TEXT'
    EXPORTING
      id       = 'ST'
      language = 'E'
      name     = ls_header-VBELN
      object   = 'VBBK'.

* Download PDF (GUI dependent!)
  CALL FUNCTION 'GUI_DOWNLOAD'
    EXPORTING
      filename = 'C:/Invoices/invoice.pdf'
      filetype = 'BIN'.

* Also try old WS_DOWNLOAD
  CALL FUNCTION 'WS_DOWNLOAD'
    EXPORTING
      filename = 'C:/temp/backup.txt'.
""",

"ZMM_005_VENDOR_SCORECARD": """*----------------------------------------------------------------------*
* Program: ZMM_005_VENDOR_SCORECARD
* Description: Vendor performance scorecard
*----------------------------------------------------------------------*
REPORT ZMM_005_VENDOR_SCORECARD.

TABLES: LFA1, LFB1, LFM1, EKKO, EKPO.

DATA: lt_vendors LIKE LFA1 OCCURS 200 WITH HEADER LINE.
DATA: lv_score TYPE p DECIMALS 2.
DATA: lv_on_time TYPE i, lv_total_del TYPE i.

  SELECT * FROM LFA1 INTO TABLE lt_vendors.

  LOOP AT lt_vendors.
*   Get company code data (LFB1 also deprecated → BP)
    SELECT SINGLE * FROM LFB1 INTO DATA(ls_lfb1)
      WHERE LIFNR = lt_vendors-LIFNR
      AND   BUKRS = '1000'.

*   Get purchasing data (LFM1 also deprecated → BP)
    SELECT SINGLE * FROM LFM1 INTO DATA(ls_lfm1)
      WHERE LIFNR = lt_vendors-LIFNR.

*   Count POs and deliveries
    SELECT COUNT(*) INTO lv_total_del FROM EKKO
      WHERE LIFNR = lt_vendors-LIFNR
      AND   BSART = 'NB'.

    IF lv_total_del > 0.
      COMPUTE lv_score = lv_on_time / lv_total_del * 100.
    ENDIF.

    WRITE: / lt_vendors-LIFNR, lt_vendors-NAME1, lv_score.
    CLEAR: lv_on_time, lv_total_del, lv_score.
  ENDLOOP.

  CALL FUNCTION 'REUSE_ALV_HIERSEQ_LIST_DISPLAY'
    TABLES
      t_outtab_header = lt_vendors
      t_outtab_item   = lt_vendors.

  CALL FUNCTION 'WS_UPLOAD'
    EXPORTING
      filename = 'C:/upload/scores.csv'.
""",

# ─────────────────────────────────────────────────────────────────
# ADDITIONAL MIGRATION-CRITICAL PROGRAMS
# ─────────────────────────────────────────────────────────────────

"ZFI_ASSET_DEPRECIATION": """*----------------------------------------------------------------------*
* Program: ZFI_ASSET_DEPRECIATION
* Description: Fixed asset depreciation run and reporting
* Author: RAJESH.IYER
* Date: 20170315
*----------------------------------------------------------------------*
REPORT ZFI_ASSET_DEPRECIATION.

TABLES: ANLA, ANLP, ANLB, ANEK, ANEP, T093.

DATA: BEGIN OF lt_assets OCCURS 0,
        BUKRS TYPE ANLA-BUKRS,
        ANLN1 TYPE ANLA-ANLN1,
        ANLN2 TYPE ANLA-ANLN2,
        TXT50 TYPE ANLA-TXT50,
        AKTIV TYPE ANLA-AKTIV,
        NDJAR TYPE ANLB-NDJAR,
        KANSW TYPE ANLP-KANSW,
        NAFAZ TYPE ANLP-NAFAZ,
      END OF lt_assets.

DATA: lv_total_acq TYPE anlp-kansw,
      lv_total_dep TYPE anlp-nafaz,
      lv_nbv       TYPE anlp-kansw,
      lv_lines     TYPE i.

PARAMETERS: p_bukrs TYPE anla-bukrs DEFAULT '1000',
            p_gjahr TYPE anlp-gjahr DEFAULT '2024',
            p_afasl TYPE anlb-afasl DEFAULT '0010'.

START-OF-SELECTION.

* Get asset master data from ANLA (table remains but CDS preferred in S/4)
  SELECT * FROM ANLA
    INTO CORRESPONDING FIELDS OF TABLE lt_assets
    WHERE BUKRS = p_bukrs
    AND   DEAKT = '00000000'.

  DESCRIBE TABLE lt_assets LINES lv_lines.

  LOOP AT lt_assets.
*   Get depreciation values from ANLP (posted depreciation)
    SELECT SINGLE KANSW NAFAZ FROM ANLP
      INTO (lt_assets-KANSW, lt_assets-NAFAZ)
      WHERE BUKRS = p_bukrs
      AND   ANLN1 = lt_assets-ANLN1
      AND   ANLN2 = lt_assets-ANLN2
      AND   GJAHR = p_gjahr
      AND   AFABE = '01'.

    ADD lt_assets-KANSW TO lv_total_acq.
    ADD lt_assets-NAFAZ TO lv_total_dep.

    MODIFY lt_assets.
  ENDLOOP.

  COMPUTE lv_nbv = lv_total_acq - lv_total_dep.

* Post depreciation run via BAPI
  CALL FUNCTION 'BAPI_ASSET_ACQUISITION_POST'
    EXPORTING
      companycode = p_bukrs.

  CALL FUNCTION 'BAPI_TRANSACTION_COMMIT'.

  WRITE: / 'Asset Count:', lv_lines.
  WRITE: / 'Total Acquisition:', lv_total_acq.
  WRITE: / 'Total Depreciation:', lv_total_dep.
  WRITE: / 'Net Book Value:', lv_nbv.

  CALL FUNCTION 'REUSE_ALV_LIST_DISPLAY'
    EXPORTING
      i_structure_name = 'ANLA'
    TABLES
      t_outtab         = lt_assets.
""",

"ZMM_BATCH_MANAGEMENT": """*----------------------------------------------------------------------*
* Program: ZMM_BATCH_MANAGEMENT
* Description: Batch creation and management for raw materials
* Author: SURESH.PATEL
* Date: 20180622
*----------------------------------------------------------------------*
REPORT ZMM_BATCH_MANAGEMENT.

TABLES: MCH1, MCHA, MCHB, MARA, MARC.

DATA: BEGIN OF lt_batches OCCURS 0,
        MATNR TYPE MCH1-MATNR,
        CHARG TYPE MCH1-CHARG,
        WERKS TYPE MCHA-WERKS,
        CLABS TYPE MCHB-CLABS,
        HSDAT TYPE MCH1-HSDAT,
        VFDAT TYPE MCH1-VFDAT,
      END OF lt_batches.

DATA: lt_return LIKE BAPIRET2 OCCURS 0 WITH HEADER LINE.
DATA: lv_batch  TYPE MCH1-CHARG,
      lv_count  TYPE i,
      lv_msg    TYPE string.

PARAMETERS: p_matnr TYPE mara-matnr OBLIGATORY,
            p_werks TYPE marc-werks DEFAULT '1000',
            p_charg TYPE mch1-charg.

START-OF-SELECTION.

* Read existing batches from MCH1 (batch master)
  SELECT * FROM MCH1
    INTO CORRESPONDING FIELDS OF TABLE lt_batches
    WHERE MATNR = p_matnr.

  IF sy-subrc <> 0.
    MESSAGE 'No batches found' TYPE 'I'.
    RETURN.
  ENDIF.

* Get plant-specific batch data from MCHA
  LOOP AT lt_batches.
    SELECT SINGLE * FROM MCHA
      INTO CORRESPONDING FIELDS OF lt_batches
      WHERE MATNR = lt_batches-MATNR
      AND   CHARG = lt_batches-CHARG
      AND   WERKS = p_werks.

*   Get stock from MCHB (batch stocks)
    SELECT SINGLE CLABS FROM MCHB
      INTO lt_batches-CLABS
      WHERE MATNR = lt_batches-MATNR
      AND   CHARG = lt_batches-CHARG
      AND   WERKS = p_werks
      AND   LGORT = '0001'.

    ADD 1 TO lv_count.
    MODIFY lt_batches.
  ENDLOOP.

* Create new batch via BAPI
  IF p_charg IS NOT INITIAL.
    CALL FUNCTION 'BAPI_BATCH_CREATE'
      EXPORTING
        material = p_matnr
        batch    = p_charg
        plant    = p_werks
      IMPORTING
        batch    = lv_batch
      TABLES
        return   = lt_return.

    LOOP AT lt_return WHERE type = 'E'.
      CONCATENATE 'Error:' lt_return-message INTO lv_msg SEPARATED BY ' '.
      WRITE: / lv_msg.
    ENDLOOP.

    CALL FUNCTION 'BAPI_TRANSACTION_COMMIT'.
  ENDIF.

  WRITE: / 'Total batches:', lv_count.

  CALL FUNCTION 'REUSE_ALV_GRID_DISPLAY'
    EXPORTING
      i_structure_name = 'MCH1'
    TABLES
      t_outtab         = lt_batches.
""",

"ZPM_WORK_ORDER": """*----------------------------------------------------------------------*
* Program: ZPM_WORK_ORDER
* Description: Plant maintenance work order creation and status
* Author: VIKRAM.SINGH
* Date: 20190405
*----------------------------------------------------------------------*
REPORT ZPM_WORK_ORDER.

TABLES: AUFK, AFKO, AFIH, ILOA, EQUI, TPLNR.

DATA: BEGIN OF lt_orders OCCURS 0,
        AUFNR TYPE AUFK-AUFNR,
        AUART TYPE AUFK-AUART,
        KTEXT TYPE AUFK-KTEXT,
        ERDAT TYPE AUFK-ERDAT,
        TPLNR TYPE ILOA-TPLNR,
        EQUNR TYPE ILOA-EQUNR,
        GSTRP TYPE AFKO-GSTRP,
        GLTRP TYPE AFKO-GLTRP,
        AUSVN TYPE AUFK-AUSVN,
      END OF lt_orders.

DATA: lt_return LIKE BAPIRET2 OCCURS 0 WITH HEADER LINE.
DATA: lv_aufnr  TYPE aufk-aufnr,
      lv_count  TYPE i,
      lv_overdue TYPE i.

PARAMETERS: p_werks TYPE iloa-swerk DEFAULT '1000',
            p_auart TYPE aufk-auart DEFAULT 'PM01',
            p_datum TYPE sy-datum DEFAULT sy-datum.

START-OF-SELECTION.

* Get maintenance orders from AUFK
  SELECT * FROM AUFK
    INTO CORRESPONDING FIELDS OF TABLE lt_orders
    WHERE AUART = p_auart
    AND   ERDAT >= '20230101'.

  LOOP AT lt_orders.
*   Get scheduling data from AFKO
    SELECT SINGLE GSTRP GLTRP FROM AFKO
      INTO (lt_orders-GSTRP, lt_orders-GLTRP)
      WHERE AUFNR = lt_orders-AUFNR.

*   Get location data from ILOA
    SELECT SINGLE TPLNR EQUNR FROM ILOA
      INTO (lt_orders-TPLNR, lt_orders-EQUNR)
      WHERE AUFNR = lt_orders-AUFNR.

*   Count overdue
    IF lt_orders-GLTRP < p_datum AND lt_orders-AUSVN < '90'.
      ADD 1 TO lv_overdue.
    ENDIF.

    ADD 1 TO lv_count.
    MODIFY lt_orders.
  ENDLOOP.

* Create new order via BAPI
  CALL FUNCTION 'BAPI_ALM_ORDER_CREATE'
    EXPORTING
      it_header  = lt_orders
    IMPORTING
      es_order   = lv_aufnr
    TABLES
      return     = lt_return.

  CALL FUNCTION 'BAPI_TRANSACTION_COMMIT'.

  WRITE: / 'Total orders:', lv_count.
  WRITE: / 'Overdue orders:', lv_overdue.

  CALL FUNCTION 'REUSE_ALV_LIST_DISPLAY'
    EXPORTING
      i_structure_name = 'AUFK'
    TABLES
      t_outtab         = lt_orders.
""",

"ZQM_INSPECTION": """*----------------------------------------------------------------------*
* Program: ZQM_INSPECTION
* Description: Quality inspection lot processing and results recording
* Author: PRIYA.NAIR
* Date: 20200118
*----------------------------------------------------------------------*
REPORT ZQM_INSPECTION.

TABLES: QALS, QAVE, QASR, QAMR, QAPP.

DATA: BEGIN OF lt_lots OCCURS 0,
        PRUEFLOS TYPE QALS-PRUEFLOS,
        MATNR    TYPE QALS-MATNR,
        CHARG    TYPE QALS-CHARG,
        WERK     TYPE QALS-WERK,
        ART      TYPE QALS-ART,
        HERESSION TYPE QALS-HERESSION,
        STAT     TYPE QALS-STAT,
        VCODE    TYPE QAVE-VCODE,
      END OF lt_lots.

DATA: lt_return LIKE BAPIRET2 OCCURS 0 WITH HEADER LINE.
DATA: lv_count TYPE i,
      lv_pass  TYPE i,
      lv_fail  TYPE i.

FIELD-SYMBOLS: <fs_lot> TYPE ANY.

PARAMETERS: p_werk  TYPE qals-werk DEFAULT '1000',
            p_art   TYPE qals-art  DEFAULT '01',
            p_datum TYPE sy-datum DEFAULT sy-datum.

START-OF-SELECTION.

* Get inspection lots from QALS
  SELECT * FROM QALS
    INTO CORRESPONDING FIELDS OF TABLE lt_lots
    WHERE WERK = p_werk
    AND   ART  = p_art
    AND   ERDAT >= '20230101'.

  DESCRIBE TABLE lt_lots LINES lv_count.

  LOOP AT lt_lots.
*   Get usage decision from QAVE
    SELECT SINGLE VCODE FROM QAVE
      INTO lt_lots-VCODE
      WHERE PRUEFLOS = lt_lots-PRUEFLOS.

    IF lt_lots-VCODE = 'A' OR lt_lots-VCODE = 'A1'.
      ADD 1 TO lv_pass.
    ELSE.
      ADD 1 TO lv_fail.
    ENDIF.

    MODIFY lt_lots.
  ENDLOOP.

* Record inspection results via BAPI
  CALL FUNCTION 'BAPI_INSPOPER_RECORDRESULTS'
    TABLES
      return = lt_return.

  LOOP AT lt_return WHERE type = 'E'.
    WRITE: / 'Error:', lt_return-message.
  ENDLOOP.

  CALL FUNCTION 'BAPI_TRANSACTION_COMMIT'.

  TRANSLATE p_werk TO UPPER CASE.

  WRITE: / 'Plant:', p_werk.
  WRITE: / 'Total lots:', lv_count.
  WRITE: / 'Passed:', lv_pass.
  WRITE: / 'Failed:', lv_fail.

  CALL FUNCTION 'REUSE_ALV_GRID_DISPLAY'
    EXPORTING
      i_structure_name = 'QALS'
    TABLES
      t_outtab         = lt_lots.
""",

"ZSD_CREDIT_MGMT": """*----------------------------------------------------------------------*
* Program: ZSD_CREDIT_MGMT
* Description: Customer credit management check and exposure report
* Author: ANITA.RAO
* Date: 20180910
*----------------------------------------------------------------------*
REPORT ZSD_CREDIT_MGMT.

TABLES: KNA1, KNB1, KNKK, VBAK, VBAP, BSID.

DATA: BEGIN OF lt_credit OCCURS 0,
        KUNNR TYPE KNA1-KUNNR,
        NAME1 TYPE KNA1-NAME1,
        KLIMK TYPE KNKK-KLIMK,
        SKFOR TYPE KNKK-SKFOR,
        SSOBL TYPE KNKK-SSOBL,
        OPEN_ITEMS TYPE BSID-DMBTR,
        EXPOSURE TYPE BSID-DMBTR,
      END OF lt_credit.

DATA: lt_open LIKE BSID OCCURS 100 WITH HEADER LINE.
DATA: lv_total_exp  TYPE bsid-dmbtr,
      lv_overlimit  TYPE i,
      lv_count      TYPE i,
      lv_cust_name  TYPE string.

PARAMETERS: p_bukrs TYPE knb1-bukrs DEFAULT '1000',
            p_kkber TYPE knkk-kkber DEFAULT '1000'.

START-OF-SELECTION.

* Get customer credit data from KNKK (credit master)
  SELECT * FROM KNKK
    INTO CORRESPONDING FIELDS OF TABLE lt_credit
    WHERE KKBER = p_kkber.

  LOOP AT lt_credit.
*   Get customer name from KNA1 (deprecated → BP in S/4)
    SELECT SINGLE NAME1 FROM KNA1
      INTO lt_credit-NAME1
      WHERE KUNNR = lt_credit-KUNNR.

*   Get open receivables from BSID (open AR items → ACDOCA)
    SELECT SUM( DMBTR ) FROM BSID
      INTO lt_credit-OPEN_ITEMS
      WHERE BUKRS = p_bukrs
      AND   KUNNR = lt_credit-KUNNR.

*   Calculate total exposure
    COMPUTE lt_credit-EXPOSURE = lt_credit-OPEN_ITEMS + lt_credit-SKFOR + lt_credit-SSOBL.
    ADD lt_credit-EXPOSURE TO lv_total_exp.

*   Check if over credit limit
    IF lt_credit-EXPOSURE > lt_credit-KLIMK AND lt_credit-KLIMK > 0.
      ADD 1 TO lv_overlimit.
    ENDIF.

    ADD 1 TO lv_count.
    MODIFY lt_credit.
  ENDLOOP.

* In S/4HANA, use UKM (Unified Credit Management) instead of KNKK
  CONCATENATE 'Total customers:' lv_count INTO lv_cust_name SEPARATED BY ' '.

  WRITE: / lv_cust_name.
  WRITE: / 'Over credit limit:', lv_overlimit.
  WRITE: / 'Total exposure:', lv_total_exp.

  CALL FUNCTION 'REUSE_ALV_GRID_DISPLAY'
    EXPORTING
      i_structure_name = 'KNKK'
    TABLES
      t_outtab         = lt_credit.

  CALL FUNCTION 'GUI_DOWNLOAD'
    EXPORTING
      filename = 'C:/reports/credit_exposure.xlsx'
      filetype = 'ASC'.
""",

"ZCO_PROFITABILITY": """*----------------------------------------------------------------------*
* Program: ZCO_PROFITABILITY
* Description: CO-PA profitability analysis and segment reporting
* Author: DEEPAK.GUPTA
* Date: 20190728
*----------------------------------------------------------------------*
REPORT ZCO_PROFITABILITY.

TABLES: CE1T800, CE2T800, TKA01, CSKS, CEPC.

DATA: BEGIN OF lt_copa OCCURS 0,
        PESSION TYPE CE1T800-PESSION,
        VRGAR   TYPE CE1T800-VRGAR,
        BUKRS   TYPE CE1T800-BUKRS,
        GJAHR   TYPE CE1T800-GJAHR,
        PERDE   TYPE CE1T800-PERDE,
        VKORG   TYPE CE1T800-VKORG,
        ARTNR   TYPE CE1T800-ARTNR,
        VV010   TYPE CE1T800-VV010,
        VV020   TYPE CE1T800-VV020,
      END OF lt_copa.

DATA: lv_revenue  TYPE ce1t800-vv010,
      lv_cost     TYPE ce1t800-vv020,
      lv_margin   TYPE ce1t800-vv010,
      lv_pct      TYPE p DECIMALS 2,
      lv_lines    TYPE i.

FIELD-SYMBOLS: <fs_copa> TYPE ANY.

PARAMETERS: p_bukrs TYPE ce1t800-bukrs DEFAULT '1000',
            p_gjahr TYPE ce1t800-gjahr DEFAULT '2024'.

START-OF-SELECTION.

* Read CO-PA actual line items from CE1xxxx (operating concern T800)
  SELECT * FROM CE1T800
    INTO CORRESPONDING FIELDS OF TABLE lt_copa
    WHERE BUKRS = p_bukrs
    AND   GJAHR = p_gjahr
    AND   VRGAR = 'F'.

  DESCRIBE TABLE lt_copa LINES lv_lines.

  LOOP AT lt_copa.
    ADD lt_copa-VV010 TO lv_revenue.
    ADD lt_copa-VV020 TO lv_cost.
    MODIFY lt_copa.
  ENDLOOP.

  COMPUTE lv_margin = lv_revenue - lv_cost.
  IF lv_revenue > 0.
    COMPUTE lv_pct = lv_margin / lv_revenue * 100.
  ENDIF.

* In S/4HANA, CO-PA is account-based by default (not costing-based).
* CE1xxxx/CE2xxxx tables may need review for compatibility.

* Get cost center data from COEP (CO line items → ACDOCA in S/4)
  SELECT * FROM COEP
    INTO CORRESPONDING FIELDS OF TABLE lt_copa
    WHERE BUKRS = p_bukrs
    AND   GJAHR = p_gjahr
    UP TO 100 ROWS.

  TRANSLATE p_bukrs TO UPPER CASE.

  WRITE: / 'Company Code:', p_bukrs.
  WRITE: / 'Revenue:', lv_revenue.
  WRITE: / 'Cost:', lv_cost.
  WRITE: / 'Margin:', lv_margin.
  WRITE: / 'Margin %:', lv_pct.
  WRITE: / 'Line items:', lv_lines.

  CALL FUNCTION 'REUSE_ALV_LIST_DISPLAY'
    EXPORTING
      i_structure_name = 'CE1T800'
    TABLES
      t_outtab         = lt_copa.
""",

"ZWM_TRANSFER_ORDER": """*----------------------------------------------------------------------*
* Program: ZWM_TRANSFER_ORDER
* Description: Warehouse transfer order creation and confirmation
* Author: MOHAN.KRISHNA
* Date: 20180215
*----------------------------------------------------------------------*
REPORT ZWM_TRANSFER_ORDER.

TABLES: LQUA, LTAP, LTAK, LAGP, T300.

DATA: BEGIN OF lt_quants OCCURS 0,
        LGNUM TYPE LQUA-LGNUM,
        LGTYP TYPE LQUA-LGTYP,
        LGPLA TYPE LQUA-LGPLA,
        MATNR TYPE LQUA-MATNR,
        GESME TYPE LQUA-GESME,
        MEINS TYPE LQUA-MEINS,
        CHARG TYPE LQUA-CHARG,
        BESTQ TYPE LQUA-BESTQ,
      END OF lt_quants.

DATA: BEGIN OF lt_to_items OCCURS 0,
        TANUM TYPE LTAP-TANUM,
        TAPOS TYPE LTAP-TAPOS,
        MATNR TYPE LTAP-MATNR,
        VLTYP TYPE LTAP-VLTYP,
        VLPLA TYPE LTAP-VLPLA,
        NLTYP TYPE LTAP-NLTYP,
        NLPLA TYPE LTAP-NLPLA,
        VSOLM TYPE LTAP-VSOLM,
      END OF lt_to_items.

DATA: lt_return LIKE BAPIRET2 OCCURS 0 WITH HEADER LINE.
DATA: lv_tanum   TYPE ltak-tanum,
      lv_count   TYPE i,
      lv_total_q TYPE lqua-gesme.

PARAMETERS: p_lgnum TYPE lqua-lgnum DEFAULT '100',
            p_lgtyp TYPE lqua-lgtyp DEFAULT '001',
            p_matnr TYPE lqua-matnr.

START-OF-SELECTION.

* Get warehouse quants from LQUA (stock per storage bin)
  SELECT * FROM LQUA
    INTO CORRESPONDING FIELDS OF TABLE lt_quants
    WHERE LGNUM = p_lgnum
    AND   LGTYP = p_lgtyp
    AND   BESTQ = ' '.

  DESCRIBE TABLE lt_quants LINES lv_count.

  LOOP AT lt_quants.
    ADD lt_quants-GESME TO lv_total_q.

*   Get existing TOs for this material from LTAP
    SELECT * FROM LTAP
      APPENDING CORRESPONDING FIELDS OF TABLE lt_to_items
      WHERE LGNUM = p_lgnum
      AND   MATNR = lt_quants-MATNR.
  ENDLOOP.

* Create transfer order via BAPI
* Note: In S/4HANA with EWM, WM is deprecated — use EWM APIs instead
  CALL FUNCTION 'BAPI_WHSE_TO_CREATE'
    EXPORTING
      warehouse_number = p_lgnum
    IMPORTING
      to_number        = lv_tanum
    TABLES
      return           = lt_return.

  LOOP AT lt_return WHERE type = 'E'.
    WRITE: / 'Error:', lt_return-message.
  ENDLOOP.

  CALL FUNCTION 'BAPI_TRANSACTION_COMMIT'.

  WRITE: / 'Warehouse:', p_lgnum.
  WRITE: / 'Storage bins:', lv_count.
  WRITE: / 'Total quantity:', lv_total_q.
  WRITE: / 'TO Number:', lv_tanum.

  CALL FUNCTION 'REUSE_ALV_GRID_DISPLAY'
    EXPORTING
      i_structure_name = 'LQUA'
    TABLES
      t_outtab         = lt_quants.

  CALL FUNCTION 'GUI_DOWNLOAD'
    EXPORTING
      filename = 'C:/wm/transfer_orders.csv'
      filetype = 'ASC'.
""",

# ─────────────────────────────────────────────────────────────────
# TREASURY PROGRAMS
# ─────────────────────────────────────────────────────────────────

"ZTR_CASH_POSITION": """*----------------------------------------------------------------------*
* Program: ZTR_CASH_POSITION
* Description: Treasury cash position report across all bank accounts
* Author: MAHESH.IYER
* Date: 20170825
*----------------------------------------------------------------------*
REPORT ZTR_CASH_POSITION.

TABLES: FEBEP, FEBKO, T012, T012K, BNKA.

DATA: BEGIN OF lt_cash OCCURS 0,
        BUKRS TYPE FEBEP-BUKRS,
        HBKID TYPE FEBEP-HBKID,
        HKTID TYPE FEBEP-HKTID,
        VALUT TYPE FEBEP-VALUT,
        KWBTR TYPE FEBEP-KWBTR,
        SHKZG TYPE FEBEP-SHKZG,
      END OF lt_cash.

DATA: lv_total_in  TYPE p DECIMALS 2,
      lv_total_out TYPE p DECIMALS 2,
      lv_balance   TYPE p DECIMALS 2.

PARAMETERS: p_bukrs TYPE FEBEP-BUKRS DEFAULT '1000',
            p_datum TYPE sy-datum DEFAULT sy-datum.

START-OF-SELECTION.

  SELECT * FROM FEBEP
    INTO CORRESPONDING FIELDS OF TABLE lt_cash
    WHERE BUKRS = p_bukrs
    AND   VALUT <= p_datum.

  LOOP AT lt_cash.
    SELECT SINGLE * FROM BNKA INTO CORRESPONDING FIELDS OF lt_cash
      WHERE BANKL = lt_cash-HBKID.

    IF lt_cash-SHKZG = 'S'.
      ADD lt_cash-KWBTR TO lv_total_in.
    ELSE.
      ADD lt_cash-KWBTR TO lv_total_out.
    ENDIF.
  ENDLOOP.

  COMPUTE lv_balance = lv_total_in - lv_total_out.

  WRITE: / 'Company Code:', p_bukrs.
  WRITE: / 'Cash Inflows:', lv_total_in.
  WRITE: / 'Cash Outflows:', lv_total_out.
  WRITE: / 'Net Position:', lv_balance.

  CALL FUNCTION 'REUSE_ALV_GRID_DISPLAY'
    EXPORTING
      i_structure_name = 'FEBEP'
    TABLES
      t_outtab         = lt_cash.
""",

"ZTR_FX_REVALUATION": """*----------------------------------------------------------------------*
* Program: ZTR_FX_REVALUATION
* Description: Foreign exchange revaluation for open items
* Author: DEEPA.MEHTA
* Date: 20180312
*----------------------------------------------------------------------*
REPORT ZTR_FX_REVALUATION.

TABLES: BSEG, BKPF, TCURR, T001.

DATA: BEGIN OF lt_open OCCURS 0,
        BUKRS TYPE BSEG-BUKRS,
        BELNR TYPE BSEG-BELNR,
        GJAHR TYPE BSEG-GJAHR,
        DMBTR TYPE BSEG-DMBTR,
        WRBTR TYPE BSEG-WRBTR,
        WAERS TYPE BKPF-WAERS,
        HKONT TYPE BSEG-HKONT,
      END OF lt_open.

DATA: lv_rate_old TYPE tcurr-ukurs,
      lv_rate_new TYPE tcurr-ukurs,
      lv_diff     TYPE p DECIMALS 2,
      lv_total    TYPE p DECIMALS 2.

PARAMETERS: p_bukrs TYPE BKPF-BUKRS DEFAULT '2000',
            p_date  TYPE sy-datum DEFAULT sy-datum.

START-OF-SELECTION.

  SELECT * FROM BSEG
    INTO CORRESPONDING FIELDS OF TABLE lt_open
    WHERE BUKRS = p_bukrs
    AND   AUGDT = '00000000'.

  LOOP AT lt_open.
    SELECT SINGLE * FROM TCURR
      WHERE KURST = 'M'
      AND   FCURR = lt_open-WAERS
      AND   TCURR = 'INR'.

    MOVE TCURR-UKURS TO lv_rate_new.

    COMPUTE lv_diff = lt_open-WRBTR * ( lv_rate_new - lv_rate_old ).
    ADD lv_diff TO lv_total.

    WRITE: / lt_open-BELNR, lt_open-WAERS, lt_open-WRBTR,
             lv_rate_new, lv_diff.
  ENDLOOP.

  WRITE: / 'Total FX Revaluation:', lv_total.
""",

"ZTR_BANK_RECONCILIATION": """*----------------------------------------------------------------------*
* Program: ZTR_BANK_RECONCILIATION
* Description: Auto bank reconciliation matching SAP to bank statement
* Author: SANJAY.GUPTA
* Date: 20190104
*----------------------------------------------------------------------*
REPORT ZTR_BANK_RECONCILIATION.

TABLES: FEBEP, BSEG, BKPF, T012.

DATA: BEGIN OF lt_bank OCCURS 0,
        KUESSION TYPE FEBEP-ESESSION,
        VALUT    TYPE FEBEP-VALUT,
        KWBTR    TYPE FEBEP-KWBTR,
        VESSION  TYPE FEBEP-VESSION,
      END OF lt_bank.

DATA: BEGIN OF lt_sap OCCURS 0,
        BELNR TYPE BSEG-BELNR,
        BUDAT TYPE BKPF-BUDAT,
        DMBTR TYPE BSEG-DMBTR,
      END OF lt_sap.

DATA: lv_matched   TYPE i,
      lv_unmatched TYPE i.

PARAMETERS: p_bukrs TYPE BKPF-BUKRS DEFAULT '1000',
            p_hbkid TYPE FEBEP-HBKID.

START-OF-SELECTION.

  SELECT * FROM FEBEP INTO CORRESPONDING FIELDS OF TABLE lt_bank
    WHERE BUKRS = p_bukrs AND HBKID = p_hbkid.

  SELECT * FROM BSEG INTO CORRESPONDING FIELDS OF TABLE lt_sap
    WHERE BUKRS = p_bukrs AND HKONT LIKE '1131%'.

  LOOP AT lt_bank.
    READ TABLE lt_sap WITH KEY DMBTR = lt_bank-KWBTR.
    IF sy-subrc = 0.
      ADD 1 TO lv_matched.
    ELSE.
      ADD 1 TO lv_unmatched.
    ENDIF.
  ENDLOOP.

  WRITE: / 'Matched:', lv_matched, 'Unmatched:', lv_unmatched.
""",

"ZTR_PAYMENT_FACTORY": """*----------------------------------------------------------------------*
* Program: ZTR_PAYMENT_FACTORY
* Description: Central payment factory processing for all company codes
* Author: VIJAY.SHARMA
* Date: 20200618
*----------------------------------------------------------------------*
REPORT ZTR_PAYMENT_FACTORY.

TABLES: BSIK, BSAK, LFA1, T042Z.

DATA: BEGIN OF lt_payments OCCURS 0,
        BUKRS TYPE BSIK-BUKRS,
        LIFNR TYPE BSIK-LIFNR,
        BELNR TYPE BSIK-BELNR,
        DMBTR TYPE BSIK-DMBTR,
        ZFBDT TYPE BSIK-ZFBDT,
        ZLSPR TYPE BSIK-ZLSPR,
      END OF lt_payments.

DATA: lv_total TYPE p DECIMALS 2,
      lv_count TYPE i.

SELECT-OPTIONS: s_bukrs FOR BSIK-BUKRS,
                s_lifnr FOR BSIK-LIFNR.

START-OF-SELECTION.

  SELECT * FROM BSIK INTO CORRESPONDING FIELDS OF TABLE lt_payments
    WHERE BUKRS IN s_bukrs
    AND   LIFNR IN s_lifnr
    AND   ZLSPR = ' '.

  LOOP AT lt_payments.
    SELECT SINGLE * FROM LFA1 WHERE LIFNR = lt_payments-LIFNR.

    MOVE lt_payments-DMBTR TO lv_total.
    ADD 1 TO lv_count.

    CALL FUNCTION 'BAPI_ACC_DOCUMENT_POST'
      EXPORTING
        documentheader = ls_header.

    COMMIT WORK.
  ENDLOOP.

  WRITE: / 'Payments processed:', lv_count, 'Total:', lv_total.
""",

"ZTR_CASH_FORECAST": """*----------------------------------------------------------------------*
* Program: ZTR_CASH_FORECAST
* Description: 30-day rolling cash flow forecast
* Author: KAVITA.RAO
* Date: 20210309
*----------------------------------------------------------------------*
REPORT ZTR_CASH_FORECAST.

TABLES: BSID, BSIK, FEBEP, T001.

DATA: BEGIN OF lt_forecast OCCURS 0,
        BUKRS  TYPE BSID-BUKRS,
        FDATE  TYPE sy-datum,
        INFLOW TYPE p DECIMALS 2,
        OUTFLOW TYPE p DECIMALS 2,
      END OF lt_forecast.

DATA: lv_day TYPE i.

PARAMETERS: p_bukrs TYPE BKPF-BUKRS DEFAULT '1000'.

START-OF-SELECTION.

  SELECT * FROM BSID
    INTO CORRESPONDING FIELDS OF TABLE lt_forecast
    WHERE BUKRS = p_bukrs
    AND   ZFBDT BETWEEN sy-datum AND sy-datum + 30.

  SELECT * FROM BSIK
    APPENDING CORRESPONDING FIELDS OF TABLE lt_forecast
    WHERE BUKRS = p_bukrs
    AND   ZFBDT BETWEEN sy-datum AND sy-datum + 30.

  SORT lt_forecast BY FDATE.

  LOOP AT lt_forecast.
    WRITE: / lt_forecast-FDATE, lt_forecast-INFLOW, lt_forecast-OUTFLOW.
  ENDLOOP.

  CALL FUNCTION 'REUSE_ALV_LIST_DISPLAY'
    EXPORTING
      i_structure_name = 'BSEG'
    TABLES
      t_outtab         = lt_forecast.
""",

# ─────────────────────────────────────────────────────────────────
# PROJECT SYSTEMS PROGRAMS
# ─────────────────────────────────────────────────────────────────

"ZPS_WBS_REPORT": """*----------------------------------------------------------------------*
* Program: ZPS_WBS_REPORT
* Description: WBS element status report with budget vs actuals
* Author: ARUN.JOSHI
* Date: 20170516
*----------------------------------------------------------------------*
REPORT ZPS_WBS_REPORT.

TABLES: PRPS, PROJ, BPGE, COSP.

DATA: BEGIN OF lt_wbs OCCURS 0,
        PSPNR  TYPE PRPS-PSPNR,
        POSID  TYPE PRPS-POSID,
        POST1  TYPE PRPS-POST1,
        PSPHI  TYPE PRPS-PSPHI,
        BUDGET TYPE BPGE-WTJHR,
        ACTUAL TYPE COSP-WTG001,
      END OF lt_wbs.

DATA: lv_variance TYPE p DECIMALS 2.

PARAMETERS: p_pspid TYPE PROJ-PSPID.

START-OF-SELECTION.

  SELECT * FROM PRPS INTO CORRESPONDING FIELDS OF TABLE lt_wbs
    WHERE PSPHI = ( SELECT PSPNR FROM PROJ WHERE PSPID = p_pspid ).

  LOOP AT lt_wbs.
    SELECT SINGLE * FROM BPGE WHERE OBJNR = lt_wbs-PSPNR.
    SELECT SINGLE * FROM COSP WHERE OBJNR = lt_wbs-PSPNR.

    COMPUTE lv_variance = lt_wbs-BUDGET - lt_wbs-ACTUAL.

    WRITE: / lt_wbs-POSID, lt_wbs-POST1,
             lt_wbs-BUDGET, lt_wbs-ACTUAL, lv_variance.
  ENDLOOP.
""",

"ZPS_NETWORK_SCHEDULE": """*----------------------------------------------------------------------*
* Program: ZPS_NETWORK_SCHEDULE
* Description: Project network scheduling with critical path
* Author: RAJESH.PATEL
* Date: 20180923
*----------------------------------------------------------------------*
REPORT ZPS_NETWORK_SCHEDULE.

TABLES: AUFK, AFVC, AFVV, PROJ.

DATA: BEGIN OF lt_activities OCCURS 0,
        AUFNR  TYPE AUFK-AUFNR,
        VORNR  TYPE AFVC-VORNR,
        LTXA1  TYPE AFVC-LTXA1,
        FSAVD  TYPE AFVC-FSAVD,
        FSSBD  TYPE AFVC-FSSBD,
        DAESSION TYPE AFVV-DAESSION,
      END OF lt_activities.

PARAMETERS: p_pspid TYPE PROJ-PSPID.

START-OF-SELECTION.

  SELECT * FROM AFVC INTO CORRESPONDING FIELDS OF TABLE lt_activities
    WHERE AUFPL IN ( SELECT AUFPL FROM AUFK WHERE AUFNR LIKE p_pspid ).

  SORT lt_activities BY FSAVD.

  LOOP AT lt_activities.
    WRITE: / lt_activities-VORNR, lt_activities-LTXA1,
             lt_activities-FSAVD, lt_activities-FSSBD.
  ENDLOOP.

  CALL FUNCTION 'REUSE_ALV_GRID_DISPLAY'
    EXPORTING
      i_structure_name = 'AFVC'
    TABLES
      t_outtab         = lt_activities.
""",

"ZPS_BUDGET_TRANSFER": """*----------------------------------------------------------------------*
* Program: ZPS_BUDGET_TRANSFER
* Description: Budget transfer between WBS elements
* Author: SUNITA.NAIR
* Date: 20190207
*----------------------------------------------------------------------*
REPORT ZPS_BUDGET_TRANSFER.

TABLES: PRPS, BPGE, BPJA.

DATA: lt_return TYPE STANDARD TABLE OF BAPIRET2,
      ls_return TYPE BAPIRET2,
      lv_from_wbs TYPE PRPS-POSID,
      lv_to_wbs   TYPE PRPS-POSID,
      lv_amount   TYPE BPGE-WTJHR.

PARAMETERS: p_from TYPE PRPS-POSID,
            p_to   TYPE PRPS-POSID,
            p_amt  TYPE p DECIMALS 2.

START-OF-SELECTION.

  MOVE p_from TO lv_from_wbs.
  MOVE p_to TO lv_to_wbs.
  MOVE p_amt TO lv_amount.

  SELECT SINGLE * FROM PRPS WHERE POSID = lv_from_wbs.
  IF sy-subrc <> 0.
    WRITE: / 'Source WBS not found'.
    EXIT.
  ENDIF.

  CALL FUNCTION 'BAPI_BUS2054_SET_DATA'
    EXPORTING
      i_wbs_element = lv_from_wbs.

  CALL FUNCTION 'BAPI_TRANSACTION_COMMIT'.

  WRITE: / 'Budget transferred:', lv_amount,
           'from', lv_from_wbs, 'to', lv_to_wbs.
""",

"ZPS_PROJECT_SETTLEMENT": """*----------------------------------------------------------------------*
* Program: ZPS_PROJECT_SETTLEMENT
* Description: Project settlement run to receiver objects
* Author: NEHA.VERMA
* Date: 20200415
*----------------------------------------------------------------------*
REPORT ZPS_PROJECT_SETTLEMENT.

TABLES: PROJ, PRPS, COSP, COSS.

DATA: BEGIN OF lt_settle OCCURS 0,
        PSPNR TYPE PRPS-PSPNR,
        POSID TYPE PRPS-POSID,
        POST1 TYPE PRPS-POST1,
        WKGBTR TYPE COSP-WTG001,
      END OF lt_settle.

DATA: lv_total TYPE p DECIMALS 2.

PARAMETERS: p_pspid TYPE PROJ-PSPID,
            p_gjahr TYPE BKPF-GJAHR DEFAULT '2024'.

START-OF-SELECTION.

  SELECT * FROM PRPS INTO CORRESPONDING FIELDS OF TABLE lt_settle
    WHERE PSPHI = ( SELECT PSPNR FROM PROJ WHERE PSPID = p_pspid ).

  LOOP AT lt_settle.
    SELECT SINGLE * FROM COSP
      WHERE OBJNR = lt_settle-PSPNR
      AND   GJAHR = p_gjahr.

    ADD lt_settle-WKGBTR TO lv_total.

    WRITE: / lt_settle-POSID, lt_settle-POST1, lt_settle-WKGBTR.
  ENDLOOP.

  WRITE: / 'Total settlement amount:', lv_total.

  CALL FUNCTION 'BAPI_ACC_DOCUMENT_POST'
    EXPORTING
      documentheader = ls_header.

  COMMIT WORK AND WAIT.
""",

"ZPS_MILESTONE_BILLING": """*----------------------------------------------------------------------*
* Program: ZPS_MILESTONE_BILLING
* Description: Milestone billing for project-based sales
* Author: POOJA.DAS
* Date: 20210622
*----------------------------------------------------------------------*
REPORT ZPS_MILESTONE_BILLING.

TABLES: PRPS, MLST, VBRK, VBRP.

DATA: BEGIN OF lt_milestones OCCURS 0,
        PSPNR TYPE PRPS-PSPNR,
        POSID TYPE PRPS-POSID,
        MSTNR TYPE MLST-MSTNR,
        MSTXT TYPE MLST-MSTXT,
        PCTGE TYPE p DECIMALS 2,
      END OF lt_milestones.

DATA: lv_billing_amt TYPE p DECIMALS 2.

PARAMETERS: p_pspid TYPE PROJ-PSPID.

START-OF-SELECTION.

  SELECT * FROM MLST INTO CORRESPONDING FIELDS OF TABLE lt_milestones
    WHERE PSPNR IN ( SELECT PSPNR FROM PRPS WHERE PSPHI = p_pspid ).

  LOOP AT lt_milestones.
    WRITE: / lt_milestones-POSID, lt_milestones-MSTNR,
             lt_milestones-MSTXT, lt_milestones-PCTGE, '%'.
  ENDLOOP.

  CALL FUNCTION 'BAPI_BILLINGDOC_CREATEMULTIPLE'.
  COMMIT WORK.
""",

# ─────────────────────────────────────────────────────────────────
# WAREHOUSE / EWM PROGRAMS
# ─────────────────────────────────────────────────────────────────

"ZWM_STOCK_TRANSFER": """*----------------------------------------------------------------------*
* Program: ZWM_STOCK_TRANSFER
* Description: Inter-warehouse stock transfer posting
* Author: GANESH.PILLAI
* Date: 20180110
*----------------------------------------------------------------------*
REPORT ZWM_STOCK_TRANSFER.

TABLES: LQUA, LTAP, LTBK, MARD.

DATA: BEGIN OF lt_transfer OCCURS 0,
        LGNUM TYPE LQUA-LGNUM,
        MATNR TYPE LQUA-MATNR,
        LGTYP TYPE LQUA-LGTYP,
        LGPLA TYPE LQUA-LGPLA,
        GESME TYPE LQUA-GESME,
      END OF lt_transfer.

PARAMETERS: p_lgnum_f TYPE LQUA-LGNUM DEFAULT '100',
            p_lgnum_t TYPE LQUA-LGNUM DEFAULT '200',
            p_matnr   TYPE LQUA-MATNR.

START-OF-SELECTION.

  SELECT * FROM LQUA INTO CORRESPONDING FIELDS OF TABLE lt_transfer
    WHERE LGNUM = p_lgnum_f
    AND   MATNR = p_matnr.

  LOOP AT lt_transfer.
    CALL FUNCTION 'L_TO_CREATE_MOVE_SU'
      EXPORTING
        i_lgnum = lt_transfer-LGNUM
        i_matnr = lt_transfer-MATNR
        i_anfme = lt_transfer-GESME.

    WRITE: / lt_transfer-MATNR, lt_transfer-GESME, 'transferred'.
  ENDLOOP.

  CALL FUNCTION 'BAPI_TRANSACTION_COMMIT'.
""",

"ZWM_PUTAWAY_STRATEGY": """*----------------------------------------------------------------------*
* Program: ZWM_PUTAWAY_STRATEGY
* Description: Custom putaway strategy based on material group
* Author: VIKRAM.REDDY
* Date: 20190504
*----------------------------------------------------------------------*
REPORT ZWM_PUTAWAY_STRATEGY.

TABLES: LQUA, LAGP, MARA, T331.

DATA: BEGIN OF lt_bins OCCURS 0,
        LGNUM TYPE LAGP-LGNUM,
        LGTYP TYPE LAGP-LGTYP,
        LGPLA TYPE LAGP-LGPLA,
        KOBER TYPE LAGP-KOBER,
        MAXLE TYPE LAGP-MAXLE,
        VERME TYPE LAGP-VERME,
      END OF lt_bins.

DATA: lv_free_cap TYPE p DECIMALS 2.

PARAMETERS: p_lgnum TYPE LAGP-LGNUM DEFAULT '100',
            p_matnr TYPE MARA-MATNR.

START-OF-SELECTION.

  SELECT * FROM MARA WHERE MATNR = p_matnr.

  SELECT * FROM LAGP INTO CORRESPONDING FIELDS OF TABLE lt_bins
    WHERE LGNUM = p_lgnum
    AND   VERME < MAXLE.

  SORT lt_bins BY VERME ASCENDING.

  LOOP AT lt_bins.
    COMPUTE lv_free_cap = lt_bins-MAXLE - lt_bins-VERME.
    WRITE: / lt_bins-LGTYP, lt_bins-LGPLA, lv_free_cap, 'free capacity'.
  ENDLOOP.
""",

"ZWM_PICKING_WAVE": """*----------------------------------------------------------------------*
* Program: ZWM_PICKING_WAVE
* Description: Generate picking waves for outbound deliveries
* Author: SURESH.KUMAR
* Date: 20200818
*----------------------------------------------------------------------*
REPORT ZWM_PICKING_WAVE.

TABLES: LTAK, LTAP, LIKP, LIPS.

DATA: BEGIN OF lt_wave OCCURS 0,
        LGNUM TYPE LTAK-LGNUM,
        TESSION TYPE LTAK-TESSION,
        MATNR TYPE LTAP-MATNR,
        VSOLM TYPE LTAP-VSOLM,
        VLENR TYPE LIKP-VBELN,
      END OF lt_wave.

DATA: lv_wave_count TYPE i.

PARAMETERS: p_lgnum TYPE LTAK-LGNUM DEFAULT '100'.

START-OF-SELECTION.

  SELECT * FROM LIKP
    INTO CORRESPONDING FIELDS OF TABLE lt_wave
    WHERE LGNUM = p_lgnum
    AND   KOSTA = ' '.

  LOOP AT lt_wave.
    CALL FUNCTION 'L_TO_CREATE_DN'
      EXPORTING
        i_lgnum = lt_wave-LGNUM
        i_vbeln = lt_wave-VLENR.

    ADD 1 TO lv_wave_count.
    WRITE: / lt_wave-VLENR, lt_wave-MATNR, lt_wave-VSOLM.
  ENDLOOP.

  WRITE: / 'Picking TOs created:', lv_wave_count.
""",

"ZWM_INVENTORY_COUNT": """*----------------------------------------------------------------------*
* Program: ZWM_INVENTORY_COUNT
* Description: WM cycle count with variance reporting
* Author: ASHOK.MISHRA
* Date: 20210301
*----------------------------------------------------------------------*
REPORT ZWM_INVENTORY_COUNT.

TABLES: LQUA, LINV, LAGP.

DATA: BEGIN OF lt_count OCCURS 0,
        LGNUM TYPE LQUA-LGNUM,
        LGTYP TYPE LQUA-LGTYP,
        LGPLA TYPE LQUA-LGPLA,
        MATNR TYPE LQUA-MATNR,
        GESME TYPE LQUA-GESME,
        COUNT_QTY TYPE p DECIMALS 3,
      END OF lt_count.

DATA: lv_variance TYPE p DECIMALS 3,
      lv_total_var TYPE p DECIMALS 3.

PARAMETERS: p_lgnum TYPE LQUA-LGNUM DEFAULT '100'.

START-OF-SELECTION.

  SELECT * FROM LQUA INTO CORRESPONDING FIELDS OF TABLE lt_count
    WHERE LGNUM = p_lgnum.

  LOOP AT lt_count.
    COMPUTE lv_variance = lt_count-COUNT_QTY - lt_count-GESME.
    ADD lv_variance TO lv_total_var.

    WRITE: / lt_count-LGPLA, lt_count-MATNR,
             lt_count-GESME, lt_count-COUNT_QTY, lv_variance.
  ENDLOOP.

  WRITE: / 'Total variance:', lv_total_var.
""",

"ZWM_SHIPPING_DOCK": """*----------------------------------------------------------------------*
* Program: ZWM_SHIPPING_DOCK
* Description: Shipping dock assignment and load building
* Author: MEERA.BANERJEE
* Date: 20220115
*----------------------------------------------------------------------*
REPORT ZWM_SHIPPING_DOCK.

TABLES: LTAK, LTAP, VTTK, VTTP.

DATA: BEGIN OF lt_loads OCCURS 0,
        LGNUM TYPE LTAK-LGNUM,
        TESSION TYPE LTAK-TESSION,
        MATNR TYPE LTAP-MATNR,
        VSOLM TYPE LTAP-VSOLM,
        NLPLA TYPE LTAP-NLPLA,
      END OF lt_loads.

PARAMETERS: p_lgnum TYPE LTAK-LGNUM DEFAULT '100',
            p_dock  TYPE LTAP-NLPLA.

START-OF-SELECTION.

  SELECT * FROM LTAP INTO CORRESPONDING FIELDS OF TABLE lt_loads
    WHERE LGNUM = p_lgnum
    AND   NLPLA = p_dock
    AND   PESSION = '0'.

  LOOP AT lt_loads.
    WRITE: / lt_loads-TESSION, lt_loads-MATNR, lt_loads-VSOLM.

    CALL FUNCTION 'L_TO_CONFIRM'
      EXPORTING
        i_lgnum = lt_loads-LGNUM
        i_tanum = lt_loads-TESSION.
  ENDLOOP.

  CALL FUNCTION 'BAPI_TRANSACTION_COMMIT'.
""",

# ─────────────────────────────────────────────────────────────────
# HR / HCM PROGRAMS
# ─────────────────────────────────────────────────────────────────

"ZHR_PAYROLL_RUN": """*----------------------------------------------------------------------*
* Program: ZHR_PAYROLL_RUN
* Description: Monthly payroll run with PF/ESI/TDS calculations
* Author: REKHA.CHATTERJEE
* Date: 20160915
*----------------------------------------------------------------------*
REPORT ZHR_PAYROLL_RUN.

TABLES: PA0001, PA0008, PA0014, PA0015, T510, T511.

DATA: BEGIN OF lt_payroll OCCURS 0,
        PERNR TYPE PA0001-PERNR,
        ENAME TYPE PA0001-ENAME,
        BTRTL TYPE PA0001-BTRTL,
        BASIC TYPE PA0008-ANSAL,
        GROSS TYPE p DECIMALS 2,
        PF    TYPE p DECIMALS 2,
        ESI   TYPE p DECIMALS 2,
        TDS   TYPE p DECIMALS 2,
        NET   TYPE p DECIMALS 2,
      END OF lt_payroll.

DATA: lv_total_net TYPE p DECIMALS 2.

SELECT-OPTIONS: s_pernr FOR PA0001-PERNR,
                s_btrtl FOR PA0001-BTRTL.

START-OF-SELECTION.

  SELECT * FROM PA0001
    INTO CORRESPONDING FIELDS OF TABLE lt_payroll
    WHERE PERNR IN s_pernr
    AND   BTRTL IN s_btrtl.

  LOOP AT lt_payroll.
    SELECT SINGLE * FROM PA0008 WHERE PERNR = lt_payroll-PERNR.

    MOVE PA0008-ANSAL TO lt_payroll-BASIC.
    COMPUTE lt_payroll-GROSS = lt_payroll-BASIC / 12.
    COMPUTE lt_payroll-PF = lt_payroll-BASIC * '0.12'.
    COMPUTE lt_payroll-ESI = lt_payroll-GROSS * '0.0075'.
    COMPUTE lt_payroll-TDS = lt_payroll-GROSS * '0.10'.
    COMPUTE lt_payroll-NET = lt_payroll-GROSS - lt_payroll-PF
                            - lt_payroll-ESI - lt_payroll-TDS.

    ADD lt_payroll-NET TO lv_total_net.

    WRITE: / lt_payroll-PERNR, lt_payroll-ENAME,
             lt_payroll-GROSS, lt_payroll-NET.
  ENDLOOP.

  WRITE: / 'Total Net Payroll:', lv_total_net.

  CALL FUNCTION 'REUSE_ALV_GRID_DISPLAY'
    EXPORTING
      i_structure_name = 'PA0001'
    TABLES
      t_outtab         = lt_payroll.
""",

"ZHR_TIME_EVALUATION": """*----------------------------------------------------------------------*
* Program: ZHR_TIME_EVALUATION
* Description: Time evaluation with overtime and shift premium
* Author: DIVYA.DESAI
* Date: 20180403
*----------------------------------------------------------------------*
REPORT ZHR_TIME_EVALUATION.

TABLES: PA0001, PA2001, PA2002, T554S, TEVEN.

DATA: BEGIN OF lt_time OCCURS 0,
        PERNR  TYPE PA0001-PERNR,
        ENAME  TYPE PA0001-ENAME,
        BEGDA  TYPE PA2001-BEGDA,
        ENDDA  TYPE PA2001-ENDDA,
        STDAZ  TYPE p DECIMALS 2,
        OVTHR  TYPE p DECIMALS 2,
      END OF lt_time.

PARAMETERS: p_month TYPE sy-datum DEFAULT sy-datum.

SELECT-OPTIONS: s_pernr FOR PA0001-PERNR.

START-OF-SELECTION.

  SELECT * FROM PA2001 INTO CORRESPONDING FIELDS OF TABLE lt_time
    WHERE PERNR IN s_pernr
    AND   BEGDA >= p_month
    AND   ENDDA <= p_month + 30.

  LOOP AT lt_time.
    SELECT SINGLE ENAME FROM PA0001 INTO lt_time-ENAME
      WHERE PERNR = lt_time-PERNR.

    IF lt_time-STDAZ > 8.
      COMPUTE lt_time-OVTHR = lt_time-STDAZ - 8.
    ENDIF.

    WRITE: / lt_time-PERNR, lt_time-ENAME,
             lt_time-STDAZ, lt_time-OVTHR.
  ENDLOOP.
""",

"ZHR_ORG_STRUCTURE": """*----------------------------------------------------------------------*
* Program: ZHR_ORG_STRUCTURE
* Description: Org structure hierarchy report
* Author: PRAKASH.SINGH
* Date: 20190720
*----------------------------------------------------------------------*
REPORT ZHR_ORG_STRUCTURE.

TABLES: HRP1000, HRP1001, PA0001, T527X.

DATA: BEGIN OF lt_org OCCURS 0,
        OBJID TYPE HRP1000-OBJID,
        SHORT TYPE HRP1000-SHORT,
        STEXT TYPE HRP1000-STEXT,
        OTYPE TYPE HRP1001-OTYPE,
      END OF lt_org.

PARAMETERS: p_orgid TYPE HRP1000-OBJID DEFAULT '50000000'.

START-OF-SELECTION.

  SELECT * FROM HRP1000 INTO CORRESPONDING FIELDS OF TABLE lt_org
    WHERE PLVAR = '01'
    AND   OTYPE = 'O'
    AND   BEGDA <= sy-datum
    AND   ENDDA >= sy-datum.

  LOOP AT lt_org.
    SELECT SINGLE * FROM HRP1001
      WHERE OBJID = lt_org-OBJID
      AND   RSIGN = 'B'
      AND   RELAT = '002'.

    WRITE: / lt_org-OBJID, lt_org-SHORT, lt_org-STEXT.
  ENDLOOP.

  CALL FUNCTION 'REUSE_ALV_GRID_DISPLAY'
    EXPORTING
      i_structure_name = 'HRP1000'
    TABLES
      t_outtab         = lt_org.
""",

"ZHR_RECRUITMENT": """*----------------------------------------------------------------------*
* Program: ZHR_RECRUITMENT
* Description: Recruitment pipeline report with applicant tracking
* Author: SWATI.MALHOTRA
* Date: 20200125
*----------------------------------------------------------------------*
REPORT ZHR_RECRUITMENT.

TABLES: PB0001, PB0002, T750X, T750A.

DATA: BEGIN OF lt_applicants OCCURS 0,
        APLNO TYPE PB0001-APLNO,
        NACHN TYPE PB0002-NACHN,
        VORNA TYPE PB0002-VORNA,
        STESSION TYPE PB0001-STESSION,
        APDAT TYPE PB0001-APDAT,
      END OF lt_applicants.

DATA: lv_count TYPE i.

START-OF-SELECTION.

  SELECT * FROM PB0001 INTO CORRESPONDING FIELDS OF TABLE lt_applicants
    WHERE APDAT BETWEEN sy-datum - 90 AND sy-datum.

  LOOP AT lt_applicants.
    SELECT SINGLE * FROM PB0002
      WHERE APLNO = lt_applicants-APLNO.

    MOVE PB0002-NACHN TO lt_applicants-NACHN.

    ADD 1 TO lv_count.
    WRITE: / lt_applicants-APLNO, lt_applicants-NACHN,
             lt_applicants-VORNA, lt_applicants-STESSION.
  ENDLOOP.

  WRITE: / 'Total applicants:', lv_count.
""",

"ZHR_TRAINING_MGMT": """*----------------------------------------------------------------------*
* Program: ZHR_TRAINING_MGMT
* Description: Training management and completion tracking
* Author: ANITA.KAUR
* Date: 20210508
*----------------------------------------------------------------------*
REPORT ZHR_TRAINING_MGMT.

TABLES: HRP1000, HRP1001, PA0001.

DATA: BEGIN OF lt_training OCCURS 0,
        OBJID TYPE HRP1000-OBJID,
        STEXT TYPE HRP1000-STEXT,
        BEGDA TYPE HRP1000-BEGDA,
        ENDDA TYPE HRP1000-ENDDA,
        PERNR TYPE PA0001-PERNR,
        STATUS TYPE c LENGTH 1,
      END OF lt_training.

START-OF-SELECTION.

  SELECT * FROM HRP1000 INTO CORRESPONDING FIELDS OF TABLE lt_training
    WHERE PLVAR = '01'
    AND   OTYPE = 'E'
    AND   BEGDA >= sy-datum - 365.

  LOOP AT lt_training.
    READ TABLE lt_training WITH KEY STATUS = 'C'.

    WRITE: / lt_training-OBJID, lt_training-STEXT,
             lt_training-BEGDA, lt_training-STATUS.
  ENDLOOP.
""",

"ZHR_LEAVE_QUOTA": """*----------------------------------------------------------------------*
* Program: ZHR_LEAVE_QUOTA
* Description: Leave quota generation and balance report
* Author: LATA.PILLAI
* Date: 20200930
*----------------------------------------------------------------------*
REPORT ZHR_LEAVE_QUOTA.

TABLES: PA2001, PA2006, PA0001, T554S.

DATA: BEGIN OF lt_leave OCCURS 0,
        PERNR  TYPE PA0001-PERNR,
        ENAME  TYPE PA0001-ENAME,
        KTART  TYPE PA2006-KTART,
        ANZHL  TYPE PA2006-ANZHL,
        KVERB  TYPE PA2006-KVERB,
        REMAIN TYPE p DECIMALS 2,
      END OF lt_leave.

SELECT-OPTIONS: s_pernr FOR PA0001-PERNR.

START-OF-SELECTION.

  SELECT * FROM PA2006 INTO CORRESPONDING FIELDS OF TABLE lt_leave
    WHERE PERNR IN s_pernr
    AND   BEGDA <= sy-datum
    AND   ENDDA >= sy-datum.

  LOOP AT lt_leave.
    SELECT SINGLE ENAME FROM PA0001 INTO lt_leave-ENAME
      WHERE PERNR = lt_leave-PERNR.

    COMPUTE lt_leave-REMAIN = lt_leave-ANZHL - lt_leave-KVERB.

    WRITE: / lt_leave-PERNR, lt_leave-ENAME,
             lt_leave-KTART, lt_leave-ANZHL,
             lt_leave-KVERB, lt_leave-REMAIN.
  ENDLOOP.
""",

"ZHR_TAX_REPORTER": """*----------------------------------------------------------------------*
* Program: ZHR_TAX_REPORTER
* Description: Employee tax declaration and Form 16 data extraction
* Author: GEETA.RAO
* Date: 20190215
*----------------------------------------------------------------------*
REPORT ZHR_TAX_REPORTER.

TABLES: PA0001, PA0008, PA0581, PA0582, T511K.

DATA: BEGIN OF lt_tax OCCURS 0,
        PERNR TYPE PA0001-PERNR,
        ENAME TYPE PA0001-ENAME,
        GROSS_SAL TYPE p DECIMALS 2,
        SEC80C    TYPE p DECIMALS 2,
        SEC80D    TYPE p DECIMALS 2,
        HRA_EXMPT TYPE p DECIMALS 2,
        TAXABLE   TYPE p DECIMALS 2,
      END OF lt_tax.

SELECT-OPTIONS: s_pernr FOR PA0001-PERNR.

PARAMETERS: p_gjahr TYPE BKPF-GJAHR DEFAULT '2024'.

START-OF-SELECTION.

  SELECT * FROM PA0001 INTO CORRESPONDING FIELDS OF TABLE lt_tax
    WHERE PERNR IN s_pernr.

  LOOP AT lt_tax.
    SELECT SINGLE * FROM PA0008 WHERE PERNR = lt_tax-PERNR.
    SELECT SINGLE * FROM PA0581 WHERE PERNR = lt_tax-PERNR.

    MOVE PA0008-ANSAL TO lt_tax-GROSS_SAL.

    COMPUTE lt_tax-TAXABLE = lt_tax-GROSS_SAL
            - lt_tax-SEC80C - lt_tax-SEC80D - lt_tax-HRA_EXMPT.

    WRITE: / lt_tax-PERNR, lt_tax-ENAME,
             lt_tax-GROSS_SAL, lt_tax-TAXABLE.
  ENDLOOP.

  CALL FUNCTION 'REUSE_ALV_GRID_DISPLAY'
    EXPORTING
      i_structure_name = 'PA0001'
    TABLES
      t_outtab         = lt_tax.
""",

"ZHR_BENEFITS_ENROLLMENT": """*----------------------------------------------------------------------*
* Program: ZHR_BENEFITS_ENROLLMENT
* Description: Benefits enrollment processing and status report
* Author: AMIT.SHARMA
* Date: 20210812
*----------------------------------------------------------------------*
REPORT ZHR_BENEFITS_ENROLLMENT.

TABLES: PA0001, PA0167, PA0168, T74FC.

DATA: BEGIN OF lt_benefits OCCURS 0,
        PERNR TYPE PA0001-PERNR,
        ENAME TYPE PA0001-ENAME,
        BESSION TYPE PA0167-BESSION,
        BPLAN TYPE PA0167-BPLAN,
        BEESSION TYPE PA0167-BEESSION,
        ENDDA TYPE PA0167-ENDDA,
      END OF lt_benefits.

SELECT-OPTIONS: s_pernr FOR PA0001-PERNR.

START-OF-SELECTION.

  SELECT * FROM PA0167 INTO CORRESPONDING FIELDS OF TABLE lt_benefits
    WHERE PERNR IN s_pernr
    AND   BEGDA <= sy-datum
    AND   ENDDA >= sy-datum.

  LOOP AT lt_benefits.
    SELECT SINGLE ENAME FROM PA0001 INTO lt_benefits-ENAME
      WHERE PERNR = lt_benefits-PERNR.

    WRITE: / lt_benefits-PERNR, lt_benefits-ENAME,
             lt_benefits-BPLAN, lt_benefits-BEESSION.
  ENDLOOP.
""",

# ─────────────────────────────────────────────────────────────────
# BASIS / TECHNICAL PROGRAMS
# ─────────────────────────────────────────────────────────────────

"ZBC_TRANSPORT_ANALYSIS": """*----------------------------------------------------------------------*
* Program: ZBC_TRANSPORT_ANALYSIS
* Description: Transport request analysis and dependency checker
* Author: MOHAN.VERMA
* Date: 20170612
*----------------------------------------------------------------------*
REPORT ZBC_TRANSPORT_ANALYSIS.

TABLES: E070, E071, TSTRFCOFIL, TADIR.

DATA: BEGIN OF lt_transports OCCURS 0,
        TRKORR TYPE E070-TRKORR,
        AS4TEXT TYPE E070-AS4TEXT,
        TRSTATUS TYPE E070-TRSTATUS,
        AS4DATE TYPE E070-AS4DATE,
        AS4USER TYPE E070-AS4USER,
        OBJ_COUNT TYPE i,
      END OF lt_transports.

SELECT-OPTIONS: s_user FOR E070-AS4USER,
                s_date FOR E070-AS4DATE.

START-OF-SELECTION.

  SELECT * FROM E070 INTO CORRESPONDING FIELDS OF TABLE lt_transports
    WHERE AS4USER IN s_user
    AND   AS4DATE IN s_date
    AND   TRSTATUS IN ('D', 'L', 'R').

  LOOP AT lt_transports.
    SELECT COUNT(*) FROM E071 INTO lt_transports-OBJ_COUNT
      WHERE TRKORR = lt_transports-TRKORR.

    WRITE: / lt_transports-TRKORR, lt_transports-AS4TEXT,
             lt_transports-TRSTATUS, lt_transports-OBJ_COUNT.
  ENDLOOP.

  CALL FUNCTION 'REUSE_ALV_GRID_DISPLAY'
    EXPORTING
      i_structure_name = 'E070'
    TABLES
      t_outtab         = lt_transports.
""",

"ZBC_JOB_SCHEDULER": """*----------------------------------------------------------------------*
* Program: ZBC_JOB_SCHEDULER
* Description: Custom job scheduling with dependency management
* Author: PRAKASH.SINGH
* Date: 20180826
*----------------------------------------------------------------------*
REPORT ZBC_JOB_SCHEDULER.

TABLES: TBTCO, TBTCP, TBTCS.

DATA: BEGIN OF lt_jobs OCCURS 0,
        JOBNAME  TYPE TBTCO-JOBNAME,
        JOBCOUNT TYPE TBTCO-JOBCOUNT,
        STRTDATE TYPE TBTCO-STRTDATE,
        STRTTIME TYPE TBTCO-STRTTIME,
        ENDDATE  TYPE TBTCO-ENDDATE,
        ENDTIME  TYPE TBTCO-ENDTIME,
        STATUS   TYPE TBTCO-STATUS,
      END OF lt_jobs.

DATA: lv_active TYPE i, lv_finished TYPE i, lv_aborted TYPE i.

SELECT-OPTIONS: s_name FOR TBTCO-JOBNAME,
                s_date FOR TBTCO-STRTDATE.

START-OF-SELECTION.

  SELECT * FROM TBTCO INTO CORRESPONDING FIELDS OF TABLE lt_jobs
    WHERE JOBNAME IN s_name
    AND   STRTDATE IN s_date.

  LOOP AT lt_jobs.
    CASE lt_jobs-STATUS.
      WHEN 'R'. ADD 1 TO lv_active.
      WHEN 'F'. ADD 1 TO lv_finished.
      WHEN 'A'. ADD 1 TO lv_aborted.
    ENDCASE.

    WRITE: / lt_jobs-JOBNAME, lt_jobs-STATUS,
             lt_jobs-STRTDATE, lt_jobs-ENDDATE.
  ENDLOOP.

  WRITE: / 'Active:', lv_active, 'Finished:', lv_finished,
           'Aborted:', lv_aborted.
""",

"ZBC_USER_AUDIT": """*----------------------------------------------------------------------*
* Program: ZBC_USER_AUDIT
* Description: User activity audit report with login analysis
* Author: SANJAY.GUPTA
* Date: 20190410
*----------------------------------------------------------------------*
REPORT ZBC_USER_AUDIT.

TABLES: USR02, USR04, USR10, AGR_USERS, USR41.

DATA: BEGIN OF lt_users OCCURS 0,
        BNAME  TYPE USR02-BNAME,
        TRDAT  TYPE USR02-TRDAT,
        LTIME  TYPE USR02-LTIME,
        UFLAG  TYPE USR02-UFLAG,
        USTYP  TYPE USR02-USTYP,
        ROLES  TYPE i,
      END OF lt_users.

SELECT-OPTIONS: s_user FOR USR02-BNAME.

PARAMETERS: p_days TYPE i DEFAULT 90.

START-OF-SELECTION.

  SELECT * FROM USR02 INTO CORRESPONDING FIELDS OF TABLE lt_users
    WHERE BNAME IN s_user.

  LOOP AT lt_users.
    SELECT COUNT(*) FROM AGR_USERS INTO lt_users-ROLES
      WHERE UNAME = lt_users-BNAME.

    IF lt_users-TRDAT < sy-datum - p_days AND lt_users-UFLAG = 0.
      WRITE: / lt_users-BNAME, 'INACTIVE', lt_users-TRDAT,
               lt_users-ROLES, 'roles'.
    ENDIF.
  ENDLOOP.
""",

"ZBC_TABLE_ARCHIVER": """*----------------------------------------------------------------------*
* Program: ZBC_TABLE_ARCHIVER
* Description: Custom table archiving with size monitoring
* Author: VIJAY.SHARMA
* Date: 20200715
*----------------------------------------------------------------------*
REPORT ZBC_TABLE_ARCHIVER.

TABLES: DD02L, DB02, TADIR.

DATA: BEGIN OF lt_tables OCCURS 0,
        TABNAME TYPE DD02L-TABNAME,
        TABCLASS TYPE DD02L-TABCLASS,
        SQLDTAB TYPE DD02L-SQLDTAB,
        ROWS    TYPE i,
        SIZE_MB TYPE p DECIMALS 2,
      END OF lt_tables.

PARAMETERS: p_prefix TYPE c LENGTH 4 DEFAULT 'ZT%',
            p_min_mb TYPE p DECIMALS 2 DEFAULT 100.

START-OF-SELECTION.

  SELECT * FROM DD02L INTO CORRESPONDING FIELDS OF TABLE lt_tables
    WHERE TABNAME LIKE p_prefix
    AND   AS4LOCAL = 'A'.

  LOOP AT lt_tables.
    EXEC SQL.
      SELECT COUNT(*) INTO :lt_tables-ROWS
      FROM (lt_tables-TABNAME)
    ENDEXEC.

    IF lt_tables-SIZE_MB > p_min_mb.
      WRITE: / lt_tables-TABNAME, lt_tables-ROWS,
               lt_tables-SIZE_MB, 'MB'.
    ENDIF.
  ENDLOOP.
""",

"ZBC_IDOC_MONITOR": """*----------------------------------------------------------------------*
* Program: ZBC_IDOC_MONITOR
* Description: IDoc processing monitor with error reprocessing
* Author: DEEPA.MEHTA
* Date: 20210205
*----------------------------------------------------------------------*
REPORT ZBC_IDOC_MONITOR.

TABLES: EDIDC, EDIDS, EDID4, EDSAPPL.

DATA: BEGIN OF lt_idocs OCCURS 0,
        DOCNUM TYPE EDIDC-DOCNUM,
        IDOCTP TYPE EDIDC-IDOCTP,
        MESTYP TYPE EDIDC-MESTYP,
        STATUS TYPE EDIDC-STATUS,
        CREDAT TYPE EDIDC-CREDAT,
        SNDPRN TYPE EDIDC-SNDPRN,
        RCVPRN TYPE EDIDC-RCVPRN,
      END OF lt_idocs.

DATA: lv_errors TYPE i, lv_success TYPE i.

SELECT-OPTIONS: s_mestyp FOR EDIDC-MESTYP,
                s_status FOR EDIDC-STATUS,
                s_date   FOR EDIDC-CREDAT.

START-OF-SELECTION.

  SELECT * FROM EDIDC INTO CORRESPONDING FIELDS OF TABLE lt_idocs
    WHERE MESTYP IN s_mestyp
    AND   STATUS IN s_status
    AND   CREDAT IN s_date.

  LOOP AT lt_idocs.
    IF lt_idocs-STATUS >= '50'.
      ADD 1 TO lv_errors.

      CALL FUNCTION 'IDOC_PROCESS_MASS'
        EXPORTING
          docnum = lt_idocs-DOCNUM.
    ELSE.
      ADD 1 TO lv_success.
    ENDIF.

    WRITE: / lt_idocs-DOCNUM, lt_idocs-MESTYP,
             lt_idocs-STATUS, lt_idocs-SNDPRN.
  ENDLOOP.

  WRITE: / 'Success:', lv_success, 'Errors:', lv_errors.
""",

# ─────────────────────────────────────────────────────────────────
# CROSS-APPLICATION PROGRAMS
# ─────────────────────────────────────────────────────────────────

"ZCA_WORKFLOW_ENGINE": """*----------------------------------------------------------------------*
* Program: ZCA_WORKFLOW_ENGINE
* Description: Custom workflow engine for multi-level approvals
* Author: KAVITA.RAO
* Date: 20170905
*----------------------------------------------------------------------*
REPORT ZCA_WORKFLOW_ENGINE.

TABLES: SWW_WI2OBJ, SWWWIHEAD, SWW_CONTOB.

DATA: BEGIN OF lt_workflows OCCURS 0,
        WI_ID   TYPE SWWWIHEAD-WI_ID,
        WI_TYPE TYPE SWWWIHEAD-WI_TYPE,
        WI_STAT TYPE SWWWIHEAD-WI_STAT,
        WI_CD   TYPE SWWWIHEAD-WI_CD,
        WI_CT   TYPE SWWWIHEAD-WI_CT,
        WI_AAGENT TYPE SWWWIHEAD-WI_AAGENT,
      END OF lt_workflows.

SELECT-OPTIONS: s_stat FOR SWWWIHEAD-WI_STAT,
                s_date FOR SWWWIHEAD-WI_CD.

START-OF-SELECTION.

  SELECT * FROM SWWWIHEAD INTO CORRESPONDING FIELDS OF TABLE lt_workflows
    WHERE WI_STAT IN s_stat
    AND   WI_CD IN s_date.

  LOOP AT lt_workflows.
    WRITE: / lt_workflows-WI_ID, lt_workflows-WI_TYPE,
             lt_workflows-WI_STAT, lt_workflows-WI_AAGENT.
  ENDLOOP.

  CALL FUNCTION 'REUSE_ALV_GRID_DISPLAY'
    EXPORTING
      i_structure_name = 'SWWWIHEAD'
    TABLES
      t_outtab         = lt_workflows.
""",

"ZCA_OUTPUT_MGMT": """*----------------------------------------------------------------------*
* Program: ZCA_OUTPUT_MGMT
* Description: Custom output management with PDF/Email dispatch
* Author: ASHOK.MISHRA
* Date: 20180315
*----------------------------------------------------------------------*
REPORT ZCA_OUTPUT_MGMT.

TABLES: NAST, TNAPR, TSP01.

DATA: BEGIN OF lt_output OCCURS 0,
        KAPESSION TYPE NAST-KAPESSION,
        OBJKY  TYPE NAST-OBJKY,
        KSCHL  TYPE NAST-KSCHL,
        NAESSION TYPE NAST-NAESSION,
        VSTAT  TYPE NAST-VSTAT,
        DAESSION TYPE NAST-DAESSION,
      END OF lt_output.

SELECT-OPTIONS: s_kappl FOR NAST-KAPESSION,
                s_kschl FOR NAST-KSCHL.

START-OF-SELECTION.

  SELECT * FROM NAST INTO CORRESPONDING FIELDS OF TABLE lt_output
    WHERE KAPESSION IN s_kappl
    AND   KSCHL IN s_kschl
    AND   VSTAT = '0'.

  LOOP AT lt_output.
    CALL FUNCTION 'WFMC_MESSAGE_SINGLE'
      EXPORTING
        pi_kappl = lt_output-KAPESSION
        pi_objky = lt_output-OBJKY
        pi_kschl = lt_output-KSCHL.

    WRITE: / lt_output-OBJKY, lt_output-KSCHL, lt_output-VSTAT.
  ENDLOOP.
""",

"ZCA_CHANGE_DOCUMENT": """*----------------------------------------------------------------------*
* Program: ZCA_CHANGE_DOCUMENT
* Description: Change document analysis for audit trail
* Author: GANESH.PILLAI
* Date: 20190628
*----------------------------------------------------------------------*
REPORT ZCA_CHANGE_DOCUMENT.

TABLES: CDHDR, CDPOS.

DATA: BEGIN OF lt_changes OCCURS 0,
        OBJECTCLAS TYPE CDHDR-OBJECTCLAS,
        OBJECTID   TYPE CDHDR-OBJECTID,
        CHANGENR   TYPE CDHDR-CHANGENR,
        USERNAME   TYPE CDHDR-USERNAME,
        UDATE      TYPE CDHDR-UDATE,
        UTIME      TYPE CDHDR-UTIME,
        TCODE      TYPE CDHDR-TCODE,
      END OF lt_changes.

DATA: BEGIN OF lt_details OCCURS 0,
        FNAME    TYPE CDPOS-FNAME,
        VALUE_OLD TYPE CDPOS-VALUE_OLD,
        VALUE_NEW TYPE CDPOS-VALUE_NEW,
      END OF lt_details.

SELECT-OPTIONS: s_objcl FOR CDHDR-OBJECTCLAS,
                s_date  FOR CDHDR-UDATE.

START-OF-SELECTION.

  SELECT * FROM CDHDR INTO CORRESPONDING FIELDS OF TABLE lt_changes
    WHERE OBJECTCLAS IN s_objcl
    AND   UDATE IN s_date.

  LOOP AT lt_changes.
    SELECT * FROM CDPOS INTO CORRESPONDING FIELDS OF TABLE lt_details
      WHERE OBJECTCLAS = lt_changes-OBJECTCLAS
      AND   OBJECTID   = lt_changes-OBJECTID
      AND   CHANGENR   = lt_changes-CHANGENR.

    LOOP AT lt_details.
      WRITE: / lt_changes-OBJECTID, lt_changes-USERNAME,
               lt_details-FNAME, lt_details-VALUE_OLD,
               lt_details-VALUE_NEW.
    ENDLOOP.
  ENDLOOP.
""",

"ZCA_NUMBER_RANGE": """*----------------------------------------------------------------------*
* Program: ZCA_NUMBER_RANGE
* Description: Number range monitoring and gap analysis
* Author: NEHA.VERMA
* Date: 20200210
*----------------------------------------------------------------------*
REPORT ZCA_NUMBER_RANGE.

TABLES: NRIV.

DATA: BEGIN OF lt_ranges OCCURS 0,
        OBJECT   TYPE NRIV-OBJECT,
        SUBOBJECT TYPE NRIV-SUBOBJECT,
        NRRANGENR TYPE NRIV-NRRANGENR,
        FROMNUMBER TYPE NRIV-FROMNUMBER,
        TONUMBER  TYPE NRIV-TONUMBER,
        NRLEVEL   TYPE NRIV-NRLEVEL,
        PCT_USED  TYPE p DECIMALS 2,
      END OF lt_ranges.

SELECT-OPTIONS: s_obj FOR NRIV-OBJECT.

START-OF-SELECTION.

  SELECT * FROM NRIV INTO CORRESPONDING FIELDS OF TABLE lt_ranges
    WHERE OBJECT IN s_obj.

  LOOP AT lt_ranges.
    IF lt_ranges-TONUMBER > 0.
      COMPUTE lt_ranges-PCT_USED =
        ( lt_ranges-NRLEVEL - lt_ranges-FROMNUMBER ) /
        ( lt_ranges-TONUMBER - lt_ranges-FROMNUMBER ) * 100.
    ENDIF.

    IF lt_ranges-PCT_USED > 80.
      WRITE: / lt_ranges-OBJECT, lt_ranges-NRRANGENR,
               lt_ranges-PCT_USED, '% WARNING'.
    ELSE.
      WRITE: / lt_ranges-OBJECT, lt_ranges-NRRANGENR,
               lt_ranges-PCT_USED, '%'.
    ENDIF.
  ENDLOOP.
""",

"ZCA_BATCH_INPUT": """*----------------------------------------------------------------------*
* Program: ZCA_BATCH_INPUT
* Description: Generic batch input processor with error handling
* Author: RAJESH.PATEL
* Date: 20210520
*----------------------------------------------------------------------*
REPORT ZCA_BATCH_INPUT.

TABLES: APQI, APQD.

DATA: lt_bdcdata TYPE STANDARD TABLE OF BDCDATA WITH HEADER LINE,
      lt_msg     TYPE STANDARD TABLE OF BDCMSGCOLL WITH HEADER LINE.

DATA: BEGIN OF lt_sessions OCCURS 0,
        GROUPID TYPE APQI-GROUPID,
        CREATOR TYPE APQI-CREATOR,
        CREESSION TYPE APQI-CREESSION,
        QID     TYPE APQI-QID,
        QSTATE  TYPE APQI-QSTATE,
      END OF lt_sessions.

PARAMETERS: p_tcode TYPE sy-tcode DEFAULT 'XK01',
            p_mode  TYPE c LENGTH 1 DEFAULT 'N'.

START-OF-SELECTION.

  SELECT * FROM APQI INTO CORRESPONDING FIELDS OF TABLE lt_sessions
    WHERE QSTATE = 'R'.

  LOOP AT lt_sessions.
    CALL FUNCTION 'BDC_OPEN_GROUP'
      EXPORTING
        group = lt_sessions-GROUPID.

    CALL TRANSACTION p_tcode USING lt_bdcdata
      MODE p_mode MESSAGES INTO lt_msg.

    LOOP AT lt_msg WHERE msgtyp = 'E'.
      WRITE: / 'Error:', lt_msg-msgv1, lt_msg-msgv2.
    ENDLOOP.

    CALL FUNCTION 'BDC_CLOSE_GROUP'.
  ENDLOOP.
""",

# ─────────────────────────────────────────────────────────────────
# INDUSTRY-SPECIFIC PROGRAMS
# ─────────────────────────────────────────────────────────────────

"ZIS_RETAIL_POS": """*----------------------------------------------------------------------*
* Program: ZIS_RETAIL_POS
* Description: POS data upload and retail transaction processing
* Author: SUNITA.NAIR
* Date: 20180525
*----------------------------------------------------------------------*
REPORT ZIS_RETAIL_POS.

TABLES: WBRK, WBHI, VBRK.

DATA: BEGIN OF lt_pos OCCURS 0,
        LOCNR  TYPE c LENGTH 10,
        TRANID TYPE c LENGTH 20,
        TRANDATE TYPE sy-datum,
        AMOUNT TYPE p DECIMALS 2,
        ITEMS  TYPE i,
      END OF lt_pos.

DATA: lv_total_sales TYPE p DECIMALS 2.

PARAMETERS: p_locnr TYPE c LENGTH 10,
            p_date  TYPE sy-datum DEFAULT sy-datum.

START-OF-SELECTION.

  SELECT * FROM WBRK INTO CORRESPONDING FIELDS OF TABLE lt_pos
    WHERE LOCNR = p_locnr
    AND   ERDAT = p_date.

  LOOP AT lt_pos.
    ADD lt_pos-AMOUNT TO lv_total_sales.

    WRITE: / lt_pos-TRANID, lt_pos-TRANDATE,
             lt_pos-AMOUNT, lt_pos-ITEMS.
  ENDLOOP.

  WRITE: / 'Total POS Sales:', lv_total_sales.

  CALL FUNCTION 'BAPI_ACC_DOCUMENT_POST'
    EXPORTING
      documentheader = ls_header.
  COMMIT WORK.
""",

"ZIS_PHARMA_BATCH": """*----------------------------------------------------------------------*
* Program: ZIS_PHARMA_BATCH
* Description: Pharma batch traceability with expiry management
* Author: MEERA.BANERJEE
* Date: 20190810
*----------------------------------------------------------------------*
REPORT ZIS_PHARMA_BATCH.

TABLES: MCHA, MCH1, MCHB, MARD.

DATA: BEGIN OF lt_batches OCCURS 0,
        MATNR TYPE MCHA-MATNR,
        CHARG TYPE MCHA-CHARG,
        WERKS TYPE MCHB-WERKS,
        CLABS TYPE MCHB-CLABS,
        HSDAT TYPE MCH1-HSDAT,
        VFDAT TYPE MCH1-VFDAT,
        DAYS_TO_EXPIRY TYPE i,
      END OF lt_batches.

DATA: lv_expired TYPE i, lv_near_expiry TYPE i.

SELECT-OPTIONS: s_matnr FOR MCHA-MATNR.

START-OF-SELECTION.

  SELECT * FROM MCH1 INTO CORRESPONDING FIELDS OF TABLE lt_batches
    WHERE MATNR IN s_matnr.

  LOOP AT lt_batches.
    SELECT SINGLE * FROM MCHB
      WHERE MATNR = lt_batches-MATNR
      AND   CHARG = lt_batches-CHARG.

    COMPUTE lt_batches-DAYS_TO_EXPIRY = lt_batches-VFDAT - sy-datum.

    IF lt_batches-DAYS_TO_EXPIRY < 0.
      ADD 1 TO lv_expired.
    ELSEIF lt_batches-DAYS_TO_EXPIRY < 30.
      ADD 1 TO lv_near_expiry.
    ENDIF.

    WRITE: / lt_batches-MATNR, lt_batches-CHARG,
             lt_batches-VFDAT, lt_batches-DAYS_TO_EXPIRY.
  ENDLOOP.

  WRITE: / 'Expired:', lv_expired, 'Near expiry:', lv_near_expiry.
""",

"ZIS_AUTOMOTIVE_JIT": """*----------------------------------------------------------------------*
* Program: ZIS_AUTOMOTIVE_JIT
* Description: JIT (Just-In-Time) call processing for automotive supply
* Author: VIKRAM.REDDY
* Date: 20200310
*----------------------------------------------------------------------*
REPORT ZIS_AUTOMOTIVE_JIT.

TABLES: JITIT, JITHD, LIKP, LIPS.

DATA: BEGIN OF lt_jit OCCURS 0,
        INTNUM TYPE JITHD-INTNUM,
        REFNR  TYPE JITHD-REFNR,
        MAESSION TYPE JITIT-MAESSION,
        MATNR  TYPE JITIT-MATNR,
        RQTY   TYPE JITIT-RQTY,
        STATUS TYPE JITHD-STATUS,
      END OF lt_jit.

DATA: lv_open TYPE i, lv_processed TYPE i.

PARAMETERS: p_werks TYPE JITHD-WERKS DEFAULT '1002'.

START-OF-SELECTION.

  SELECT * FROM JITHD INTO CORRESPONDING FIELDS OF TABLE lt_jit
    WHERE WERKS = p_werks
    AND   STATUS IN ('01', '02', '03').

  LOOP AT lt_jit.
    IF lt_jit-STATUS = '01'.
      ADD 1 TO lv_open.
    ELSE.
      ADD 1 TO lv_processed.
    ENDIF.

    WRITE: / lt_jit-INTNUM, lt_jit-MATNR,
             lt_jit-RQTY, lt_jit-STATUS.
  ENDLOOP.

  WRITE: / 'Open JIT calls:', lv_open,
           'Processed:', lv_processed.
""",

"ZIS_UTILITIES_BILLING": """*----------------------------------------------------------------------*
* Program: ZIS_UTILITIES_BILLING
* Description: Utility meter reading and billing calculation
* Author: POOJA.DAS
* Date: 20210415
*----------------------------------------------------------------------*
REPORT ZIS_UTILITIES_BILLING.

TABLES: EABLG, ERDK, EVER, DBERCHZ.

DATA: BEGIN OF lt_billing OCCURS 0,
        ANLAGE TYPE EVER-ANLAGE,
        AESSION TYPE EABLG-AESSION,
        ABLBELNR TYPE EABLG-ABLBELNR,
        I_ZWSTND TYPE EABLG-I_ZWSTND,
        CONSUMPTION TYPE p DECIMALS 2,
        AMOUNT TYPE p DECIMALS 2,
      END OF lt_billing.

PARAMETERS: p_period TYPE c LENGTH 6 DEFAULT '202401'.

START-OF-SELECTION.

  SELECT * FROM EABLG INTO CORRESPONDING FIELDS OF TABLE lt_billing
    WHERE ABLEESSION LIKE p_period.

  LOOP AT lt_billing.
    COMPUTE lt_billing-AMOUNT = lt_billing-CONSUMPTION * '8.50'.

    WRITE: / lt_billing-ANLAGE, lt_billing-CONSUMPTION,
             lt_billing-AMOUNT.
  ENDLOOP.

  CALL FUNCTION 'REUSE_ALV_GRID_DISPLAY'
    EXPORTING
      i_structure_name = 'EABLG'
    TABLES
      t_outtab         = lt_billing.
""",

"ZIS_INSURANCE_CLAIMS": """*----------------------------------------------------------------------*
* Program: ZIS_INSURANCE_CLAIMS
* Description: Insurance claim processing and settlement
* Author: LATA.PILLAI
* Date: 20220201
*----------------------------------------------------------------------*
REPORT ZIS_INSURANCE_CLAIMS.

TABLES: ICLI_CLAIM, ICLI_RESERVE, BSEG.

DATA: BEGIN OF lt_claims OCCURS 0,
        CLAIM_ID  TYPE c LENGTH 20,
        POLICY_NR TYPE c LENGTH 20,
        CLAIMANT  TYPE c LENGTH 40,
        LOSS_DATE TYPE sy-datum,
        AMOUNT    TYPE p DECIMALS 2,
        RESERVE   TYPE p DECIMALS 2,
        STATUS    TYPE c LENGTH 2,
      END OF lt_claims.

DATA: lv_total_reserve TYPE p DECIMALS 2.

SELECT-OPTIONS: s_status FOR lt_claims-STATUS.

START-OF-SELECTION.

  SELECT * FROM ICLI_CLAIM
    INTO CORRESPONDING FIELDS OF TABLE lt_claims
    WHERE STATUS IN s_status.

  LOOP AT lt_claims.
    ADD lt_claims-RESERVE TO lv_total_reserve.

    WRITE: / lt_claims-CLAIM_ID, lt_claims-POLICY_NR,
             lt_claims-CLAIMANT, lt_claims-AMOUNT, lt_claims-STATUS.
  ENDLOOP.

  WRITE: / 'Total reserves:', lv_total_reserve.
""",

# ─────────────────────────────────────────────────────────────────
# ADVANCED FINANCE PROGRAMS
# ─────────────────────────────────────────────────────────────────

"ZFI_INTERCOMPANY_ELIM": """*----------------------------------------------------------------------*
* Program: ZFI_INTERCOMPANY_ELIM
* Description: Intercompany elimination entries for consolidation
* Author: MAHESH.IYER
* Date: 20180615
*----------------------------------------------------------------------*
REPORT ZFI_INTERCOMPANY_ELIM.

TABLES: BSEG, BKPF, T001, GLT0.

DATA: BEGIN OF lt_ic_items OCCURS 0,
        BUKRS  TYPE BSEG-BUKRS,
        HKONT  TYPE BSEG-HKONT,
        BELNR  TYPE BSEG-BELNR,
        DMBTR  TYPE BSEG-DMBTR,
        SHKZG  TYPE BSEG-SHKZG,
        VBUND  TYPE BSEG-VBUND,
      END OF lt_ic_items.

DATA: lv_elim_total TYPE p DECIMALS 2.

SELECT-OPTIONS: s_bukrs FOR BSEG-BUKRS,
                s_gjahr FOR BKPF-GJAHR.

START-OF-SELECTION.

  SELECT * FROM BSEG INTO CORRESPONDING FIELDS OF TABLE lt_ic_items
    WHERE BUKRS IN s_bukrs
    AND   VBUND <> ' '
    AND   VBUND <> BUKRS.

  LOOP AT lt_ic_items.
    ADD lt_ic_items-DMBTR TO lv_elim_total.

    WRITE: / lt_ic_items-BUKRS, lt_ic_items-VBUND,
             lt_ic_items-HKONT, lt_ic_items-DMBTR.
  ENDLOOP.

  WRITE: / 'Total IC elimination:', lv_elim_total.

  CALL FUNCTION 'BAPI_ACC_DOCUMENT_POST'
    EXPORTING
      documentheader = ls_header.
  COMMIT WORK AND WAIT.
""",

"ZFI_HEDGE_ACCOUNTING": """*----------------------------------------------------------------------*
* Program: ZFI_HEDGE_ACCOUNTING
* Description: Hedge accounting effectiveness test and valuation
* Author: DEEPA.MEHTA
* Date: 20190903
*----------------------------------------------------------------------*
REPORT ZFI_HEDGE_ACCOUNTING.

TABLES: FWBS_BSEG, VDARL, TCURR.

DATA: BEGIN OF lt_hedges OCCURS 0,
        DEAL_NR   TYPE c LENGTH 13,
        HEDGE_TYPE TYPE c LENGTH 4,
        NOMINAL   TYPE p DECIMALS 2,
        FAIR_VALUE TYPE p DECIMALS 2,
        EFFECTIVE  TYPE p DECIMALS 4,
      END OF lt_hedges.

PARAMETERS: p_bukrs TYPE BKPF-BUKRS DEFAULT '2000',
            p_date  TYPE sy-datum DEFAULT sy-datum.

START-OF-SELECTION.

  SELECT * FROM VDARL INTO CORRESPONDING FIELDS OF TABLE lt_hedges
    WHERE BUKRS = p_bukrs.

  LOOP AT lt_hedges.
    IF lt_hedges-NOMINAL > 0.
      COMPUTE lt_hedges-EFFECTIVE =
        lt_hedges-FAIR_VALUE / lt_hedges-NOMINAL.
    ENDIF.

    IF lt_hedges-EFFECTIVE BETWEEN '0.80' AND '1.25'.
      WRITE: / lt_hedges-DEAL_NR, 'EFFECTIVE',
               lt_hedges-EFFECTIVE.
    ELSE.
      WRITE: / lt_hedges-DEAL_NR, 'INEFFECTIVE',
               lt_hedges-EFFECTIVE.
    ENDIF.
  ENDLOOP.
""",

"ZFI_LEASE_ACCOUNTING": """*----------------------------------------------------------------------*
* Program: ZFI_LEASE_ACCOUNTING
* Description: IFRS 16 / Ind AS 116 lease accounting calculation
* Author: SANJAY.GUPTA
* Date: 20200720
*----------------------------------------------------------------------*
REPORT ZFI_LEASE_ACCOUNTING.

TABLES: BSEG, BKPF, ANLA.

DATA: BEGIN OF lt_leases OCCURS 0,
        LEASE_ID  TYPE c LENGTH 20,
        ASSET_DESC TYPE c LENGTH 40,
        START_DATE TYPE sy-datum,
        END_DATE   TYPE sy-datum,
        MONTHLY_PMT TYPE p DECIMALS 2,
        ROU_ASSET  TYPE p DECIMALS 2,
        LEASE_LIAB TYPE p DECIMALS 2,
      END OF lt_leases.

DATA: lv_total_rou TYPE p DECIMALS 2,
      lv_total_liab TYPE p DECIMALS 2.

PARAMETERS: p_bukrs TYPE BKPF-BUKRS DEFAULT '1000'.

START-OF-SELECTION.

  SELECT * FROM ANLA INTO CORRESPONDING FIELDS OF TABLE lt_leases
    WHERE BUKRS = p_bukrs
    AND   ANLKL = '3000'.

  LOOP AT lt_leases.
    ADD lt_leases-ROU_ASSET TO lv_total_rou.
    ADD lt_leases-LEASE_LIAB TO lv_total_liab.

    WRITE: / lt_leases-LEASE_ID, lt_leases-ASSET_DESC,
             lt_leases-ROU_ASSET, lt_leases-LEASE_LIAB.
  ENDLOOP.

  WRITE: / 'Total ROU Assets:', lv_total_rou.
  WRITE: / 'Total Lease Liabilities:', lv_total_liab.
""",

"ZFI_REVENUE_RECOGNITION": """*----------------------------------------------------------------------*
* Program: ZFI_REVENUE_RECOGNITION
* Description: Revenue recognition as per Ind AS 115 / IFRS 15
* Author: KAVITA.RAO
* Date: 20210316
*----------------------------------------------------------------------*
REPORT ZFI_REVENUE_RECOGNITION.

TABLES: VBRK, VBRP, BSEG, BKPF.

DATA: BEGIN OF lt_revenue OCCURS 0,
        VBELN TYPE VBRK-VBELN,
        FKART TYPE VBRK-FKART,
        NETWR TYPE VBRK-NETWR,
        WAERK TYPE VBRK-WAERK,
        FKDAT TYPE VBRK-FKDAT,
        RECOGNIZED TYPE p DECIMALS 2,
        DEFERRED   TYPE p DECIMALS 2,
      END OF lt_revenue.

DATA: lv_total_rec TYPE p DECIMALS 2,
      lv_total_def TYPE p DECIMALS 2.

SELECT-OPTIONS: s_fkdat FOR VBRK-FKDAT.

START-OF-SELECTION.

  SELECT * FROM VBRK INTO CORRESPONDING FIELDS OF TABLE lt_revenue
    WHERE FKDAT IN s_fkdat
    AND   FKSTO = ' '.

  LOOP AT lt_revenue.
    IF lt_revenue-FKART = 'F2'.
      MOVE lt_revenue-NETWR TO lt_revenue-RECOGNIZED.
    ELSE.
      MOVE lt_revenue-NETWR TO lt_revenue-DEFERRED.
    ENDIF.

    ADD lt_revenue-RECOGNIZED TO lv_total_rec.
    ADD lt_revenue-DEFERRED TO lv_total_def.

    WRITE: / lt_revenue-VBELN, lt_revenue-FKDAT,
             lt_revenue-RECOGNIZED, lt_revenue-DEFERRED.
  ENDLOOP.

  WRITE: / 'Recognized:', lv_total_rec, 'Deferred:', lv_total_def.
""",

"ZFI_TAX_REPORTING": """*----------------------------------------------------------------------*
* Program: ZFI_TAX_REPORTING
* Description: Comprehensive GST/TDS tax return preparation
* Author: ARUN.JOSHI
* Date: 20220110
*----------------------------------------------------------------------*
REPORT ZFI_TAX_REPORTING.

TABLES: BSEG, BKPF, J_1IEXCHDR, WITH_ITEM.

DATA: BEGIN OF lt_tax OCCURS 0,
        BUKRS TYPE BSEG-BUKRS,
        BELNR TYPE BSEG-BELNR,
        GJAHR TYPE BSEG-GJAHR,
        MWSKZ TYPE BSEG-MWSKZ,
        FWBAS TYPE BSEG-FWBAS,
        HWBAS TYPE BSEG-HWBAS,
        TAX_AMT TYPE p DECIMALS 2,
      END OF lt_tax.

DATA: lv_cgst TYPE p DECIMALS 2,
      lv_sgst TYPE p DECIMALS 2,
      lv_igst TYPE p DECIMALS 2.

SELECT-OPTIONS: s_bukrs FOR BSEG-BUKRS,
                s_gjahr FOR BKPF-GJAHR,
                s_monat FOR BKPF-MONAT.

START-OF-SELECTION.

  SELECT * FROM BSEG INTO CORRESPONDING FIELDS OF TABLE lt_tax
    WHERE BUKRS IN s_bukrs
    AND   MWSKZ <> ' '.

  LOOP AT lt_tax.
    CASE lt_tax-MWSKZ.
      WHEN 'CG'. ADD lt_tax-TAX_AMT TO lv_cgst.
      WHEN 'SG'. ADD lt_tax-TAX_AMT TO lv_sgst.
      WHEN 'IG'. ADD lt_tax-TAX_AMT TO lv_igst.
    ENDCASE.

    WRITE: / lt_tax-BELNR, lt_tax-MWSKZ, lt_tax-FWBAS,
             lt_tax-TAX_AMT.
  ENDLOOP.

  WRITE: / 'CGST:', lv_cgst, 'SGST:', lv_sgst, 'IGST:', lv_igst.
""",

# ─────────────────────────────────────────────────────────────────
# ADVANCED MM PROGRAMS
# ─────────────────────────────────────────────────────────────────

"ZMM_VENDOR_EVAL": """*----------------------------------------------------------------------*
* Program: ZMM_VENDOR_EVAL
* Description: Vendor evaluation scoring with delivery & quality metrics
* Author: PRAKASH.SINGH
* Date: 20180420
*----------------------------------------------------------------------*
REPORT ZMM_VENDOR_EVAL.

TABLES: LFA1, EKKO, EKPO, EBAN, MKPF.

DATA: BEGIN OF lt_vendors OCCURS 0,
        LIFNR TYPE LFA1-LIFNR,
        NAME1 TYPE LFA1-NAME1,
        PO_COUNT TYPE i,
        ON_TIME  TYPE i,
        LATE     TYPE i,
        QUALITY_SCORE TYPE p DECIMALS 2,
        OVERALL_SCORE TYPE p DECIMALS 2,
      END OF lt_vendors.

SELECT-OPTIONS: s_lifnr FOR LFA1-LIFNR.

START-OF-SELECTION.

  SELECT * FROM LFA1 INTO CORRESPONDING FIELDS OF TABLE lt_vendors
    WHERE LIFNR IN s_lifnr.

  LOOP AT lt_vendors.
    SELECT COUNT(*) FROM EKKO INTO lt_vendors-PO_COUNT
      WHERE LIFNR = lt_vendors-LIFNR.

    IF lt_vendors-PO_COUNT > 0.
      COMPUTE lt_vendors-OVERALL_SCORE =
        ( lt_vendors-ON_TIME / lt_vendors-PO_COUNT ) * 100.
    ENDIF.

    WRITE: / lt_vendors-LIFNR, lt_vendors-NAME1,
             lt_vendors-PO_COUNT, lt_vendors-OVERALL_SCORE.
  ENDLOOP.

  CALL FUNCTION 'REUSE_ALV_GRID_DISPLAY'
    EXPORTING
      i_structure_name = 'LFA1'
    TABLES
      t_outtab         = lt_vendors.
""",

"ZMM_CONTRACT_RELEASE": """*----------------------------------------------------------------------*
* Program: ZMM_CONTRACT_RELEASE
* Description: Contract release order creation against outline agreements
* Author: SWATI.MALHOTRA
* Date: 20190715
*----------------------------------------------------------------------*
REPORT ZMM_CONTRACT_RELEASE.

TABLES: EKKO, EKPO, EKAB.

DATA: BEGIN OF lt_contracts OCCURS 0,
        EBELN TYPE EKKO-EBELN,
        LIFNR TYPE EKKO-LIFNR,
        KDATB TYPE EKKO-KDATB,
        KDATE TYPE EKKO-KDATE,
        MATNR TYPE EKPO-MATNR,
        KTMNG TYPE EKPO-KTMNG,
        KBMNG TYPE EKAB-KBMNG,
        REMAINING TYPE p DECIMALS 3,
      END OF lt_contracts.

SELECT-OPTIONS: s_ebeln FOR EKKO-EBELN,
                s_lifnr FOR EKKO-LIFNR.

START-OF-SELECTION.

  SELECT * FROM EKKO INTO CORRESPONDING FIELDS OF TABLE lt_contracts
    WHERE EBELN IN s_ebeln
    AND   LIFNR IN s_lifnr
    AND   BSART IN ('MK', 'WK').

  LOOP AT lt_contracts.
    SELECT SINGLE * FROM EKPO
      WHERE EBELN = lt_contracts-EBELN.

    COMPUTE lt_contracts-REMAINING =
      lt_contracts-KTMNG - lt_contracts-KBMNG.

    WRITE: / lt_contracts-EBELN, lt_contracts-LIFNR,
             lt_contracts-MATNR, lt_contracts-REMAINING.
  ENDLOOP.
""",

"ZMM_CONSIGNMENT": """*----------------------------------------------------------------------*
* Program: ZMM_CONSIGNMENT
* Description: Consignment stock monitoring and settlement
* Author: ANITA.KAUR
* Date: 20200528
*----------------------------------------------------------------------*
REPORT ZMM_CONSIGNMENT.

TABLES: MKPF, MSEG, MARD, MSKU.

DATA: BEGIN OF lt_consign OCCURS 0,
        MATNR TYPE MSKU-MATNR,
        WERKS TYPE MSKU-WERKS,
        LIFNR TYPE MSKU-LIFNR,
        KULAB TYPE MSKU-KULAB,
        KUINS TYPE MSKU-KUINS,
        TOTAL TYPE p DECIMALS 3,
      END OF lt_consign.

SELECT-OPTIONS: s_werks FOR MSKU-WERKS,
                s_lifnr FOR MSKU-LIFNR.

START-OF-SELECTION.

  SELECT * FROM MSKU INTO CORRESPONDING FIELDS OF TABLE lt_consign
    WHERE WERKS IN s_werks
    AND   LIFNR IN s_lifnr.

  LOOP AT lt_consign.
    COMPUTE lt_consign-TOTAL = lt_consign-KULAB + lt_consign-KUINS.

    WRITE: / lt_consign-MATNR, lt_consign-LIFNR,
             lt_consign-KULAB, lt_consign-KUINS, lt_consign-TOTAL.
  ENDLOOP.
""",

"ZMM_SUBCONTRACT": """*----------------------------------------------------------------------*
* Program: ZMM_SUBCONTRACT
* Description: Subcontracting stock monitoring and challan tracking
* Author: GEETA.RAO
* Date: 20210312
*----------------------------------------------------------------------*
REPORT ZMM_SUBCONTRACT.

TABLES: EKKO, EKPO, MSSL, MSEG.

DATA: BEGIN OF lt_subcon OCCURS 0,
        EBELN TYPE EKKO-EBELN,
        LIFNR TYPE EKKO-LIFNR,
        MATNR TYPE EKPO-MATNR,
        MENGE TYPE EKPO-MENGE,
        WEMNG TYPE EKPO-WEMNG,
        PENDING TYPE p DECIMALS 3,
      END OF lt_subcon.

SELECT-OPTIONS: s_lifnr FOR EKKO-LIFNR.

START-OF-SELECTION.

  SELECT * FROM EKKO INTO CORRESPONDING FIELDS OF TABLE lt_subcon
    WHERE LIFNR IN s_lifnr
    AND   BSART = 'L'.

  LOOP AT lt_subcon.
    SELECT SINGLE * FROM EKPO
      WHERE EBELN = lt_subcon-EBELN.

    COMPUTE lt_subcon-PENDING = lt_subcon-MENGE - lt_subcon-WEMNG.

    WRITE: / lt_subcon-EBELN, lt_subcon-LIFNR,
             lt_subcon-MATNR, lt_subcon-PENDING, 'pending'.
  ENDLOOP.
""",

# ─────────────────────────────────────────────────────────────────
# ADVANCED SD PROGRAMS
# ─────────────────────────────────────────────────────────────────

"ZSD_REBATE_SETTLEMENT": """*----------------------------------------------------------------------*
* Program: ZSD_REBATE_SETTLEMENT
* Description: Rebate agreement settlement and credit memo creation
* Author: MOHAN.VERMA
* Date: 20190220
*----------------------------------------------------------------------*
REPORT ZSD_REBATE_SETTLEMENT.

TABLES: KONA, KONV, VBRK, VBRP.

DATA: BEGIN OF lt_rebates OCCURS 0,
        KNUMA TYPE KONA-KNUMA,
        BOESSION TYPE KONA-BOESSION,
        LIFNR TYPE KONA-LIFNR,
        KUNNR TYPE KONA-KUNNR,
        DATAB TYPE KONA-DATAB,
        DATBI TYPE KONA-DATBI,
        ACCRUAL TYPE p DECIMALS 2,
        SETTLED TYPE p DECIMALS 2,
      END OF lt_rebates.

SELECT-OPTIONS: s_kunnr FOR KONA-KUNNR.

START-OF-SELECTION.

  SELECT * FROM KONA INTO CORRESPONDING FIELDS OF TABLE lt_rebates
    WHERE KUNNR IN s_kunnr
    AND   BOESSION = '0003'.

  LOOP AT lt_rebates.
    WRITE: / lt_rebates-KNUMA, lt_rebates-KUNNR,
             lt_rebates-ACCRUAL, lt_rebates-SETTLED.
  ENDLOOP.

  CALL FUNCTION 'BAPI_BILLINGDOC_CREATEMULTIPLE'.
  COMMIT WORK.
""",

"ZSD_RETURNS_PROCESSING": """*----------------------------------------------------------------------*
* Program: ZSD_RETURNS_PROCESSING
* Description: Customer returns processing with credit memo posting
* Author: REKHA.CHATTERJEE
* Date: 20200625
*----------------------------------------------------------------------*
REPORT ZSD_RETURNS_PROCESSING.

TABLES: VBAK, VBAP, VBRK, LIKP, LIPS.

DATA: BEGIN OF lt_returns OCCURS 0,
        VBELN TYPE VBAK-VBELN,
        KUNNR TYPE VBAK-KUNNR,
        AUART TYPE VBAK-AUART,
        MATNR TYPE VBAP-MATNR,
        KWMENG TYPE VBAP-KWMENG,
        NETWR TYPE VBAP-NETWR,
        REASON TYPE c LENGTH 4,
      END OF lt_returns.

DATA: lv_return_value TYPE p DECIMALS 2.

SELECT-OPTIONS: s_vbeln FOR VBAK-VBELN,
                s_kunnr FOR VBAK-KUNNR.

START-OF-SELECTION.

  SELECT * FROM VBAK INTO CORRESPONDING FIELDS OF TABLE lt_returns
    WHERE VBELN IN s_vbeln
    AND   KUNNR IN s_kunnr
    AND   AUART IN ('RE', 'ZRE').

  LOOP AT lt_returns.
    SELECT SINGLE * FROM VBAP
      WHERE VBELN = lt_returns-VBELN.

    ADD lt_returns-NETWR TO lv_return_value.

    WRITE: / lt_returns-VBELN, lt_returns-KUNNR,
             lt_returns-MATNR, lt_returns-KWMENG,
             lt_returns-NETWR.
  ENDLOOP.

  WRITE: / 'Total return value:', lv_return_value.
""",

"ZSD_INTERCOMPANY_BILLING": """*----------------------------------------------------------------------*
* Program: ZSD_INTERCOMPANY_BILLING
* Description: Intercompany billing for cross-company sales
* Author: DIVYA.DESAI
* Date: 20210918
*----------------------------------------------------------------------*
REPORT ZSD_INTERCOMPANY_BILLING.

TABLES: VBRK, VBRP, VBAK, VBAP, T001.

DATA: BEGIN OF lt_ic_billing OCCURS 0,
        VBELN  TYPE VBRK-VBELN,
        FKART  TYPE VBRK-FKART,
        BUKRS  TYPE VBRK-BUKRS,
        NETWR  TYPE VBRK-NETWR,
        WAERK  TYPE VBRK-WAERK,
        FKDAT  TYPE VBRK-FKDAT,
        VBELN_SO TYPE VBAK-VBELN,
        BUKRS_SO TYPE c LENGTH 4,
      END OF lt_ic_billing.

DATA: lv_total TYPE p DECIMALS 2.

SELECT-OPTIONS: s_fkdat FOR VBRK-FKDAT,
                s_bukrs FOR VBRK-BUKRS.

START-OF-SELECTION.

  SELECT * FROM VBRK INTO CORRESPONDING FIELDS OF TABLE lt_ic_billing
    WHERE FKDAT IN s_fkdat
    AND   BUKRS IN s_bukrs
    AND   FKART IN ('IV', 'ZIV').

  LOOP AT lt_ic_billing.
    SELECT SINGLE VBELN FROM VBRP INTO lt_ic_billing-VBELN_SO
      WHERE VBELN = lt_ic_billing-VBELN.

    ADD lt_ic_billing-NETWR TO lv_total.

    WRITE: / lt_ic_billing-VBELN, lt_ic_billing-BUKRS,
             lt_ic_billing-NETWR, lt_ic_billing-FKDAT.
  ENDLOOP.

  WRITE: / 'Total IC billing:', lv_total.

  CALL FUNCTION 'REUSE_ALV_GRID_DISPLAY'
    EXPORTING
      i_structure_name = 'VBRK'
    TABLES
      t_outtab         = lt_ic_billing.
""",

    # =========================================================================
    # 85. BKPF/BSEG — Financial Document Reporter (FI)
    # =========================================================================
    "Z_FI_BKPF_BSEG_REPORT": """
REPORT z_fi_bkpf_bseg_report.

TABLES: bkpf, bseg.

SELECT-OPTIONS: s_bukrs FOR bkpf-bukrs,
                s_belnr FOR bkpf-belnr,
                s_gjahr FOR bkpf-gjahr.

DATA: lt_docs TYPE TABLE OF bkpf,
      lt_items TYPE TABLE OF bseg.

SELECT * FROM bkpf INTO TABLE lt_docs
  WHERE bukrs IN s_bukrs
    AND belnr IN s_belnr
    AND gjahr IN s_gjahr.

LOOP AT lt_docs INTO DATA(ls_doc).
  SELECT * FROM bseg INTO TABLE lt_items
    WHERE bukrs = ls_doc-bukrs
      AND belnr = ls_doc-belnr
      AND gjahr = ls_doc-gjahr.

  WRITE: / ls_doc-belnr, ls_doc-blart, ls_doc-budat.
  LOOP AT lt_items INTO DATA(ls_item).
    WRITE: /10 ls_item-buzei, ls_item-hkont,
               ls_item-dmbtr, ls_item-wrbtr.
  ENDLOOP.
ENDLOOP.
""",

    # =========================================================================
    # 86. KONV — Pricing Condition Analyzer (SD)
    # =========================================================================
    "Z_SD_KONV_PRICING": """
REPORT z_sd_konv_pricing.

TABLES: konv.

SELECT-OPTIONS: s_knumv FOR konv-knumv.
PARAMETERS: p_kposn TYPE konv-kposn.

DATA: lt_cond TYPE TABLE OF konv.

SELECT * FROM konv INTO TABLE lt_cond
  WHERE knumv IN s_knumv
    AND kposn = p_kposn.

LOOP AT lt_cond INTO DATA(ls_cond).
  WRITE: / ls_cond-kschl, ls_cond-kbetr,
           ls_cond-kwert, ls_cond-waers.
ENDLOOP.
""",

    # =========================================================================
    # 87. COEP — CO Line Item Report (Cost Object Controlling)
    # =========================================================================
    "Z_CO_COEP_LINEITEM": """
REPORT z_co_coep_lineitem.

TABLES: coep.

SELECT-OPTIONS: s_objnr FOR coep-objnr,
                s_gjahr FOR coep-gjahr,
                s_perio FOR coep-perab.

DATA: lt_coep TYPE TABLE OF coep,
      lv_sum  TYPE coep-wkgbtr.

SELECT * FROM coep INTO TABLE lt_coep
  WHERE objnr IN s_objnr
    AND gjahr IN s_gjahr
    AND perab IN s_perio
    AND versn = '000'.

LOOP AT lt_coep INTO DATA(ls_coep).
  WRITE: / ls_coep-objnr, ls_coep-kstar, ls_coep-wkgbtr,
           ls_coep-perab, ls_coep-beknz.
  lv_sum = lv_sum + ls_coep-wkgbtr.
ENDLOOP.

WRITE: / 'Total actual costs:', lv_sum.
""",

    # =========================================================================
    # 88. CE1xxxx — CO-PA Profitability Report
    # =========================================================================
    "Z_COPA_CE1_REPORT": """
REPORT z_copa_ce1_report.

*----------------------------------------------------------------------*
* CO-PA costing-based analysis — reads CE1xxxx operating concern table
* This table is REMOVED in S/4HANA (replaced by account-based CO-PA
* in ACDOCA). Critical migration candidate.
*----------------------------------------------------------------------*

TABLES: ce1t100.

SELECT-OPTIONS: s_paobjnr FOR ce1t100-paobjnr,
                s_gjahr   FOR ce1t100-gjahr.

DATA: lt_copa TYPE TABLE OF ce1t100.

SELECT * FROM ce1t100 INTO TABLE lt_copa
  WHERE paobjnr IN s_paobjnr
    AND gjahr IN s_gjahr.

LOOP AT lt_copa INTO DATA(ls_copa).
  WRITE: / ls_copa-paobjnr, ls_copa-gjahr,
           ls_copa-vv010, ls_copa-vv020.
ENDLOOP.
""",

    # =========================================================================
    # 89. KNA1/KNB1 — Customer Master Reader
    # =========================================================================
    "Z_SD_KNA1_CUSTOMER_MASTER": """
REPORT z_sd_kna1_customer_master.

TABLES: kna1, knb1.

SELECT-OPTIONS: s_kunnr FOR kna1-kunnr,
                s_bukrs FOR knb1-bukrs.

DATA: lt_cust TYPE TABLE OF kna1,
      lt_comp TYPE TABLE OF knb1.

SELECT * FROM kna1 INTO TABLE lt_cust
  WHERE kunnr IN s_kunnr.

LOOP AT lt_cust INTO DATA(ls_cust).
  WRITE: / ls_cust-kunnr, ls_cust-name1, ls_cust-land1, ls_cust-stcd1.

  SELECT * FROM knb1 INTO TABLE lt_comp
    WHERE kunnr = ls_cust-kunnr
      AND bukrs IN s_bukrs.

  LOOP AT lt_comp INTO DATA(ls_comp).
    WRITE: /10 ls_comp-bukrs, ls_comp-akont, ls_comp-zterm.
  ENDLOOP.
ENDLOOP.
""",

    # =========================================================================
    # 90. LFA1/LFB1 — Vendor Master Reader
    # =========================================================================
    "Z_MM_LFA1_VENDOR_MASTER": """
REPORT z_mm_lfa1_vendor_master.

TABLES: lfa1, lfb1.

SELECT-OPTIONS: s_lifnr FOR lfa1-lifnr,
                s_bukrs FOR lfb1-bukrs.

DATA: lt_vend TYPE TABLE OF lfa1.

SELECT * FROM lfa1 INTO TABLE lt_vend
  WHERE lifnr IN s_lifnr.

LOOP AT lt_vend INTO DATA(ls_vend).
  WRITE: / ls_vend-lifnr, ls_vend-name1, ls_vend-land1.

  SELECT SINGLE * FROM lfb1 INTO DATA(ls_comp)
    WHERE lifnr = ls_vend-lifnr
      AND bukrs IN s_bukrs.

  IF sy-subrc = 0.
    WRITE: ls_comp-akont, ls_comp-zterm, ls_comp-zwels.
  ENDIF.
ENDLOOP.
""",

    # =========================================================================
    # 91. FAGLFLEXT — New GL Totals Report (FI)
    # =========================================================================
    "Z_FI_FAGLFLEXT_TOTALS": """
REPORT z_fi_faglflext_totals.

TABLES: faglflext.

SELECT-OPTIONS: s_bukrs FOR faglflext-rbukrs,
                s_racct FOR faglflext-racct,
                s_gjahr FOR faglflext-ryear.

DATA: lt_totals TYPE TABLE OF faglflext.

SELECT * FROM faglflext INTO TABLE lt_totals
  WHERE rbukrs IN s_bukrs
    AND racct IN s_racct
    AND ryear IN s_gjahr
    AND rldnr = '0L'.

LOOP AT lt_totals INTO DATA(ls_tot).
  WRITE: / ls_tot-racct, ls_tot-rbukrs,
           ls_tot-hsl01, ls_tot-hsl02, ls_tot-hsl03,
           ls_tot-hsl04, ls_tot-hsl05, ls_tot-hsl06.
ENDLOOP.
""",

    # =========================================================================
    # 92. ANLA/ANLC — Asset Master & Values Report
    # =========================================================================
    "Z_FI_AA_ASSET_REPORT": """
REPORT z_fi_aa_asset_report.

TABLES: anla, anlc.

SELECT-OPTIONS: s_bukrs FOR anla-bukrs,
                s_anlkl FOR anla-anlkl,
                s_gjahr FOR anlc-gjahr.

DATA: lt_assets TYPE TABLE OF anla,
      lv_nbv   TYPE anlc-kansw.

SELECT * FROM anla INTO TABLE lt_assets
  WHERE bukrs IN s_bukrs
    AND anlkl IN s_anlkl.

LOOP AT lt_assets INTO DATA(ls_asset).
  SELECT SINGLE kansw knafa FROM anlc INTO (ls_asset-kansw, ls_asset-knafa)
    WHERE bukrs = ls_asset-bukrs
      AND anln1 = ls_asset-anln1
      AND anln2 = ls_asset-anln2
      AND gjahr IN s_gjahr
      AND afabe = '01'.

  lv_nbv = ls_asset-kansw - ls_asset-knafa.
  WRITE: / ls_asset-anln1, ls_asset-txt50, ls_asset-anlkl,
           ls_asset-kansw, ls_asset-knafa, lv_nbv.
ENDLOOP.
""",

    # =========================================================================
    # 93. VBBE — Individual Customer Requirement (Removed in S/4HANA)
    # =========================================================================
    "Z_SD_VBBE_REQUIREMENTS": """
REPORT z_sd_vbbe_requirements.

*----------------------------------------------------------------------*
* CRITICAL: Table VBBE is REMOVED in S/4HANA.
* Individual customer requirements are derived at runtime from VBEP.
* This program must be rewritten for S/4HANA compatibility.
*----------------------------------------------------------------------*

TABLES: vbbe.

SELECT-OPTIONS: s_vbeln FOR vbbe-vbeln,
                s_matnr FOR vbbe-matnr,
                s_werks FOR vbbe-werks.

DATA: lt_req TYPE TABLE OF vbbe.

SELECT * FROM vbbe INTO TABLE lt_req
  WHERE vbeln IN s_vbeln
    AND matnr IN s_matnr
    AND werks IN s_werks.

LOOP AT lt_req INTO DATA(ls_req).
  WRITE: / ls_req-vbeln, ls_req-posnr, ls_req-matnr,
           ls_req-werks, ls_req-omeng, ls_req-mbdat.
ENDLOOP.
""",

    # =========================================================================
    # 94. MBEW — Material Valuation Report (Material Ledger)
    # =========================================================================
    "Z_MM_MBEW_VALUATION": """
REPORT z_mm_mbew_valuation.

TABLES: mbew.

SELECT-OPTIONS: s_matnr FOR mbew-matnr,
                s_bwkey FOR mbew-bwkey.

DATA: lt_val TYPE TABLE OF mbew.

SELECT * FROM mbew INTO TABLE lt_val
  WHERE matnr IN s_matnr
    AND bwkey IN s_bwkey.

LOOP AT lt_val INTO DATA(ls_val).
  WRITE: / ls_val-matnr, ls_val-bwkey, ls_val-vprsv,
           ls_val-verpr, ls_val-stprs, ls_val-lbkum,
           ls_val-salk3, ls_val-peinh.
ENDLOOP.
""",

    # =========================================================================
    # 95. NAST — Output Message Control Reader
    # =========================================================================
    "Z_SD_NAST_OUTPUT": """
REPORT z_sd_nast_output.

*----------------------------------------------------------------------*
* NAST-based output determination is replaced by BRF+/PPF in S/4HANA.
* This program reads output messages — must migrate to new output mgmt.
*----------------------------------------------------------------------*

TABLES: nast.

SELECT-OPTIONS: s_objky FOR nast-objky,
                s_kappl FOR nast-kappl,
                s_kschl FOR nast-kschl.

DATA: lt_output TYPE TABLE OF nast.

SELECT * FROM nast INTO TABLE lt_output
  WHERE objky IN s_objky
    AND kappl IN s_kappl
    AND kschl IN s_kschl.

LOOP AT lt_output INTO DATA(ls_out).
  WRITE: / ls_out-objky, ls_out-kappl, ls_out-kschl,
           ls_out-naession, ls_out-vstat.
ENDLOOP.
""",

    # =========================================================================
    # 96. BSAD/BSID — Cleared/Open Customer Items (FI-AR)
    # =========================================================================
    "Z_FI_BSAD_BSID_REPORT": """
REPORT z_fi_bsad_bsid_report.

*----------------------------------------------------------------------*
* BSAD (cleared) / BSID (open) — In S/4HANA these are compatibility
* views from ACDOCA. The open/cleared split is based on AUGDT field.
*----------------------------------------------------------------------*

TABLES: bsid, bsad.

SELECT-OPTIONS: s_bukrs FOR bsid-bukrs,
                s_kunnr FOR bsid-kunnr,
                s_budat FOR bsid-budat.

DATA: lt_open    TYPE TABLE OF bsid,
      lt_cleared TYPE TABLE OF bsad,
      lv_open    TYPE bsid-dmbtr,
      lv_cleared TYPE bsad-dmbtr.

SELECT * FROM bsid INTO TABLE lt_open
  WHERE bukrs IN s_bukrs
    AND kunnr IN s_kunnr
    AND budat IN s_budat.

LOOP AT lt_open INTO DATA(ls_open).
  lv_open = lv_open + ls_open-dmbtr.
  WRITE: / 'OPEN', ls_open-belnr, ls_open-budat,
           ls_open-dmbtr, ls_open-kunnr.
ENDLOOP.

SELECT * FROM bsad INTO TABLE lt_cleared
  WHERE bukrs IN s_bukrs
    AND kunnr IN s_kunnr
    AND budat IN s_budat.

LOOP AT lt_cleared INTO DATA(ls_clr).
  lv_cleared = lv_cleared + ls_clr-dmbtr.
  WRITE: / 'CLRD', ls_clr-belnr, ls_clr-budat,
           ls_clr-dmbtr, ls_clr-augdt.
ENDLOOP.

WRITE: / 'Open total:', lv_open, '| Cleared total:', lv_cleared.
""",

    # =========================================================================
    # 97. REGUH/REGUP — Payment Run Analysis (FI-AP)
    # =========================================================================
    "Z_FI_REGUH_PAYMENT": """
REPORT z_fi_reguh_payment.

TABLES: reguh, regup.

SELECT-OPTIONS: s_laufd FOR reguh-laufd,
                s_laufi FOR reguh-laufi,
                s_zbukr FOR reguh-zbukr.

DATA: lt_header TYPE TABLE OF reguh,
      lt_items  TYPE TABLE OF regup.

SELECT * FROM reguh INTO TABLE lt_header
  WHERE laufd IN s_laufd
    AND laufi IN s_laufi
    AND zbukr IN s_zbukr.

LOOP AT lt_header INTO DATA(ls_hdr).
  WRITE: / ls_hdr-laufd, ls_hdr-laufi, ls_hdr-lifnr,
           ls_hdr-rwbtr, ls_hdr-waession.

  SELECT * FROM regup INTO TABLE lt_items
    WHERE laufd = ls_hdr-laufd
      AND laufi = ls_hdr-laufi
      AND zbukr = ls_hdr-zbukr.

  LOOP AT lt_items INTO DATA(ls_item).
    WRITE: /10 ls_item-belnr, ls_item-dmbtr.
  ENDLOOP.
ENDLOOP.
""",

    # =========================================================================
    # 98. CDHDR/CDPOS — Change Document Reader
    # =========================================================================
    "Z_BC_CDHDR_CHANGES": """
REPORT z_bc_cdhdr_changes.

TABLES: cdhdr, cdpos.

SELECT-OPTIONS: s_objcl FOR cdhdr-objectclas,
                s_objid FOR cdhdr-objectid,
                s_udate FOR cdhdr-udate.

DATA: lt_hdr TYPE TABLE OF cdhdr,
      lt_pos TYPE TABLE OF cdpos.

SELECT * FROM cdhdr INTO TABLE lt_hdr
  WHERE objectclas IN s_objcl
    AND objectid IN s_objid
    AND udate IN s_udate.

LOOP AT lt_hdr INTO DATA(ls_hdr).
  WRITE: / ls_hdr-objectclas, ls_hdr-objectid, ls_hdr-username,
           ls_hdr-udate, ls_hdr-utime.

  SELECT * FROM cdpos INTO TABLE lt_pos
    WHERE objectclas = ls_hdr-objectclas
      AND objectid = ls_hdr-objectid
      AND changenr = ls_hdr-changenr.

  LOOP AT lt_pos INTO DATA(ls_pos).
    WRITE: /10 ls_pos-tabname, ls_pos-fname,
               ls_pos-value_old, ls_pos-value_new.
  ENDLOOP.
ENDLOOP.
""",

    # =========================================================================
    # 99. STXH/STXL — SAPscript Text Reader (Legacy Forms)
    # =========================================================================
    "Z_BC_STXH_TEXT_READER": """
REPORT z_bc_stxh_text_reader.

*----------------------------------------------------------------------*
* SAPscript text reading — STXH/STXL.
* SAPscript/SmartForms deprecated in S/4HANA, migrate to Adobe Forms.
*----------------------------------------------------------------------*

TABLES: stxh.

SELECT-OPTIONS: s_tdobject FOR stxh-tdobject,
                s_tdname   FOR stxh-tdname,
                s_tdid     FOR stxh-tdid.

DATA: lt_texts TYPE TABLE OF stxh,
      lt_lines TYPE TABLE OF tline.

SELECT * FROM stxh INTO TABLE lt_texts
  WHERE tdobject IN s_tdobject
    AND tdname IN s_tdname
    AND tdid IN s_tdid.

LOOP AT lt_texts INTO DATA(ls_text).
  WRITE: / ls_text-tdname, ls_text-tdid, ls_text-tdspras.

  CALL FUNCTION 'READ_TEXT'
    EXPORTING
      object    = ls_text-tdobject
      name      = ls_text-tdname
      id        = ls_text-tdid
      language  = ls_text-tdspras
    TABLES
      lines     = lt_lines
    EXCEPTIONS
      OTHERS    = 1.

  LOOP AT lt_lines INTO DATA(ls_line).
    WRITE: /10 ls_line-tdline.
  ENDLOOP.
ENDLOOP.
""",

    # =========================================================================
    # 100. PROJ/PRPS — Project System Hierarchy Report
    # =========================================================================
    "Z_PS_PROJECT_REPORT": """
REPORT z_ps_project_report.

TABLES: proj, prps, prhi.

SELECT-OPTIONS: s_pspnr FOR proj-pspnr,
                s_pspid FOR proj-pspid.

DATA: lt_proj TYPE TABLE OF proj,
      lt_wbs  TYPE TABLE OF prps.

SELECT * FROM proj INTO TABLE lt_proj
  WHERE pspnr IN s_pspnr
    AND pspid IN s_pspid.

LOOP AT lt_proj INTO DATA(ls_proj).
  WRITE: / 'Project:', ls_proj-pspid, ls_proj-post1,
           'Status:', ls_proj-stat.

  SELECT * FROM prps INTO TABLE lt_wbs
    WHERE psphi = ls_proj-pspnr.

  LOOP AT lt_wbs INTO DATA(ls_wbs).
    WRITE: /10 ls_wbs-posid, ls_wbs-post1, ls_wbs-stufe,
               ls_wbs-psphi, ls_wbs-stat.
  ENDLOOP.
ENDLOOP.
""",

    # =========================================================================
    # 101. EKBE — Purchase Order History Report (GR/IR)
    # =========================================================================
    "Z_MM_EKBE_PO_HISTORY": """
REPORT z_mm_ekbe_po_history.

TABLES: ekbe.

SELECT-OPTIONS: s_ebeln FOR ekbe-ebeln,
                s_ebelp FOR ekbe-ebelp,
                s_gjahr FOR ekbe-gjahr.

DATA: lt_hist TYPE TABLE OF ekbe,
      lv_gr   TYPE ekbe-dmbtr,
      lv_ir   TYPE ekbe-dmbtr.

SELECT * FROM ekbe INTO TABLE lt_hist
  WHERE ebeln IN s_ebeln
    AND ebelp IN s_ebelp
    AND gjahr IN s_gjahr.

LOOP AT lt_hist INTO DATA(ls_hist).
  CASE ls_hist-bewtp.
    WHEN 'E'.  " Goods Receipt
      lv_gr = lv_gr + ls_hist-dmbtr.
      WRITE: / 'GR', ls_hist-belnr, ls_hist-budat, ls_hist-dmbtr.
    WHEN 'Q'.  " Invoice Receipt
      lv_ir = lv_ir + ls_hist-dmbtr.
      WRITE: / 'IR', ls_hist-belnr, ls_hist-budat, ls_hist-dmbtr.
  ENDCASE.
ENDLOOP.

WRITE: / 'GR Total:', lv_gr, '| IR Total:', lv_ir.
WRITE: / 'GR/IR Diff:', lv_gr - lv_ir.
""",

    # =========================================================================
    # 102. VBFA — Sales Document Flow Analyzer
    # =========================================================================
    "Z_SD_VBFA_DOC_FLOW": """
REPORT z_sd_vbfa_doc_flow.

TABLES: vbfa.

PARAMETERS: p_vbeln TYPE vbfa-vbelv.

DATA: lt_flow TYPE TABLE OF vbfa.

SELECT * FROM vbfa INTO TABLE lt_flow
  WHERE vbelv = p_vbeln.

SORT lt_flow BY erdat posnv.

WRITE: / 'Document Flow for:', p_vbeln.
ULINE.
LOOP AT lt_flow INTO DATA(ls_flow).
  WRITE: / ls_flow-vbelv, ls_flow-posnv, '->',
           ls_flow-vbeln, ls_flow-posnn,
           ls_flow-vbtyp_n, ls_flow-rfmng, ls_flow-rfwrt.
ENDLOOP.
""",

}


def get_extended_programs():
    """Return all extended sample ABAP programs."""
    return EXTENDED_ABAP_PROGRAMS


def get_all_programs_combined():
    """Combine with original programs from mock_data_generator."""
    try:
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mock-ecc"))
        from mock_data_generator import SAMPLE_ABAP_PROGRAMS
        combined = {}
        combined.update(SAMPLE_ABAP_PROGRAMS)
        combined.update(EXTENDED_ABAP_PROGRAMS)
        return combined
    except ImportError:
        return EXTENDED_ABAP_PROGRAMS


if __name__ == "__main__":
    programs = get_all_programs_combined()
    print(f"Total sample ABAP programs: {len(programs)}")
    total_lines = sum(len(p.split("\n")) for p in programs.values())
    print(f"Total lines of ABAP code: {total_lines}")
    print(f"\nPrograms:")
    for name in sorted(programs.keys()):
        lines = len(programs[name].split("\n"))
        print(f"  {name:45s} {lines:4d} lines")
