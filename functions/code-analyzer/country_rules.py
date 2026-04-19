"""
Migrate4HANA — Global Country Localization Rules
==================================================
Country-specific SAP migration rules for worldwide deployments.

Covers 27 country localizations with 380+ rules:
  - IN (India): GST, TDS, TCS, E-invoice, E-way bill, PAN, GSTIN, Aadhaar,
                PF/ESI, Professional Tax, GSTR filings, HSN/SAC, RCM, ITC
  - US (United States): 1099 (MISC/NEC/INT/DIV), GAAP->IFRS, SOX, sales tax,
                OFAC, FATCA, W-2/W-4/W-9, FICA/FUTA, ACH/EDI, ASC 842/606,
                state payroll taxes, economic nexus (Wayfair)
  - DE (Germany): DATEV, GoBD, HGB, ELSTER, USt-VA, SEPA, Intrastat,
                E-Bilanz, KassenSichV/TSE, Kurzarbeit, social insurance
  - BR (Brazil): NFe/NFS-e/CT-e, SPED (Fiscal/Contribuicoes/Contabil),
                ICMS/IPI/PIS/COFINS, CNPJ/CPF, NCM, CFOP, IRRF, DARF,
                eSocial, EFD-REINF, J_1B tables
  - CN (China): Golden Tax (Baiwang/Aisino), Fapiao, CIT, VAT reform,
                CAS/PRC GAAP, GB/T, social insurance, RMB cross-border,
                bank-tax integration, e-invoice mandate
  - JP (Japan): Consumption tax, qualified invoice (invoice seido),
                reduced rate 8%/10%, e-Tax, social insurance, Zengin,
                year-end adjustment, My Number
  - GB (United Kingdom): MTD (VAT, ITSA), UK VAT, PAYE RTI, Brexit customs,
                FRS, BACS/Faster Payments, CIS, auto-enrolment pension,
                IR35, plastic packaging tax
  - AE/SA (Middle East): UAE VAT, ZATCA, FATOORA Phase 2, TRN, WPS, EOSB,
                GOSI, Bahrain/Oman/Qatar VAT, free zone VAT
  - ZA (South Africa): SARS, VAT 201, EMP201, B-BBEE, UIF/SDL, IRP5/IT3,
                CIPC, exchange control, carbon tax
  - AU (Australia): GST/BAS, STP Phase 2, superannuation, ABN, PAYG,
                TPAR, FBT, WorkCover, JobKeeper/JobMaker
  - FR (France): FEC, DSN, TVA, Chorus Pro/Factur-X, SIRET/SIREN,
                DEB/DES, prelevement a la source, CET/CVAE
  - MX (Mexico): CFDI 4.0, SAT, RFC, IVA/ISR, IMSS/INFONAVIT, Carta Porte,
                DIOT, retenciones
  - KR (South Korea): e-Tax Invoice, K-IFRS, NTS, VAT, withholding,
                social insurance, ERP certification
  - IT (Italy): Fattura Elettronica, SDI, Esterometro, CU/770, F24,
                LIPE, stamp duty, Intrastat
  - PL (Poland): JPK, SAF-T, split payment, KSeF, ZUS, PIT/CIT,
                white list VAT
  - CA (Canada): GST/HST, PST/QST, T4/RL-1, CRA, CPP/EI, SIN, CEWS
  - SG (Singapore): GST, IRAS, PEPPOL, CPF, IRAS e-filing, XBRL
  - EU (European Union): Intrastat, OSS/IOSS, GDPR, reverse charge,
                PEPPOL, DAC7, CBAM, SAF-T EU
  - TH (Thailand): VAT 7%, WHT certificates, BOI, SSF, e-Tax Invoice,
                PND filing, excise, TFRS, customs, baht rounding
  - ID (Indonesia): e-Faktur, PPh 21/23/26, BPJS, PPN 11%, PPnBM,
                DGT customs, transfer pricing, e-Bupot
  - MY (Malaysia): SST Sales/Service Tax, MyInvois e-Invoice, EPF,
                SOCSO, PCB, EIS, LHDN, HRDF, customs/excise
  - PH (Philippines): BIR e-invoicing, EWT/FWT, SSS, PhilHealth,
                Pag-IBIG, VAT 12%, TRAIN law, BIR 2307
  - VN (Vietnam): e-Invoice (Hoa don dien tu), PIT, BHXH/BHYT/BHTN,
                FCT, VAT 10%, CIT 20%, transfer pricing, VND rounding
  - TW (Taiwan): GUI Uniform Invoice, VAT 5%, NHI, Labor Insurance,
                Labor Pension, XBRL, WHT, e-Invoice, business tax
  - HK (Hong Kong): Profits Tax, MPF, Salaries Tax, Property Tax,
                Stamp Duty, IRD filing, ORSO, depreciation, BEPS
  - NZ (New Zealand): GST 15%, PAYE, KiwiSaver, payday filing,
                FBT, ACC levy, RWT, NRWT, IRD e-filing, provisional tax

Also includes additional universal rules:
  - Extended ABAP obsolete patterns
  - More deprecated BAPIs and FMs
  - Fiori/UI5 migration patterns
  - HANA-specific optimizations
  - S/4HANA Cloud restrictions
"""

from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class SimplificationRule:
    id: str
    category: str
    pattern: str
    description: str
    severity: str
    auto_fix: bool = False
    fix_pattern: Optional[str] = None
    fix_replacement: Optional[str] = None
    fix_suggestion: Optional[str] = None
    s4_note: Optional[str] = None
    effort_hours: float = 0.5
    s4_version: str = "2023"
    tags: list = field(default_factory=list)
    country: str = "ALL"  # ALL = universal, IN = India, US = USA, etc.


# =============================================================================
# INDIA LOCALIZATION (IN) — 15 rules
# =============================================================================
INDIA_RULES = [
    SimplificationRule(
        id="IN-001", category="india_localization", country="IN",
        pattern=r"\bJ_1I\w+\b",
        description="India-specific table (J_1I*) — verify compatibility with S/4HANA India localization",
        severity="medium", s4_note="2267384", effort_hours=2.0, tags=["india", "gst"],
    ),
    SimplificationRule(
        id="IN-002", category="india_localization", country="IN",
        pattern=r"\bJ_1IEXCHDR\b|\bJ_1IEXCDTL\b",
        description="Excise tables replaced by GST in S/4HANA — no longer applicable post-GST",
        severity="critical", effort_hours=8.0, tags=["india", "gst", "excise"],
        fix_suggestion="Excise duty abolished post-GST. Remove excise logic, implement GST via S/4 standard.",
    ),
    SimplificationRule(
        id="IN-003", category="india_localization", country="IN",
        pattern=r"GST.*CESS|IGST|CGST|SGST|UTGST",
        description="GST tax handling — verify S/4HANA GST condition types (JIIG, JICG, JISG)",
        severity="medium", effort_hours=4.0, tags=["india", "gst"],
        fix_suggestion="S/4HANA has standard GST condition types. Map custom to standard.",
    ),
    SimplificationRule(
        id="IN-004", category="india_localization", country="IN",
        pattern=r"\bTDS\b.*\b(SECTION|194|195|196)\b|WITHHOLDING.{0,20}TAX",
        description="TDS/Withholding tax — S/4HANA uses Enhanced Extended Withholding Tax",
        severity="medium", effort_hours=3.0, tags=["india", "tds"],
    ),
    SimplificationRule(
        id="IN-005", category="india_localization", country="IN",
        pattern=r"E.?WAY\s*BILL|EWAY",
        description="E-way bill integration — verify NIC API compatibility with S/4HANA",
        severity="medium", effort_hours=2.0, tags=["india", "eway"],
    ),
    SimplificationRule(
        id="IN-006", category="india_localization", country="IN",
        pattern=r"E.?INVOICE|EINVOICE|IRN\b",
        description="E-invoice (IRN) — use SAP Document Compliance for India in S/4HANA",
        severity="medium", effort_hours=4.0, tags=["india", "einvoice"],
        fix_suggestion="Use SAP Document Compliance for India e-invoicing in S/4HANA.",
    ),
    SimplificationRule(
        id="IN-007", category="india_localization", country="IN",
        pattern=r"\bHSN\b|SAC\s*CODE",
        description="HSN/SAC code handling — verify master data mapping in S/4HANA",
        severity="low", effort_hours=1.0, tags=["india", "gst"],
    ),
    SimplificationRule(
        id="IN-008", category="india_localization", country="IN",
        pattern=r"FORM\s*16|FORM\s*26|FORM\s*24Q|FORM\s*27",
        description="Indian tax forms — verify generation capability in S/4HANA",
        severity="medium", effort_hours=4.0, tags=["india", "tds", "compliance"],
    ),
    SimplificationRule(
        id="IN-009", category="india_localization", country="IN",
        pattern=r"\bPAN\b.*\b(NUMBER|CARD|VALID)\b|PAN\s*:\s*[A-Z]{5}\d{4}[A-Z]",
        description="PAN validation — ensure BP master data includes PAN field mapping",
        severity="low", effort_hours=0.5, tags=["india", "compliance"],
    ),
    SimplificationRule(
        id="IN-010", category="india_localization", country="IN",
        pattern=r"\bGSTIN\b|GST.*REGISTRATION|GSTN",
        description="GSTIN handling — map to BP tax numbers in S/4HANA",
        severity="medium", effort_hours=2.0, tags=["india", "gst", "bp"],
        fix_suggestion="GSTIN should be maintained as tax number in Business Partner master.",
    ),
    SimplificationRule(
        id="IN-011", category="india_localization", country="IN",
        pattern=r"GSTR.?[123]|GST\s*RETURN",
        description="GSTR filing — S/4HANA has integrated GST return tools",
        severity="medium", effort_hours=3.0, tags=["india", "gst", "compliance"],
    ),
    SimplificationRule(
        id="IN-012", category="india_localization", country="IN",
        pattern=r"TRACES|TDS\s*CERTIFICATE",
        description="TRACES portal integration — verify API compatibility post-migration",
        severity="medium", effort_hours=2.0, tags=["india", "tds"],
    ),
    SimplificationRule(
        id="IN-013", category="india_localization", country="IN",
        pattern=r"\bPF\b.*\b(CONTRIBUTION|CALCULATION|PROVIDENT)\b|\bEPF\b|\bESI[C]?\b",
        description="PF/ESI calculation — verify HR payroll integration in S/4HANA HCM",
        severity="medium", effort_hours=3.0, tags=["india", "hr", "statutory"],
    ),
    SimplificationRule(
        id="IN-014", category="india_localization", country="IN",
        pattern=r"PROFESSIONAL\s*TAX|P\.?TAX",
        description="Professional tax — state-specific rates need configuration in S/4HANA",
        severity="low", effort_hours=1.0, tags=["india", "hr", "statutory"],
    ),
    SimplificationRule(
        id="IN-015", category="india_localization", country="IN",
        pattern=r"AADHAAR|AADHAR|UID\s*NUMBER",
        description="Aadhaar integration — ensure data privacy compliance in S/4HANA",
        severity="low", effort_hours=1.0, tags=["india", "compliance", "privacy"],
    ),
]

# =============================================================================
# UNITED STATES (US) — 12 rules
# =============================================================================
US_RULES = [
    SimplificationRule(
        id="US-001", category="us_localization", country="US",
        pattern=r"\b1099\b|FORM.{0,5}1099|MISC.{0,10}INCOME",
        description="1099 reporting — S/4HANA has updated 1099-MISC/NEC handling",
        severity="medium", effort_hours=4.0, tags=["us", "tax", "1099"],
        fix_suggestion="Use S/4HANA generic withholding tax with 1099 reporting class.",
    ),
    SimplificationRule(
        id="US-002", category="us_localization", country="US",
        pattern=r"SALES\s*TAX|USE\s*TAX|TAX\s*JURISDICTION",
        description="US Sales/Use tax — verify Vertex/Avalara integration or S/4 tax engine",
        severity="medium", effort_hours=4.0, tags=["us", "tax", "sales-tax"],
    ),
    SimplificationRule(
        id="US-003", category="us_localization", country="US",
        pattern=r"\bGAAP\b|US.{0,5}GAAP|ASC\s*\d{3}",
        description="US GAAP compliance — verify parallel ledger setup in Universal Journal",
        severity="high", effort_hours=8.0, tags=["us", "finance", "gaap"],
    ),
    SimplificationRule(
        id="US-004", category="us_localization", country="US",
        pattern=r"\bSOX\b|SARBANES|SARBOX|SOX\s*COMPLIANCE",
        description="SOX compliance — verify audit trail and controls in S/4HANA",
        severity="high", effort_hours=6.0, tags=["us", "compliance", "audit"],
    ),
    SimplificationRule(
        id="US-005", category="us_localization", country="US",
        pattern=r"\bOFAC\b|SANCTIONED?\s*PART|SDN\s*LIST|DENIED\s*PART",
        description="OFAC/sanctions screening — verify SAP GTS or compliance tool integration",
        severity="high", effort_hours=4.0, tags=["us", "compliance", "trade"],
    ),
    SimplificationRule(
        id="US-006", category="us_localization", country="US",
        pattern=r"W.?[249]\b|FORM\s*W[249]",
        description="W-2/W-4/W-9 processing — verify payroll integration in S/4HANA",
        severity="medium", effort_hours=3.0, tags=["us", "hr", "tax"],
    ),
    SimplificationRule(
        id="US-007", category="us_localization", country="US",
        pattern=r"FEDERAL\s*TAX|STATE\s*TAX|FICA|FUTA|SUTA",
        description="US payroll taxes — verify tax calculation engine in S/4HANA HCM",
        severity="medium", effort_hours=4.0, tags=["us", "hr", "payroll"],
    ),
    SimplificationRule(
        id="US-008", category="us_localization", country="US",
        pattern=r"\bEIN\b|EMPLOYER.{0,10}ID|TAX.{0,5}ID.{0,5}NUMBER",
        description="EIN/Tax ID — map to BP tax numbers in S/4HANA",
        severity="low", effort_hours=1.0, tags=["us", "tax", "bp"],
    ),
    SimplificationRule(
        id="US-009", category="us_localization", country="US",
        pattern=r"ACH\s*(PAYMENT|TRANSFER|FILE)|NACHA",
        description="ACH payment processing — verify bank integration format in S/4HANA",
        severity="medium", effort_hours=3.0, tags=["us", "banking", "payment"],
    ),
    SimplificationRule(
        id="US-010", category="us_localization", country="US",
        pattern=r"EDI\s*(850|810|856|820)|ANSI\s*X12",
        description="ANSI X12 EDI — verify IDoc/EDI mapping in S/4HANA",
        severity="medium", effort_hours=4.0, tags=["us", "edi", "integration"],
    ),
    SimplificationRule(
        id="US-011", category="us_localization", country="US",
        pattern=r"LEASE\s*ACCOUNT|ASC\s*842|IFRS\s*16",
        description="Lease accounting (ASC 842) — S/4HANA has integrated RE-FX",
        severity="high", effort_hours=8.0, tags=["us", "finance", "lease"],
    ),
    SimplificationRule(
        id="US-012", category="us_localization", country="US",
        pattern=r"REVENUE\s*RECOGN|ASC\s*606",
        description="Revenue recognition (ASC 606) — use S/4HANA RAR module",
        severity="high", effort_hours=8.0, tags=["us", "finance", "revenue"],
    ),
]

# =============================================================================
# GERMANY (DE) — 10 rules
# =============================================================================
GERMANY_RULES = [
    SimplificationRule(
        id="DE-001", category="de_localization", country="DE",
        pattern=r"\bDATEV\b|DATEV.{0,10}(EXPORT|INTERFACE|FORMAT)",
        description="DATEV interface — S/4HANA has updated DATEV export format",
        severity="medium", effort_hours=4.0, tags=["de", "tax", "datev"],
    ),
    SimplificationRule(
        id="DE-002", category="de_localization", country="DE",
        pattern=r"\bGoBD\b|GDPdU|GRUNDSAETZE",
        description="GoBD compliance (German fiscal data access) — verify S/4 archiving & audit trail",
        severity="high", effort_hours=6.0, tags=["de", "compliance", "audit"],
    ),
    SimplificationRule(
        id="DE-003", category="de_localization", country="DE",
        pattern=r"\bHGB\b|HANDELSGESETZBUCH|GERMAN\s*GAAP",
        description="HGB (German GAAP) — verify parallel ledger configuration in ACDOCA",
        severity="high", effort_hours=4.0, tags=["de", "finance", "accounting"],
    ),
    SimplificationRule(
        id="DE-004", category="de_localization", country="DE",
        pattern=r"ELSTER|ELEKTRONISCHE\s*STEUER|ESTAM",
        description="ELSTER (electronic tax filing) — verify S/4HANA integration",
        severity="medium", effort_hours=3.0, tags=["de", "tax", "compliance"],
    ),
    SimplificationRule(
        id="DE-005", category="de_localization", country="DE",
        pattern=r"UMSATZSTEUER|UST.?VA|VORSTEUER",
        description="German VAT (Umsatzsteuer) — verify tax procedure TAXD in S/4HANA",
        severity="medium", effort_hours=3.0, tags=["de", "tax", "vat"],
    ),
    SimplificationRule(
        id="DE-006", category="de_localization", country="DE",
        pattern=r"\bIDNR\b|STEUER.?ID|TAX.?IDENT.?NR",
        description="German Tax ID (Steuer-ID) — map to BP tax numbers",
        severity="low", effort_hours=1.0, tags=["de", "tax", "bp"],
    ),
    SimplificationRule(
        id="DE-007", category="de_localization", country="DE",
        pattern=r"ZUSAMMENFASSENDE\s*MELDUNG|EC\s*SALES|ZM\b",
        description="EC Sales List (Zusammenfassende Meldung) — verify EU reporting in S/4",
        severity="medium", effort_hours=2.0, tags=["de", "tax", "eu"],
    ),
    SimplificationRule(
        id="DE-008", category="de_localization", country="DE",
        pattern=r"SEPA\s*(TRANSFER|MANDATE|DD)|PAIN\.00[138]",
        description="SEPA payment format — verify SEPA payment method in S/4HANA",
        severity="medium", effort_hours=2.0, tags=["de", "banking", "sepa"],
    ),
    SimplificationRule(
        id="DE-009", category="de_localization", country="DE",
        pattern=r"KURZARBEIT|MINI.?JOB|SOZIALVERSICHERUNG",
        description="German payroll specifics — verify HCM payroll engine compatibility",
        severity="medium", effort_hours=4.0, tags=["de", "hr", "payroll"],
    ),
    SimplificationRule(
        id="DE-010", category="de_localization", country="DE",
        pattern=r"INTRASTAT|EXTRASTAT|DEB\b|ZOLL\b",
        description="Intrastat/Customs reporting — verify trade compliance in S/4HANA GTS",
        severity="medium", effort_hours=3.0, tags=["de", "trade", "customs"],
    ),
]

# =============================================================================
# BRAZIL (BR) — 10 rules
# =============================================================================
BRAZIL_RULES = [
    SimplificationRule(
        id="BR-001", category="br_localization", country="BR",
        pattern=r"NOTA\s*FISCAL|NF.?[eE]|NFE\b",
        description="Nota Fiscal Eletrônica (NF-e) — S/4HANA has integrated NF-e with Document Compliance",
        severity="critical", effort_hours=8.0, tags=["br", "tax", "nfe"],
        fix_suggestion="Use SAP Document Compliance for NF-e in S/4HANA.",
    ),
    SimplificationRule(
        id="BR-002", category="br_localization", country="BR",
        pattern=r"\bSPED\b|SPED.{0,10}(FISCAL|CONTRIB|CONTAB)",
        description="SPED (Sistema Público de Escrituração Digital) — verify S/4HANA SPED generation",
        severity="high", effort_hours=6.0, tags=["br", "tax", "compliance"],
    ),
    SimplificationRule(
        id="BR-003", category="br_localization", country="BR",
        pattern=r"\bICMS\b|ICMS.{0,10}(CALC|ST|RATE)",
        description="ICMS tax — verify tax procedure TAXBRA and condition types in S/4HANA",
        severity="high", effort_hours=4.0, tags=["br", "tax"],
    ),
    SimplificationRule(
        id="BR-004", category="br_localization", country="BR",
        pattern=r"PIS\s*/?\s*COFINS|PIS\b|COFINS\b",
        description="PIS/COFINS contributions — verify tax calculation in S/4HANA",
        severity="high", effort_hours=4.0, tags=["br", "tax"],
    ),
    SimplificationRule(
        id="BR-005", category="br_localization", country="BR",
        pattern=r"\bCNPJ\b|CPF\b|CNPJ.{0,5}VALID",
        description="CNPJ/CPF (Brazilian tax IDs) — map to BP tax numbers in S/4HANA",
        severity="medium", effort_hours=2.0, tags=["br", "tax", "bp"],
    ),
    SimplificationRule(
        id="BR-006", category="br_localization", country="BR",
        pattern=r"NCM\s*CODE|NCM\b|TIPI\b",
        description="NCM classification code — verify material master mapping in S/4HANA",
        severity="medium", effort_hours=2.0, tags=["br", "tax", "materials"],
    ),
    SimplificationRule(
        id="BR-007", category="br_localization", country="BR",
        pattern=r"CFOP\b|CFOP\s*CODE",
        description="CFOP (fiscal operation code) — verify configuration in S/4HANA",
        severity="medium", effort_hours=2.0, tags=["br", "tax"],
    ),
    SimplificationRule(
        id="BR-008", category="br_localization", country="BR",
        pattern=r"\bIRRF\b|IMPOSTO.*RENDA|RETIDO.*FONTE",
        description="IRRF (withholding income tax) — verify withholding tax config in S/4",
        severity="medium", effort_hours=3.0, tags=["br", "tax", "withholding"],
    ),
    SimplificationRule(
        id="BR-009", category="br_localization", country="BR",
        pattern=r"\bDARF\b|GUIA\s*DE\s*RECOLHIMENTO",
        description="DARF (tax payment voucher) — verify generation in S/4HANA",
        severity="medium", effort_hours=2.0, tags=["br", "tax", "payment"],
    ),
    SimplificationRule(
        id="BR-010", category="br_localization", country="BR",
        pattern=r"J_1B\w+",
        description="Brazil-specific SAP table (J_1B*) — verify S/4HANA compatibility",
        severity="medium", effort_hours=3.0, tags=["br", "localization"],
    ),
]

# =============================================================================
# CHINA (CN) — 8 rules
# =============================================================================
CHINA_RULES = [
    SimplificationRule(
        id="CN-001", category="cn_localization", country="CN",
        pattern=r"GOLDEN\s*TAX|FAPIAO|BAIWANG|AISINO",
        description="Golden Tax / Fapiao — verify e-invoice integration in S/4HANA China",
        severity="critical", effort_hours=8.0, tags=["cn", "tax", "fapiao"],
    ),
    SimplificationRule(
        id="CN-002", category="cn_localization", country="CN",
        pattern=r"VAT\s*REFORM|YINGYE\s*SHUI|ZENGZHI\s*SHUI",
        description="China VAT reform — verify tax procedure TAXCN in S/4HANA",
        severity="high", effort_hours=4.0, tags=["cn", "tax", "vat"],
    ),
    SimplificationRule(
        id="CN-003", category="cn_localization", country="CN",
        pattern=r"\bCIT\b.*CHINA|ENTERPRISE\s*INCOME\s*TAX|QIYE\s*SUODE",
        description="China Corporate Income Tax — verify tax reporting in S/4HANA",
        severity="medium", effort_hours=3.0, tags=["cn", "tax"],
    ),
    SimplificationRule(
        id="CN-004", category="cn_localization", country="CN",
        pattern=r"CHINESE\s*ACCOUNTING|PRC\s*GAAP|CAS\b",
        description="Chinese Accounting Standards (CAS/PRC GAAP) — verify ledger setup",
        severity="high", effort_hours=6.0, tags=["cn", "finance", "accounting"],
    ),
    SimplificationRule(
        id="CN-005", category="cn_localization", country="CN",
        pattern=r"\bGB/T\b|GUOBIAO\b",
        description="GB/T standards — verify compliance in S/4HANA",
        severity="low", effort_hours=1.0, tags=["cn", "compliance"],
    ),
    SimplificationRule(
        id="CN-006", category="cn_localization", country="CN",
        pattern=r"SOCIAL\s*INSURANCE|HOUSING\s*FUND|WUXIAN\s*YIJIN",
        description="China social insurance / housing fund — verify HR configuration",
        severity="medium", effort_hours=4.0, tags=["cn", "hr", "statutory"],
    ),
    SimplificationRule(
        id="CN-007", category="cn_localization", country="CN",
        pattern=r"J_3R\w+|J_3G\w+",
        description="China-specific SAP table (J_3*) — verify S/4HANA compatibility",
        severity="medium", effort_hours=2.0, tags=["cn", "localization"],
    ),
    SimplificationRule(
        id="CN-008", category="cn_localization", country="CN",
        pattern=r"RMB\b|CNY\b|RENMINBI",
        description="RMB/CNY currency — verify currency configuration in S/4HANA",
        severity="low", effort_hours=0.5, tags=["cn", "currency"],
    ),
]

# =============================================================================
# CHINA ADDITIONAL — expanded to 15+ total China rules
# =============================================================================
CHINA_EXTRA_RULES = [
    SimplificationRule(
        id="CN-009", category="COUNTRY_CN", country="CN",
        pattern=r"FAPIAO.*SPECIAL|SPECIAL.*FAPIAO|ZHUANYONG\s*FAPIAO|VAT\s*SPECIAL\s*INVOICE",
        description="Special VAT Fapiao — verify special invoice issuance and input tax credit deduction in S/4HANA",
        severity="high", effort_hours=5.0, tags=["cn", "tax", "fapiao", "special"],
        fix_suggestion="Configure special VAT fapiao workflow with Golden Tax integration in S/4HANA.",
    ),
    SimplificationRule(
        id="CN-010", category="COUNTRY_CN", country="CN",
        pattern=r"FAPIAO.*ORDINARY|ORDINARY.*FAPIAO|PUTONG\s*FAPIAO",
        description="Ordinary VAT Fapiao — verify ordinary invoice handling (no input credit) in S/4HANA",
        severity="medium", effort_hours=3.0, tags=["cn", "tax", "fapiao", "ordinary"],
        fix_suggestion="Configure ordinary fapiao document type in S/4HANA billing. No input tax credit applicable.",
    ),
    SimplificationRule(
        id="CN-011", category="COUNTRY_CN", country="CN",
        pattern=r"ELECTRONIC\s*FAPIAO|E.?FAPIAO|DIANZI\s*FAPIAO|QUANDIAN\s*FAPIAO",
        description="Electronic Fapiao (fully digitized e-invoice) — mandatory transition from paper fapiao",
        severity="critical", effort_hours=6.0, tags=["cn", "tax", "fapiao", "electronic"],
        fix_suggestion="Implement electronic fapiao integration via S/4HANA Document Compliance for China.",
        s4_note="3089413",
    ),
    SimplificationRule(
        id="CN-012", category="COUNTRY_CN", country="CN",
        pattern=r"VAT.*MULTI.?RATE|VAT.*6\s*PERCENT|VAT.*9\s*PERCENT|VAT.*13\s*PERCENT|TAXCN.*RATE",
        description="China VAT multi-rate handling (6%/9%/13%) — verify tax code configuration per industry in S/4HANA",
        severity="medium", effort_hours=3.0, tags=["cn", "tax", "vat", "rates"],
        fix_suggestion="Configure TAXCN tax procedure with correct rate tiers: 13% manufacturing, 9% transport/construction, 6% services.",
    ),
    SimplificationRule(
        id="CN-013", category="COUNTRY_CN", country="CN",
        pattern=r"CIT.*RETURN|QIYE\s*SUODE.*SHUI|ANNUAL.*TAX.*SETTLE.*CN|NIANQING",
        description="CIT (Corporate Income Tax) annual settlement — verify tax reporting and quarterly prepayment in S/4HANA",
        severity="medium", effort_hours=4.0, tags=["cn", "tax", "cit", "reporting"],
        fix_suggestion="Configure CIT quarterly prepayment and annual settlement reports in S/4HANA tax reporting.",
    ),
    SimplificationRule(
        id="CN-014", category="COUNTRY_CN", country="CN",
        pattern=r"CAS\s*\d+|CHINESE\s*ACCOUNTING\s*STANDARD|ASBE\b|PRC\s*GAAP.*IFRS",
        description="Chinese Accounting Standards (CAS/ASBE) vs IFRS differences — verify parallel ledger for dual reporting",
        severity="high", effort_hours=8.0, tags=["cn", "finance", "cas", "ifrs"],
        fix_suggestion="Configure parallel ledgers in S/4HANA: CAS-compliant leading ledger + IFRS non-leading for multinational reporting.",
    ),
    SimplificationRule(
        id="CN-015", category="COUNTRY_CN", country="CN",
        pattern=r"WUXIAN.*YIJIN.*CALC|SOCIAL_INS.*CALC.*CN|YANGLAO|YILIAO|SHIYE|GONGSHANG|SHENGYU",
        description="China social insurance fund calculations (pension/medical/unemployment/work injury/maternity) — city-specific rates",
        severity="medium", effort_hours=5.0, tags=["cn", "hr", "social-insurance", "statutory"],
        fix_suggestion="Configure city-specific social insurance rates and base ceilings in S/4HANA Payroll China.",
    ),
    SimplificationRule(
        id="CN-016", category="COUNTRY_CN", country="CN",
        pattern=r"RMB.*CROSS.?BORDER|CROSS.?BORDER.*RMB|RCPMIS|RENMINBI.*INTERNATION",
        description="RMB cross-border payment handling — verify SAFE/PBOC reporting and foreign exchange controls in S/4HANA",
        severity="medium", effort_hours=4.0, tags=["cn", "banking", "rmb", "cross-border"],
        fix_suggestion="Configure cross-border RMB payment formats and SAFE reporting requirements in S/4HANA payment program.",
    ),
    SimplificationRule(
        id="CN-017", category="COUNTRY_CN", country="CN",
        pattern=r"BANK.*TAX.*INTEGR.*CN|YIN.?SHUI.*HULIAN|TAX.*BANK.*INTERFACE.*CN",
        description="Bank-tax integration (Yin-Shui-Hu-Lian) — direct tax payment interface with Chinese banks",
        severity="medium", effort_hours=4.0, tags=["cn", "banking", "tax", "integration"],
        fix_suggestion="Configure bank-tax interface for automated tax payment submission through banking channels in S/4HANA.",
    ),
    SimplificationRule(
        id="CN-018", category="COUNTRY_CN", country="CN",
        pattern=r"HOUSING\s*FUND.*CALC|GONGJIJIN|HOUSING_PROVIDENT|HPF\b.*CN",
        description="Housing Provident Fund (Gongjijin) — verify employer/employee contribution calculation with city-specific rates",
        severity="medium", effort_hours=3.0, tags=["cn", "hr", "housing-fund", "statutory"],
        fix_suggestion="Configure Housing Provident Fund rates per city (5-12%) in S/4HANA Payroll China.",
    ),
    SimplificationRule(
        id="CN-019", category="COUNTRY_CN", country="CN",
        pattern=r"IIT\b.*CHINA|INDIVIDUAL\s*INCOME\s*TAX.*CN|GEREN\s*SUODE",
        description="China IIT (Individual Income Tax) — verify progressive rate table and special deductions in S/4HANA HCM",
        severity="medium", effort_hours=4.0, tags=["cn", "hr", "payroll", "iit"],
        fix_suggestion="Configure IIT 7-tier progressive rates and six special additional deductions in S/4HANA Payroll China.",
    ),
]

# =============================================================================
# UK (GB) — 8 rules
# =============================================================================
UK_RULES = [
    SimplificationRule(
        id="GB-001", category="gb_localization", country="GB",
        pattern=r"MAKING\s*TAX\s*DIGITAL|MTD\b|HMRC.{0,10}VAT",
        description="Making Tax Digital (MTD) — verify HMRC VAT submission in S/4HANA",
        severity="high", effort_hours=6.0, tags=["gb", "tax", "mtd"],
    ),
    SimplificationRule(
        id="GB-002", category="gb_localization", country="GB",
        pattern=r"UK\s*VAT|VAT\s*RETURN|BOX\s*[1-9].*VAT",
        description="UK VAT return — verify VAT reporting changes post-Brexit in S/4HANA",
        severity="medium", effort_hours=3.0, tags=["gb", "tax", "vat"],
    ),
    SimplificationRule(
        id="GB-003", category="gb_localization", country="GB",
        pattern=r"\bPAYE\b|P11D|P60\b|P45\b",
        description="UK PAYE / tax forms — verify payroll integration in S/4HANA",
        severity="medium", effort_hours=4.0, tags=["gb", "hr", "payroll"],
    ),
    SimplificationRule(
        id="GB-004", category="gb_localization", country="GB",
        pattern=r"\bBREXIT\b|BORDER\s*OPER|CUSTOMS\s*DEC",
        description="Brexit customs — verify customs declaration process in S/4HANA GTS",
        severity="high", effort_hours=6.0, tags=["gb", "trade", "customs"],
    ),
    SimplificationRule(
        id="GB-005", category="gb_localization", country="GB",
        pattern=r"UK\s*FRS|FRS\s*10[012]|IFRS\s*UK",
        description="UK Financial Reporting Standards — verify ledger config in S/4HANA",
        severity="medium", effort_hours=4.0, tags=["gb", "finance", "accounting"],
    ),
    SimplificationRule(
        id="GB-006", category="gb_localization", country="GB",
        pattern=r"BACS\b|FASTER\s*PAYMENT|CHAPS\b",
        description="UK payment methods (BACS/CHAPS/FPS) — verify payment formats in S/4HANA",
        severity="medium", effort_hours=2.0, tags=["gb", "banking", "payment"],
    ),
    SimplificationRule(
        id="GB-007", category="gb_localization", country="GB",
        pattern=r"CIS\s*DEDUCT|CONSTRUCTION\s*INDUSTRY",
        description="CIS (Construction Industry Scheme) — verify deduction handling",
        severity="medium", effort_hours=3.0, tags=["gb", "tax", "construction"],
    ),
    SimplificationRule(
        id="GB-008", category="gb_localization", country="GB",
        pattern=r"VAT\s*NUMBER.*GB|GB\s*\d{9}|GB\s*\d{12}",
        description="UK VAT number — map to BP tax numbers (changed format post-Brexit)",
        severity="low", effort_hours=1.0, tags=["gb", "tax", "bp"],
    ),
]

# =============================================================================
# UK ADDITIONAL — expanded to 15+ total UK rules
# =============================================================================
UK_EXTRA_RULES = [
    SimplificationRule(
        id="GB-009", category="COUNTRY_GB", country="GB",
        pattern=r"MTD.*ITSA|INCOME\s*TAX.*SELF.*ASSESS.*MTD|MTD.*INCOME\s*TAX",
        description="MTD for ITSA (Income Tax Self Assessment) — mandatory digital record keeping and quarterly updates to HMRC",
        severity="high", effort_hours=6.0, tags=["gb", "tax", "mtd", "itsa"],
        fix_suggestion="Prepare for MTD ITSA by configuring quarterly income/expense submission via HMRC APIs in S/4HANA.",
    ),
    SimplificationRule(
        id="GB-010", category="COUNTRY_GB", country="GB",
        pattern=r"UK\s*VAT.*STANDARD|VAT.*20\s*PERCENT|VAT.*REDUCED.*5|VAT.*ZERO.*RATED",
        description="UK VAT rate tiers (standard 20%/reduced 5%/zero-rated) — verify tax code configuration post-Brexit",
        severity="medium", effort_hours=3.0, tags=["gb", "tax", "vat", "rates"],
        fix_suggestion="Configure UK-specific VAT codes separate from EU rates. Standard 20%, reduced 5%, zero-rated for exports.",
    ),
    SimplificationRule(
        id="GB-011", category="COUNTRY_GB", country="GB",
        pattern=r"RTI\b.*PAYE|PAYE.*RTI|REAL.?TIME.*INFORM.*PAYE|FPS\b.*HMRC|EPS\b.*HMRC",
        description="PAYE Real-Time Information (RTI) — FPS/EPS submission to HMRC on or before payday",
        severity="high", effort_hours=5.0, tags=["gb", "hr", "payroll", "rti"],
        fix_suggestion="Configure RTI FPS (Full Payment Submission) and EPS (Employer Payment Summary) in S/4HANA Payroll UK.",
    ),
    SimplificationRule(
        id="GB-012", category="COUNTRY_GB", country="GB",
        pattern=r"CUSTOMS.*DECLAR.*BREXIT|CDS\b.*CUSTOMS|CHIEF\b.*CUSTOMS|IMPORT.*DECLAR.*UK",
        description="Brexit customs declarations (CDS replacing CHIEF) — verify UK customs declaration process in S/4HANA GTS",
        severity="high", effort_hours=8.0, tags=["gb", "trade", "customs", "brexit"],
        fix_suggestion="Configure UK Customs Declaration Service (CDS) integration in S/4HANA GTS for import/export declarations.",
    ),
    SimplificationRule(
        id="GB-013", category="COUNTRY_GB", country="GB",
        pattern=r"FRS\s*102|FRS\s*105|UK\s*GAAP\s*FRS|MICRO.*ENTITY.*FRS",
        description="FRS 102/105 accounting standards — verify chart of accounts and disclosure requirements in S/4HANA",
        severity="medium", effort_hours=4.0, tags=["gb", "finance", "frs", "accounting"],
        fix_suggestion="Configure FRS 102/105 compliant chart of accounts and financial statement structures in S/4HANA.",
    ),
    SimplificationRule(
        id="GB-014", category="COUNTRY_GB", country="GB",
        pattern=r"AUTO.?ENROL.*PENSION|WORKPLACE\s*PENSION|NEST\b.*PENSION|AE_PENSION",
        description="Auto-enrolment workplace pension — verify employer contributions (min 3%) and opt-out process in S/4HANA HCM",
        severity="medium", effort_hours=4.0, tags=["gb", "hr", "pension", "auto-enrolment"],
        fix_suggestion="Configure auto-enrolment pension contributions (employer 3% + employee 5%) in S/4HANA Payroll UK.",
    ),
    SimplificationRule(
        id="GB-015", category="COUNTRY_GB", country="GB",
        pattern=r"IR35\b|OFF.?PAYROLL|DEEMED\s*EMPLOYMENT|IR35.*STATUS|INTERMEDIARIES.*LEGISL",
        description="IR35 off-payroll working rules — verify deemed employment status determination for contractors",
        severity="medium", effort_hours=4.0, tags=["gb", "hr", "ir35", "compliance"],
        fix_suggestion="Configure IR35 status tracking in S/4HANA vendor master. Implement deemed employer deductions.",
    ),
    SimplificationRule(
        id="GB-016", category="COUNTRY_GB", country="GB",
        pattern=r"PLASTIC.*PACKAG.*TAX|PPT\b.*TAX|PPT_RETURN|PLASTIC.*TAX.*200",
        description="Plastic Packaging Tax (PPT) — verify packaging material tracking and quarterly returns in S/4HANA",
        severity="medium", effort_hours=3.0, tags=["gb", "tax", "plastic", "environment"],
        fix_suggestion="Configure material classification for plastic packaging (>30% threshold) and PPT return reporting.",
    ),
    SimplificationRule(
        id="GB-017", category="COUNTRY_GB", country="GB",
        pattern=r"FASTER\s*PAYMENT.*PROCESS|FPS.*PAYMENT.*UK|UK.*INSTANT.*PAYMENT",
        description="Faster Payments Service (FPS) — verify instant payment processing and format in S/4HANA",
        severity="medium", effort_hours=3.0, tags=["gb", "banking", "payment", "fps"],
        fix_suggestion="Configure Faster Payments payment method with ISO 20022 format in S/4HANA bank communication.",
    ),
]

# =============================================================================
# MIDDLE EAST (AE/SA) — 8 rules
# =============================================================================
MIDDLE_EAST_RULES = [
    SimplificationRule(
        id="ME-001", category="me_localization", country="AE",
        pattern=r"UAE\s*VAT|FEDERAL\s*TAX\s*AUTH|FTA\b.*VAT",
        description="UAE VAT — verify VAT configuration in S/4HANA (introduced 2018)",
        severity="high", effort_hours=4.0, tags=["ae", "tax", "vat"],
    ),
    SimplificationRule(
        id="ME-002", category="me_localization", country="SA",
        pattern=r"\bZAKAT\b|ZATCA\b|GAZT\b|ZAKAT\s*TAX",
        description="Saudi Zakat & Tax (ZATCA) — verify compliance in S/4HANA",
        severity="high", effort_hours=6.0, tags=["sa", "tax", "zakat"],
    ),
    SimplificationRule(
        id="ME-003", category="me_localization", country="SA",
        pattern=r"FATOORA\b|ZATCA.{0,10}(EINVOIC|INVOICE)|SAUDI.{0,10}E.?INVOIC",
        description="FATOORA (Saudi e-Invoicing) — use SAP Document Compliance",
        severity="critical", effort_hours=8.0, tags=["sa", "tax", "einvoice"],
        fix_suggestion="Use SAP Document Compliance for ZATCA FATOORA in S/4HANA.",
    ),
    SimplificationRule(
        id="ME-004", category="me_localization", country="AE",
        pattern=r"\bTRN\b.*\d{15}|TAX\s*REGISTRATION\s*NUMBER.*UAE",
        description="UAE TRN (Tax Registration Number) — map to BP tax numbers",
        severity="low", effort_hours=1.0, tags=["ae", "tax", "bp"],
    ),
    SimplificationRule(
        id="ME-005", category="me_localization", country="AE",
        pattern=r"WPS\b|WAGE\s*PROTECTION|SIF\s*FILE",
        description="UAE WPS (Wage Protection System) — verify payroll integration",
        severity="medium", effort_hours=4.0, tags=["ae", "hr", "payroll"],
    ),
    SimplificationRule(
        id="ME-006", category="me_localization", country="AE",
        pattern=r"GRATUITY.*UAE|END.?OF.?SERVICE|EOSB",
        description="UAE End of Service Gratuity (EOSB) — verify HR calculation",
        severity="medium", effort_hours=2.0, tags=["ae", "hr", "statutory"],
    ),
    SimplificationRule(
        id="ME-007", category="me_localization", country="SA",
        pattern=r"GOSI\b|GENERAL\s*ORG.*SOCIAL\s*INS",
        description="Saudi GOSI (social insurance) — verify HR/payroll config",
        severity="medium", effort_hours=3.0, tags=["sa", "hr", "statutory"],
    ),
    SimplificationRule(
        id="ME-008", category="me_localization", country="AE",
        pattern=r"J_1A\w+",
        description="Middle East SAP table (J_1A*) — verify S/4HANA compatibility",
        severity="medium", effort_hours=2.0, tags=["ae", "localization"],
    ),
]

# =============================================================================
# MIDDLE EAST ADDITIONAL — expanded to 15+ total ME rules
# =============================================================================
MIDDLE_EAST_EXTRA_RULES = [
    SimplificationRule(
        id="ME-009", category="COUNTRY_SA", country="SA",
        pattern=r"FATOORA.*PHASE\s*2|ZATCA.*PHASE\s*2|INTEGRATION\s*PHASE|CLEARANCE\s*MODEL",
        description="FATOORA Phase 2 (integration/clearance) — real-time invoice clearance with ZATCA platform mandatory",
        severity="critical", effort_hours=10.0, tags=["sa", "tax", "einvoice", "fatoora"],
        fix_suggestion="Implement ZATCA Phase 2 clearance model via SAP Document Compliance. Configure API credentials and cryptographic stamping.",
        s4_note="3089413",
    ),
    SimplificationRule(
        id="ME-010", category="COUNTRY_AE", country="AE",
        pattern=r"UAE\s*VAT.*5\s*PERCENT|FTA.*VAT.*RETURN|VAT.*RETURN.*201.*UAE",
        description="UAE VAT (5%) return filing — verify VAT return form 201 generation and FTA submission",
        severity="medium", effort_hours=3.0, tags=["ae", "tax", "vat", "return"],
        fix_suggestion="Configure UAE VAT return (Form 201) generation from S/4HANA tax data for FTA e-filing.",
    ),
    SimplificationRule(
        id="ME-011", category="COUNTRY_AE", country="AE",
        pattern=r"TRN\b.*VALIDAT|TRN_CHECK|TAX.*REG.*NUM.*15|TRN.*\d{15}",
        description="TRN (Tax Registration Number) validation — 15-digit format verification for UAE tax compliance",
        severity="low", effort_hours=1.0, tags=["ae", "tax", "trn", "validation"],
        fix_suggestion="Validate TRN format (15-digit numeric) in Business Partner tax number fields in S/4HANA.",
    ),
    SimplificationRule(
        id="ME-012", category="COUNTRY_AE", country="AE",
        pattern=r"WPS.*SIF|SIF.*FILE.*GENERAT|WAGE.*PROTECT.*FILE|WPS.*BANK.*FORMAT",
        description="WPS (Wage Protection System) SIF file generation — verify salary transfer file format per bank requirements",
        severity="medium", effort_hours=4.0, tags=["ae", "hr", "wps", "payroll"],
        fix_suggestion="Configure WPS SIF (Salary Information File) format per Central Bank standards in S/4HANA Payroll.",
    ),
    SimplificationRule(
        id="ME-013", category="COUNTRY_AE", country="AE",
        pattern=r"EOSB.*CALC|GRATUITY.*CALC|END.*SERVICE.*CALC|EOSB.*PROVISION",
        description="EOSB (End of Service Benefits) calculation — verify UAE labor law provisions (21/30 days per year of service)",
        severity="medium", effort_hours=3.0, tags=["ae", "hr", "eosb", "statutory"],
        fix_suggestion="Configure EOSB calculation: 21 days/year for first 5 years, 30 days/year thereafter in S/4HANA HCM.",
    ),
    SimplificationRule(
        id="ME-014", category="COUNTRY_SA", country="SA",
        pattern=r"GOSI.*CALC|GOSI.*CONTRIB|GOSI.*RATE|GOSI.*ANNUITIES|GOSI.*HAZARD",
        description="GOSI social insurance calculation — verify annuities (9%+9%) and occupational hazards (2%) contributions",
        severity="medium", effort_hours=3.0, tags=["sa", "hr", "gosi", "statutory"],
        fix_suggestion="Configure GOSI rates: Saudi nationals 9%+9%, non-nationals 2% occupational hazards in S/4HANA Payroll.",
    ),
    SimplificationRule(
        id="ME-015", category="COUNTRY_AE", country="AE",
        pattern=r"FREE\s*ZONE\s*VAT|FZCO.*VAT|DESIGNATED\s*ZONE|JAFZA.*VAT|DAFZA.*VAT",
        description="Free zone / Designated zone VAT handling — special VAT treatment for UAE free zone entities",
        severity="medium", effort_hours=4.0, tags=["ae", "tax", "vat", "freezone"],
        fix_suggestion="Configure designated zone VAT conditions (zero-rated B2B within zone) in S/4HANA tax determination.",
    ),
    SimplificationRule(
        id="ME-016", category="COUNTRY_AE", country="AE",
        pattern=r"BAHRAIN\s*VAT|OMAN\s*VAT|QATAR\s*VAT|GCC\s*VAT|VAT.*READINESS.*GCC",
        description="GCC VAT readiness (Bahrain 10%/Oman 5%/Qatar) — verify multi-country VAT configuration for GCC operations",
        severity="medium", effort_hours=4.0, tags=["ae", "sa", "gcc", "vat"],
        fix_suggestion="Configure country-specific VAT rates and registration requirements for each GCC jurisdiction in S/4HANA.",
    ),
    SimplificationRule(
        id="ME-017", category="COUNTRY_SA", country="SA",
        pattern=r"ZAKAT.*CALC|ZAKAT.*BASE|ZAKAT.*RATE.*2\.5|ZAKAT_RETURN",
        description="Zakat base calculation (2.5% on net assets) — verify Zakat return preparation and ZATCA filing",
        severity="high", effort_hours=5.0, tags=["sa", "tax", "zakat", "compliance"],
        fix_suggestion="Configure Zakat calculation formula based on net invested capital method in S/4HANA tax reporting.",
    ),
]

# =============================================================================
# JAPAN (JP) — 6 rules
# =============================================================================
JAPAN_RULES = [
    SimplificationRule(
        id="JP-001", category="jp_localization", country="JP",
        pattern=r"CONSUMPTION\s*TAX|SHOHI.?ZEI|KEIGEN\s*ZEIRITSU",
        description="Japan Consumption Tax / reduced rate — verify tax procedure in S/4HANA",
        severity="high", effort_hours=4.0, tags=["jp", "tax"],
    ),
    SimplificationRule(
        id="JP-002", category="jp_localization", country="JP",
        pattern=r"INVOICE\s*SYSTEM|TEKIKAKU\s*INVOICE|QUALIFIED\s*INVOICE",
        description="Japan Qualified Invoice System (2023) — verify S/4HANA compliance",
        severity="critical", effort_hours=8.0, tags=["jp", "tax", "invoice"],
    ),
    SimplificationRule(
        id="JP-003", category="jp_localization", country="JP",
        pattern=r"E.?TAX|ELTAX|KOKUZEI|JIKO\s*SHINKOKU",
        description="Japan e-Tax / eLTAX — verify electronic filing integration",
        severity="medium", effort_hours=3.0, tags=["jp", "tax", "compliance"],
    ),
    SimplificationRule(
        id="JP-004", category="jp_localization", country="JP",
        pattern=r"SHAKAI\s*HOKEN|SOCIAL\s*INSURANCE.*JP|KENKO\s*HOKEN",
        description="Japan social insurance (Shakai Hoken) — verify HR config",
        severity="medium", effort_hours=3.0, tags=["jp", "hr", "statutory"],
    ),
    SimplificationRule(
        id="JP-005", category="jp_localization", country="JP",
        pattern=r"J_1J\w+",
        description="Japan-specific SAP table (J_1J*) — verify S/4HANA compatibility",
        severity="medium", effort_hours=2.0, tags=["jp", "localization"],
    ),
    SimplificationRule(
        id="JP-006", category="jp_localization", country="JP",
        pattern=r"ZENGIN\b|BANK.*FORMAT.*JP",
        description="Zengin bank payment format — verify payment method in S/4HANA",
        severity="medium", effort_hours=2.0, tags=["jp", "banking", "payment"],
    ),
]

# =============================================================================
# JAPAN ADDITIONAL — expanded to 14+ total Japan rules
# =============================================================================
JAPAN_EXTRA_RULES = [
    SimplificationRule(
        id="JP-007", category="COUNTRY_JP", country="JP",
        pattern=r"INVOICE\s*SEIDO|TEKIKAKU\s*SEIKYUSHO|QUALIFIED\s*INVOICE\s*SYSTEM|T\d{13}",
        description="Qualified Invoice System (Invoice Seido) — mandatory from Oct 2023, verify T-number registration and invoice format",
        severity="critical", effort_hours=8.0, tags=["jp", "tax", "invoice", "seido"],
        fix_suggestion="Configure qualified invoice number (T+13 digits) in BP master. Update billing output formats in S/4HANA.",
        s4_note="3191072",
    ),
    SimplificationRule(
        id="JP-008", category="COUNTRY_JP", country="JP",
        pattern=r"KEIGEN\s*ZEIRITSU|REDUCED.*RATE.*8.*JP|TAX.*8\s*PERCENT.*JP|FOOD.*TAX.*JP",
        description="Reduced consumption tax rate (8%) vs standard (10%) — verify dual-rate handling for food/newspapers",
        severity="medium", effort_hours=3.0, tags=["jp", "tax", "reduced-rate"],
        fix_suggestion="Configure dual consumption tax codes (8% reduced for food/newspapers, 10% standard) in S/4HANA tax procedure.",
    ),
    SimplificationRule(
        id="JP-009", category="COUNTRY_JP", country="JP",
        pattern=r"NENMATSU\s*CHOSEI|YEAR.?END\s*ADJUST.*JP|NENCHOU|GENSEN\s*CHOSHU",
        description="Year-end adjustment (Nenmatsu Chosei) — verify withholding tax reconciliation process in S/4HANA HCM",
        severity="medium", effort_hours=4.0, tags=["jp", "hr", "payroll", "year-end"],
        fix_suggestion="Configure year-end tax adjustment calculation for insurance/mortgage/dependent deductions in S/4HANA Payroll Japan.",
    ),
    SimplificationRule(
        id="JP-010", category="COUNTRY_JP", country="JP",
        pattern=r"MY\s*NUMBER|MYNUMBER|INDIVIDUAL\s*NUMBER.*JP|KOJIN\s*BANGO",
        description="My Number (Individual Number) handling — verify data protection and tax form output with 12-digit number",
        severity="high", effort_hours=4.0, tags=["jp", "compliance", "privacy", "mynumber"],
        fix_suggestion="Implement My Number encryption and access control in S/4HANA. Required on withholding tax certificates.",
        s4_note="2339773",
    ),
    SimplificationRule(
        id="JP-011", category="COUNTRY_JP", country="JP",
        pattern=r"SHAKAI\s*HOKEN.*CALC|HEALTH_INS.*JP|KOSEI\s*NENKIN|KENKO\s*HOKEN.*CALC",
        description="Social insurance calculations (Kenko Hoken/Kosei Nenkin) — verify standard monthly remuneration tiers",
        severity="medium", effort_hours=4.0, tags=["jp", "hr", "social-insurance", "statutory"],
        fix_suggestion="Configure social insurance grade tables (hyojun houshu getsu gaku) in S/4HANA Payroll Japan.",
    ),
    SimplificationRule(
        id="JP-012", category="COUNTRY_JP", country="JP",
        pattern=r"ZENGIN.*FORMAT|ZENGIN.*FILE|BANK.*TRANSFER.*JP|ZENGINKYO",
        description="Zengin payment format — verify fixed-length bank transfer file format for Japanese banking system",
        severity="medium", effort_hours=3.0, tags=["jp", "banking", "payment", "zengin"],
        fix_suggestion="Configure Zengin format (120-byte fixed length) in S/4HANA payment method for domestic transfers.",
    ),
    SimplificationRule(
        id="JP-013", category="COUNTRY_JP", country="JP",
        pattern=r"E.?TAX.*FILING.*JP|KOKUZEI.*DENSHISHINKOKU|ELTAX.*FILING|EDINET",
        description="e-Tax/eLTAX electronic filing — verify corporate tax return XML generation and submission",
        severity="medium", effort_hours=4.0, tags=["jp", "tax", "etax", "filing"],
        fix_suggestion="Configure e-Tax XML output for corporate tax returns and eLTAX for local tax in S/4HANA.",
    ),
    SimplificationRule(
        id="JP-014", category="COUNTRY_JP", country="JP",
        pattern=r"STAMP\s*TAX.*JP|INSHI\s*ZEI|REVENUE\s*STAMP|KEIYAKU.*INSHI",
        description="Japan stamp tax (Inshi Zei) on contracts — verify electronic contract handling to avoid stamp tax",
        severity="low", effort_hours=2.0, tags=["jp", "tax", "stamp"],
        fix_suggestion="Electronic contracts in S/4HANA are exempt from stamp tax. Consider digital transformation.",
    ),
]

# =============================================================================
# AUSTRALIA (AU) — 6 rules
# =============================================================================
AUSTRALIA_RULES = [
    SimplificationRule(
        id="AU-001", category="au_localization", country="AU",
        pattern=r"\bBAS\b|BUSINESS\s*ACTIVITY\s*STATEMENT|GST.*AUSTRALIA",
        description="Australian BAS / GST — verify tax procedure TAXAU in S/4HANA",
        severity="medium", effort_hours=3.0, tags=["au", "tax", "gst"],
    ),
    SimplificationRule(
        id="AU-002", category="au_localization", country="AU",
        pattern=r"\bSTP\b|SINGLE\s*TOUCH\s*PAYROLL",
        description="Single Touch Payroll (STP) — verify ATO reporting in S/4HANA",
        severity="high", effort_hours=6.0, tags=["au", "hr", "payroll"],
    ),
    SimplificationRule(
        id="AU-003", category="au_localization", country="AU",
        pattern=r"SUPERANNUATION|SUPER\s*GUARANTEE|SGC\b",
        description="Superannuation — verify contribution calculation in S/4HANA HCM",
        severity="medium", effort_hours=4.0, tags=["au", "hr", "super"],
    ),
    SimplificationRule(
        id="AU-004", category="au_localization", country="AU",
        pattern=r"\bABN\b|AUSTRALIAN\s*BUSINESS\s*NUMBER",
        description="ABN — map to BP tax numbers in S/4HANA",
        severity="low", effort_hours=1.0, tags=["au", "tax", "bp"],
    ),
    SimplificationRule(
        id="AU-005", category="au_localization", country="AU",
        pattern=r"\bPAYG\b|PAY.?AS.?YOU.?GO",
        description="PAYG withholding / installments — verify tax configuration",
        severity="medium", effort_hours=2.0, tags=["au", "tax", "withholding"],
    ),
    SimplificationRule(
        id="AU-006", category="au_localization", country="AU",
        pattern=r"TPAR\b|TAXABLE\s*PAYMENT.*REPORT",
        description="TPAR (Taxable Payments Annual Report) — verify reporting in S/4",
        severity="medium", effort_hours=2.0, tags=["au", "tax", "compliance"],
    ),
]

# =============================================================================
# AUSTRALIA ADDITIONAL — expanded to 14+ total Australia rules
# =============================================================================
AUSTRALIA_EXTRA_RULES = [
    SimplificationRule(
        id="AU-007", category="COUNTRY_AU", country="AU",
        pattern=r"STP.*PHASE\s*2|STP_V2|SINGLE\s*TOUCH.*PHASE\s*2|STP2",
        description="STP Phase 2 — expanded reporting with income types, country codes, and tax treatment codes to ATO",
        severity="high", effort_hours=6.0, tags=["au", "hr", "payroll", "stp2"],
        fix_suggestion="Configure STP Phase 2 reporting categories (gross, OTE, salary sacrifice) in S/4HANA Payroll Australia.",
    ),
    SimplificationRule(
        id="AU-008", category="COUNTRY_AU", country="AU",
        pattern=r"SUPER.*GUARANTEE.*RATE|SGC.*RATE|SUPER.*11|SUPER.*12|SUPERSTREAM",
        description="Superannuation guarantee rate (11.5%/12%) — verify annual rate increases and SuperStream electronic reporting",
        severity="medium", effort_hours=3.0, tags=["au", "hr", "super", "statutory"],
        fix_suggestion="Update superannuation guarantee rate annually (12% from July 2025) in S/4HANA Payroll Australia.",
    ),
    SimplificationRule(
        id="AU-009", category="COUNTRY_AU", country="AU",
        pattern=r"FBT\b.*CALC|FRINGE\s*BENEFIT.*TAX|FBT.*RETURN|FBT.*47\s*PERCENT",
        description="FBT (Fringe Benefits Tax) — verify grossed-up value calculation and annual return (April-March year)",
        severity="medium", effort_hours=3.0, tags=["au", "tax", "fbt", "hr"],
        fix_suggestion="Configure FBT calculation with Type 1 (GST credit) and Type 2 (no GST credit) gross-up rates in S/4HANA.",
    ),
    SimplificationRule(
        id="AU-010", category="COUNTRY_AU", country="AU",
        pattern=r"WORKCOVER\b|WORKERS\s*COMP.*AU|WORKCOVER.*PREMIUM|WC_RATE",
        description="WorkCover / Workers Compensation premiums — verify state-specific premium calculations",
        severity="medium", effort_hours=3.0, tags=["au", "hr", "workcover", "statutory"],
        fix_suggestion="Configure state-specific WorkCover premium rates by industry classification in S/4HANA Payroll.",
    ),
    SimplificationRule(
        id="AU-011", category="COUNTRY_AU", country="AU",
        pattern=r"JOBKEEPER|JOBMAKER|COVID.*SUBSID.*AU|CASHFLOW\s*BOOST",
        description="JobKeeper/JobMaker government schemes — verify historical processing and ATO reconciliation",
        severity="low", effort_hours=2.0, tags=["au", "hr", "government", "subsidy"],
        fix_suggestion="Archive JobKeeper/JobMaker historical data. Ensure ATO reconciliation completed before migration.",
    ),
    SimplificationRule(
        id="AU-012", category="COUNTRY_AU", country="AU",
        pattern=r"BAS.*LODG|BAS_SUBMIT|ACTIVITY\s*STATEMENT.*LODG|IAS\b.*LODG",
        description="BAS/IAS lodgment — verify quarterly/monthly activity statement generation for GST, PAYG, FTC",
        severity="medium", effort_hours=3.0, tags=["au", "tax", "bas", "lodgment"],
        fix_suggestion="Configure BAS report with all labels (1A, 1B, 4, 5A, 5B, 6A, 6B, 7, 8A, 8B, 9) in S/4HANA.",
    ),
    SimplificationRule(
        id="AU-013", category="COUNTRY_AU", country="AU",
        pattern=r"PAYG.*INSTALL|PAYG_INSTALLMENT|PAYG.*QUARTERLY|PAYG_INCOME\s*TAX",
        description="PAYG installments — verify quarterly income tax installment calculations and BAS integration",
        severity="medium", effort_hours=2.0, tags=["au", "tax", "payg", "installment"],
        fix_suggestion="Configure PAYG installment amount/rate method in S/4HANA for quarterly ATO prepayments.",
    ),
    SimplificationRule(
        id="AU-014", category="COUNTRY_AU", country="AU",
        pattern=r"ABN.*VALID|ABN_CHECK|ABN.*\d{2}\s*\d{3}\s*\d{3}\s*\d{3}|ABN.*WITHHOLD",
        description="ABN validation and no-ABN withholding — verify 11-digit ABN check and 47% withholding for missing ABN",
        severity="low", effort_hours=1.0, tags=["au", "tax", "abn", "validation"],
        fix_suggestion="Configure ABN validation in BP master. Implement no-ABN withholding rule (47%) in S/4HANA.",
    ),
]

# =============================================================================
# FRANCE (FR) — 6 rules
# =============================================================================
FRANCE_RULES = [
    SimplificationRule(
        id="FR-001", category="fr_localization", country="FR",
        pattern=r"\bFEC\b|FICHIER\s*DES\s*ECRITURES|AUDIT\s*FILE.*FR",
        description="FEC (Fichier des Ecritures Comptables) — verify audit file in S/4HANA",
        severity="high", effort_hours=4.0, tags=["fr", "compliance", "audit"],
    ),
    SimplificationRule(
        id="FR-002", category="fr_localization", country="FR",
        pattern=r"\bDSN\b|DECLARATION\s*SOCIALE\s*NOMINATIVE",
        description="DSN (payroll reporting) — verify HR integration in S/4HANA",
        severity="high", effort_hours=6.0, tags=["fr", "hr", "payroll"],
    ),
    SimplificationRule(
        id="FR-003", category="fr_localization", country="FR",
        pattern=r"\bTVA\b|TAXE.*VALEUR.*AJOUTEE",
        description="French TVA (VAT) — verify tax procedure TAXFRA in S/4HANA",
        severity="medium", effort_hours=3.0, tags=["fr", "tax", "vat"],
    ),
    SimplificationRule(
        id="FR-004", category="fr_localization", country="FR",
        pattern=r"CHORUS\s*PRO|FACTUR.?X|ZUGFERD.*FR",
        description="Chorus Pro / Factur-X (French e-invoicing) — verify S/4 compliance",
        severity="high", effort_hours=6.0, tags=["fr", "tax", "einvoice"],
    ),
    SimplificationRule(
        id="FR-005", category="fr_localization", country="FR",
        pattern=r"\bSIRET\b|\bSIREN\b|SIRET\s*NUMBER",
        description="SIRET/SIREN — map to BP identification numbers in S/4HANA",
        severity="low", effort_hours=1.0, tags=["fr", "tax", "bp"],
    ),
    SimplificationRule(
        id="FR-006", category="fr_localization", country="FR",
        pattern=r"DEB\b|DES\b.*INTRASTAT|DECLARATION.*ECHANGE",
        description="DEB/DES (Intrastat France) — verify EU trade reporting in S/4HANA",
        severity="medium", effort_hours=2.0, tags=["fr", "trade", "eu"],
    ),
]

# =============================================================================
# FRANCE ADDITIONAL — expanded to 14+ total France rules
# =============================================================================
FRANCE_EXTRA_RULES = [
    SimplificationRule(
        id="FR-007", category="COUNTRY_FR", country="FR",
        pattern=r"PRELEVEMENT.*SOURCE|PAS\b.*IMPOT|WITHHOLDING.*INCOME.*FR|TAUX\s*PAS",
        description="Prelevement a la source (PAYE income tax) — verify employer withholding calculation with DGFiP rates",
        severity="high", effort_hours=5.0, tags=["fr", "hr", "payroll", "pas"],
        fix_suggestion="Configure PAS (prelevement a la source) with individualized/neutral rates from DGFiP in S/4HANA Payroll France.",
    ),
    SimplificationRule(
        id="FR-008", category="COUNTRY_FR", country="FR",
        pattern=r"CET\b.*TAX|CVAE\b|CONTRIBUTION.*VALEUR.*AJOUTEE|CFE\b.*TAX",
        description="CET (CFE + CVAE) local business taxes — verify territorial economic contribution calculation",
        severity="medium", effort_hours=3.0, tags=["fr", "tax", "cet", "cvae"],
        fix_suggestion="Configure CET/CVAE calculation based on value added and CFE based on property values in S/4HANA.",
    ),
    SimplificationRule(
        id="FR-009", category="COUNTRY_FR", country="FR",
        pattern=r"FEC.*GENERAT|FEC.*EXPORT|FEC_FILE|AUDIT.*FILE.*FRANCE|FEC.*XML",
        description="FEC file generation — verify complete journal entry export with mandatory fields for French tax audit",
        severity="high", effort_hours=4.0, tags=["fr", "compliance", "fec", "audit"],
        fix_suggestion="Generate FEC from S/4HANA ACDOCA with all 18 mandatory columns. Verify encoding (ISO 8859-15).",
    ),
    SimplificationRule(
        id="FR-010", category="COUNTRY_FR", country="FR",
        pattern=r"DSN.*MENSUEL|DSN_MONTHLY|DSN.*EVENT|DSN.*BLOCK.*S21|DECLARATION.*SOCIALE",
        description="DSN monthly/event declarations — verify all S21 blocks for payroll social reporting to URSSAF/CPAM",
        severity="high", effort_hours=6.0, tags=["fr", "hr", "dsn", "social"],
        fix_suggestion="Configure DSN blocks S21.G00.06 through S21.G00.78 in S/4HANA Payroll France for URSSAF/Net-entreprises.",
    ),
    SimplificationRule(
        id="FR-011", category="COUNTRY_FR", country="FR",
        pattern=r"CHORUS.*PRO.*SUBMIT|FACTURX.*GENERAT|ZUGFERD.*FR.*FORMAT|E.?INVOIC.*FR",
        description="Chorus Pro / Factur-X e-invoicing submission — mandatory for B2G, upcoming B2B mandate (2026+)",
        severity="high", effort_hours=6.0, tags=["fr", "einvoice", "chorus", "facturx"],
        fix_suggestion="Implement Factur-X (EN 16931 / ZUGFeRD) format generation in S/4HANA for Chorus Pro submission.",
        s4_note="3089413",
    ),
    SimplificationRule(
        id="FR-012", category="COUNTRY_FR", country="FR",
        pattern=r"SIRET.*VALID|SIRET.*\d{14}|SIREN.*VALID|SIREN.*\d{9}|SIRET_CHECK",
        description="SIRET (14-digit) / SIREN (9-digit) validation — verify establishment identification in BP master",
        severity="low", effort_hours=1.0, tags=["fr", "tax", "siret", "validation"],
        fix_suggestion="Configure SIRET/SIREN validation rules in Business Partner master data. SIRET = SIREN + NIC (5 digits).",
    ),
    SimplificationRule(
        id="FR-013", category="COUNTRY_FR", country="FR",
        pattern=r"URSSAF\b|COTISATION.*SOCIALE|CSG\b|CRDS\b|CHARGE.*SOCIALE.*FR",
        description="URSSAF social charges (CSG/CRDS/etc.) — verify employer/employee social contribution rates in payroll",
        severity="medium", effort_hours=4.0, tags=["fr", "hr", "payroll", "urssaf"],
        fix_suggestion="Configure CSG (9.2%), CRDS (0.5%), and other URSSAF contribution rates in S/4HANA Payroll France.",
    ),
    SimplificationRule(
        id="FR-014", category="COUNTRY_FR", country="FR",
        pattern=r"DEB.*INTRASTAT.*FR|DES.*SERVICE.*FR|EMEBI\b|ENQUETE.*STAT.*ECHANGE",
        description="DEB/DES French Intrastat (now EMEBI) — verify EU goods/services trade declaration thresholds",
        severity="medium", effort_hours=3.0, tags=["fr", "trade", "intrastat", "eu"],
        fix_suggestion="Configure EMEBI (formerly DEB) reporting with correct thresholds in S/4HANA Foreign Trade.",
    ),
]

# =============================================================================
# MEXICO (MX) — 5 rules
# =============================================================================
MEXICO_RULES = [
    SimplificationRule(
        id="MX-001", category="mx_localization", country="MX",
        pattern=r"\bCFDI\b|COMPROBANTE\s*FISCAL",
        description="CFDI (Mexican e-invoice) — use SAP Document Compliance in S/4HANA",
        severity="critical", effort_hours=8.0, tags=["mx", "tax", "cfdi"],
    ),
    SimplificationRule(
        id="MX-002", category="mx_localization", country="MX",
        pattern=r"\bSAT\b.*MEXICO|SERVICIO.*ADMINISTRACION.*TRIBUTARIA",
        description="SAT (Mexican tax authority) — verify digital seal and reporting",
        severity="high", effort_hours=4.0, tags=["mx", "tax", "compliance"],
    ),
    SimplificationRule(
        id="MX-003", category="mx_localization", country="MX",
        pattern=r"\bRFC\b.*MEXICO|REGISTRO\s*FEDERAL|RFC\s*[A-Z]{3,4}\d{6}",
        description="Mexican RFC (tax ID) — map to BP tax numbers (note: SAP RFC is different)",
        severity="low", effort_hours=1.0, tags=["mx", "tax", "bp"],
    ),
    SimplificationRule(
        id="MX-004", category="mx_localization", country="MX",
        pattern=r"\bIVA\b.*MEXICO|\bISR\b|IMPUESTO.*VALOR.*AGREGADO",
        description="Mexican IVA/ISR taxes — verify tax procedure TAXMX in S/4HANA",
        severity="medium", effort_hours=3.0, tags=["mx", "tax"],
    ),
    SimplificationRule(
        id="MX-005", category="mx_localization", country="MX",
        pattern=r"J_1M\w+",
        description="Mexico-specific SAP table (J_1M*) — verify S/4HANA compatibility",
        severity="medium", effort_hours=2.0, tags=["mx", "localization"],
    ),
]

# =============================================================================
# MEXICO ADDITIONAL — expanded to 10+ total Mexico rules
# =============================================================================
MEXICO_EXTRA_RULES = [
    SimplificationRule(
        id="MX-006", category="COUNTRY_MX", country="MX",
        pattern=r"CFDI\s*4\.?0|CFDI.*VERSION\s*4|CFDI_V40|COMPROBANTE.*4\.0",
        description="CFDI 4.0 (mandatory from 2023) — verify updated XML schema with fiscal regime and postal code validations",
        severity="critical", effort_hours=6.0, tags=["mx", "tax", "cfdi", "v4"],
        fix_suggestion="Update SAP Document Compliance to CFDI 4.0 schema. Verify RegimenFiscal and DomicilioFiscalReceptor fields.",
    ),
    SimplificationRule(
        id="MX-007", category="COUNTRY_MX", country="MX",
        pattern=r"IMSS\b|INSTITUTO.*MEXICANO.*SEGURO|SUA\b.*IMSS|CUOTAS.*OBRERO",
        description="IMSS (social security) contributions — verify employer/employee quota calculation in S/4HANA HCM",
        severity="medium", effort_hours=4.0, tags=["mx", "hr", "imss", "statutory"],
        fix_suggestion="Configure IMSS contribution rates by branch (EyM, IV, CEAV, RT, Guarderias) in S/4HANA Payroll Mexico.",
    ),
    SimplificationRule(
        id="MX-008", category="COUNTRY_MX", country="MX",
        pattern=r"INFONAVIT\b|CREDITO.*INFONAVIT|VIVIENDA.*DESCUENTO",
        description="INFONAVIT housing credit deductions — verify employee housing loan deduction processing in payroll",
        severity="medium", effort_hours=3.0, tags=["mx", "hr", "infonavit", "statutory"],
        fix_suggestion="Configure INFONAVIT credit deduction types (VSM/CF/percentage) in S/4HANA Payroll Mexico.",
    ),
    SimplificationRule(
        id="MX-009", category="COUNTRY_MX", country="MX",
        pattern=r"CARTA\s*PORTE|COMPLEMENTO.*TRANSPORTE|CFDI.*CARTA.*PORTE",
        description="Carta Porte complement (CFDI transport) — mandatory for goods in transit, verify SAP logistics integration",
        severity="high", effort_hours=5.0, tags=["mx", "tax", "cfdi", "transport"],
        fix_suggestion="Configure Carta Porte complement generation for transport CFDIs in S/4HANA with route/merchandise details.",
    ),
    SimplificationRule(
        id="MX-010", category="COUNTRY_MX", country="MX",
        pattern=r"DIOT\b|DECLARACION.*INFORMATIVA.*OPERACION|PROVEEDOR.*DIOT",
        description="DIOT (vendor operations information return) — monthly filing of vendor payments above threshold to SAT",
        severity="medium", effort_hours=3.0, tags=["mx", "tax", "diot", "compliance"],
        fix_suggestion="Configure DIOT report extraction from AP data in S/4HANA for monthly SAT filing.",
    ),
    SimplificationRule(
        id="MX-011", category="COUNTRY_MX", country="MX",
        pattern=r"RETENCION.*CFDI|CFDI.*RETENCION|CONSTANCIA.*RETENCION|PAGO.*PROVISIONAL",
        description="CFDI de Retenciones (withholding certificates) — verify withholding tax CFDI generation for SAT",
        severity="medium", effort_hours=3.0, tags=["mx", "tax", "withholding", "cfdi"],
        fix_suggestion="Configure withholding tax CFDI generation for payments subject to ISR/IVA retention in S/4HANA.",
    ),
    SimplificationRule(
        id="MX-012", category="COUNTRY_MX", country="MX",
        pattern=r"CONTABILIDAD.*ELECTRON|XML.*CONTABILIDAD.*SAT|CATALOGO.*CUENTAS.*SAT",
        description="Contabilidad Electronica (electronic accounting) — monthly trial balance and chart of accounts XML to SAT",
        severity="medium", effort_hours=4.0, tags=["mx", "tax", "accounting", "electronic"],
        fix_suggestion="Configure SAT-compliant chart of accounts mapping and monthly XML generation in S/4HANA.",
    ),
]

# =============================================================================
# ITALY (IT) — 5 rules
# =============================================================================
ITALY_RULES = [
    SimplificationRule(
        id="IT-001", category="it_localization", country="IT",
        pattern=r"FATTURA\s*ELETTRONICA|SDI\b|SISTEMA.*INTERSCAMBIO",
        description="Fattura Elettronica (Italian e-invoice via SDI) — verify S/4HANA integration",
        severity="critical", effort_hours=6.0, tags=["it", "tax", "einvoice"],
    ),
    SimplificationRule(
        id="IT-002", category="it_localization", country="IT",
        pattern=r"ESTEROMETRO|SPESOMETRO",
        description="Italian cross-border reporting — verify compliance in S/4HANA",
        severity="medium", effort_hours=3.0, tags=["it", "tax", "compliance"],
    ),
    SimplificationRule(
        id="IT-003", category="it_localization", country="IT",
        pattern=r"\bCODICE\s*FISCALE\b|PARTITA\s*IVA",
        description="Italian tax codes — map to BP tax numbers in S/4HANA",
        severity="low", effort_hours=1.0, tags=["it", "tax", "bp"],
    ),
    SimplificationRule(
        id="IT-004", category="it_localization", country="IT",
        pattern=r"CERTIFICAZIONE\s*UNICA|CU\s*\d{4}|MODELLO\s*770",
        description="Italian withholding tax certificates — verify in S/4HANA",
        severity="medium", effort_hours=3.0, tags=["it", "tax", "withholding"],
    ),
    SimplificationRule(
        id="IT-005", category="it_localization", country="IT",
        pattern=r"J_1I[^A-Z]|RFVITAX",
        description="Italy-specific SAP programs — verify S/4HANA compatibility",
        severity="medium", effort_hours=2.0, tags=["it", "localization"],
    ),
]

# =============================================================================
# ITALY ADDITIONAL — expanded to 12+ total Italy rules
# =============================================================================
ITALY_EXTRA_RULES = [
    SimplificationRule(
        id="IT-006", category="COUNTRY_IT", country="IT",
        pattern=r"SDI.*SUBMIT|SDI.*CHANNEL|SISTEMA.*INTERSCAMBIO.*SEND|SDI.*CODICE.*DESTINAT",
        description="SDI (Sistema di Interscambio) submission — verify electronic invoice channel and 7-char recipient code",
        severity="high", effort_hours=4.0, tags=["it", "einvoice", "sdi", "submission"],
        fix_suggestion="Configure SDI channel (direct/PEC/intermediary) in S/4HANA Document Compliance for Italy.",
    ),
    SimplificationRule(
        id="IT-007", category="COUNTRY_IT", country="IT",
        pattern=r"F24\b.*PAYMENT|MODELLO\s*F24|F24.*COMPENSAZIONE|TRIBUT.*F24",
        description="Modello F24 (unified tax payment form) — verify generation for VAT, IRPEF, INPS, IRAP payments",
        severity="medium", effort_hours=3.0, tags=["it", "tax", "f24", "payment"],
        fix_suggestion="Configure F24 payment form generation with correct tribute codes in S/4HANA.",
    ),
    SimplificationRule(
        id="IT-008", category="COUNTRY_IT", country="IT",
        pattern=r"LIPE\b|LIQUIDAZIONE.*PERIODICA.*IVA|COMUNICAZIONE.*IVA.*PERIODICA",
        description="LIPE (periodic VAT settlement communication) — quarterly VAT settlement report to Agenzia delle Entrate",
        severity="medium", effort_hours=3.0, tags=["it", "tax", "vat", "lipe"],
        fix_suggestion="Configure quarterly LIPE (Liquidazioni Periodiche IVA) XML generation in S/4HANA for AdE submission.",
    ),
    SimplificationRule(
        id="IT-009", category="COUNTRY_IT", country="IT",
        pattern=r"BOLLO.*VIRTUALE|STAMP.*DUTY.*IT|IMPOSTA.*BOLLO|BOLLO.*FATTURA",
        description="Italian stamp duty (imposta di bollo) on invoices > EUR 77.47 — verify automatic stamp duty calculation",
        severity="low", effort_hours=2.0, tags=["it", "tax", "stamp-duty"],
        fix_suggestion="Configure automatic EUR 2 stamp duty (bollo) for invoices exceeding EUR 77.47 exempt from VAT.",
    ),
    SimplificationRule(
        id="IT-010", category="COUNTRY_IT", country="IT",
        pattern=r"INTRASTAT.*IT|INTRA.*1.*IT|MODELLO\s*INTRA|SCAMBI.*INTRACOMUNITARI",
        description="Italian Intrastat (Modello INTRA) — verify goods/services intra-EU trade reporting to Agenzia delle Dogane",
        severity="medium", effort_hours=3.0, tags=["it", "trade", "intrastat", "eu"],
        fix_suggestion="Configure INTRA 1/2 (sales/purchases) reporting with commodity codes in S/4HANA Foreign Trade.",
    ),
    SimplificationRule(
        id="IT-011", category="COUNTRY_IT", country="IT",
        pattern=r"INPS\b.*CONTRIB|CONTRIBUT.*INPS|PREVIDENZ.*INPS|INPS.*DENUNCIA",
        description="INPS social security contributions — verify employer/employee pension and insurance contributions",
        severity="medium", effort_hours=3.0, tags=["it", "hr", "inps", "statutory"],
        fix_suggestion="Configure INPS contribution rates and DMA/UniEmens reporting in S/4HANA Payroll Italy.",
    ),
    SimplificationRule(
        id="IT-012", category="COUNTRY_IT", country="IT",
        pattern=r"REGIME\s*FORFETTARIO|FLAT\s*TAX.*IT|IVA.*ESENTE.*REGIME",
        description="Regime Forfettario (flat-rate scheme) — verify simplified VAT treatment for small taxpayers",
        severity="low", effort_hours=2.0, tags=["it", "tax", "forfettario", "vat"],
        fix_suggestion="Configure flat-rate scheme tax codes (VAT exempt) for eligible entities in S/4HANA.",
    ),
]

# =============================================================================
# SOUTH KOREA (KR) — 4 rules
# =============================================================================
KOREA_RULES = [
    SimplificationRule(
        id="KR-001", category="kr_localization", country="KR",
        pattern=r"E.?TAX\s*INVOICE|HOMETAX|GUKSE.?CHEONG",
        description="Korean e-Tax Invoice — verify NTS integration in S/4HANA",
        severity="high", effort_hours=6.0, tags=["kr", "tax", "einvoice"],
    ),
    SimplificationRule(
        id="KR-002", category="kr_localization", country="KR",
        pattern=r"K.?IFRS|KOREAN\s*IFRS",
        description="K-IFRS — verify accounting standard compliance in S/4HANA",
        severity="medium", effort_hours=4.0, tags=["kr", "finance", "accounting"],
    ),
    SimplificationRule(
        id="KR-003", category="kr_localization", country="KR",
        pattern=r"BUSINESS\s*REGISTRATION.*KR|SAEOPJA\b",
        description="Korean business registration number — map to BP",
        severity="low", effort_hours=1.0, tags=["kr", "tax", "bp"],
    ),
    SimplificationRule(
        id="KR-004", category="kr_localization", country="KR",
        pattern=r"J_3K\w+",
        description="Korea-specific SAP table — verify S/4HANA compatibility",
        severity="medium", effort_hours=2.0, tags=["kr", "localization"],
    ),
]

# =============================================================================
# SOUTH KOREA ADDITIONAL — expanded to 10+ total Korea rules
# =============================================================================
KOREA_EXTRA_RULES = [
    SimplificationRule(
        id="KR-005", category="COUNTRY_KR", country="KR",
        pattern=r"NTS\b.*INVOICE|HOMETAX.*SUBMIT|GUKSE.*CHONG.*INVOICE|ETAX.*INVOICE.*KR",
        description="NTS (National Tax Service) e-Tax invoice submission — verify Hometax API integration for B2B invoices",
        severity="high", effort_hours=5.0, tags=["kr", "tax", "etax", "nts"],
        fix_suggestion="Configure NTS e-Tax invoice submission via Hometax API in S/4HANA Document Compliance.",
    ),
    SimplificationRule(
        id="KR-006", category="COUNTRY_KR", country="KR",
        pattern=r"VAT\s*RETURN.*KR|BUGASE\b|VAT.*FILING.*KOREA|BUGATAX",
        description="Korean VAT return filing — verify semi-annual/quarterly VAT return preparation for NTS",
        severity="medium", effort_hours=3.0, tags=["kr", "tax", "vat", "return"],
        fix_suggestion="Configure Korean VAT return report with sales/purchase tax invoice summaries in S/4HANA.",
    ),
    SimplificationRule(
        id="KR-007", category="COUNTRY_KR", country="KR",
        pattern=r"WITHHOLDING.*TAX.*KR|WONCHEON.*JINGSU|TAX.*WITHHOLD.*KOREA|KR.*WHT",
        description="Korean withholding tax (Woncheon Jingsu) — verify tax type codes and rates for various income categories",
        severity="medium", effort_hours=3.0, tags=["kr", "tax", "withholding"],
        fix_suggestion="Configure Korean withholding tax types (interest, dividends, royalties, services) in S/4HANA.",
    ),
    SimplificationRule(
        id="KR-008", category="COUNTRY_KR", country="KR",
        pattern=r"SOCIAL\s*INSURANCE.*KR|NPS\b.*KOREA|NHIS\b.*KOREA|EI\b.*KOREA|GOYONG.*BOHEOM",
        description="Korean social insurance (NPS/NHIS/EI/IACI) — verify four major insurance contribution calculations",
        severity="medium", effort_hours=4.0, tags=["kr", "hr", "social-insurance", "statutory"],
        fix_suggestion="Configure NPS (national pension), NHIS (health), EI (employment), IACI (industrial accident) in S/4HANA Payroll.",
    ),
    SimplificationRule(
        id="KR-009", category="COUNTRY_KR", country="KR",
        pattern=r"ERP\s*CERTIF.*KR|GUKGA.*PYOJUN|NATIONAL\s*STANDARD.*ERP|KR.*ERP.*AUDIT",
        description="Korean ERP certification requirements — verify NTS-certified ERP module compliance for tax reporting",
        severity="medium", effort_hours=4.0, tags=["kr", "compliance", "certification"],
        fix_suggestion="Ensure S/4HANA meets Korean NTS ERP certification requirements for tax invoice and reporting.",
    ),
    SimplificationRule(
        id="KR-010", category="COUNTRY_KR", country="KR",
        pattern=r"YEAR.?END.*TAX.*KR|YEONMAL\s*JEONSAN|ANNUAL.*SETTLE.*KR|CREDIT\s*CARD.*DEDUCT.*KR",
        description="Korean year-end tax settlement — verify comprehensive income deduction calculation for employees",
        severity="medium", effort_hours=4.0, tags=["kr", "hr", "payroll", "year-end"],
        fix_suggestion="Configure year-end settlement with credit card, medical, education, donation deductions in S/4HANA Payroll Korea.",
    ),
]

# =============================================================================
# SOUTH AFRICA (ZA) — 4 rules
# =============================================================================
SOUTH_AFRICA_RULES = [
    SimplificationRule(
        id="ZA-001", category="za_localization", country="ZA",
        pattern=r"\bSARS\b|SOUTH\s*AFRICAN\s*REVENUE",
        description="SARS compliance — verify tax reporting in S/4HANA",
        severity="medium", effort_hours=3.0, tags=["za", "tax", "compliance"],
    ),
    SimplificationRule(
        id="ZA-002", category="za_localization", country="ZA",
        pattern=r"VAT\s*201|EMP\s*201|EMP\s*501",
        description="SA VAT 201 / EMP 201 returns — verify generation in S/4HANA",
        severity="medium", effort_hours=3.0, tags=["za", "tax"],
    ),
    SimplificationRule(
        id="ZA-003", category="za_localization", country="ZA",
        pattern=r"\bBBBEE\b|BROAD.?BASED\s*BLACK|B.?BBEE\s*LEVEL",
        description="B-BBEE compliance reporting — verify vendor scoring in S/4HANA",
        severity="medium", effort_hours=2.0, tags=["za", "compliance"],
    ),
    SimplificationRule(
        id="ZA-004", category="za_localization", country="ZA",
        pattern=r"\bUIF\b|UNEMPLOYMENT\s*INSURANCE.*ZA|SDL\b.*LEVY",
        description="UIF/SDL (SA statutory deductions) — verify payroll config",
        severity="medium", effort_hours=3.0, tags=["za", "hr", "statutory"],
    ),
]

# =============================================================================
# SOUTH AFRICA ADDITIONAL — expanded to 10+ total ZA rules
# =============================================================================
SOUTH_AFRICA_EXTRA_RULES = [
    SimplificationRule(
        id="ZA-005", category="COUNTRY_ZA", country="ZA",
        pattern=r"IRP5\b|IT3\b.*TAX|EMPLOYEE\s*TAX\s*CERT.*ZA|IRP5.*SUBMIT",
        description="IRP5/IT3 employee tax certificates — verify annual submission to SARS and e@syFile format",
        severity="medium", effort_hours=3.0, tags=["za", "hr", "tax", "irp5"],
        fix_suggestion="Configure IRP5/IT3(a) certificate generation with SARS source codes in S/4HANA Payroll South Africa.",
    ),
    SimplificationRule(
        id="ZA-006", category="COUNTRY_ZA", country="ZA",
        pattern=r"CIPC\b|COMPANIES.*INTELLECTUAL.*PROPERTY|ANNUAL\s*RETURN.*CIPC",
        description="CIPC (Companies and Intellectual Property Commission) — verify company registration and annual return filing",
        severity="low", effort_hours=2.0, tags=["za", "compliance", "cipc"],
        fix_suggestion="Ensure CIPC registration numbers are maintained in company master data for annual return filing.",
    ),
    SimplificationRule(
        id="ZA-007", category="COUNTRY_ZA", country="ZA",
        pattern=r"EXCHANGE\s*CONTROL.*ZA|SARB\b.*EXCHANGE|FOREX.*REPORTING.*ZA|BOP\b.*REPORTING",
        description="Exchange control / SARB reporting — verify foreign exchange transaction reporting for balance of payments",
        severity="medium", effort_hours=3.0, tags=["za", "banking", "exchange-control"],
        fix_suggestion="Configure SARB BoP (Balance of Payments) category codes on foreign currency transactions in S/4HANA.",
    ),
    SimplificationRule(
        id="ZA-008", category="COUNTRY_ZA", country="ZA",
        pattern=r"CARBON\s*TAX.*ZA|CARBON.*LEVY.*SA|GREENHOUSE.*TAX.*ZA|CARBON_OFFSET",
        description="South Africa carbon tax — verify emission reporting and carbon tax offset tracking per Carbon Tax Act",
        severity="medium", effort_hours=3.0, tags=["za", "tax", "carbon", "environment"],
        fix_suggestion="Configure carbon tax calculation per tCO2e and allowance/offset tracking in S/4HANA.",
    ),
    SimplificationRule(
        id="ZA-009", category="COUNTRY_ZA", country="ZA",
        pattern=r"ETI\b.*ZA|EMPLOYMENT\s*TAX\s*INCENTIVE|ETI.*CLAIM|YOUTH\s*EMPLOY.*INCENT",
        description="ETI (Employment Tax Incentive) — verify youth employment incentive PAYE offset calculation",
        severity="low", effort_hours=2.0, tags=["za", "hr", "tax", "eti"],
        fix_suggestion="Configure ETI calculation for qualifying employees (18-29 years, below threshold) in S/4HANA Payroll.",
    ),
    SimplificationRule(
        id="ZA-010", category="COUNTRY_ZA", country="ZA",
        pattern=r"VAT\s*VENDOR.*ZA|VAT\s*REG.*SOUTH\s*AFRICA|VAT.*ZA.*\d{10}",
        description="South Africa VAT vendor registration — verify VAT number (10-digit) and VAT201 return configuration",
        severity="medium", effort_hours=2.0, tags=["za", "tax", "vat", "registration"],
        fix_suggestion="Configure 10-digit SA VAT number validation and VAT201 return periods (monthly/bi-monthly) in S/4HANA.",
    ),
]

# =============================================================================
# POLAND (PL) — 4 rules
# =============================================================================
POLAND_RULES = [
    SimplificationRule(
        id="PL-001", category="pl_localization", country="PL",
        pattern=r"\bJPK\b|JEDNOLITY\s*PLIK|SAF.?T.*PL",
        description="JPK (Polish SAF-T) — verify JPK_V7M generation in S/4HANA",
        severity="high", effort_hours=6.0, tags=["pl", "tax", "saft"],
    ),
    SimplificationRule(
        id="PL-002", category="pl_localization", country="PL",
        pattern=r"SPLIT\s*PAYMENT.*PL|MECHANIZM.*PODZIELONEJ",
        description="Polish split payment mechanism — verify in S/4HANA",
        severity="high", effort_hours=4.0, tags=["pl", "tax", "payment"],
    ),
    SimplificationRule(
        id="PL-003", category="pl_localization", country="PL",
        pattern=r"\bNIP\b.*POLAND|NUMER.*IDENTYFIKACJI|NIP\s*\d{10}",
        description="Polish NIP (tax ID) — map to BP tax numbers",
        severity="low", effort_hours=1.0, tags=["pl", "tax", "bp"],
    ),
    SimplificationRule(
        id="PL-004", category="pl_localization", country="PL",
        pattern=r"KSEF\b|KRAJOWY\s*SYSTEM.*FAKTUR",
        description="KSeF (Polish national e-invoicing) — verify S/4HANA readiness",
        severity="critical", effort_hours=8.0, tags=["pl", "tax", "einvoice"],
    ),
]

# =============================================================================
# POLAND ADDITIONAL — expanded to 10+ total Poland rules
# =============================================================================
POLAND_EXTRA_RULES = [
    SimplificationRule(
        id="PL-005", category="COUNTRY_PL", country="PL",
        pattern=r"JPK_V7M|JPK_V7K|JPK.*VDEK|JEDNOLITY.*PLIK.*V7",
        description="JPK_V7M/V7K (new SAF-T with VAT return) — combined JPK declaration replacing JPK_VAT and VAT-7",
        severity="high", effort_hours=5.0, tags=["pl", "tax", "jpk", "saft"],
        fix_suggestion="Configure JPK_V7M (monthly) or JPK_V7K (quarterly) generation with GTU codes in S/4HANA.",
    ),
    SimplificationRule(
        id="PL-006", category="COUNTRY_PL", country="PL",
        pattern=r"KSEF.*SUBMIT|KSEF.*API|KRAJOWY.*SYSTEM.*FAKTUR.*INTEGR|KSEF.*TOKEN",
        description="KSeF (Krajowy System e-Faktur) integration — structured e-invoice submission to national platform",
        severity="critical", effort_hours=8.0, tags=["pl", "einvoice", "ksef"],
        fix_suggestion="Implement KSeF API integration via SAP Document Compliance for structured e-invoice submission.",
        s4_note="3089413",
    ),
    SimplificationRule(
        id="PL-007", category="COUNTRY_PL", country="PL",
        pattern=r"ZUS\b.*CONTRIB|ZUS_CALC|ZAKLAD.*UBEZPIECZEN|ZUS.*DRA|ZUS.*RCA",
        description="ZUS social insurance contributions — verify employer/employee rates for pension, disability, sickness, health",
        severity="medium", effort_hours=4.0, tags=["pl", "hr", "zus", "statutory"],
        fix_suggestion="Configure ZUS contribution rates (emerytalne 19.52%, rentowe 8%, chorobowe 2.45%) in S/4HANA Payroll Poland.",
    ),
    SimplificationRule(
        id="PL-008", category="COUNTRY_PL", country="PL",
        pattern=r"PIT.*POLAND|PIT.?37|PIT.?11|PIT.?4R|PIT.*ROCZN|ANNUAL.*TAX.*PIT.*PL",
        description="Polish PIT (personal income tax) forms — verify PIT-11/PIT-4R annual reporting to tax office",
        severity="medium", effort_hours=3.0, tags=["pl", "hr", "tax", "pit"],
        fix_suggestion="Configure PIT-11 (employee annual info) and PIT-4R (employer annual declaration) in S/4HANA Payroll Poland.",
    ),
    SimplificationRule(
        id="PL-009", category="COUNTRY_PL", country="PL",
        pattern=r"CIT.*POLAND|CIT.?8|PODATEK.*DOCHODOW.*OSOB.*PRAWN|CIT.*PL.*RETURN",
        description="Polish CIT (corporate income tax) — verify CIT-8 annual return and quarterly advance payment calculation",
        severity="medium", effort_hours=3.0, tags=["pl", "tax", "cit", "corporate"],
        fix_suggestion="Configure CIT-8 return preparation and quarterly CIT advance calculation in S/4HANA.",
    ),
    SimplificationRule(
        id="PL-010", category="COUNTRY_PL", country="PL",
        pattern=r"WHITE\s*LIST.*VAT|BIALA\s*LISTA|VAT.*BANK.*ACCOUNT.*PL|WYKAZ.*PODMIOTOW",
        description="Polish VAT white list verification — mandatory bank account check before payment to VAT-registered vendors",
        severity="high", effort_hours=3.0, tags=["pl", "tax", "vat", "whitelist"],
        fix_suggestion="Implement VAT white list bank account verification in S/4HANA payment process via MF API.",
    ),
    SimplificationRule(
        id="PL-011", category="COUNTRY_PL", country="PL",
        pattern=r"GTU\b.*CODE|GRUPA.*TOWAR|GTU_\d{2}|OZNACZENIE.*GTU",
        description="GTU (goods/services group codes) in JPK_V7 — verify 13 GTU category codes for sales transactions",
        severity="medium", effort_hours=2.0, tags=["pl", "tax", "gtu", "jpk"],
        fix_suggestion="Configure GTU codes (GTU_01 to GTU_13) mapping by material/service group in S/4HANA for JPK_V7.",
    ),
]

# =============================================================================
# CANADA (CA) — 3 rules
# =============================================================================
CANADA_RULES = [
    SimplificationRule(
        id="CA-001", category="ca_localization", country="CA",
        pattern=r"\bGST\b.*CANAD|\bHST\b|HARMONIZED\s*SALES\s*TAX",
        description="Canadian GST/HST — verify tax procedure TAXCA and provincial tax in S/4HANA",
        severity="medium", effort_hours=4.0, tags=["ca", "tax", "gst"],
    ),
    SimplificationRule(
        id="CA-002", category="ca_localization", country="CA",
        pattern=r"\bT4\b.*SLIP|T4A\b|RL.?1\b|CANADIAN\s*PAYROLL",
        description="Canadian T4/RL-1 payroll reporting — verify HCM payroll integration",
        severity="medium", effort_hours=4.0, tags=["ca", "hr", "payroll"],
    ),
    SimplificationRule(
        id="CA-003", category="ca_localization", country="CA",
        pattern=r"\bBN\b.*CANADA|BUSINESS\s*NUMBER.*CRA|CRA\b.*TAX",
        description="Canadian Business Number (CRA) — map to BP tax numbers in S/4HANA",
        severity="low", effort_hours=1.0, tags=["ca", "tax", "bp"],
    ),
]

# =============================================================================
# INDIA ADDITIONAL — expanded to 30+ total India rules
# =============================================================================
INDIA_EXTRA_RULES = [
    SimplificationRule(
        id="IN-016", category="COUNTRY_IN", country="IN",
        pattern=r"RCM\b|REVERSE\s*CHARGE.*INDIA|REVERSE\s*CHARGE.*GST",
        description="GST Reverse Charge Mechanism (RCM) — verify RCM configuration in S/4HANA",
        severity="medium", effort_hours=3.0, tags=["india", "gst", "rcm"],
    ),
    SimplificationRule(
        id="IN-017", category="COUNTRY_IN", country="IN",
        pattern=r"TCS\b.*COLLECT|TAX\s*COLLECTED.*SOURCE|206C",
        description="TCS (Tax Collected at Source) — verify withholding tax config for TCS in S/4HANA",
        severity="medium", effort_hours=3.0, tags=["india", "tcs", "tax"],
    ),
    SimplificationRule(
        id="IN-018", category="COUNTRY_IN", country="IN",
        pattern=r"INPUT\s*TAX\s*CREDIT|ITC\b.*GST|GSTR.?2[AB]",
        description="GST Input Tax Credit (ITC) / GSTR-2A/2B reconciliation — verify in S/4HANA",
        severity="high", effort_hours=4.0, tags=["india", "gst", "itc"],
    ),
    SimplificationRule(
        id="IN-019", category="COUNTRY_IN", country="IN",
        pattern=r"\bJ_1IEXCHDR\b",
        description="J_1IEXCHDR (Excise header) table removed — excise duty abolished after GST rollout July 2017",
        severity="critical", effort_hours=6.0, tags=["india", "excise", "gst"],
        fix_suggestion="Remove all excise header logic. Use GST condition types JIIG/JICG/JISG in S/4HANA.",
        s4_note="2338067",
    ),
    SimplificationRule(
        id="IN-020", category="COUNTRY_IN", country="IN",
        pattern=r"\bJ_1IEXCDTL\b",
        description="J_1IEXCDTL (Excise detail) table removed — migrate excise line items to GST framework",
        severity="critical", effort_hours=6.0, tags=["india", "excise", "gst"],
        fix_suggestion="Excise detail tables are obsolete post-GST. Migrate to S/4HANA GST tax procedure.",
        s4_note="2338067",
    ),
    SimplificationRule(
        id="IN-021", category="COUNTRY_IN", country="IN",
        pattern=r"J_1IG_GSTIN|J_1IGSTIN|GSTIN_VALIDATE",
        description="J_1IG_GSTIN validation — verify 15-digit GSTIN pattern (2-char state + 10-char PAN + 3-char) in S/4HANA BP master",
        severity="medium", effort_hours=2.0, tags=["india", "gst", "validation"],
        fix_suggestion="Use S/4HANA standard GSTIN validation in Business Partner tax number category.",
        s4_note="2526025",
    ),
    SimplificationRule(
        id="IN-022", category="COUNTRY_IN", country="IN",
        pattern=r"\bJ_1IEWT\b|J_1IEWT_CERT|J_1I_EWT_",
        description="J_1IEWT (India Extended Withholding Tax) — migrate to Enhanced EWT in S/4HANA",
        severity="high", effort_hours=5.0, tags=["india", "tds", "withholding"],
        fix_suggestion="Use S/4HANA Enhanced Extended Withholding Tax with India-specific configuration.",
        s4_note="2206980",
    ),
    SimplificationRule(
        id="IN-023", category="COUNTRY_IN", country="IN",
        pattern=r"HSN\s*MANDATORY|HSN_CODE\s*CHECK|SAC\s*MANDATORY|SAC_CODE\s*VALID",
        description="HSN/SAC code mandatory validation — 8-digit HSN for goods, 6-digit SAC for services required on GST invoices",
        severity="high", effort_hours=3.0, tags=["india", "gst", "hsn", "sac"],
        fix_suggestion="Configure HSN/SAC as mandatory fields in material master and service master for GST compliance.",
        s4_note="2526025",
    ),
    SimplificationRule(
        id="IN-024", category="COUNTRY_IN", country="IN",
        pattern=r"IRN\s*GENERAT|NIC\s*API|EINV_API|IRN_HASH|E_INVOICE_IRN",
        description="E-invoice IRN generation via NIC API — use SAP Document Compliance cloud service for IRN",
        severity="critical", effort_hours=6.0, tags=["india", "einvoice", "irn", "nic"],
        fix_suggestion="Replace custom IRN generation with SAP Document Compliance for India. Configure NIC API credentials in S/4HANA.",
        s4_note="2904193",
    ),
    SimplificationRule(
        id="IN-025", category="COUNTRY_IN", country="IN",
        pattern=r"EWAY.*THRESHOLD|EWAY_BILL_LIMIT|EWAY.*50000|EWAY.*DISTANCE",
        description="E-way bill threshold checks (INR 50,000) — verify distance-based validity and part-B transport rules",
        severity="medium", effort_hours=3.0, tags=["india", "eway", "logistics"],
        fix_suggestion="Configure E-way bill thresholds and transport document rules in S/4HANA logistics.",
    ),
    SimplificationRule(
        id="IN-026", category="COUNTRY_IN", country="IN",
        pattern=r"J_1IRRGST|J_1I_GST_RET|GST_RETURN_TAB",
        description="J_1IRRGST (GST return tables) — verify S/4HANA GST return filing integration with GSTN portal",
        severity="high", effort_hours=4.0, tags=["india", "gst", "returns"],
        fix_suggestion="Use S/4HANA standard GST return preparation with GSTN API integration.",
    ),
    SimplificationRule(
        id="IN-027", category="COUNTRY_IN", country="IN",
        pattern=r"GSTR.?1\b|GSTR1_FILE|GSTR_1_DATA|B2B_INVOICE.*GST|B2C_INVOICE.*GST",
        description="GSTR-1 (outward supplies) filing — verify B2B/B2C/CDNR/EXP invoice data extraction for GSTN",
        severity="high", effort_hours=4.0, tags=["india", "gst", "gstr1"],
        fix_suggestion="Use S/4HANA GST compliance solution for automated GSTR-1 data preparation.",
        s4_note="2526025",
    ),
    SimplificationRule(
        id="IN-028", category="COUNTRY_IN", country="IN",
        pattern=r"GSTR.?3B|GSTR_3B|GST_SUMMARY_RETURN",
        description="GSTR-3B (summary return) filing — verify monthly/quarterly summary tax liability computation",
        severity="high", effort_hours=3.0, tags=["india", "gst", "gstr3b"],
        fix_suggestion="S/4HANA provides GSTR-3B summary preparation from transaction data. Verify configuration.",
    ),
    SimplificationRule(
        id="IN-029", category="COUNTRY_IN", country="IN",
        pattern=r"\bEPF\b.*CALC|\bEPFO\b|PF_CONTRIBUTION|PF_WAGE|EPF_RATE|PF_TRUST",
        description="EPF/PF contribution calculation — verify PF wage ceiling (INR 15,000) and employer/employee rates (12%) in S/4HANA HCM",
        severity="medium", effort_hours=4.0, tags=["india", "hr", "pf", "statutory"],
        fix_suggestion="Configure PF calculation with current statutory rates in S/4HANA Payroll India (wage type /3F1).",
    ),
    SimplificationRule(
        id="IN-030", category="COUNTRY_IN", country="IN",
        pattern=r"\bESIC?\b.*CALC|ESI_CONTRIBUTION|ESI_WAGE|ESI_CEILING|ESI_RATE",
        description="ESI contribution calculation — verify ESI wage ceiling (INR 21,000) and contribution rates in S/4HANA HCM",
        severity="medium", effort_hours=3.0, tags=["india", "hr", "esi", "statutory"],
        fix_suggestion="Configure ESI calculation rules with current wage ceiling and rates in S/4HANA Payroll India.",
    ),
    SimplificationRule(
        id="IN-031", category="COUNTRY_IN", country="IN",
        pattern=r"PTAX\b|P_TAX_STATE|PROFESSIONAL_TAX.*STATE|PT_SLAB|PT_MAHARASHTRA|PT_KARNATAKA",
        description="Professional tax state-wise slab tables — varies by state (Maharashtra, Karnataka, etc.), verify configuration",
        severity="medium", effort_hours=2.0, tags=["india", "hr", "ptax", "statutory"],
        fix_suggestion="Configure state-wise professional tax slabs in S/4HANA payroll. Each state has different rates and slabs.",
    ),
    SimplificationRule(
        id="IN-032", category="COUNTRY_IN", country="IN",
        pattern=r"SECTION\s*194C|SEC_194C|TDS_194C|CONTRACTOR.*TDS",
        description="TDS Section 194C (contractor payments) — verify threshold (INR 30,000 single / INR 1,00,000 aggregate) and rates",
        severity="medium", effort_hours=2.0, tags=["india", "tds", "194c"],
        fix_suggestion="Configure TDS Section 194C with correct thresholds and rates (1%/2%) in S/4HANA withholding tax.",
        s4_note="2206980",
    ),
    SimplificationRule(
        id="IN-033", category="COUNTRY_IN", country="IN",
        pattern=r"SECTION\s*194J|SEC_194J|TDS_194J|PROFESSIONAL.*FEE.*TDS|TECHNICAL.*FEE.*TDS",
        description="TDS Section 194J (professional/technical fees) — verify rate (2%/10%) and threshold (INR 30,000)",
        severity="medium", effort_hours=2.0, tags=["india", "tds", "194j"],
        fix_suggestion="Configure TDS Section 194J with dual rates (2% technical, 10% professional) in S/4HANA.",
        s4_note="2206980",
    ),
    SimplificationRule(
        id="IN-034", category="COUNTRY_IN", country="IN",
        pattern=r"SECTION\s*194H|SEC_194H|TDS_194H|COMMISSION.*TDS|BROKERAGE.*TDS",
        description="TDS Section 194H (commission/brokerage) — verify threshold (INR 15,000) and rate (5%)",
        severity="medium", effort_hours=2.0, tags=["india", "tds", "194h"],
        fix_suggestion="Configure TDS Section 194H for commission payments in S/4HANA withholding tax type.",
        s4_note="2206980",
    ),
    SimplificationRule(
        id="IN-035", category="COUNTRY_IN", country="IN",
        pattern=r"SECTION\s*195\b|SEC_195\b|TDS_195|NRI.*TDS|NON.?RESIDENT.*TDS|DTAA",
        description="TDS Section 195 (payments to non-residents) — verify DTAA treaty rates and lower certificate handling",
        severity="high", effort_hours=4.0, tags=["india", "tds", "195", "nri"],
        fix_suggestion="Configure Section 195 with DTAA rates per country. Use withholding tax certificate process in S/4HANA.",
        s4_note="2206980",
    ),
    SimplificationRule(
        id="IN-036", category="COUNTRY_IN", country="IN",
        pattern=r"SECTION\s*196A|SEC_196A|TDS_196A|INCOME.*NRI.*UNIT",
        description="TDS Section 196A (income from mutual funds to NRI) — verify rate and exemptions in S/4HANA",
        severity="medium", effort_hours=2.0, tags=["india", "tds", "196a"],
        fix_suggestion="Configure Section 196A withholding tax type for mutual fund payments to non-residents.",
    ),
    SimplificationRule(
        id="IN-037", category="COUNTRY_IN", country="IN",
        pattern=r"AADHAAR.*PAN\s*LINK|PAN.*AADHAAR\s*LINK|AADHAAR_PAN|LINK.*AADHAAR.*PAN",
        description="Aadhaar-PAN linking validation — mandatory for tax compliance; verify field mapping in BP master data",
        severity="medium", effort_hours=2.0, tags=["india", "compliance", "aadhaar", "pan"],
        fix_suggestion="Ensure Aadhaar-PAN linked status is captured in Business Partner master for tax compliance.",
    ),
    SimplificationRule(
        id="IN-038", category="COUNTRY_IN", country="IN",
        pattern=r"J_1IEXCOBJ|J_1IEXCDEF|J_1IMATGRP|J_1IEXCREG",
        description="Legacy India excise objects/definitions — completely obsolete after GST, remove all references",
        severity="critical", effort_hours=4.0, tags=["india", "excise", "legacy"],
        fix_suggestion="All J_1IEXC* excise objects are obsolete. Clean up and replace with GST tax procedure TAXINN.",
        s4_note="2338067",
    ),
    SimplificationRule(
        id="IN-039", category="COUNTRY_IN", country="IN",
        pattern=r"GSTR.?2A|GSTR_2A|GSTR2A_RECON|PURCHASE.*RECONCIL.*GST",
        description="GSTR-2A/2B purchase reconciliation — verify auto-populated inward supply matching with S/4HANA",
        severity="high", effort_hours=5.0, tags=["india", "gst", "gstr2a", "reconciliation"],
        fix_suggestion="Use S/4HANA GST reconciliation features to match GSTR-2A/2B with purchase register.",
    ),
    SimplificationRule(
        id="IN-040", category="COUNTRY_IN", country="IN",
        pattern=r"LUT\b.*GST|LETTER.*UNDERTAKING.*EXPORT|BOND.*EXPORT.*GST",
        description="LUT (Letter of Undertaking) for GST-free exports — verify export without payment of IGST workflow",
        severity="medium", effort_hours=2.0, tags=["india", "gst", "export", "lut"],
        fix_suggestion="Configure LUT-based export billing in S/4HANA with zero-rated IGST condition types.",
    ),
]

# =============================================================================
# US ADDITIONAL — expanded to 25+ total US rules
# =============================================================================
US_EXTRA_RULES = [
    SimplificationRule(
        id="US-013", category="COUNTRY_US", country="US",
        pattern=r"FATCA\b|FOREIGN\s*ACCOUNT\s*TAX|FBAR\b",
        description="FATCA/FBAR foreign account reporting — verify compliance in S/4HANA",
        severity="high", effort_hours=6.0, tags=["us", "tax", "compliance"],
    ),
    SimplificationRule(
        id="US-014", category="COUNTRY_US", country="US",
        pattern=r"NEXUS\b.*TAX|WAYFAIR|ECONOMIC\s*NEXUS|MARKETPLACE\s*FACILITATOR",
        description="US economic nexus / Wayfair — verify multi-state tax engine in S/4HANA",
        severity="medium", effort_hours=4.0, tags=["us", "tax", "sales-tax"],
    ),
    SimplificationRule(
        id="US-015", category="COUNTRY_US", country="US",
        pattern=r"1099.?NEC|FORM.*1099.*NEC|NONEMPLOYEE\s*COMP",
        description="1099-NEC (Non-Employee Compensation) — separated from 1099-MISC since 2020, verify S/4HANA reporting class",
        severity="medium", effort_hours=3.0, tags=["us", "tax", "1099"],
        fix_suggestion="Configure separate 1099-NEC reporting class in S/4HANA withholding tax. Box 1 for NEC payments.",
    ),
    SimplificationRule(
        id="US-016", category="COUNTRY_US", country="US",
        pattern=r"1099.?INT|FORM.*1099.*INT|INTEREST\s*INCOME.*1099",
        description="1099-INT (Interest Income) — verify interest payment reporting setup in S/4HANA",
        severity="medium", effort_hours=2.0, tags=["us", "tax", "1099"],
        fix_suggestion="Map interest payment document types to 1099-INT reporting class in S/4HANA.",
    ),
    SimplificationRule(
        id="US-017", category="COUNTRY_US", country="US",
        pattern=r"1099.?DIV|FORM.*1099.*DIV|DIVIDEND.*1099",
        description="1099-DIV (Dividends and Distributions) — verify dividend reporting in S/4HANA treasury",
        severity="medium", effort_hours=2.0, tags=["us", "tax", "1099"],
        fix_suggestion="Configure 1099-DIV reporting for qualified and ordinary dividends in S/4HANA.",
    ),
    SimplificationRule(
        id="US-018", category="COUNTRY_US", country="US",
        pattern=r"SOX.*AUDIT\s*LOG|AUDIT\s*TRAIL.*SOX|CHANGE\s*LOG.*SOX|SOX.*CONTROL",
        description="SOX audit logging requirements — verify change document logging and access controls in S/4HANA",
        severity="high", effort_hours=8.0, tags=["us", "compliance", "sox", "audit"],
        fix_suggestion="Enable comprehensive change document logging. Configure SAP GRC Access Control for SOX compliance.",
        s4_note="2191480",
    ),
    SimplificationRule(
        id="US-019", category="COUNTRY_US", country="US",
        pattern=r"GAAP.*IFRS\s*MAP|IFRS.*GAAP\s*MAP|PARALLEL.*LEDGER.*GAAP|LEDGER.*US.?GAAP",
        description="GAAP to IFRS mapping impacts — verify parallel ledger configuration in Universal Journal (ACDOCA)",
        severity="high", effort_hours=10.0, tags=["us", "finance", "gaap", "ifrs"],
        fix_suggestion="Configure parallel ledgers in S/4HANA (leading ledger IFRS, non-leading US GAAP or vice versa).",
    ),
    SimplificationRule(
        id="US-020", category="COUNTRY_US", country="US",
        pattern=r"OFAC.*SCREEN|SDN.*SCREEN|DENIED.*PARTY.*SCREEN|SANCTIONED.*SCREEN",
        description="OFAC sanctions screening integration — verify SAP GTS denied party screening in S/4HANA",
        severity="critical", effort_hours=6.0, tags=["us", "compliance", "ofac", "trade"],
        fix_suggestion="Integrate SAP GTS Compliance Management for OFAC/SDN screening in S/4HANA SD/MM processes.",
    ),
    SimplificationRule(
        id="US-021", category="COUNTRY_US", country="US",
        pattern=r"FICA\s*TAX|FICA_CALC|SOCIAL\s*SECURITY\s*TAX|OASDI|MEDICARE\s*TAX",
        description="FICA (Social Security + Medicare) tax computation — verify wage base limits and rates in S/4HANA HCM",
        severity="medium", effort_hours=4.0, tags=["us", "hr", "payroll", "fica"],
        fix_suggestion="Configure FICA wage types with current Social Security wage base ($168,600 for 2024) in S/4HANA Payroll.",
    ),
    SimplificationRule(
        id="US-022", category="COUNTRY_US", country="US",
        pattern=r"FUTA\s*TAX|FUTA_CALC|FEDERAL\s*UNEMPLOYMENT|SUTA\s*TAX|STATE\s*UNEMPLOYMENT",
        description="FUTA/SUTA unemployment tax computation — verify taxable wage base and credit reduction states",
        severity="medium", effort_hours=3.0, tags=["us", "hr", "payroll", "futa"],
        fix_suggestion="Configure FUTA (6% on first $7,000) and state-specific SUTA rates in S/4HANA Payroll.",
    ),
    SimplificationRule(
        id="US-023", category="COUNTRY_US", country="US",
        pattern=r"ACH.*FORMAT|NACHA.*FORMAT|ACH_PAYMENT_FILE|ACH.*BATCH",
        description="ACH/NACHA payment file processing — verify ACH payment method and NACHA format in S/4HANA",
        severity="medium", effort_hours=4.0, tags=["us", "banking", "ach", "payment"],
        fix_suggestion="Configure ACH payment method with NACHA file format in S/4HANA payment program (F110).",
    ),
    SimplificationRule(
        id="US-024", category="COUNTRY_US", country="US",
        pattern=r"EDI.*PROCESS|EDI.*IDOC|X12.*PROCESS|EDI_PARTNER|EDI.*940|EDI.*945",
        description="EDI/ANSI X12 processing — verify IDoc-EDI mapping and partner profiles in S/4HANA",
        severity="medium", effort_hours=5.0, tags=["us", "edi", "integration"],
        fix_suggestion="Migrate EDI partner profiles and IDoc mappings. Consider SAP Integration Suite for EDI.",
    ),
    SimplificationRule(
        id="US-025", category="COUNTRY_US", country="US",
        pattern=r"ASC\s*842.*LEASE|LEASE.*ASC\s*842|RIGHT.*USE.*ASSET|ROU_ASSET|LEASE\s*LIAB",
        description="ASC 842 lease accounting — use S/4HANA RE-FX (Real Estate Flexible) for lease capitalization",
        severity="high", effort_hours=10.0, tags=["us", "finance", "lease", "asc842"],
        fix_suggestion="Implement S/4HANA RE-FX for ASC 842 compliance. Migrate operating leases to right-of-use assets.",
        s4_note="2684804",
    ),
    SimplificationRule(
        id="US-026", category="COUNTRY_US", country="US",
        pattern=r"ASC\s*606.*REVENUE|REVENUE.*ASC\s*606|POC.*REVENUE|CONTRACT.*REVENUE.*RECOGN",
        description="ASC 606 revenue recognition — use S/4HANA RAR (Revenue Accounting and Reporting) module",
        severity="high", effort_hours=10.0, tags=["us", "finance", "revenue", "asc606"],
        fix_suggestion="Implement S/4HANA RAR for ASC 606 five-step model. Migrate existing POC/milestone-based recognition.",
        s4_note="2565814",
    ),
    SimplificationRule(
        id="US-027", category="COUNTRY_US", country="US",
        pattern=r"STATE\s*PAYROLL\s*TAX|SIT\b.*TAX|STATE\s*INCOME\s*TAX|SUI\b.*TAX|SDI\b.*TAX",
        description="State-specific payroll taxes (SIT, SUI, SDI) — verify multi-state payroll configuration in S/4HANA",
        severity="medium", effort_hours=6.0, tags=["us", "hr", "payroll", "state-tax"],
        fix_suggestion="Configure state-specific tax tables for all applicable states in S/4HANA Payroll (BSI TaxFactory or equivalent).",
    ),
    SimplificationRule(
        id="US-028", category="COUNTRY_US", country="US",
        pattern=r"SALES\s*TAX.*VERTEX|VERTEX.*INTEGRATION|AVALARA.*INTEGR|TAXJAR",
        description="External tax engine integration (Vertex/Avalara) — verify S/4HANA tax interface compatibility",
        severity="medium", effort_hours=5.0, tags=["us", "tax", "vertex", "avalara"],
        fix_suggestion="Update Vertex/Avalara integration to use S/4HANA tax determination APIs and ACDOCA postings.",
    ),
    SimplificationRule(
        id="US-029", category="COUNTRY_US", country="US",
        pattern=r"W.?2\s*PRINT|W2_GENERAT|W2_FILING|YEAR.?END.*W.?2",
        description="W-2 wage and tax statement generation — verify year-end processing and e-filing in S/4HANA HCM",
        severity="medium", effort_hours=4.0, tags=["us", "hr", "payroll", "w2"],
        fix_suggestion="Configure W-2 year-end forms using S/4HANA payroll year-end processing (report RPCTWNU0).",
    ),
    SimplificationRule(
        id="US-030", category="COUNTRY_US", country="US",
        pattern=r"ACA\b.*REPORT|AFFORDABLE\s*CARE|FORM\s*1094|FORM\s*1095|ACA_COMPLIANCE",
        description="ACA (Affordable Care Act) reporting — verify 1094-C/1095-C form generation in S/4HANA HCM",
        severity="medium", effort_hours=4.0, tags=["us", "hr", "aca", "compliance"],
        fix_suggestion="Configure ACA reporting with employee eligibility tracking in S/4HANA Benefits module.",
    ),
]

# =============================================================================
# GERMANY ADDITIONAL — expanded to 20+ total Germany rules
# =============================================================================
GERMANY_EXTRA_RULES = [
    SimplificationRule(
        id="DE-011", category="COUNTRY_DE", country="DE",
        pattern=r"EBILANZ\b|E.?BILANZ|ELEKTRONISCHE\s*BILANZ|XBRL.*DE",
        description="E-Bilanz (electronic balance sheet) — verify XBRL taxonomy export in S/4HANA",
        severity="medium", effort_hours=4.0, tags=["de", "tax", "compliance"],
    ),
    SimplificationRule(
        id="DE-012", category="COUNTRY_DE", country="DE",
        pattern=r"KASSENSICHERUNGSVERORDNUNG|TSE\b|TECHNISCHE\s*SICHERHEITS",
        description="German fiscal cash register (KassenSichV/TSE) — verify POS integration in S/4HANA",
        severity="medium", effort_hours=3.0, tags=["de", "compliance", "pos"],
    ),
    SimplificationRule(
        id="DE-013", category="COUNTRY_DE", country="DE",
        pattern=r"DATEV_FORMAT|DATEV.*ASCII|DATEV.*KOST|DATEV.*BUCHUNG",
        description="DATEV export format (ASCII/KOST) — verify DATEV Unternehmen Online compatible export from S/4HANA",
        severity="medium", effort_hours=3.0, tags=["de", "tax", "datev", "export"],
        fix_suggestion="Use S/4HANA standard DATEV interface (transaction RFBIDE00 or DATEV Schnittstelle).",
    ),
    SimplificationRule(
        id="DE-014", category="COUNTRY_DE", country="DE",
        pattern=r"GOBD.*ARCHIV|ARCHIV.*GOBD|AUFBEWAHRUNG.*DIGITAL|DIGITAL.*AUFBEWAHRUNG",
        description="GoBD archiving requirements — verify document archiving with tamper-proof audit trail in S/4HANA",
        severity="high", effort_hours=6.0, tags=["de", "compliance", "archiving", "gobd"],
        fix_suggestion="Configure SAP ArchiveLink with GoBD-compliant storage. Enable change document logging.",
        s4_note="2192657",
    ),
    SimplificationRule(
        id="DE-015", category="COUNTRY_DE", country="DE",
        pattern=r"HGB.*RETENTION|AUFBEWAHRUNGSFRIST|RETENTION.*10\s*YEAR|AUFBEWAHR.*PFLICHT",
        description="HGB retention period rules (6/10 years) — verify document retention policies in S/4HANA archiving",
        severity="medium", effort_hours=3.0, tags=["de", "compliance", "retention", "hgb"],
        fix_suggestion="Configure ILM (Information Lifecycle Management) in S/4HANA with HGB retention periods.",
    ),
    SimplificationRule(
        id="DE-016", category="COUNTRY_DE", country="DE",
        pattern=r"ELSTER.*SUBMIT|ELSTER.*SEND|ELSTER_CERTIF|ERE_ELSTER|ELSTER.*XML",
        description="ELSTER electronic tax filing submission — verify XML generation and certificate handling for Finanzamt",
        severity="medium", effort_hours=4.0, tags=["de", "tax", "elster", "filing"],
        fix_suggestion="Use S/4HANA ELSTER integration for automated tax declaration submission to Finanzamt.",
    ),
    SimplificationRule(
        id="DE-017", category="COUNTRY_DE", country="DE",
        pattern=r"UST.?VA.*MELD|USTVA_FORM|VORANMELDUNG|VAT.*ADVANCE.*RETURN.*DE",
        description="USt-VA (Umsatzsteuervoranmeldung) — monthly/quarterly VAT advance return filing via ELSTER",
        severity="high", effort_hours=4.0, tags=["de", "tax", "vat", "ustva"],
        fix_suggestion="Configure USt-VA report generation in S/4HANA with ELSTER-compatible XML output.",
    ),
    SimplificationRule(
        id="DE-018", category="COUNTRY_DE", country="DE",
        pattern=r"SEPA.*MANDAT|SEPA_MANDATE|LASTSCHRIFT.*MANDAT|DIRECT\s*DEBIT.*MANDAT",
        description="SEPA mandate management — verify SEPA Direct Debit mandate lifecycle in S/4HANA FI-CA or FI-AR",
        severity="medium", effort_hours=3.0, tags=["de", "banking", "sepa", "mandate"],
        fix_suggestion="Use S/4HANA SEPA mandate management in payment processing. Verify mandate reference numbers.",
    ),
    SimplificationRule(
        id="DE-019", category="COUNTRY_DE", country="DE",
        pattern=r"INTRASTAT.*MELD|INTRASTAT_DE|VERSENDUNG|EINGANG.*INTRA",
        description="Intrastat declaration (Germany-specific) — verify dispatch/arrival thresholds and commodity codes",
        severity="medium", effort_hours=3.0, tags=["de", "trade", "intrastat", "customs"],
        fix_suggestion="Configure German Intrastat reporting thresholds and commodity code mapping in S/4HANA Foreign Trade.",
    ),
    SimplificationRule(
        id="DE-020", category="COUNTRY_DE", country="DE",
        pattern=r"SOZIALVERSICH.*BEITRAG|SV_BEITRAG|KV_BEITRAG|RV_BEITRAG|AV_BEITRAG|PV_BEITRAG",
        description="German social insurance contributions (KV/RV/AV/PV) — verify payroll calculation with current rates and ceilings",
        severity="medium", effort_hours=5.0, tags=["de", "hr", "payroll", "social-insurance"],
        fix_suggestion="Configure social insurance contribution rates and Beitragsbemessungsgrenze in S/4HANA Payroll Germany.",
    ),
    SimplificationRule(
        id="DE-021", category="COUNTRY_DE", country="DE",
        pattern=r"KURZARBEIT.*GELD|KUG\b|SHORT.?TIME.*WORK.*DE|KURZARBEIT.*CALC",
        description="Kurzarbeit (short-time work allowance) — verify KuG calculation and Bundesagentur reporting in S/4HANA HCM",
        severity="medium", effort_hours=4.0, tags=["de", "hr", "payroll", "kurzarbeit"],
        fix_suggestion="Configure Kurzarbeitergeld calculation rules with current rates (60%/67%) in S/4HANA Payroll.",
    ),
    SimplificationRule(
        id="DE-022", category="COUNTRY_DE", country="DE",
        pattern=r"LOHNSTEUER.*ANMELD|LST_ANMELDUNG|WAGE\s*TAX.*RETURN.*DE|ELSTAM",
        description="German wage tax return (Lohnsteueranmeldung) / ELStAM — verify electronic filing in S/4HANA HCM",
        severity="medium", effort_hours=3.0, tags=["de", "hr", "payroll", "tax"],
        fix_suggestion="Configure ELStAM (Elektronische Lohnsteuerabzugsmerkmale) interface in S/4HANA Payroll Germany.",
    ),
    SimplificationRule(
        id="DE-023", category="COUNTRY_DE", country="DE",
        pattern=r"BETRIEBLICHE.*ALTERSVERSORG|BAV\b|COMPANY\s*PENSION.*DE|DIREKTVERSICHERUNG",
        description="Company pension scheme (betriebliche Altersversorgung) — verify pension fund integration in S/4HANA HCM",
        severity="medium", effort_hours=3.0, tags=["de", "hr", "pension", "bav"],
        fix_suggestion="Configure bAV (company pension) wage types and contribution limits in S/4HANA Payroll Germany.",
    ),
]

# =============================================================================
# BRAZIL ADDITIONAL — expanded to 20+ total Brazil rules
# =============================================================================
BRAZIL_EXTRA_RULES = [
    SimplificationRule(
        id="BR-011", category="COUNTRY_BR", country="BR",
        pattern=r"REINF\b|EFD.?REINF|ESCRITURACAO.*RETENCOES",
        description="EFD-REINF (withholding tax digital bookkeeping) — verify S/4HANA reporting",
        severity="high", effort_hours=4.0, tags=["br", "tax", "compliance"],
    ),
    SimplificationRule(
        id="BR-012", category="COUNTRY_BR", country="BR",
        pattern=r"ESOCIAL\b|E.?SOCIAL.*BRAZIL",
        description="eSocial (Brazilian digital labor obligations) — verify HR integration in S/4HANA",
        severity="high", effort_hours=6.0, tags=["br", "hr", "compliance"],
    ),
    SimplificationRule(
        id="BR-013", category="COUNTRY_BR", country="BR",
        pattern=r"NFS.?E\b|NOTA.*SERVICO.*ELETRON|NFSE_GENERATE",
        description="NFS-e (Nota Fiscal de Servico Eletronica) — municipality-level e-invoice for services, verify S/4HANA integration",
        severity="high", effort_hours=6.0, tags=["br", "tax", "nfse", "services"],
        fix_suggestion="Use SAP Document Compliance for NFS-e generation per municipality requirements in S/4HANA.",
    ),
    SimplificationRule(
        id="BR-014", category="COUNTRY_BR", country="BR",
        pattern=r"CT.?E\b|CONHECIMENTO.*TRANSPORTE|CTE_ELECTRONIC",
        description="CT-e (Conhecimento de Transporte Eletronico) — electronic transport document for freight, verify in S/4HANA",
        severity="high", effort_hours=5.0, tags=["br", "tax", "cte", "logistics"],
        fix_suggestion="Configure CT-e generation for transport operations in S/4HANA with Document Compliance.",
    ),
    SimplificationRule(
        id="BR-015", category="COUNTRY_BR", country="BR",
        pattern=r"SPED.*FISCAL|EFD_FISCAL|ESCRITURACAO.*FISCAL.*DIGITAL",
        description="SPED Fiscal (EFD ICMS/IPI) — digital fiscal bookkeeping for state taxes, verify generation in S/4HANA",
        severity="high", effort_hours=6.0, tags=["br", "tax", "sped", "fiscal"],
        fix_suggestion="Use S/4HANA standard SPED Fiscal reports with correct register blocks (0, C, D, E, H, K).",
    ),
    SimplificationRule(
        id="BR-016", category="COUNTRY_BR", country="BR",
        pattern=r"SPED.*CONTRIBU|EFD_CONTRIB|PIS.*COFINS.*SPED",
        description="SPED Contribuicoes (EFD PIS/COFINS) — digital bookkeeping for federal contributions",
        severity="high", effort_hours=5.0, tags=["br", "tax", "sped", "contributions"],
        fix_suggestion="Configure SPED Contribuicoes blocks (0, A, C, D, F, M) in S/4HANA for PIS/COFINS reporting.",
    ),
    SimplificationRule(
        id="BR-017", category="COUNTRY_BR", country="BR",
        pattern=r"SPED.*CONTAB|ECD\b.*BRAZIL|ESCRITURACAO.*CONTAB.*DIGITAL",
        description="SPED Contabil (ECD) — digital accounting bookkeeping, verify ACDOCA integration in S/4HANA",
        severity="high", effort_hours=5.0, tags=["br", "tax", "sped", "accounting"],
        fix_suggestion="Generate SPED Contabil from S/4HANA Universal Journal (ACDOCA) with correct chart of accounts mapping.",
    ),
    SimplificationRule(
        id="BR-018", category="COUNTRY_BR", country="BR",
        pattern=r"\bIPI\b.*TAX|\bIPI\b.*CALC|IMPOSTO.*PRODUTO.*INDUSTRIAL",
        description="IPI (Imposto sobre Produtos Industrializados) — federal excise tax, verify tax procedure TAXBRA conditions",
        severity="medium", effort_hours=3.0, tags=["br", "tax", "ipi"],
        fix_suggestion="Configure IPI condition types in S/4HANA tax procedure TAXBRA. Verify NCM-based rates.",
    ),
    SimplificationRule(
        id="BR-019", category="COUNTRY_BR", country="BR",
        pattern=r"ICMS.*ST\b|ICMS_SUBSTIT|SUBSTITUICAO\s*TRIBUT",
        description="ICMS-ST (substituicao tributaria) — tax substitution for supply chain, verify ST calculation in S/4HANA",
        severity="high", effort_hours=5.0, tags=["br", "tax", "icms", "st"],
        fix_suggestion="Configure ICMS-ST MVA (margem de valor agregado) tables by state and product in S/4HANA.",
    ),
    SimplificationRule(
        id="BR-020", category="COUNTRY_BR", country="BR",
        pattern=r"CNPJ.*VALID|CNPJ_CHECK|CNPJ.*\d{2}\.\d{3}\.\d{3}|CPF.*VALID|CPF_CHECK",
        description="CNPJ/CPF validation algorithms — verify modulo-11 check digit validation in Business Partner master",
        severity="low", effort_hours=1.0, tags=["br", "tax", "validation", "bp"],
        fix_suggestion="Use S/4HANA standard CNPJ (14-digit) and CPF (11-digit) validation in BP tax number fields.",
    ),
    SimplificationRule(
        id="BR-021", category="COUNTRY_BR", country="BR",
        pattern=r"DARF.*GENERAT|DARF_PAYMENT|DARF.*BARCODE|DARF.*BOLETO",
        description="DARF payment document generation — verify barcode/QR code generation for federal tax payments",
        severity="medium", effort_hours=3.0, tags=["br", "tax", "payment", "darf"],
        fix_suggestion="Configure DARF generation with correct revenue codes (codigo de receita) in S/4HANA.",
    ),
    SimplificationRule(
        id="BR-022", category="COUNTRY_BR", country="BR",
        pattern=r"J_1B_NFE|J_1BNFE_|J_1BNFDOC|J_1BNFLIN|J_1BNFTAX",
        description="J_1B NF-e specific tables — verify S/4HANA compatibility for NF-e document/line/tax tables",
        severity="high", effort_hours=4.0, tags=["br", "localization", "nfe", "tables"],
        fix_suggestion="S/4HANA has updated J_1B* tables for NF-e. Verify custom extensions and enhancements.",
        s4_note="2267384",
    ),
]

# =============================================================================
# CANADA ADDITIONAL — expanded to 10+ total Canada rules
# =============================================================================
CANADA_EXTRA_RULES = [
    SimplificationRule(
        id="CA-004", category="COUNTRY_CA", country="CA",
        pattern=r"PST\b.*CANAD|QST\b|PROVINCIAL\s*SALES\s*TAX|TVQ\b|QUEBEC.*TAX",
        description="Provincial sales taxes (PST/QST/TVQ) — verify province-specific tax configuration in S/4HANA",
        severity="medium", effort_hours=4.0, tags=["ca", "tax", "pst", "qst"],
        fix_suggestion="Configure province-specific tax codes: BC PST 7%, SK PST 6%, MB PST 7%, QST 9.975% in S/4HANA.",
    ),
    SimplificationRule(
        id="CA-005", category="COUNTRY_CA", country="CA",
        pattern=r"CPP\b.*CANAD|CANADA\s*PENSION|QPP\b|QUEBEC.*PENSION|CPP_CONTRIB",
        description="CPP/QPP (Canada/Quebec Pension Plan) — verify contribution rates and maximum pensionable earnings",
        severity="medium", effort_hours=3.0, tags=["ca", "hr", "cpp", "statutory"],
        fix_suggestion="Configure CPP2 enhanced contributions and QPP separate rates for Quebec employees in S/4HANA Payroll.",
    ),
    SimplificationRule(
        id="CA-006", category="COUNTRY_CA", country="CA",
        pattern=r"EI\b.*CANAD|EMPLOYMENT\s*INSURANCE.*CA|EI_PREMIUM|QPIP\b",
        description="EI (Employment Insurance) / QPIP (Quebec Parental Insurance) — verify premium calculations",
        severity="medium", effort_hours=2.0, tags=["ca", "hr", "ei", "statutory"],
        fix_suggestion="Configure EI premium rates (employer 1.4x employee) and QPIP for Quebec in S/4HANA Payroll Canada.",
    ),
    SimplificationRule(
        id="CA-007", category="COUNTRY_CA", country="CA",
        pattern=r"SIN\b.*CANAD|SOCIAL\s*INSURANCE\s*NUMBER|SIN.*\d{3}.*\d{3}.*\d{3}",
        description="SIN (Social Insurance Number) handling — verify data privacy and Luhn check validation",
        severity="low", effort_hours=1.0, tags=["ca", "hr", "sin", "privacy"],
        fix_suggestion="Configure SIN validation (9-digit Luhn algorithm) with encryption in S/4HANA HR master data.",
    ),
    SimplificationRule(
        id="CA-008", category="COUNTRY_CA", country="CA",
        pattern=r"T4.*AMEND|T4_SUMMARY|T4A.*SLIP|RL.?1.*SOMMAIRE|RL.?2\b",
        description="T4/T4A/RL-1/RL-2 tax slip filing — verify CRA/Revenu Quebec electronic filing requirements",
        severity="medium", effort_hours=4.0, tags=["ca", "hr", "payroll", "t4"],
        fix_suggestion="Configure T4/T4A Summary and RL-1 Sommaire XML generation for CRA/RQ e-filing in S/4HANA.",
    ),
    SimplificationRule(
        id="CA-009", category="COUNTRY_CA", country="CA",
        pattern=r"ROE\b.*CANAD|RECORD\s*OF\s*EMPLOYMENT|ROE_WEB|SERVICE\s*CANADA.*ROE",
        description="ROE (Record of Employment) — verify electronic ROE submission to Service Canada via ROE Web",
        severity="medium", effort_hours=2.0, tags=["ca", "hr", "roe", "statutory"],
        fix_suggestion="Configure electronic ROE generation and Service Canada ROE Web submission in S/4HANA Payroll.",
    ),
    SimplificationRule(
        id="CA-010", category="COUNTRY_CA", country="CA",
        pattern=r"CEWS\b|CANADA\s*EMERGENCY\s*WAGE|CERS\b|CANADA\s*RECOVERY|CRHP\b",
        description="Canadian COVID subsidies (CEWS/CERS/CRHP) — verify historical claim reconciliation before migration",
        severity="low", effort_hours=2.0, tags=["ca", "hr", "government", "subsidy"],
        fix_suggestion="Archive CEWS/CERS/CRHP historical claims. Ensure CRA reconciliation completed before S/4HANA migration.",
    ),
]

# =============================================================================
# SINGAPORE (SG) — 2 rules
# =============================================================================
SINGAPORE_RULES = [
    SimplificationRule(
        id="SG-001", category="sg_localization", country="SG",
        pattern=r"GST.*SINGAPORE|IRAS\b|INLAND\s*REVENUE.*SG",
        description="Singapore GST / IRAS — verify tax procedure TAXSG in S/4HANA",
        severity="medium", effort_hours=3.0, tags=["sg", "tax", "gst"],
    ),
    SimplificationRule(
        id="SG-002", category="sg_localization", country="SG",
        pattern=r"PEPPOL.*SG|INVO.*NOW|SG\s*E.?INVOICE",
        description="Singapore PEPPOL e-invoicing (InvoiceNow) — verify S/4 Document Compliance",
        severity="medium", effort_hours=4.0, tags=["sg", "einvoice", "peppol"],
    ),
]

# =============================================================================
# SINGAPORE ADDITIONAL — expanded to 8+ total Singapore rules
# =============================================================================
SINGAPORE_EXTRA_RULES = [
    SimplificationRule(
        id="SG-003", category="COUNTRY_SG", country="SG",
        pattern=r"CPF\b.*SINGAPORE|CENTRAL\s*PROVIDENT\s*FUND|CPF_CONTRIB|CPF.*RATE",
        description="CPF (Central Provident Fund) contributions — verify age-based contribution rates (employer+employee)",
        severity="medium", effort_hours=3.0, tags=["sg", "hr", "cpf", "statutory"],
        fix_suggestion="Configure CPF contribution rates by age band (37% total for <=55) in S/4HANA Payroll Singapore.",
    ),
    SimplificationRule(
        id="SG-004", category="COUNTRY_SG", country="SG",
        pattern=r"GST.*9\s*PERCENT.*SG|GST.*SINGAPORE.*RATE|IRAS.*GST.*RETURN|GST\s*F5",
        description="Singapore GST (9% from 2024) — verify GST return (F5/F7/F8) generation for IRAS filing",
        severity="medium", effort_hours=3.0, tags=["sg", "tax", "gst", "iras"],
        fix_suggestion="Update GST rate to 9% and configure GST F5 return generation for IRAS in S/4HANA.",
    ),
    SimplificationRule(
        id="SG-005", category="COUNTRY_SG", country="SG",
        pattern=r"IRAS.*E.?FILING|IRAS.*CORP.*TAX|FORM.*C.?S|IRAS.*DIGITAL",
        description="IRAS corporate tax e-filing — verify Form C-S/C generation for annual corporate income tax return",
        severity="medium", effort_hours=3.0, tags=["sg", "tax", "iras", "corporate"],
        fix_suggestion="Configure corporate tax computation and Form C-S preparation in S/4HANA for IRAS e-filing.",
    ),
    SimplificationRule(
        id="SG-006", category="COUNTRY_SG", country="SG",
        pattern=r"XBRL.*SG|XBRL.*ACRA|ACRA.*FILING|ANNUAL\s*RETURN.*ACRA",
        description="ACRA XBRL filing (Singapore financial statements) — verify XBRL taxonomy-compliant report generation",
        severity="medium", effort_hours=3.0, tags=["sg", "compliance", "xbrl", "acra"],
        fix_suggestion="Configure XBRL financial statement generation per ACRA taxonomy in S/4HANA.",
    ),
    SimplificationRule(
        id="SG-007", category="COUNTRY_SG", country="SG",
        pattern=r"SDL\b.*SG|SKILLS.*DEVELOPMENT.*LEVY|FWL\b|FOREIGN\s*WORKER\s*LEVY",
        description="SDL (Skills Development Levy) / FWL (Foreign Worker Levy) — verify levy calculations in payroll",
        severity="low", effort_hours=2.0, tags=["sg", "hr", "levy", "statutory"],
        fix_suggestion="Configure SDL (0.25% or min $2) and FWL by sector/worker type in S/4HANA Payroll Singapore.",
    ),
    SimplificationRule(
        id="SG-008", category="COUNTRY_SG", country="SG",
        pattern=r"IR8A\b|APPENDIX.*8A|IR8S\b|IRAS.*EMPLOYMENT\s*INCOME|AIS\b.*IRAS",
        description="IR8A/IR8S employment income reporting — verify Auto-Inclusion Scheme (AIS) submission to IRAS",
        severity="medium", effort_hours=3.0, tags=["sg", "hr", "tax", "ir8a"],
        fix_suggestion="Configure IR8A/Appendix 8A/8B/IR8S form generation for IRAS AIS submission in S/4HANA Payroll.",
    ),
]

# =============================================================================
# EU-WIDE RULES — 5 rules
# =============================================================================
EU_RULES = [
    SimplificationRule(
        id="EU-001", category="eu_localization", country="EU",
        pattern=r"INTRASTAT\b|INTRA.?COMMUNITY|INTRA.?EU",
        description="Intrastat / Intra-EU reporting — verify trade statistics in S/4HANA",
        severity="medium", effort_hours=3.0, tags=["eu", "trade", "intrastat"],
    ),
    SimplificationRule(
        id="EU-002", category="eu_localization", country="EU",
        pattern=r"OSS\b|ONE\s*STOP\s*SHOP|IOSS\b|MOSS\b",
        description="EU OSS/IOSS (VAT e-commerce) — verify tax configuration in S/4HANA",
        severity="medium", effort_hours=4.0, tags=["eu", "tax", "vat"],
    ),
    SimplificationRule(
        id="EU-003", category="eu_localization", country="EU",
        pattern=r"\bGDPR\b|DATA\s*PROTECTION.*EU|DSGVO",
        description="GDPR/DSGVO — verify data privacy & Information Lifecycle Management in S/4HANA",
        severity="high", effort_hours=8.0, tags=["eu", "compliance", "privacy"],
    ),
    SimplificationRule(
        id="EU-004", category="eu_localization", country="EU",
        pattern=r"REVERSE\s*CHARGE.*VAT|VAT\s*REVERSE|AUTOLIQUIDATION",
        description="EU Reverse Charge VAT — verify tax configuration in S/4HANA",
        severity="medium", effort_hours=2.0, tags=["eu", "tax", "vat"],
    ),
    SimplificationRule(
        id="EU-005", category="eu_localization", country="EU",
        pattern=r"PEPPOL\b|OPEN\s*PEPPOL|UBL\s*INVOICE",
        description="PEPPOL e-invoicing network — verify S/4HANA Document Compliance",
        severity="medium", effort_hours=4.0, tags=["eu", "einvoice", "peppol"],
    ),
]

# =============================================================================
# EU ADDITIONAL — expanded to 10+ total EU rules
# =============================================================================
EU_EXTRA_RULES = [
    SimplificationRule(
        id="EU-006", category="COUNTRY_EU", country="EU",
        pattern=r"DAC\s*7|DAC7\b|DIGITAL\s*PLATFORM.*REPORT|DIRECTIVE.*2021.*514",
        description="DAC7 (Digital Platform Operators Directive) — verify seller reporting for digital platform operators",
        severity="medium", effort_hours=4.0, tags=["eu", "compliance", "dac7", "digital"],
        fix_suggestion="Implement DAC7 seller data collection and annual reporting to tax authorities in S/4HANA.",
    ),
    SimplificationRule(
        id="EU-007", category="COUNTRY_EU", country="EU",
        pattern=r"CBAM\b|CARBON\s*BORDER.*ADJUST|CBAM.*REPORT|CBAM.*CERTIFICATE",
        description="CBAM (Carbon Border Adjustment Mechanism) — verify embedded emissions reporting for EU imports",
        severity="medium", effort_hours=5.0, tags=["eu", "trade", "cbam", "environment"],
        fix_suggestion="Configure CBAM transitional reporting (from Oct 2023) and certificate purchase tracking in S/4HANA.",
    ),
    SimplificationRule(
        id="EU-008", category="COUNTRY_EU", country="EU",
        pattern=r"SAF.?T\b.*EU|STANDARD\s*AUDIT\s*FILE.*TAX|OECD.*SAF.?T",
        description="SAF-T (Standard Audit File for Tax) EU/OECD — verify country-specific SAF-T generation from S/4HANA",
        severity="medium", effort_hours=4.0, tags=["eu", "compliance", "saft", "audit"],
        fix_suggestion="Configure country-specific SAF-T XML generation (PT, NO, LT, PL, AT variations) from S/4HANA ACDOCA.",
    ),
    SimplificationRule(
        id="EU-009", category="COUNTRY_EU", country="EU",
        pattern=r"VIES\b|VAT\s*INFORMATION\s*EXCHANGE|VIES.*VALID|EC\s*SALES\s*LIST",
        description="VIES (VAT Information Exchange System) — verify intra-EU customer VAT ID validation and EC Sales List",
        severity="medium", effort_hours=2.0, tags=["eu", "tax", "vat", "vies"],
        fix_suggestion="Configure VIES VAT ID validation in S/4HANA BP master and EC Sales List reporting.",
    ),
    SimplificationRule(
        id="EU-010", category="COUNTRY_EU", country="EU",
        pattern=r"VIDA\b|VAT\s*IN.*DIGITAL\s*AGE|EU.*E.?INVOICE.*MANDATE|VIDAR\b",
        description="ViDA (VAT in the Digital Age) — EU-wide e-invoicing and digital reporting mandate (from 2028+)",
        severity="medium", effort_hours=6.0, tags=["eu", "tax", "vida", "einvoice"],
        fix_suggestion="Prepare for ViDA: structured e-invoicing, real-time digital reporting, single VAT registration. Plan S/4HANA readiness.",
    ),
]


# =============================================================================
# AUSTRALIA EXPANDED — 5 more rules (AU_015–AU_019)
# =============================================================================
AUSTRALIA_NEW_RULES = [
    SimplificationRule(
        id="AU-015", category="COUNTRY_AU", country="AU",
        pattern=r"STP.*PHASE\s*2.*REPORT|STP2.*REPORT|STP_PHASE2.*SUBMIT",
        description="STP Phase 2 reporting — expanded income types, country codes, and disaggregation of gross to ATO",
        severity="high", effort_hours=6.0, tags=["au", "hr", "payroll", "stp2", "reporting"],
        fix_suggestion="Configure STP Phase 2 income types (SAW, ETP, LPP) and disaggregated gross reporting in S/4HANA Payroll.",
    ),
    SimplificationRule(
        id="AU-016", category="COUNTRY_AU", country="AU",
        pattern=r"TPAR\b.*ANNUAL|TAXABLE\s*PAYMENT.*ANNUAL.*REPORT|TPAR.*LODGE",
        description="TPAR (Taxable Payments Annual Report) — contractor payment reporting to ATO for building, cleaning, courier, IT",
        severity="medium", effort_hours=3.0, tags=["au", "tax", "tpar", "compliance"],
        fix_suggestion="Configure TPAR extraction for reportable industries (building, cleaning, courier, IT, security) in S/4HANA AP.",
    ),
    SimplificationRule(
        id="AU-017", category="COUNTRY_AU", country="AU",
        pattern=r"FBT\b.*REPORT|FBT.*ANNUAL.*RETURN|FRINGE\s*BENEFIT.*REPORT",
        description="FBT (Fringe Benefits Tax) annual reporting — verify grossed-up taxable values and employee reporting",
        severity="medium", effort_hours=3.0, tags=["au", "tax", "fbt", "compliance"],
        fix_suggestion="Configure FBT annual return with Type 1/Type 2 gross-up, reportable fringe benefits on payment summaries.",
    ),
    SimplificationRule(
        id="AU-018", category="COUNTRY_AU", country="AU",
        pattern=r"WET\b|WINE\s*EQUAL.*TAX|WINE\s*TAX|WET.*REBATE",
        description="Wine Equalisation Tax (WET) — verify 29% wholesale value tax and producer rebate calculation",
        severity="medium", effort_hours=2.0, tags=["au", "tax", "wet", "excise"],
        fix_suggestion="Configure WET condition type at 29% of wholesale value and producer rebate cap in S/4HANA tax procedure TAXAU.",
    ),
    SimplificationRule(
        id="AU-019", category="COUNTRY_AU", country="AU",
        pattern=r"FUEL\s*TAX\s*CREDIT|FTC\b.*AU|FTC.*CLAIM|FUEL.*CREDIT.*BAS",
        description="Fuel Tax Credits (FTC) — verify eligible fuel credit claims on BAS for heavy vehicles and machinery",
        severity="low", effort_hours=2.0, tags=["au", "tax", "fuel", "bas"],
        fix_suggestion="Configure fuel tax credit rates by fuel type and usage in S/4HANA. Include FTC claims in BAS label 7C/7D.",
    ),
]

# =============================================================================
# THAILAND (TH) — 12 rules
# =============================================================================
THAILAND_RULES = [
    SimplificationRule(
        id="TH-001", category="COUNTRY_TH", country="TH",
        pattern=r"J1BTAX\b|TH.*VAT.*OUTPUT|THAI.*OUTPUT\s*TAX|VAT.*7.*PERCENT.*TH",
        description="Thailand VAT 7% output tax — migrate J1BTAX to S/4HANA tax reporting framework",
        severity="high", effort_hours=5.0, tags=["th", "tax", "vat", "output"],
        fix_suggestion="Replace J1BTAX-based output tax logic with S/4HANA tax reporting framework for Thailand 7% VAT.",
    ),
    SimplificationRule(
        id="TH-002", category="COUNTRY_TH", country="TH",
        pattern=r"TH.*INPUT\s*VAT|INPUT.*TAX.*DEDUCT.*TH|VAT.*INPUT.*THAI",
        description="Thailand input VAT deduction rules — verify input tax credit eligibility and timing differences",
        severity="medium", effort_hours=3.0, tags=["th", "tax", "vat", "input"],
        fix_suggestion="Configure input VAT deduction rules in S/4HANA with proper tax code mapping for eligible/ineligible input tax.",
    ),
    SimplificationRule(
        id="TH-003", category="COUNTRY_TH", country="TH",
        pattern=r"WHT.*1\b|WHT.*3\b|WHT.*5\b|WHT.*53\b|WITHHOLDING\s*TAX.*CERT.*TH",
        description="Withholding tax certificates (WHT 1/3/5/53) — verify form generation and Revenue Dept submission",
        severity="high", effort_hours=5.0, tags=["th", "tax", "withholding", "certificate"],
        fix_suggestion="Configure withholding tax types for PND 1/3/5/53 certificates in S/4HANA with auto-generation of WHT forms.",
    ),
    SimplificationRule(
        id="TH-004", category="COUNTRY_TH", country="TH",
        pattern=r"BOI\b.*TH|BOARD.*INVESTMENT.*TH|BOI.*PRIVILEGE|BOI.*TAX\s*EXEMPT",
        description="BOI (Board of Investment) privilege reporting — verify tax incentive tracking and separate accounting",
        severity="medium", effort_hours=4.0, tags=["th", "tax", "boi", "incentive"],
        fix_suggestion="Configure BOI privilege tracking with separate profit centers for BOI/non-BOI activities in S/4HANA.",
    ),
    SimplificationRule(
        id="TH-005", category="COUNTRY_TH", country="TH",
        pattern=r"SSF\b.*TH|SOCIAL\s*SECURITY\s*FUND.*TH|THAI.*SOC.*SEC|SSO.*CONTRIB.*TH",
        description="Social Security Fund (SSF) contributions — verify employer/employee 5% contribution cap",
        severity="medium", effort_hours=3.0, tags=["th", "hr", "social", "statutory"],
        fix_suggestion="Configure Social Security Fund contribution at 5% (capped at 750 THB/month) in S/4HANA Payroll Thailand.",
    ),
    SimplificationRule(
        id="TH-006", category="COUNTRY_TH", country="TH",
        pattern=r"PROVIDENT\s*FUND.*TH|PVD\b.*TH|THAI.*PROVIDENT|PVD.*DEDUCT",
        description="Provident Fund deductions — verify voluntary contribution rates and tax-exempt thresholds",
        severity="medium", effort_hours=2.0, tags=["th", "hr", "provident", "statutory"],
        fix_suggestion="Configure Provident Fund deduction rates (2-15% employee choice) and tax exemption limits in S/4HANA Payroll.",
    ),
    SimplificationRule(
        id="TH-007", category="COUNTRY_TH", country="TH",
        pattern=r"E.?TAX\s*INVOICE.*TH|ETDA\b|THAI.*E.?INVOICE|E.?TAX.*MANDATE.*TH",
        description="e-Tax Invoice mandate (ETDA) — verify electronic tax invoice/receipt generation per Revenue Dept rules",
        severity="high", effort_hours=6.0, tags=["th", "tax", "einvoice", "etda"],
        fix_suggestion="Implement ETDA-compliant e-Tax Invoice with XML signing and digital certificate in S/4HANA Document Compliance.",
    ),
    SimplificationRule(
        id="TH-008", category="COUNTRY_TH", country="TH",
        pattern=r"PND\s*1\b|PND\s*3\b|PND\s*53\b|REVENUE\s*DEPT.*FILING.*TH",
        description="Revenue Department filing (PND 1/3/53) — verify monthly/annual withholding tax return submission",
        severity="high", effort_hours=4.0, tags=["th", "tax", "filing", "pnd"],
        fix_suggestion="Configure PND 1 (employee), PND 3 (individual), PND 53 (company) withholding returns in S/4HANA reporting.",
    ),
    SimplificationRule(
        id="TH-009", category="COUNTRY_TH", country="TH",
        pattern=r"EXCISE\s*TAX.*TH|THAI.*EXCISE|EXCISE.*DEPT.*TH",
        description="Thailand excise tax reporting — verify excise duty calculation for regulated goods",
        severity="medium", effort_hours=3.0, tags=["th", "tax", "excise"],
        fix_suggestion="Configure excise tax condition types for regulated products (alcohol, tobacco, fuel) in S/4HANA tax procedure.",
    ),
    SimplificationRule(
        id="TH-010", category="COUNTRY_TH", country="TH",
        pattern=r"THAI\s*GAAP|TFRS\b|TAS\b.*ACCOUNT|GAAP.*TFRS.*CONVERT",
        description="Thai GAAP to TFRS (Thai Financial Reporting Standards) conversion — verify dual reporting setup",
        severity="medium", effort_hours=5.0, tags=["th", "accounting", "tfrs", "gaap"],
        fix_suggestion="Configure parallel ledger for Thai GAAP to TFRS conversion in S/4HANA with ACDOCA-based dual reporting.",
    ),
    SimplificationRule(
        id="TH-011", category="COUNTRY_TH", country="TH",
        pattern=r"CUSTOMS\s*DUTY.*TH|THAI.*CUSTOMS|IMPORT.*DUTY.*TH|TH.*TARIFF",
        description="Thailand customs duty reporting — verify import/export duty calculation and Customs Dept integration",
        severity="medium", effort_hours=3.0, tags=["th", "trade", "customs", "duty"],
        fix_suggestion="Configure customs duty condition types and tariff classification for Thai Customs integration in S/4HANA GTS.",
    ),
    SimplificationRule(
        id="TH-012", category="COUNTRY_TH", country="TH",
        pattern=r"THB.*ROUND|THAI\s*BAHT.*ROUND|SATANG.*ROUND|TH.*CURRENCY.*ROUND",
        description="Thai baht rounding rules — verify satang rounding and currency decimal handling",
        severity="low", effort_hours=1.0, tags=["th", "fi", "currency", "rounding"],
        fix_suggestion="Configure Thai baht rounding rules (2 decimal places for satang) in S/4HANA currency settings.",
    ),
]

# =============================================================================
# INDONESIA (ID) — 12 rules
# =============================================================================
INDONESIA_RULES = [
    SimplificationRule(
        id="ID-001", category="COUNTRY_ID", country="ID",
        pattern=r"E.?FAKTUR\b|ELECTRONIC\s*TAX\s*INVOICE.*ID|FAKTUR\s*PAJAK",
        description="e-Faktur (electronic tax invoice) — verify DJP-compliant e-Faktur generation and NSFP numbering",
        severity="high", effort_hours=6.0, tags=["id", "tax", "efaktur", "einvoice"],
        fix_suggestion="Configure e-Faktur integration with DJP for tax invoice generation, NSFP number allocation in S/4HANA.",
    ),
    SimplificationRule(
        id="ID-002", category="COUNTRY_ID", country="ID",
        pattern=r"PPH\s*21\b|PPH21\b|EMPLOYEE\s*INCOME\s*TAX.*ID|PAJAK.*PENGHASILAN.*21",
        description="PPh 21 (employee income tax) — verify progressive rate calculation and monthly reporting",
        severity="high", effort_hours=5.0, tags=["id", "hr", "payroll", "pph21"],
        fix_suggestion="Configure PPh 21 progressive tax brackets (5-35%) and TER method in S/4HANA Payroll Indonesia.",
    ),
    SimplificationRule(
        id="ID-003", category="COUNTRY_ID", country="ID",
        pattern=r"PPH\s*23\b|PPH23\b|WITHHOLDING.*SERVICE.*ID|PAJAK.*23",
        description="PPh 23 (withholding on services) — verify 2% services / 15% dividends-interest withholding rates",
        severity="medium", effort_hours=3.0, tags=["id", "tax", "withholding", "pph23"],
        fix_suggestion="Configure PPh 23 withholding tax types (2% services, 15% dividends/interest/royalties) in S/4HANA.",
    ),
    SimplificationRule(
        id="ID-004", category="COUNTRY_ID", country="ID",
        pattern=r"PPH\s*26\b|PPH26\b|NON.?RESIDENT.*WHT.*ID|PAJAK.*26",
        description="PPh 26 (non-resident withholding tax) — verify 20% default rate and treaty relief application",
        severity="medium", effort_hours=3.0, tags=["id", "tax", "withholding", "pph26", "nonresident"],
        fix_suggestion="Configure PPh 26 at 20% default with DGT-1 form for tax treaty reduced rates in S/4HANA withholding tax.",
    ),
    SimplificationRule(
        id="ID-005", category="COUNTRY_ID", country="ID",
        pattern=r"BPJS\s*KESEHATAN|BPJS.*HEALTH|JKN\b.*ID|HEALTH\s*INSURANCE.*ID",
        description="BPJS Kesehatan (national health insurance) — verify employer 4% and employee 1% contribution",
        severity="medium", effort_hours=3.0, tags=["id", "hr", "bpjs", "health"],
        fix_suggestion="Configure BPJS Kesehatan contributions (4% employer, 1% employee, capped at salary ceiling) in S/4HANA Payroll.",
    ),
    SimplificationRule(
        id="ID-006", category="COUNTRY_ID", country="ID",
        pattern=r"BPJS\s*KETENAGAKERJAAN|BPJS.*EMPLOY|JHT\b|JKK\b|JKM\b|JP\b.*BPJS",
        description="BPJS Ketenagakerjaan (employment insurance) — verify JHT/JKK/JKM/JP contribution calculations",
        severity="medium", effort_hours=4.0, tags=["id", "hr", "bpjs", "employment"],
        fix_suggestion="Configure BPJS Ketenagakerjaan: JHT (5.7%), JKK (0.24-1.74%), JKM (0.3%), JP (3%) in S/4HANA Payroll.",
    ),
    SimplificationRule(
        id="ID-007", category="COUNTRY_ID", country="ID",
        pattern=r"PPN\b.*11|VAT.*11.*PERCENT.*ID|PPN\b.*CALC|PAJAK.*PERTAMBAHAN.*NILAI",
        description="VAT (PPN) 11% calculation — verify standard rate and exempt/non-taxable supply classification",
        severity="high", effort_hours=4.0, tags=["id", "tax", "vat", "ppn"],
        fix_suggestion="Configure PPN at 11% standard rate with proper exempt and non-taxable supply codes in S/4HANA tax procedure.",
    ),
    SimplificationRule(
        id="ID-008", category="COUNTRY_ID", country="ID",
        pattern=r"PPNBM\b|PPnBM\b|LUXURY.*GOODS.*TAX.*ID|SALES.*TAX.*LUXURY",
        description="PPnBM (Luxury Goods Sales Tax) — verify luxury goods tax rates (10-200%) on applicable items",
        severity="medium", effort_hours=3.0, tags=["id", "tax", "ppnbm", "luxury"],
        fix_suggestion="Configure PPnBM condition types with tiered rates by goods category in S/4HANA tax procedure for Indonesia.",
    ),
    SimplificationRule(
        id="ID-009", category="COUNTRY_ID", country="ID",
        pattern=r"DGT\b.*CUSTOMS.*ID|DJBC\b|CUSTOMS.*INTEGR.*ID|BEA\s*CUKAI",
        description="DGT/DJBC customs integration — verify import duty calculation and Bea Cukai system interface",
        severity="medium", effort_hours=4.0, tags=["id", "trade", "customs", "djbc"],
        fix_suggestion="Configure customs duty integration with DJBC (Bea Cukai) for import/export declarations in S/4HANA GTS.",
    ),
    SimplificationRule(
        id="ID-010", category="COUNTRY_ID", country="ID",
        pattern=r"TRANSFER\s*PRICING.*ID|TP.*DOC.*ID|PMK.*213|MASTER\s*FILE.*LOCAL\s*FILE.*ID",
        description="Transfer pricing documentation (PMK-213) — verify master file, local file, and CbCR preparation",
        severity="medium", effort_hours=5.0, tags=["id", "tax", "transfer_pricing", "compliance"],
        fix_suggestion="Configure transfer pricing documentation (master file, local file, CbCR) extraction from S/4HANA for DGT filing.",
    ),
    SimplificationRule(
        id="ID-011", category="COUNTRY_ID", country="ID",
        pattern=r"IDR.*ROUND|RUPIAH.*ROUND|ID.*CURRENCY.*ROUND|IDR.*DECIMAL",
        description="IDR currency rounding — verify Indonesian Rupiah zero-decimal rounding rules",
        severity="low", effort_hours=1.0, tags=["id", "fi", "currency", "rounding"],
        fix_suggestion="Configure IDR with zero decimal places in S/4HANA currency settings. Verify rounding in tax calculations.",
    ),
    SimplificationRule(
        id="ID-012", category="COUNTRY_ID", country="ID",
        pattern=r"E.?BUPOT\b|ELECTRONIC.*BUKTI\s*POTONG|EBUPOT.*REPORT|WITHHOLDING.*REPORT.*ID",
        description="e-Bupot (electronic withholding tax slip) — verify e-Bupot generation for PPh 23/26 reporting to DJP",
        severity="high", effort_hours=4.0, tags=["id", "tax", "ebupot", "withholding"],
        fix_suggestion="Configure e-Bupot generation for PPh 23/26 withholding slips with DJP online submission in S/4HANA.",
    ),
]

# =============================================================================
# MALAYSIA (MY) — 10 rules
# =============================================================================
MALAYSIA_RULES = [
    SimplificationRule(
        id="MY-001", category="COUNTRY_MY", country="MY",
        pattern=r"SST.*SALES\s*TAX.*MY|SALES\s*TAX.*10.*MY|SST.*10\s*PERCENT",
        description="SST Sales Tax 10% — verify sales tax registration, taxable goods classification, and SST-02 return",
        severity="high", effort_hours=4.0, tags=["my", "tax", "sst", "sales"],
        fix_suggestion="Configure SST Sales Tax at 10% for taxable goods with SST-02 return generation in S/4HANA tax procedure.",
    ),
    SimplificationRule(
        id="MY-002", category="COUNTRY_MY", country="MY",
        pattern=r"SST.*SERVICE\s*TAX.*MY|SERVICE\s*TAX.*8.*MY|SST.*8\s*PERCENT",
        description="SST Service Tax 8% — verify taxable service classification and SST-02 return for services",
        severity="high", effort_hours=4.0, tags=["my", "tax", "sst", "service"],
        fix_suggestion="Configure SST Service Tax at 8% for taxable services with proper group classification in S/4HANA.",
    ),
    SimplificationRule(
        id="MY-003", category="COUNTRY_MY", country="MY",
        pattern=r"MYINVOIS\b|MY.*E.?INVOICE.*MANDATE|LHDN.*E.?INVOICE|E.?INVOICE.*MY",
        description="e-Invoice mandate (MyInvois/LHDN) — verify electronic invoice compliance with IRBM requirements",
        severity="high", effort_hours=6.0, tags=["my", "tax", "einvoice", "myinvois"],
        fix_suggestion="Implement MyInvois e-Invoice integration with LHDN portal for B2B/B2C invoice validation in S/4HANA.",
    ),
    SimplificationRule(
        id="MY-004", category="COUNTRY_MY", country="MY",
        pattern=r"EPF\b.*MY|KWSP\b|EMPLOYEE.*PROVIDENT.*FUND.*MY|EPF.*CONTRIB",
        description="EPF (KWSP) contributions — verify employer 12-13% and employee 11% statutory contribution rates",
        severity="medium", effort_hours=3.0, tags=["my", "hr", "epf", "statutory"],
        fix_suggestion="Configure EPF/KWSP contribution rates (employer 12/13%, employee 11%) with age-based tiers in S/4HANA Payroll.",
    ),
    SimplificationRule(
        id="MY-005", category="COUNTRY_MY", country="MY",
        pattern=r"SOCSO\b|PERKESO\b|SOCIAL\s*SECURITY.*MY|SOCSO.*CONTRIB",
        description="SOCSO (PERKESO) contributions — verify Employment Injury and Invalidity Pension scheme rates",
        severity="medium", effort_hours=3.0, tags=["my", "hr", "socso", "statutory"],
        fix_suggestion="Configure SOCSO contribution tables for Employment Injury (1.75%) and Invalidity Pension schemes in S/4HANA.",
    ),
    SimplificationRule(
        id="MY-006", category="COUNTRY_MY", country="MY",
        pattern=r"PCB\b.*MY|MTD\b.*MY|POTONGAN\s*CUKAI\s*BULANAN|MONTHLY\s*TAX\s*DEDUCT.*MY",
        description="PCB (Potongan Cukai Bulanan) monthly tax deductions — verify MTD calculation per LHDN schedule",
        severity="high", effort_hours=4.0, tags=["my", "hr", "payroll", "pcb"],
        fix_suggestion="Configure PCB/MTD monthly tax deduction calculation using LHDN computerised formula in S/4HANA Payroll.",
    ),
    SimplificationRule(
        id="MY-007", category="COUNTRY_MY", country="MY",
        pattern=r"EIS\b.*MY|EMPLOYMENT\s*INSURANCE.*MY|SIP\b.*MY|PRIHATIN.*EIS",
        description="EIS (Employment Insurance System) — verify employer 0.2% and employee 0.2% contribution",
        severity="medium", effort_hours=2.0, tags=["my", "hr", "eis", "statutory"],
        fix_suggestion="Configure EIS/SIP contribution at 0.2% each for employer and employee in S/4HANA Payroll Malaysia.",
    ),
    SimplificationRule(
        id="MY-008", category="COUNTRY_MY", country="MY",
        pattern=r"LHDN\b.*ANNUAL|LHDN.*REPORT|IRBM.*FILING|ANNUAL.*RETURN.*MY",
        description="LHDN (IRBM) annual tax reporting — verify Form E, Form EA/EC, and CP8D submission",
        severity="high", effort_hours=4.0, tags=["my", "tax", "lhdn", "filing"],
        fix_suggestion="Configure LHDN annual reporting (Form E employer return, EA/EC employee statements, CP8D) in S/4HANA.",
    ),
    SimplificationRule(
        id="MY-009", category="COUNTRY_MY", country="MY",
        pattern=r"HRDF\b|HRD\s*CORP|PSMB\b|TRAINING\s*LEVY.*MY|HRDF.*LEVY",
        description="HRDF (HRD Corp) training levy — verify 1% employer levy for companies with 10+ employees",
        severity="low", effort_hours=2.0, tags=["my", "hr", "hrdf", "levy"],
        fix_suggestion="Configure HRDF training levy at 1% of monthly wages for eligible employers in S/4HANA Payroll Malaysia.",
    ),
    SimplificationRule(
        id="MY-010", category="COUNTRY_MY", country="MY",
        pattern=r"CUSTOMS.*DUTY.*MY|EXCISE.*DUTY.*MY|RMCD\b|JKDM\b|MY.*TARIFF",
        description="Malaysia customs and excise duties — verify RMCD/JKDM duty calculation and declaration",
        severity="medium", effort_hours=3.0, tags=["my", "trade", "customs", "excise"],
        fix_suggestion="Configure customs/excise duty condition types and RMCD (JKDM) integration in S/4HANA GTS for Malaysia.",
    ),
]

# =============================================================================
# PHILIPPINES (PH) — 10 rules
# =============================================================================
PHILIPPINES_RULES = [
    SimplificationRule(
        id="PH-001", category="COUNTRY_PH", country="PH",
        pattern=r"BIR.*E.?INVOICE|CAS\b.*PH|EIS\b.*BIR|COMPUTERIZED.*ACCOUNTING.*PH",
        description="BIR e-invoicing (CAS/EIS) — verify Computerized Accounting System accreditation and e-invoice generation",
        severity="high", effort_hours=6.0, tags=["ph", "tax", "einvoice", "bir"],
        fix_suggestion="Configure BIR-accredited CAS/EIS e-invoicing with proper invoice numbering and PTU permits in S/4HANA.",
    ),
    SimplificationRule(
        id="PH-002", category="COUNTRY_PH", country="PH",
        pattern=r"EWT\b.*PH|EXPANDED\s*WITHHOLDING.*TAX|EWT.*RATE.*PH",
        description="Expanded Withholding Tax (EWT) — verify creditable withholding tax rates (1-15%) by income type",
        severity="medium", effort_hours=4.0, tags=["ph", "tax", "withholding", "ewt"],
        fix_suggestion="Configure EWT rates by income payment type (1-15% per RR 11-2018) in S/4HANA withholding tax configuration.",
    ),
    SimplificationRule(
        id="PH-003", category="COUNTRY_PH", country="PH",
        pattern=r"FWT\b.*PH|FINAL\s*WITHHOLDING.*TAX.*PH|FWT.*RATE.*PH",
        description="Final Withholding Tax (FWT) — verify non-creditable final tax on passive income (dividends, interest)",
        severity="medium", effort_hours=3.0, tags=["ph", "tax", "withholding", "fwt"],
        fix_suggestion="Configure FWT rates for passive income (20% interest, 10% dividends to citizens) in S/4HANA withholding tax.",
    ),
    SimplificationRule(
        id="PH-004", category="COUNTRY_PH", country="PH",
        pattern=r"SSS\b.*PH|SOCIAL\s*SECURITY\s*SYSTEM.*PH|SSS.*CONTRIB.*PH",
        description="SSS (Social Security System) contributions — verify employer and employee contribution table",
        severity="medium", effort_hours=3.0, tags=["ph", "hr", "sss", "statutory"],
        fix_suggestion="Configure SSS contribution table with monthly salary credit brackets in S/4HANA Payroll Philippines.",
    ),
    SimplificationRule(
        id="PH-005", category="COUNTRY_PH", country="PH",
        pattern=r"PHILHEALTH\b|PHIL.*HEALTH.*CONTRIB|PHILHEALTH.*PH",
        description="PhilHealth contributions — verify premium rate sharing between employer and employee",
        severity="medium", effort_hours=2.0, tags=["ph", "hr", "philhealth", "statutory"],
        fix_suggestion="Configure PhilHealth premium rate (5% shared equally) with income ceiling in S/4HANA Payroll Philippines.",
    ),
    SimplificationRule(
        id="PH-006", category="COUNTRY_PH", country="PH",
        pattern=r"PAG.?IBIG\b|HDMF\b|HOME.*DEVELOP.*MUTUAL.*FUND|PAGIBIG.*CONTRIB",
        description="Pag-IBIG (HDMF) Fund contributions — verify mandatory savings contribution (employer + employee)",
        severity="medium", effort_hours=2.0, tags=["ph", "hr", "pagibig", "statutory"],
        fix_suggestion="Configure Pag-IBIG Fund contribution (2% employee, 2% employer, capped at 5K salary) in S/4HANA Payroll.",
    ),
    SimplificationRule(
        id="PH-007", category="COUNTRY_PH", country="PH",
        pattern=r"VAT.*12.*PH|PH.*VAT.*COMPUTE|OUTPUT.*VAT.*PH|INPUT.*VAT.*PH",
        description="VAT 12% computation — verify output/input VAT calculation, zero-rated, and VAT-exempt transactions",
        severity="high", effort_hours=4.0, tags=["ph", "tax", "vat"],
        fix_suggestion="Configure Philippine VAT at 12% with proper zero-rated and exempt supply classification in S/4HANA tax procedure.",
    ),
    SimplificationRule(
        id="PH-008", category="COUNTRY_PH", country="PH",
        pattern=r"PERCENTAGE\s*TAX.*PH|NON.?VAT.*TAX.*PH|3.*PERCENT.*TAX.*PH",
        description="Percentage tax (non-VAT registered) — verify 3% gross receipts tax for non-VAT taxpayers",
        severity="medium", effort_hours=2.0, tags=["ph", "tax", "percentage"],
        fix_suggestion="Configure 3% percentage tax for non-VAT registered taxpayers under threshold in S/4HANA tax procedure.",
    ),
    SimplificationRule(
        id="PH-009", category="COUNTRY_PH", country="PH",
        pattern=r"TRAIN\s*LAW|RA\s*10963|TRAIN.*COMPLIANCE|TAX\s*REFORM.*PH",
        description="TRAIN law (RA 10963) compliance — verify updated income tax brackets, excise taxes, and VAT exemptions",
        severity="high", effort_hours=5.0, tags=["ph", "tax", "train", "reform"],
        fix_suggestion="Update income tax brackets per TRAIN law (0-35% progressive), revised excise taxes in S/4HANA configuration.",
    ),
    SimplificationRule(
        id="PH-010", category="COUNTRY_PH", country="PH",
        pattern=r"BIR\s*2307\b|FORM\s*2307|CERTIFICATE.*CREDITABLE.*TAX.*PH",
        description="BIR Form 2307 (Certificate of Creditable Tax Withheld) — verify issuance and tracking of WHT certificates",
        severity="medium", effort_hours=3.0, tags=["ph", "tax", "withholding", "2307"],
        fix_suggestion="Configure BIR 2307 certificate generation for creditable withholding tax with quarterly reporting in S/4HANA.",
    ),
]

# =============================================================================
# VIETNAM (VN) — 10 rules
# =============================================================================
VIETNAM_RULES = [
    SimplificationRule(
        id="VN-001", category="COUNTRY_VN", country="VN",
        pattern=r"HOA\s*DON\s*DIEN\s*TU|E.?INVOICE.*VN|VN.*E.?INVOICE.*MANDATE|HDDT\b",
        description="e-Invoice mandate (Hoa don dien tu) — verify electronic invoice generation per Decree 123/2020",
        severity="high", effort_hours=6.0, tags=["vn", "tax", "einvoice", "hddt"],
        fix_suggestion="Implement Hoa don dien tu (e-Invoice) with GDT registration and XML format per Decree 123 in S/4HANA.",
    ),
    SimplificationRule(
        id="VN-002", category="COUNTRY_VN", country="VN",
        pattern=r"PIT\b.*VN|PERSONAL\s*INCOME\s*TAX.*VN|VN.*PIT.*PROGRESSIVE|THUE\s*TNCN",
        description="PIT progressive rates (5-35%) — verify Vietnamese personal income tax bracket calculation",
        severity="medium", effort_hours=4.0, tags=["vn", "hr", "payroll", "pit"],
        fix_suggestion="Configure PIT progressive rates (5-35% in 7 brackets) with resident/non-resident rules in S/4HANA Payroll.",
    ),
    SimplificationRule(
        id="VN-003", category="COUNTRY_VN", country="VN",
        pattern=r"BHXH\b|SOCIAL\s*INSURANCE.*VN|VN.*SOC.*INSUR|BAO\s*HIEM\s*XA\s*HOI",
        description="Social Insurance (BHXH) — verify employer 17.5% and employee 8% contribution on salary",
        severity="medium", effort_hours=3.0, tags=["vn", "hr", "bhxh", "statutory"],
        fix_suggestion="Configure BHXH contributions (17.5% employer, 8% employee on capped salary) in S/4HANA Payroll Vietnam.",
    ),
    SimplificationRule(
        id="VN-004", category="COUNTRY_VN", country="VN",
        pattern=r"BHYT\b|HEALTH\s*INSURANCE.*VN|VN.*HEALTH.*INSUR|BAO\s*HIEM\s*Y\s*TE",
        description="Health Insurance (BHYT) — verify employer 3% and employee 1.5% contribution calculation",
        severity="medium", effort_hours=2.0, tags=["vn", "hr", "bhyt", "statutory"],
        fix_suggestion="Configure BHYT health insurance contributions (3% employer, 1.5% employee) in S/4HANA Payroll Vietnam.",
    ),
    SimplificationRule(
        id="VN-005", category="COUNTRY_VN", country="VN",
        pattern=r"BHTN\b|UNEMPLOYMENT\s*INSURANCE.*VN|VN.*UNEMPL.*INSUR|BAO\s*HIEM\s*THAT\s*NGHIEP",
        description="Unemployment Insurance (BHTN) — verify 1% employer and 1% employee contribution",
        severity="medium", effort_hours=2.0, tags=["vn", "hr", "bhtn", "statutory"],
        fix_suggestion="Configure BHTN unemployment insurance (1% employer, 1% employee on capped salary) in S/4HANA Payroll.",
    ),
    SimplificationRule(
        id="VN-006", category="COUNTRY_VN", country="VN",
        pattern=r"FCT\b.*VN|FOREIGN\s*CONTRACTOR\s*TAX|VN.*CONTRACTOR.*TAX|THUE\s*NHA\s*THAU",
        description="Foreign Contractor Tax (FCT) — verify deemed VAT and CIT withholding on foreign contractor payments",
        severity="high", effort_hours=4.0, tags=["vn", "tax", "fct", "withholding"],
        fix_suggestion="Configure FCT with deemed VAT (1-5%) and CIT (1-10%) rates by service type in S/4HANA withholding tax.",
    ),
    SimplificationRule(
        id="VN-007", category="COUNTRY_VN", country="VN",
        pattern=r"VAT.*10.*VN|VN.*VAT.*CALC|GTGT\b|THUE\s*GIA\s*TRI\s*GIA\s*TANG",
        description="VAT 10% calculation — verify standard rate, 5% reduced rate, and exempt supply classification",
        severity="high", effort_hours=4.0, tags=["vn", "tax", "vat"],
        fix_suggestion="Configure Vietnam VAT rates (10% standard, 5% reduced, 0% export, exempt) in S/4HANA tax procedure.",
    ),
    SimplificationRule(
        id="VN-008", category="COUNTRY_VN", country="VN",
        pattern=r"CIT.*20.*VN|VN.*CORPORATE\s*TAX|THUE\s*TNDN|CIT.*VN.*CALC",
        description="CIT 20% corporate income tax — verify standard rate and incentive zone/sector reduced rates",
        severity="medium", effort_hours=3.0, tags=["vn", "tax", "cit", "corporate"],
        fix_suggestion="Configure CIT at 20% standard with preferential rates (10-17%) for incentive zones/sectors in S/4HANA.",
    ),
    SimplificationRule(
        id="VN-009", category="COUNTRY_VN", country="VN",
        pattern=r"DECREE\s*132|TRANSFER\s*PRICING.*VN|TP.*DOC.*VN|VN.*TRANSFER.*PRICE",
        description="Transfer pricing (Decree 132/2020) — verify related-party transaction documentation and reporting",
        severity="medium", effort_hours=5.0, tags=["vn", "tax", "transfer_pricing", "compliance"],
        fix_suggestion="Configure transfer pricing documentation per Decree 132 (local file, master file, CbCR) from S/4HANA data.",
    ),
    SimplificationRule(
        id="VN-010", category="COUNTRY_VN", country="VN",
        pattern=r"VND.*ROUND|DONG.*ROUND|VN.*CURRENCY.*ROUND|VND.*DECIMAL",
        description="VND rounding rules — verify Vietnamese Dong zero-decimal rounding in tax and financial calculations",
        severity="low", effort_hours=1.0, tags=["vn", "fi", "currency", "rounding"],
        fix_suggestion="Configure VND with zero decimal places in S/4HANA currency settings. Verify rounding in all tax calculations.",
    ),
]

# =============================================================================
# TAIWAN (TW) — 10 rules
# =============================================================================
TAIWAN_RULES = [
    SimplificationRule(
        id="TW-001", category="COUNTRY_TW", country="TW",
        pattern=r"GUI\b.*TW|UNIFORM\s*INVOICE.*TW|GOVERNMENT\s*UNIFORM\s*INVOICE|GUI.*NUMBER",
        description="GUI (Government Uniform Invoice) — verify invoice numbering, lottery participation, and MoF reporting",
        severity="high", effort_hours=5.0, tags=["tw", "tax", "gui", "invoice"],
        fix_suggestion="Configure GUI invoice numbering with MoF-allocated number ranges and bimonthly lottery integration in S/4HANA.",
    ),
    SimplificationRule(
        id="TW-002", category="COUNTRY_TW", country="TW",
        pattern=r"VAT.*5.*TW|TW.*VAT.*FILING|BUSINESS\s*TAX.*TW|YING\s*YE\s*SHUI",
        description="VAT 5% filing — verify bimonthly business tax return (401/403) and input/output tax matching",
        severity="high", effort_hours=4.0, tags=["tw", "tax", "vat"],
        fix_suggestion="Configure Taiwan business tax at 5% VAT with bimonthly 401/403 return generation in S/4HANA tax procedure.",
    ),
    SimplificationRule(
        id="TW-003", category="COUNTRY_TW", country="TW",
        pattern=r"NHI\b.*TW|NATIONAL\s*HEALTH\s*INSURANCE.*TW|NHI.*CONTRIB|NHIA\b",
        description="NHI (National Health Insurance) — verify employer, employee, and government contribution sharing",
        severity="medium", effort_hours=3.0, tags=["tw", "hr", "nhi", "statutory"],
        fix_suggestion="Configure NHI premium sharing (employer 60%, employee 30%, government 10%) by category in S/4HANA Payroll.",
    ),
    SimplificationRule(
        id="TW-004", category="COUNTRY_TW", country="TW",
        pattern=r"LABOR\s*INSURANCE.*TW|TW.*LI\b.*INSUR|LAOBAO\b|LI.*PREMIUM.*TW",
        description="Labor Insurance (LI) — verify employer/employee premium contribution by category and salary bracket",
        severity="medium", effort_hours=3.0, tags=["tw", "hr", "labor_insurance", "statutory"],
        fix_suggestion="Configure Labor Insurance premium rates with employer/employee/government sharing ratios in S/4HANA Payroll.",
    ),
    SimplificationRule(
        id="TW-005", category="COUNTRY_TW", country="TW",
        pattern=r"LABOR\s*PENSION.*TW|NEW\s*LABOR\s*PENSION|OLD\s*LABOR\s*PENSION|TW.*PENSION.*6",
        description="Labor Pension (new/old system) — verify 6% employer contribution (new) or defined benefit (old) scheme",
        severity="medium", effort_hours=4.0, tags=["tw", "hr", "pension", "statutory"],
        fix_suggestion="Configure new Labor Pension (6% employer mandatory) and voluntary employee contribution in S/4HANA Payroll.",
    ),
    SimplificationRule(
        id="TW-006", category="COUNTRY_TW", country="TW",
        pattern=r"XBRL\b.*TW|TW.*FINANCIAL\s*REPORT.*XBRL|TWSE.*XBRL|MOPS.*REPORT",
        description="XBRL financial reporting — verify TWSE/MOPS mandated XBRL filing for listed companies",
        severity="medium", effort_hours=5.0, tags=["tw", "accounting", "xbrl", "reporting"],
        fix_suggestion="Configure XBRL taxonomy mapping for TWSE/MOPS financial statement filing from S/4HANA general ledger.",
    ),
    SimplificationRule(
        id="TW-007", category="COUNTRY_TW", country="TW",
        pattern=r"WHT.*DIVIDEND.*TW|WHT.*INTEREST.*TW|TW.*WITHHOLDING.*TAX|TW.*WHT.*RATE",
        description="WHT on dividends/interest — verify 21% resident and 21% non-resident withholding tax rates",
        severity="medium", effort_hours=3.0, tags=["tw", "tax", "withholding"],
        fix_suggestion="Configure withholding tax types for dividends and interest with resident/non-resident rates in S/4HANA.",
    ),
    SimplificationRule(
        id="TW-008", category="COUNTRY_TW", country="TW",
        pattern=r"E.?INVOICE.*TW|TW.*E.?INVOICE.*B2B|TW.*E.?INVOICE.*B2C|TURNKEY.*INVOICE.*TW",
        description="e-Invoice B2B/B2C — verify MoF Turnkey e-invoice platform integration for B2B and B2C transactions",
        severity="high", effort_hours=5.0, tags=["tw", "tax", "einvoice", "turnkey"],
        fix_suggestion="Configure e-Invoice Turnkey integration for B2B (exchange) and B2C (cloud) invoice types in S/4HANA.",
    ),
    SimplificationRule(
        id="TW-009", category="COUNTRY_TW", country="TW",
        pattern=r"FORM\s*401|FORM\s*403|BUSINESS\s*TAX\s*RETURN.*TW|BIMONTHLY.*TAX.*TW",
        description="Business tax filing (Form 401/403) — verify bimonthly VAT return with input/output tax reconciliation",
        severity="high", effort_hours=4.0, tags=["tw", "tax", "filing", "vat"],
        fix_suggestion="Configure Form 401 (regular) or 403 (special) bimonthly business tax return generation in S/4HANA.",
    ),
    SimplificationRule(
        id="TW-010", category="COUNTRY_TW", country="TW",
        pattern=r"EMPLOYMENT\s*GOLD.*INSUR.*TW|EGI\b.*TW|EMPLOYMENT.*INSURANCE.*TW|JIUYE\s*BAOXIAN",
        description="Employment Gold Insurance — verify employment insurance premium for involuntary unemployment benefit",
        severity="medium", effort_hours=2.0, tags=["tw", "hr", "employment_insurance", "statutory"],
        fix_suggestion="Configure Employment Insurance premium (1% shared employer/employee/government) in S/4HANA Payroll Taiwan.",
    ),
]

# =============================================================================
# HONG KONG (HK) — 10 rules
# =============================================================================
HONG_KONG_RULES = [
    SimplificationRule(
        id="HK-001", category="COUNTRY_HK", country="HK",
        pattern=r"PROFITS\s*TAX.*HK|HK.*PROFITS.*TAX|16\.5.*PROFITS|8\.25.*PROFITS|TWO.?TIER.*TAX.*HK",
        description="Profits Tax 16.5%/8.25% — verify two-tier profits tax (8.25% on first 2M HKD, 16.5% thereafter)",
        severity="high", effort_hours=4.0, tags=["hk", "tax", "profits"],
        fix_suggestion="Configure two-tier profits tax (8.25% first 2M HKD, 16.5% remainder) in S/4HANA tax configuration.",
    ),
    SimplificationRule(
        id="HK-002", category="COUNTRY_HK", country="HK",
        pattern=r"MPF\b.*HK|MANDATORY\s*PROVIDENT\s*FUND|MPF.*CONTRIB|MPFA\b",
        description="MPF (Mandatory Provident Fund) contributions — verify 5% employer and 5% employee (capped at 1,500 HKD/month)",
        severity="high", effort_hours=4.0, tags=["hk", "hr", "mpf", "statutory"],
        fix_suggestion="Configure MPF at 5% employer/employee with max relevant income cap (30,000 HKD/month) in S/4HANA Payroll.",
    ),
    SimplificationRule(
        id="HK-003", category="COUNTRY_HK", country="HK",
        pattern=r"SALARIES\s*TAX.*HK|HK.*SALARIES\s*TAX|PROGRESSIVE.*RATE.*HK|STANDARD.*RATE.*15.*HK",
        description="Salaries Tax computation — verify progressive rates (2-17%) vs standard rate (15%) assessment",
        severity="medium", effort_hours=3.0, tags=["hk", "tax", "salaries"],
        fix_suggestion="Configure Salaries Tax with progressive rates (2/6/10/14/17%) and 15% standard rate comparison in S/4HANA.",
    ),
    SimplificationRule(
        id="HK-004", category="COUNTRY_HK", country="HK",
        pattern=r"PROPERTY\s*TAX.*HK|HK.*PROPERTY.*TAX|RENTAL.*INCOME.*TAX.*HK",
        description="Property Tax reporting — verify 15% standard rate on net assessable rental income",
        severity="medium", effort_hours=2.0, tags=["hk", "tax", "property"],
        fix_suggestion="Configure Property Tax at 15% on net assessable rental value (80% of actual rent) in S/4HANA.",
    ),
    SimplificationRule(
        id="HK-005", category="COUNTRY_HK", country="HK",
        pattern=r"STAMP\s*DUTY.*HK|HK.*STAMP.*DUTY|SSD\b.*HK|BSD\b.*HK|AVD\b.*HK",
        description="Stamp Duty calculation — verify ad valorem, special, and buyer's stamp duty on property transactions",
        severity="medium", effort_hours=3.0, tags=["hk", "tax", "stamp_duty"],
        fix_suggestion="Configure stamp duty rates (AVD tiered scale, SSD, BSD for non-permanent residents) in S/4HANA.",
    ),
    SimplificationRule(
        id="HK-006", category="COUNTRY_HK", country="HK",
        pattern=r"BIR56A\b|EMPLOYER.*RETURN.*HK|IRD.*EMPLOYER|IR56\w.*HK",
        description="IRD Employer's Return (BIR56A/IR56B) — verify annual employer filing and employee notification forms",
        severity="high", effort_hours=4.0, tags=["hk", "hr", "ird", "filing"],
        fix_suggestion="Configure IR56B employee remuneration details and BIR56A employer's return for annual IRD filing in S/4HANA.",
    ),
    SimplificationRule(
        id="HK-007", category="COUNTRY_HK", country="HK",
        pattern=r"NO.*VAT.*HK|NO.*GST.*HK|HK.*NO.*SALES\s*TAX|HK.*TAX.?FREE.*SALES",
        description="No VAT/GST system — verify Hong Kong has no VAT/GST; remove any indirect tax logic for HK transactions",
        severity="low", effort_hours=1.0, tags=["hk", "tax", "vat"],
        fix_suggestion="Confirm no VAT/GST tax procedure for Hong Kong company codes in S/4HANA. Remove any indirect tax assignments.",
    ),
    SimplificationRule(
        id="HK-008", category="COUNTRY_HK", country="HK",
        pattern=r"ORSO\b.*HK|OCCUPATIONAL\s*RETIREMENT|ORSO.*SCHEME|RECOGNIZED.*RETIREMENT",
        description="ORSO (Occupational Retirement Schemes) — verify legacy scheme handling alongside MPF",
        severity="medium", effort_hours=3.0, tags=["hk", "hr", "orso", "pension"],
        fix_suggestion="Configure ORSO scheme deductions for grandfathered members alongside MPF contributions in S/4HANA Payroll.",
    ),
    SimplificationRule(
        id="HK-009", category="COUNTRY_HK", country="HK",
        pattern=r"DEPRECIATION.*ALLOW.*HK|HK.*CAPITAL.*ALLOW|IBA\b.*HK|INITIAL\s*ALLOW.*HK",
        description="Depreciation allowances — verify initial (60%), annual (10-30%), and industrial building allowances",
        severity="medium", effort_hours=3.0, tags=["hk", "tax", "depreciation", "assets"],
        fix_suggestion="Configure HK depreciation allowances (60% initial, 10-30% annual by category) in S/4HANA Asset Accounting.",
    ),
    SimplificationRule(
        id="HK-010", category="COUNTRY_HK", country="HK",
        pattern=r"TRANSFER\s*PRICING.*HK|BEPS\b.*HK|HK.*TP.*RULES|DIPN\s*46.*HK",
        description="Transfer pricing (BEPS/DIPN 46) — verify arm's length documentation and CbCR for MNEs",
        severity="medium", effort_hours=4.0, tags=["hk", "tax", "transfer_pricing", "beps"],
        fix_suggestion="Configure transfer pricing documentation per DIPN 46 with master file, local file, CbCR from S/4HANA.",
    ),
]

# =============================================================================
# NEW ZEALAND (NZ) — 10 rules
# =============================================================================
NEW_ZEALAND_RULES = [
    SimplificationRule(
        id="NZ-001", category="COUNTRY_NZ", country="NZ",
        pattern=r"GST.*15.*NZ|NZ.*GST.*CALC|GST.*NEW\s*ZEALAND|NZ.*GST.*RETURN",
        description="GST 15% calculation — verify standard rate, zero-rated, and exempt supply classification",
        severity="high", effort_hours=4.0, tags=["nz", "tax", "gst"],
        fix_suggestion="Configure NZ GST at 15% standard with zero-rated (exports, land) and exempt supplies in S/4HANA tax procedure.",
    ),
    SimplificationRule(
        id="NZ-002", category="COUNTRY_NZ", country="NZ",
        pattern=r"PAYE\b.*NZ|NZ.*PAYE.*DEDUCT|PAY\s*AS\s*YOU\s*EARN.*NZ",
        description="PAYE deductions — verify employer PAYE calculation using tax code and IR tax tables",
        severity="high", effort_hours=4.0, tags=["nz", "hr", "payroll", "paye"],
        fix_suggestion="Configure PAYE deductions using IRD tax codes (M, ME, SB, S, SH, ST, SA) and tax tables in S/4HANA Payroll.",
    ),
    SimplificationRule(
        id="NZ-003", category="COUNTRY_NZ", country="NZ",
        pattern=r"KIWISAVER\b|KIWI\s*SAVER|KS.*CONTRIB.*NZ|KIWISAVER.*3|KIWISAVER.*4|KIWISAVER.*6|KIWISAVER.*8|KIWISAVER.*10",
        description="KiwiSaver contributions (3/4/6/8/10%) — verify employee rate election and 3% employer contribution",
        severity="medium", effort_hours=3.0, tags=["nz", "hr", "kiwisaver", "statutory"],
        fix_suggestion="Configure KiwiSaver employee rates (3/4/6/8/10%) and mandatory 3% employer contribution in S/4HANA Payroll.",
    ),
    SimplificationRule(
        id="NZ-004", category="COUNTRY_NZ", country="NZ",
        pattern=r"PAYDAY\s*FILING|PAYDAY.*FILE.*NZ|NZ.*PAYDAY.*MANDATE|EI.*PAYDAY",
        description="Payday filing mandate — verify electronic employment information filing to IRD within 2 working days",
        severity="high", effort_hours=4.0, tags=["nz", "hr", "payroll", "filing"],
        fix_suggestion="Configure payday filing to submit employment information (EI) to IRD within 2 working days of each pay run.",
    ),
    SimplificationRule(
        id="NZ-005", category="COUNTRY_NZ", country="NZ",
        pattern=r"FBT\b.*NZ|FRINGE\s*BENEFIT.*TAX.*NZ|NZ.*FBT.*CALC|FBT.*RETURN.*NZ",
        description="FBT (Fringe Benefit Tax) — verify quarterly/annual FBT return and alternate rate election",
        severity="medium", effort_hours=3.0, tags=["nz", "tax", "fbt", "hr"],
        fix_suggestion="Configure FBT with single rate (63.93%) or alternate rate (49.25-63.93%) calculation in S/4HANA Payroll NZ.",
    ),
    SimplificationRule(
        id="NZ-006", category="COUNTRY_NZ", country="NZ",
        pattern=r"ACC\b.*LEVY.*NZ|ACC.*CALC.*NZ|ACCIDENT\s*COMPENSATION.*NZ|ACC.*EARNER",
        description="ACC (Accident Compensation Corporation) levy — verify earner and employer levy calculation",
        severity="medium", effort_hours=3.0, tags=["nz", "hr", "acc", "statutory"],
        fix_suggestion="Configure ACC earner's levy (deducted from employee) and employer work levy by CU classification in S/4HANA.",
    ),
    SimplificationRule(
        id="NZ-007", category="COUNTRY_NZ", country="NZ",
        pattern=r"RWT\b.*NZ|RESIDENT\s*WITHHOLDING.*TAX.*NZ|RWT.*RATE.*NZ",
        description="RWT (Resident Withholding Tax) — verify withholding on interest and dividends paid to NZ residents",
        severity="medium", effort_hours=2.0, tags=["nz", "tax", "withholding", "rwt"],
        fix_suggestion="Configure RWT rates (10.5/17.5/28/30/33/39%) based on recipient's declared rate in S/4HANA withholding tax.",
    ),
    SimplificationRule(
        id="NZ-008", category="COUNTRY_NZ", country="NZ",
        pattern=r"NRWT\b.*NZ|NON.?RESIDENT.*WHT.*NZ|NRWT.*RATE|APPROVED\s*ISSUER\s*LEVY",
        description="NRWT (Non-Resident Withholding Tax) — verify withholding on payments to non-residents and AIL option",
        severity="medium", effort_hours=3.0, tags=["nz", "tax", "withholding", "nrwt"],
        fix_suggestion="Configure NRWT rates (15% default, treaty rates) and Approved Issuer Levy (2%) option in S/4HANA.",
    ),
    SimplificationRule(
        id="NZ-009", category="COUNTRY_NZ", country="NZ",
        pattern=r"IRD.*E.?FILING.*NZ|NZ.*IRD.*ONLINE|MYIR\b|IR.*RETURN.*ONLINE.*NZ",
        description="IRD e-filing — verify electronic filing of GST, income tax, and employer returns via myIR",
        severity="medium", effort_hours=3.0, tags=["nz", "tax", "filing", "ird"],
        fix_suggestion="Configure IRD e-filing integration via myIR for GST returns, income tax, and employer schedules from S/4HANA.",
    ),
    SimplificationRule(
        id="NZ-010", category="COUNTRY_NZ", country="NZ",
        pattern=r"PROVISIONAL\s*TAX.*NZ|NZ.*PROVISIONAL.*TAX|AIM\b.*TAX.*NZ|STANDARD.*UPLIFT.*NZ",
        description="Provisional tax — verify standard uplift, estimation, or AIM (Accounting Income Method) options",
        severity="medium", effort_hours=3.0, tags=["nz", "tax", "provisional"],
        fix_suggestion="Configure provisional tax method (standard 105% uplift, estimation, or AIM) with payment dates in S/4HANA.",
    ),
]


# =============================================================================
# EXPANSION WAVE 2 — ADDITIONAL COUNTRIES (18 new jurisdictions)
# =============================================================================

# --- Spain (ES) ---
SPAIN_RULES = [
    SimplificationRule(
        id="ES-001", category="COUNTRY_ES", country="ES",
        pattern=r"\bSII\b.*SPAIN|SUMINISTRO.*INMEDIATO|ES.*SII.*INVOICE",
        description="SII (Suministro Inmediato de Información) — real-time invoice reporting to AEAT mandatory",
        severity="high", effort_hours=4.0, tags=["spain", "tax", "e-invoicing"],
        fix_suggestion="Configure SII real-time invoice XML submission to AEAT via S/4HANA tax reporting framework.",
    ),
    SimplificationRule(
        id="ES-002", category="COUNTRY_ES", country="ES",
        pattern=r"MODELO\s*\d{3}|AEAT.*REPORT|ES.*TAX.*FORM",
        description="Spanish tax models (Modelo 303/390/349/347/111/115/190) — verify S/4HANA tax declaration config",
        severity="high", effort_hours=3.0, tags=["spain", "tax", "reporting"],
        fix_suggestion="Map all Modelo declarations to S/4HANA Advanced Compliance Reporting for Spain.",
    ),
    SimplificationRule(
        id="ES-003", category="COUNTRY_ES", country="ES",
        pattern=r"IGIC|IPSI|CANARY.*TAX|CEUTA.*TAX",
        description="Canary Islands IGIC / Ceuta-Melilla IPSI — special indirect tax regimes",
        severity="medium", effort_hours=2.5, tags=["spain", "tax", "regional"],
        fix_suggestion="Configure IGIC/IPSI tax codes separately from mainland IVA in S/4HANA tax procedure.",
    ),
    SimplificationRule(
        id="ES-004", category="COUNTRY_ES", country="ES",
        pattern=r"SPANISH.*PAYROLL|NOMINA|SS.*COTIZACION|SEGURIDAD.*SOCIAL.*ES",
        description="Spanish Social Security (Seguridad Social) contributions — TC1/TC2 reporting",
        severity="high", effort_hours=3.5, tags=["spain", "payroll", "social-security"],
        fix_suggestion="Configure Spanish Social Security contribution bases and brackets in S/4HANA payroll.",
    ),
    SimplificationRule(
        id="ES-005", category="COUNTRY_ES", country="ES",
        pattern=r"SEPA.*ES|IBAN.*ES|BANCO.*DE.*ESPANA|NORMA\s*19|NORMA\s*34",
        description="Spanish banking — SEPA payments Norma 19/34/57/58 legacy formats",
        severity="medium", effort_hours=2.0, tags=["spain", "banking", "sepa"],
        fix_suggestion="Migrate Spanish bank payment formats (Norma 19/34) to SEPA ISO 20022 in S/4HANA.",
    ),
    SimplificationRule(
        id="ES-006", category="COUNTRY_ES", country="ES",
        pattern=r"FACTURAE|FACE.*PLATFORM|ES.*E.?INVOICE.*PUBLIC",
        description="FACe/FacturaE — mandatory e-invoicing for Spanish public sector",
        severity="high", effort_hours=3.0, tags=["spain", "e-invoicing", "public-sector"],
        fix_suggestion="Enable FacturaE XML 3.2.2 generation for public sector invoicing via S/4HANA document output.",
    ),
    SimplificationRule(
        id="ES-007", category="COUNTRY_ES", country="ES",
        pattern=r"INTRASTAT.*ES|DEB.*ES|SPAIN.*INTRASTAT",
        description="Spanish Intrastat / EU trade reporting obligations",
        severity="medium", effort_hours=2.0, tags=["spain", "trade", "intrastat"],
        fix_suggestion="Configure Intrastat reporting for Spain with commodity codes and partner country mapping.",
    ),
    SimplificationRule(
        id="ES-008", category="COUNTRY_ES", country="ES",
        pattern=r"IRPF|RETENCION.*ES|SPAIN.*WITHHOLDING",
        description="IRPF withholding tax on services/rent — Modelo 111/115/190",
        severity="medium", effort_hours=2.5, tags=["spain", "tax", "withholding"],
        fix_suggestion="Configure IRPF withholding tax types and rates with auto-calculation in S/4HANA.",
    ),
    SimplificationRule(
        id="ES-009", category="COUNTRY_ES", country="ES",
        pattern=r"RECARGO.*EQUIVALENCIA|SURCHARGE.*EQUIVALENCE|RE\b.*TAX.*ES",
        description="Recargo de Equivalencia — special VAT surcharge for retail",
        severity="medium", effort_hours=2.0, tags=["spain", "tax", "vat"],
        fix_suggestion="Configure VAT surcharge (Recargo de Equivalencia) tax codes for retail scenarios.",
    ),
    SimplificationRule(
        id="ES-010", category="COUNTRY_ES", country="ES",
        pattern=r"REGISTRO.*MERCANTIL|CUENTAS.*ANUALES|PGC\b.*ES",
        description="Plan General Contable (PGC) — Spanish chart of accounts compliance",
        severity="medium", effort_hours=2.0, tags=["spain", "accounting", "pgc"],
        fix_suggestion="Align GL accounts with PGC 2007 standard chart of accounts in S/4HANA.",
    ),
]

# --- Netherlands (NL) ---
NETHERLANDS_RULES = [
    SimplificationRule(
        id="NL-001", category="COUNTRY_NL", country="NL",
        pattern=r"\bBTW\b.*NL|DUTCH.*VAT|NETHERLANDS.*TAX|NL.*BELASTING",
        description="Dutch BTW (VAT) — verify tax procedure and quarterly/annual ICP reporting",
        severity="high", effort_hours=3.0, tags=["netherlands", "tax", "vat"],
        fix_suggestion="Configure Dutch BTW tax procedure with quarterly OB return and annual ICP in S/4HANA.",
    ),
    SimplificationRule(
        id="NL-002", category="COUNTRY_NL", country="NL",
        pattern=r"PEPPOL.*NL|SI.?UBL|DUTCH.*E.?INVOICE|NL.*CIUS",
        description="PEPPOL/SI-UBL — mandatory e-invoicing for Dutch government suppliers",
        severity="high", effort_hours=3.5, tags=["netherlands", "e-invoicing", "peppol"],
        fix_suggestion="Enable PEPPOL BIS 3.0 with NL-CIUS e-invoicing profile in S/4HANA.",
    ),
    SimplificationRule(
        id="NL-003", category="COUNTRY_NL", country="NL",
        pattern=r"DUTCH.*PAYROLL|LOONHEFFING|NL.*SOCIALE.*VERZEK|WKR\b",
        description="Dutch payroll — loonheffingen, WKR (werkkostenregeling) allowance scheme",
        severity="high", effort_hours=4.0, tags=["netherlands", "payroll", "tax"],
        fix_suggestion="Configure Dutch payroll with loonheffingen tables, WKR scheme, and pension ABP/PFZW in S/4HANA.",
    ),
    SimplificationRule(
        id="NL-004", category="COUNTRY_NL", country="NL",
        pattern=r"CBS\b.*NL|DUTCH.*STATISTICS|INTRASTAT.*NL|NL.*CBS",
        description="CBS statistical reporting / Dutch Intrastat declarations",
        severity="medium", effort_hours=2.0, tags=["netherlands", "reporting", "intrastat"],
        fix_suggestion="Configure CBS Intrastat reporting for NL with standard commodity code classification.",
    ),
    SimplificationRule(
        id="NL-005", category="COUNTRY_NL", country="NL",
        pattern=r"AUDITFILE.*NL|XAF.*NL|DUTCH.*AUDIT.*FILE|SAF.?T.*NL",
        description="Dutch Auditfile Financieel (XAF 3.2) — annual tax audit submission",
        severity="high", effort_hours=3.0, tags=["netherlands", "audit", "compliance"],
        fix_suggestion="Configure SAF-T NL / Auditfile Financieel XAF 3.2 export from S/4HANA GL data.",
    ),
    SimplificationRule(
        id="NL-006", category="COUNTRY_NL", country="NL",
        pattern=r"iDEAL|IDEAL.*NL|DUTCH.*PAYMENT|SEPA.*NL|NL.*DIRECT.*DEBIT",
        description="Dutch payment methods — iDEAL, SEPA direct debit, Acceptgiro migration",
        severity="medium", effort_hours=2.0, tags=["netherlands", "banking", "payments"],
        fix_suggestion="Configure SEPA payment formats and iDEAL integration for Dutch payment processing.",
    ),
    SimplificationRule(
        id="NL-007", category="COUNTRY_NL", country="NL",
        pattern=r"BV\b.*DUTCH|NV\b.*DUTCH|DUTCH.*ENTITY|KVK\b",
        description="Dutch entity types (BV/NV) — KvK Chamber of Commerce registration",
        severity="low", effort_hours=1.0, tags=["netherlands", "entity", "compliance"],
        fix_suggestion="Validate company code entity type and KvK registration in S/4HANA master data.",
    ),
    SimplificationRule(
        id="NL-008", category="COUNTRY_NL", country="NL",
        pattern=r"DUTCH.*GAAP|NL.*IFRS|JAARREKENING|ANNUAL.*ACCOUNT.*NL",
        description="Dutch GAAP / RJ guidelines — annual accounts (jaarrekening) compliance",
        severity="medium", effort_hours=2.5, tags=["netherlands", "accounting", "gaap"],
        fix_suggestion="Align GL chart of accounts with Dutch GAAP / RJ reporting structure in S/4HANA.",
    ),
]

# --- Switzerland (CH) ---
SWITZERLAND_RULES = [
    SimplificationRule(
        id="CH-001", category="COUNTRY_CH", country="CH",
        pattern=r"\bMWST\b.*CH|SWISS.*VAT|CH.*MEHRWERTSTEUER|ESTV\b",
        description="Swiss MWST (VAT) — ESTV quarterly reporting with Saldosteuersatz option",
        severity="high", effort_hours=3.0, tags=["switzerland", "tax", "vat"],
        fix_suggestion="Configure Swiss MWST tax procedure with ESTV-compatible quarterly VAT return in S/4HANA.",
    ),
    SimplificationRule(
        id="CH-002", category="COUNTRY_CH", country="CH",
        pattern=r"QR.?BILL|SWISS.*QR|CH.*QR.*PAYMENT|ESR.*CH",
        description="Swiss QR-bill — mandatory replacement of ESR/orange payment slips",
        severity="high", effort_hours=3.0, tags=["switzerland", "banking", "qr-bill"],
        fix_suggestion="Migrate from ESR payment slips to Swiss QR-bill format in S/4HANA payment output.",
    ),
    SimplificationRule(
        id="CH-003", category="COUNTRY_CH", country="CH",
        pattern=r"AHV|BVG|SWISS.*PENSION|PENSIONSKASSE|SUVA\b|CH.*SOCIAL",
        description="Swiss social insurance — AHV/IV/EO, BVG pension, SUVA accident insurance",
        severity="high", effort_hours=4.0, tags=["switzerland", "payroll", "social-insurance"],
        fix_suggestion="Configure Swiss social insurance pillars (AHV/IV/EO 1st pillar, BVG 2nd pillar, SUVA) in S/4HANA HR.",
    ),
    SimplificationRule(
        id="CH-004", category="COUNTRY_CH", country="CH",
        pattern=r"SWISS.*PAYROLL|QUELLENSTEUER|SOURCE.*TAX.*CH|CH.*WITHHOLDING",
        description="Swiss Quellensteuer (source tax) — canton-specific withholding rates",
        severity="high", effort_hours=3.5, tags=["switzerland", "payroll", "tax"],
        fix_suggestion="Configure canton-specific Quellensteuer withholding tables per ELM tariff model.",
    ),
    SimplificationRule(
        id="CH-005", category="COUNTRY_CH", country="CH",
        pattern=r"SWISSDEC|ELM\b.*CH|SWISS.*SALARY.*REPORT|CH.*LOHNAUSWEIS",
        description="Swissdec/ELM — unified electronic salary reporting to authorities",
        severity="high", effort_hours=3.0, tags=["switzerland", "payroll", "reporting"],
        fix_suggestion="Enable Swissdec ELM 5.0 certified salary reporting interface in S/4HANA payroll.",
    ),
    SimplificationRule(
        id="CH-006", category="COUNTRY_CH", country="CH",
        pattern=r"SWISS.*CUSTOMS|CH.*ZOLL|BAZG\b|SWISS.*TRADE",
        description="Swiss customs (BAZG) — import/export declarations and transit procedures",
        severity="medium", effort_hours=2.5, tags=["switzerland", "trade", "customs"],
        fix_suggestion="Configure Swiss customs integration with BAZG e-dec system via S/4HANA GTS.",
    ),
    SimplificationRule(
        id="CH-007", category="COUNTRY_CH", country="CH",
        pattern=r"MULTI.?CURRENCY.*CH|CHF.*EUR|SWISS.*FX|CH.*CURRENCY",
        description="Swiss multi-currency operations — CHF/EUR/USD parallel reporting",
        severity="medium", effort_hours=2.0, tags=["switzerland", "currency", "reporting"],
        fix_suggestion="Configure parallel currency ledger for CHF/EUR reporting in S/4HANA Universal Journal.",
    ),
    SimplificationRule(
        id="CH-008", category="COUNTRY_CH", country="CH",
        pattern=r"OR\b.*SWISS|SWISS.*CODE.*OBLIGATIONS|CH.*OR.*ACCOUNTING",
        description="Swiss OR (Code of Obligations) — accounting and financial reporting requirements",
        severity="medium", effort_hours=2.0, tags=["switzerland", "accounting", "compliance"],
        fix_suggestion="Align chart of accounts with Swiss OR / Swiss GAAP FER reporting requirements.",
    ),
]

# --- Austria (AT) ---
AUSTRIA_RULES = [
    SimplificationRule(
        id="AT-001", category="COUNTRY_AT", country="AT",
        pattern=r"\bUST\b.*AT|AUSTRIAN.*VAT|AT.*UMSATZSTEUER|FINANZ.*ONLINE.*AT",
        description="Austrian USt (VAT) — FinanzOnline UVA monthly/quarterly return",
        severity="high", effort_hours=3.0, tags=["austria", "tax", "vat"],
        fix_suggestion="Configure Austrian USt tax procedure with FinanzOnline UVA return submission.",
    ),
    SimplificationRule(
        id="AT-002", category="COUNTRY_AT", country="AT",
        pattern=r"REGISTRIERKASSE|CASH.*REGISTER.*AT|AT.*RKSV|BARUMSATZ",
        description="Austrian RKSV — tamper-proof cash register (Registrierkassensicherheit)",
        severity="high", effort_hours=3.0, tags=["austria", "compliance", "cash-register"],
        fix_suggestion="Configure RKSV-compliant cash register integration with digital certificate in S/4HANA.",
    ),
    SimplificationRule(
        id="AT-003", category="COUNTRY_AT", country="AT",
        pattern=r"AUSTRIAN.*PAYROLL|LOHNSTEUER.*AT|AT.*SV.*BEITRAG|OEGK\b",
        description="Austrian payroll — Lohnsteuer, SV-Beiträge (OEGK/PVA), DB/DZ contributions",
        severity="high", effort_hours=3.5, tags=["austria", "payroll", "social-insurance"],
        fix_suggestion="Configure Austrian payroll with Lohnsteuer tables, SV-Beiträge, and DB/DZ levy in S/4HANA.",
    ),
    SimplificationRule(
        id="AT-004", category="COUNTRY_AT", country="AT",
        pattern=r"E.?RECHNUNG.*AT|AUSTRIAN.*E.?INVOICE|PEPPOL.*AT|AT.*XR.*INVOICE",
        description="Austrian e-Rechnung — mandatory for B2G via PEPPOL / ebInterface",
        severity="high", effort_hours=3.0, tags=["austria", "e-invoicing", "peppol"],
        fix_suggestion="Enable ebInterface 6.1 or PEPPOL BIS 3.0 for Austrian public sector e-invoicing.",
    ),
    SimplificationRule(
        id="AT-005", category="COUNTRY_AT", country="AT",
        pattern=r"SAF.?T.*AT|AUSTRIAN.*AUDIT|STANDARDIZED.*AUDIT.*AT",
        description="Austrian SAF-T — standardized audit file for tax authorities",
        severity="medium", effort_hours=2.5, tags=["austria", "audit", "compliance"],
        fix_suggestion="Configure SAF-T Austria export from S/4HANA Universal Journal for tax audit.",
    ),
    SimplificationRule(
        id="AT-006", category="COUNTRY_AT", country="AT",
        pattern=r"UGB\b.*AT|AUSTRIAN.*GAAP|JAHRESABSCHLUSS.*AT|AT.*ANNUAL.*ACCOUNT",
        description="Austrian UGB — commercial code accounting and annual reporting",
        severity="medium", effort_hours=2.0, tags=["austria", "accounting", "gaap"],
        fix_suggestion="Align chart of accounts with Austrian UGB reporting requirements in S/4HANA.",
    ),
    SimplificationRule(
        id="AT-007", category="COUNTRY_AT", country="AT",
        pattern=r"INTRASTAT.*AT|AT.*EU.*TRADE|AUSTRIAN.*STAT.*REPORT",
        description="Austrian Intrastat / EU trade statistics reporting",
        severity="medium", effort_hours=2.0, tags=["austria", "trade", "intrastat"],
        fix_suggestion="Configure Austrian Intrastat reporting with Statistik Austria declarations.",
    ),
]

# --- Belgium (BE) ---
BELGIUM_RULES = [
    SimplificationRule(
        id="BE-001", category="COUNTRY_BE", country="BE",
        pattern=r"\bBTW\b.*BE|BELGIAN.*VAT|TVA.*BE|BE.*BELASTING.*TOEGEVOEGDE",
        description="Belgian BTW/TVA (VAT) — quarterly/monthly return via Intervat",
        severity="high", effort_hours=3.0, tags=["belgium", "tax", "vat"],
        fix_suggestion="Configure Belgian BTW/TVA tax procedure with Intervat e-filing in S/4HANA.",
    ),
    SimplificationRule(
        id="BE-002", category="COUNTRY_BE", country="BE",
        pattern=r"DIMONA|BELGIAN.*SOCIAL|ONSS.*RSZ|BE.*SOCIAL.*SECURITY",
        description="Belgian social security (ONSS/RSZ) — DmfA declarations and Dimona registration",
        severity="high", effort_hours=3.5, tags=["belgium", "payroll", "social-security"],
        fix_suggestion="Configure Belgian ONSS/RSZ contribution calculation and DmfA quarterly reporting.",
    ),
    SimplificationRule(
        id="BE-003", category="COUNTRY_BE", country="BE",
        pattern=r"PEPPOL.*BE|BELGIAN.*E.?INVOICE|HERMES\b.*BE|BE.*UBL",
        description="Belgian PEPPOL e-invoicing — mandatory for B2B from 2026",
        severity="high", effort_hours=3.0, tags=["belgium", "e-invoicing", "peppol"],
        fix_suggestion="Enable PEPPOL BIS 3.0 with BE CIUS profile for mandatory B2B e-invoicing.",
    ),
    SimplificationRule(
        id="BE-004", category="COUNTRY_BE", country="BE",
        pattern=r"BELGIAN.*PAYROLL|PRECOMPTE.*PROF|BEDRIJFSVOORHEFFING|BE.*WITHHOLDING.*TAX",
        description="Belgian payroll — précompte professionnel / bedrijfsvoorheffing withholding",
        severity="high", effort_hours=3.5, tags=["belgium", "payroll", "tax"],
        fix_suggestion="Configure Belgian withholding tax (PP/BV) scales and reduction codes in S/4HANA payroll.",
    ),
    SimplificationRule(
        id="BE-005", category="COUNTRY_BE", country="BE",
        pattern=r"CODA\b.*BE|BELGIAN.*BANK|BE.*CODA.*STATEMENT|ISABEL\b",
        description="Belgian CODA bank statement format — Isabel banking integration",
        severity="medium", effort_hours=2.0, tags=["belgium", "banking", "coda"],
        fix_suggestion="Configure CODA bank statement import and reconciliation in S/4HANA cash management.",
    ),
    SimplificationRule(
        id="BE-006", category="COUNTRY_BE", country="BE",
        pattern=r"BILATÉRALE.*BE|PARITAIR.*COMITE|JOINT.*COMMITTEE.*BE",
        description="Belgian joint committees (commissions paritaires) — sector-specific wage rules",
        severity="medium", effort_hours=3.0, tags=["belgium", "payroll", "collective-agreement"],
        fix_suggestion="Configure joint committee (CP) wage scales and premium rules in S/4HANA payroll.",
    ),
    SimplificationRule(
        id="BE-007", category="COUNTRY_BE", country="BE",
        pattern=r"LISTING.*281|FICHE.*281|BELGIAN.*TAX.*FORM.*281",
        description="Belgian Fiche 281 — annual tax certificates for employees/contractors",
        severity="medium", effort_hours=2.5, tags=["belgium", "tax", "reporting"],
        fix_suggestion="Configure Fiche 281.10/281.50 generation and Belcotax filing from S/4HANA.",
    ),
]

# --- Denmark (DK) ---
DENMARK_RULES = [
    SimplificationRule(
        id="DK-001", category="COUNTRY_DK", country="DK",
        pattern=r"DANISH.*MOMS|DK.*VAT|MOMS.*DK|SKAT\b.*DK",
        description="Danish MOMS (VAT) — SKAT quarterly/monthly return",
        severity="high", effort_hours=3.0, tags=["denmark", "tax", "vat"],
        fix_suggestion="Configure Danish MOMS tax procedure with SKAT e-filing in S/4HANA.",
    ),
    SimplificationRule(
        id="DK-002", category="COUNTRY_DK", country="DK",
        pattern=r"NEMHANDEL|DANISH.*E.?INVOICE|DK.*OIOUBL|NHR\b.*DK",
        description="NemHandel/OIOUBL — mandatory Danish e-invoicing (B2G and B2B via NHR)",
        severity="high", effort_hours=3.0, tags=["denmark", "e-invoicing", "nemhandel"],
        fix_suggestion="Enable OIOUBL / PEPPOL BIS 3.0 for NemHandel e-invoicing compliance.",
    ),
    SimplificationRule(
        id="DK-003", category="COUNTRY_DK", country="DK",
        pattern=r"DANISH.*PAYROLL|DK.*A.?SKAT|A.?INDKOMST|DK.*AM.?BIDRAG",
        description="Danish payroll — A-skat, AM-bidrag, eIndkomst reporting",
        severity="high", effort_hours=3.5, tags=["denmark", "payroll", "tax"],
        fix_suggestion="Configure Danish A-skat withholding, AM-bidrag, and eIndkomst monthly filing.",
    ),
    SimplificationRule(
        id="DK-004", category="COUNTRY_DK", country="DK",
        pattern=r"SAF.?T.*DK|DANISH.*AUDIT|BOGFORINGSLOVEN|DK.*BOOKKEEPING",
        description="Danish SAF-T / Bogføringsloven — digital bookkeeping law from 2024",
        severity="high", effort_hours=3.0, tags=["denmark", "audit", "compliance"],
        fix_suggestion="Configure SAF-T Denmark export and digital bookkeeping system registration.",
    ),
    SimplificationRule(
        id="DK-005", category="COUNTRY_DK", country="DK",
        pattern=r"DANISH.*BANKING|NETS\b.*DK|BETALINGSSERVICE|DK.*PBS",
        description="Danish NETS/Betalingsservice — payment processing and direct debit",
        severity="medium", effort_hours=2.0, tags=["denmark", "banking", "payments"],
        fix_suggestion="Configure NETS payment formats and Betalingsservice direct debit in S/4HANA.",
    ),
    SimplificationRule(
        id="DK-006", category="COUNTRY_DK", country="DK",
        pattern=r"ATP\b.*DK|DANISH.*PENSION|DK.*FERIEKONTO|FERIEPENGE",
        description="Danish ATP pension and Feriekonto (holiday allowance) schemes",
        severity="medium", effort_hours=2.5, tags=["denmark", "payroll", "pension"],
        fix_suggestion="Configure ATP contributions and Feriekonto holiday pay fund in S/4HANA payroll.",
    ),
]

# --- Sweden (SE) ---
SWEDEN_RULES = [
    SimplificationRule(
        id="SE-001", category="COUNTRY_SE", country="SE",
        pattern=r"SWEDISH.*MOMS|SE.*VAT|MOMS.*SE|SKATTEVERKET\b",
        description="Swedish MOMS (VAT) — Skatteverket monthly/quarterly return",
        severity="high", effort_hours=3.0, tags=["sweden", "tax", "vat"],
        fix_suggestion="Configure Swedish MOMS tax procedure with Skatteverket e-filing in S/4HANA.",
    ),
    SimplificationRule(
        id="SE-002", category="COUNTRY_SE", country="SE",
        pattern=r"PEPPOL.*SE|SWEDISH.*E.?INVOICE|SE.*SVEFAKTURA",
        description="Swedish PEPPOL e-invoicing — mandatory for public sector suppliers",
        severity="high", effort_hours=3.0, tags=["sweden", "e-invoicing", "peppol"],
        fix_suggestion="Enable PEPPOL BIS 3.0 for Swedish e-invoicing compliance.",
    ),
    SimplificationRule(
        id="SE-003", category="COUNTRY_SE", country="SE",
        pattern=r"SWEDISH.*PAYROLL|ARBETSGIVARAVGIFT|SE.*EMPLOYER.*CONTRIB|AGI\b.*SE",
        description="Swedish payroll — arbetsgivaravgifter (employer contributions), AGI reporting",
        severity="high", effort_hours=3.5, tags=["sweden", "payroll", "tax"],
        fix_suggestion="Configure Swedish employer contributions and AGI monthly reporting to Skatteverket.",
    ),
    SimplificationRule(
        id="SE-004", category="COUNTRY_SE", country="SE",
        pattern=r"SAF.?T.*SE|SWEDISH.*AUDIT|SIE\b.*SE|SE.*STANDARD.*IMPORT.*EXPORT",
        description="Swedish SIE file format — standard accounting data exchange",
        severity="medium", effort_hours=2.0, tags=["sweden", "audit", "reporting"],
        fix_suggestion="Configure SIE 4 file export for Swedish accounting data exchange.",
    ),
    SimplificationRule(
        id="SE-005", category="COUNTRY_SE", country="SE",
        pattern=r"BANKGIRO.*SE|PLUSGIRO|SWEDISH.*BANK|SE.*BG.*PAYMENT",
        description="Swedish Bankgiro/Plusgiro — payment and receivables processing",
        severity="medium", effort_hours=2.0, tags=["sweden", "banking", "payments"],
        fix_suggestion="Configure Bankgiro/Plusgiro payment formats and OCR reconciliation in S/4HANA.",
    ),
    SimplificationRule(
        id="SE-006", category="COUNTRY_SE", country="SE",
        pattern=r"ROT\b.*RUT|SE.*TAX.*DEDUCTION|HOUSEHOLD.*DEDUCT.*SE",
        description="Swedish ROT/RUT tax deductions — household services scheme",
        severity="low", effort_hours=1.5, tags=["sweden", "tax", "deduction"],
        fix_suggestion="Configure ROT/RUT deduction reporting in S/4HANA invoicing and tax framework.",
    ),
]

# --- Norway (NO) ---
NORWAY_RULES = [
    SimplificationRule(
        id="NO-001", category="COUNTRY_NO", country="NO",
        pattern=r"NORWEGIAN.*MVA|NO.*VAT|MVA.*NO|ALTINN\b.*NO",
        description="Norwegian MVA (VAT) — Altinn bi-monthly/annual return",
        severity="high", effort_hours=3.0, tags=["norway", "tax", "vat"],
        fix_suggestion="Configure Norwegian MVA tax procedure with Altinn e-filing in S/4HANA.",
    ),
    SimplificationRule(
        id="NO-002", category="COUNTRY_NO", country="NO",
        pattern=r"SAF.?T.*NO|NORWEGIAN.*SAF|NO.*STANDARD.*AUDIT|SKATTEETATEN.*SAF",
        description="Norwegian SAF-T — mandatory since 2020 for Skatteetaten",
        severity="high", effort_hours=3.5, tags=["norway", "audit", "saf-t"],
        fix_suggestion="Configure SAF-T Norway 1.10 export from S/4HANA for Skatteetaten compliance.",
    ),
    SimplificationRule(
        id="NO-003", category="COUNTRY_NO", country="NO",
        pattern=r"EHF\b.*NO|NORWEGIAN.*E.?INVOICE|NO.*PEPPOL|ANSKAFFELSER",
        description="Norwegian EHF/PEPPOL — mandatory e-invoicing for public sector",
        severity="high", effort_hours=3.0, tags=["norway", "e-invoicing", "peppol"],
        fix_suggestion="Enable EHF 3.0 / PEPPOL BIS 3.0 for Norwegian e-invoicing compliance.",
    ),
    SimplificationRule(
        id="NO-004", category="COUNTRY_NO", country="NO",
        pattern=r"NORWEGIAN.*PAYROLL|A.?MELDING|NO.*EMPLOYER.*REPORT|SKATTETREKK",
        description="Norwegian payroll — a-melding monthly employer reporting",
        severity="high", effort_hours=3.5, tags=["norway", "payroll", "tax"],
        fix_suggestion="Configure a-melding monthly reporting and skattetrekk withholding in S/4HANA payroll.",
    ),
    SimplificationRule(
        id="NO-005", category="COUNTRY_NO", country="NO",
        pattern=r"NORWEGIAN.*BANKING|AVTALEGIRO|NO.*OCR.*GIRO|KID\b.*NO",
        description="Norwegian AvtaleGiro / OCR Giro — payment and receivables with KID reference",
        severity="medium", effort_hours=2.0, tags=["norway", "banking", "payments"],
        fix_suggestion="Configure AvtaleGiro/OCR Giro payment formats with KID number generation.",
    ),
    SimplificationRule(
        id="NO-006", category="COUNTRY_NO", country="NO",
        pattern=r"OTP\b.*NO|NORWEGIAN.*PENSION|NO.*TJENESTEPENSJON|FOLKETRYGD",
        description="Norwegian OTP mandatory occupational pension and Folketrygden",
        severity="medium", effort_hours=2.5, tags=["norway", "payroll", "pension"],
        fix_suggestion="Configure OTP pension fund contributions and Folketrygd calculations in S/4HANA.",
    ),
]

# --- Finland (FI) ---
FINLAND_RULES = [
    SimplificationRule(
        id="FI-001", category="COUNTRY_FI", country="FI",
        pattern=r"FINNISH.*ALV|FI.*VAT|ALV.*FI|VERO\b.*FI",
        description="Finnish ALV (VAT) — Vero monthly/quarterly return",
        severity="high", effort_hours=3.0, tags=["finland", "tax", "vat"],
        fix_suggestion="Configure Finnish ALV tax procedure with Vero (tax admin) e-filing in S/4HANA.",
    ),
    SimplificationRule(
        id="FI-002", category="COUNTRY_FI", country="FI",
        pattern=r"FINVOICE|FINNISH.*E.?INVOICE|FI.*PEPPOL|APIX\b",
        description="Finvoice / PEPPOL — Finnish e-invoicing (B2B/B2G mandate)",
        severity="high", effort_hours=3.0, tags=["finland", "e-invoicing", "finvoice"],
        fix_suggestion="Enable Finvoice 3.0 or PEPPOL BIS 3.0 for Finnish e-invoicing compliance.",
    ),
    SimplificationRule(
        id="FI-003", category="COUNTRY_FI", country="FI",
        pattern=r"FINNISH.*PAYROLL|FI.*TYEL|TYELP\b|KELA\b.*FI|FI.*SOCIAL.*INSUR",
        description="Finnish payroll — TyEL pension, KELA sickness, unemployment insurance",
        severity="high", effort_hours=3.5, tags=["finland", "payroll", "social-insurance"],
        fix_suggestion="Configure Finnish TyEL pension, KELA sickness insurance, and YEL self-employed in S/4HANA.",
    ),
    SimplificationRule(
        id="FI-004", category="COUNTRY_FI", country="FI",
        pattern=r"SAF.?T.*FI|FINNISH.*AUDIT|FI.*STANDARD.*AUDIT",
        description="Finnish SAF-T — standardized bookkeeping data export",
        severity="medium", effort_hours=2.5, tags=["finland", "audit", "compliance"],
        fix_suggestion="Configure SAF-T Finland export from S/4HANA Universal Journal.",
    ),
    SimplificationRule(
        id="FI-005", category="COUNTRY_FI", country="FI",
        pattern=r"FINNISH.*BANKING|PANKKISIIRTO|FI.*REFERENCE.*NUMBER|FI.*PAYMENT",
        description="Finnish banking — national reference numbers and payment standards",
        severity="medium", effort_hours=2.0, tags=["finland", "banking", "payments"],
        fix_suggestion="Configure Finnish reference number generation and SEPA payment formats.",
    ),
]

# --- Ireland (IE) ---
IRELAND_RULES = [
    SimplificationRule(
        id="IE-001", category="COUNTRY_IE", country="IE",
        pattern=r"IRISH.*VAT|IE.*VAT|REVENUE.*IE|ROS\b.*IE",
        description="Irish VAT — Revenue Online Service (ROS) bi-monthly/annual return",
        severity="high", effort_hours=3.0, tags=["ireland", "tax", "vat"],
        fix_suggestion="Configure Irish VAT tax procedure with ROS e-filing in S/4HANA.",
    ),
    SimplificationRule(
        id="IE-002", category="COUNTRY_IE", country="IE",
        pattern=r"PEPPOL.*IE|IRISH.*E.?INVOICE|IE.*UBL",
        description="Irish PEPPOL e-invoicing — voluntary but recommended for public sector",
        severity="medium", effort_hours=2.5, tags=["ireland", "e-invoicing", "peppol"],
        fix_suggestion="Enable PEPPOL BIS 3.0 for Irish public sector e-invoicing.",
    ),
    SimplificationRule(
        id="IE-003", category="COUNTRY_IE", country="IE",
        pattern=r"IRISH.*PAYROLL|PAYE.*IE|IE.*PRSI|PAYE.*MODERNISATION",
        description="Irish payroll — PAYE Modernisation, PRSI, USC real-time reporting",
        severity="high", effort_hours=4.0, tags=["ireland", "payroll", "paye"],
        fix_suggestion="Configure PAYE Modernisation real-time payroll reporting to Revenue in S/4HANA.",
    ),
    SimplificationRule(
        id="IE-004", category="COUNTRY_IE", country="IE",
        pattern=r"SAF.?T.*IE|IRISH.*AUDIT|IE.*STANDARD.*AUDIT",
        description="Irish SAF-T — Revenue audit file for compliance",
        severity="medium", effort_hours=2.5, tags=["ireland", "audit", "compliance"],
        fix_suggestion="Configure SAF-T Ireland export from S/4HANA for Revenue compliance.",
    ),
    SimplificationRule(
        id="IE-005", category="COUNTRY_IE", country="IE",
        pattern=r"CRO\b.*IE|IRISH.*COMPANY|IE.*ANNUAL.*RETURN|B1.*FORM.*IE",
        description="Irish CRO annual return and B1 filing requirements",
        severity="medium", effort_hours=2.0, tags=["ireland", "compliance", "entity"],
        fix_suggestion="Align financial reporting with CRO annual return requirements in S/4HANA.",
    ),
]

# --- Portugal (PT) ---
PORTUGAL_RULES = [
    SimplificationRule(
        id="PT-001", category="COUNTRY_PT", country="PT",
        pattern=r"PORTUGUESE.*IVA|PT.*VAT|IVA.*PT|AT\b.*PORTAL.*PT",
        description="Portuguese IVA (VAT) — AT portal monthly/quarterly return",
        severity="high", effort_hours=3.0, tags=["portugal", "tax", "vat"],
        fix_suggestion="Configure Portuguese IVA tax procedure with AT e-filing in S/4HANA.",
    ),
    SimplificationRule(
        id="PT-002", category="COUNTRY_PT", country="PT",
        pattern=r"SAF.?T.*PT|PORTUGUESE.*SAF|PT.*FICHEIRO.*AUDITORIA|CIUS.?PT",
        description="Portuguese SAF-T — mandatory monthly submission to AT since 2008",
        severity="high", effort_hours=3.5, tags=["portugal", "audit", "saf-t"],
        fix_suggestion="Configure SAF-T PT 1.04 monthly export and integration with AT portal.",
    ),
    SimplificationRule(
        id="PT-003", category="COUNTRY_PT", country="PT",
        pattern=r"PORTUGUESE.*E.?INVOICE|CIUS.?PT|FATURA.*ELETRONICA.*PT",
        description="Portuguese CIUS-PT e-invoicing — public procurement mandate",
        severity="high", effort_hours=3.0, tags=["portugal", "e-invoicing", "cius"],
        fix_suggestion="Enable CIUS-PT / PEPPOL BIS 3.0 for Portuguese public sector e-invoicing.",
    ),
    SimplificationRule(
        id="PT-004", category="COUNTRY_PT", country="PT",
        pattern=r"PORTUGUESE.*PAYROLL|TSU.*PT|SEGURANCA.*SOCIAL.*PT|PT.*SS.*CONTRIB",
        description="Portuguese payroll — TSU social security contributions",
        severity="high", effort_hours=3.5, tags=["portugal", "payroll", "social-security"],
        fix_suggestion="Configure Portuguese TSU employer/employee rates and DRI reporting in S/4HANA.",
    ),
    SimplificationRule(
        id="PT-005", category="COUNTRY_PT", country="PT",
        pattern=r"ATCUD|PORTUGUESE.*QR.*CODE|PT.*INVOICE.*HASH|SERIES.*COMMUNIC.*PT",
        description="Portuguese ATCUD — unique document code with QR code and hash chain on invoices",
        severity="high", effort_hours=3.0, tags=["portugal", "compliance", "invoice"],
        fix_suggestion="Implement ATCUD series communication and QR code generation on invoices.",
    ),
]

# --- Czech Republic (CZ) ---
CZECH_RULES = [
    SimplificationRule(
        id="CZ-001", category="COUNTRY_CZ", country="CZ",
        pattern=r"CZECH.*DPH|CZ.*VAT|DPH.*CZ|KONTROLNI.*HLASENI",
        description="Czech DPH (VAT) — kontrolní hlášení (control statement) and daňové přiznání",
        severity="high", effort_hours=3.0, tags=["czech", "tax", "vat"],
        fix_suggestion="Configure Czech DPH tax procedure with kontrolní hlášení XML reporting in S/4HANA.",
    ),
    SimplificationRule(
        id="CZ-002", category="COUNTRY_CZ", country="CZ",
        pattern=r"CZECH.*E.?INVOICE|ISDOC|CZ.*PEPPOL",
        description="Czech ISDOC / PEPPOL e-invoicing format",
        severity="medium", effort_hours=2.5, tags=["czech", "e-invoicing", "isdoc"],
        fix_suggestion="Enable ISDOC or PEPPOL BIS 3.0 for Czech e-invoicing.",
    ),
    SimplificationRule(
        id="CZ-003", category="COUNTRY_CZ", country="CZ",
        pattern=r"CZECH.*PAYROLL|CZ.*SOCIAL|CSSZ\b|CZ.*HEALTH.*INSUR",
        description="Czech payroll — CSSZ social insurance and health insurance contributions",
        severity="high", effort_hours=3.5, tags=["czech", "payroll", "social-insurance"],
        fix_suggestion="Configure Czech CSSZ social and health insurance contribution calculation.",
    ),
    SimplificationRule(
        id="CZ-004", category="COUNTRY_CZ", country="CZ",
        pattern=r"EET\b.*CZ|CZECH.*SALES.*REGISTER|ELEKTRONICKA.*EVIDENCE",
        description="Czech EET (elektronická evidence tržeb) — electronic sales registration",
        severity="medium", effort_hours=2.5, tags=["czech", "compliance", "sales"],
        fix_suggestion="Configure EET electronic sales registration integration if applicable.",
    ),
    SimplificationRule(
        id="CZ-005", category="COUNTRY_CZ", country="CZ",
        pattern=r"CZECH.*INTRASTAT|CZ.*EU.*TRADE|CELNI.*SPRAVA",
        description="Czech Intrastat / EU trade reporting to Czech customs",
        severity="medium", effort_hours=2.0, tags=["czech", "trade", "intrastat"],
        fix_suggestion="Configure Czech Intrastat reporting with customs office declarations.",
    ),
]

# --- Hungary (HU) ---
HUNGARY_RULES = [
    SimplificationRule(
        id="HU-001", category="COUNTRY_HU", country="HU",
        pattern=r"HUNGARIAN.*AFA|HU.*VAT|AFA.*HU|NAV\b.*HU|ONLINE.*SZAMLA",
        description="Hungarian ÁFA (VAT) — NAV Online Számla real-time invoice reporting",
        severity="high", effort_hours=4.0, tags=["hungary", "tax", "e-invoicing"],
        fix_suggestion="Configure NAV Online Számla 3.0 real-time invoice data reporting in S/4HANA.",
    ),
    SimplificationRule(
        id="HU-002", category="COUNTRY_HU", country="HU",
        pattern=r"HUNGARIAN.*PAYROLL|HU.*SZOCHO|SZOCIALIS.*HOZZAJARULAS|HU.*TAX",
        description="Hungarian payroll — SZOCHO social contribution tax and SZJA income tax",
        severity="high", effort_hours=3.5, tags=["hungary", "payroll", "tax"],
        fix_suggestion="Configure Hungarian SZOCHO contribution and SZJA withholding in S/4HANA payroll.",
    ),
    SimplificationRule(
        id="HU-003", category="COUNTRY_HU", country="HU",
        pattern=r"HUNGARIAN.*E.?INVOICE|HU.*NAV.*INVOICE|SZAMLA.*HU",
        description="Hungarian mandatory e-invoicing — B2B via NAV from 2024",
        severity="high", effort_hours=3.5, tags=["hungary", "e-invoicing", "nav"],
        fix_suggestion="Enable NAV-compliant structured e-invoice XML generation in S/4HANA.",
    ),
    SimplificationRule(
        id="HU-004", category="COUNTRY_HU", country="HU",
        pattern=r"EKAER\b|HUNGARIAN.*TRANSPORT|HU.*GOODS.*TRANSPORT",
        description="Hungarian EKAER — electronic trade and transport control system",
        severity="medium", effort_hours=2.5, tags=["hungary", "trade", "transport"],
        fix_suggestion="Configure EKAER transport reporting for goods movement tracking in Hungary.",
    ),
    SimplificationRule(
        id="HU-005", category="COUNTRY_HU", country="HU",
        pattern=r"HUNGARIAN.*LOCAL.*TAX|IPA\b.*HU|HELYI.*ADO",
        description="Hungarian local business tax (IPA — iparűzési adó) — municipality tax",
        severity="medium", effort_hours=2.0, tags=["hungary", "tax", "local"],
        fix_suggestion="Configure IPA local business tax calculation by municipality in S/4HANA.",
    ),
]

# --- Romania (RO) ---
ROMANIA_RULES = [
    SimplificationRule(
        id="RO-001", category="COUNTRY_RO", country="RO",
        pattern=r"ROMANIAN.*TVA|RO.*VAT|TVA.*RO|ANAF\b.*RO",
        description="Romanian TVA (VAT) — ANAF monthly/quarterly D300 return and D394 reporting",
        severity="high", effort_hours=3.0, tags=["romania", "tax", "vat"],
        fix_suggestion="Configure Romanian TVA tax procedure with ANAF D300/D394 XML submissions.",
    ),
    SimplificationRule(
        id="RO-002", category="COUNTRY_RO", country="RO",
        pattern=r"RO.*E.?FACTURA|ROMANIAN.*E.?INVOICE|SPV\b.*RO|EFACTURA",
        description="Romanian e-Factura — mandatory B2B/B2G e-invoicing via SPV/ANAF",
        severity="high", effort_hours=4.0, tags=["romania", "e-invoicing", "efactura"],
        fix_suggestion="Enable RO e-Factura UBL 2.1 with CIUS-RO profile for ANAF SPV submission.",
    ),
    SimplificationRule(
        id="RO-003", category="COUNTRY_RO", country="RO",
        pattern=r"ROMANIAN.*SAF.?T|RO.*D406|SAF.?T.*RO|D406\b",
        description="Romanian SAF-T (D406) — mandatory from 2022 for large taxpayers",
        severity="high", effort_hours=3.5, tags=["romania", "audit", "saf-t"],
        fix_suggestion="Configure SAF-T Romania D406 export from S/4HANA Universal Journal for ANAF.",
    ),
    SimplificationRule(
        id="RO-004", category="COUNTRY_RO", country="RO",
        pattern=r"ROMANIAN.*E.?TRANSPORT|RO.*E.?TRANSPORT|ETRANSPORT",
        description="Romanian e-Transport — mandatory goods transport monitoring system",
        severity="high", effort_hours=3.0, tags=["romania", "transport", "compliance"],
        fix_suggestion="Configure e-Transport integration for goods movement tracking in Romania.",
    ),
    SimplificationRule(
        id="RO-005", category="COUNTRY_RO", country="RO",
        pattern=r"ROMANIAN.*PAYROLL|RO.*CAS|CASS\b.*RO|RO.*SOCIAL.*CONTRIB",
        description="Romanian payroll — CAS pension, CASS health, CAM work insurance",
        severity="high", effort_hours=3.5, tags=["romania", "payroll", "social-insurance"],
        fix_suggestion="Configure Romanian CAS/CASS/CAM contributions and D112 monthly reporting.",
    ),
]

# --- Turkey (TR) ---
TURKEY_RULES = [
    SimplificationRule(
        id="TR-001", category="COUNTRY_TR", country="TR",
        pattern=r"TURKISH.*KDV|TR.*VAT|KDV.*TR|GIB\b.*TR",
        description="Turkish KDV (VAT) — GİB monthly/quarterly return and BA-BS reporting",
        severity="high", effort_hours=3.0, tags=["turkey", "tax", "vat"],
        fix_suggestion="Configure Turkish KDV tax procedure with GİB e-filing and BA-BS forms.",
    ),
    SimplificationRule(
        id="TR-002", category="COUNTRY_TR", country="TR",
        pattern=r"E.?FATURA|TURKISH.*E.?INVOICE|TR.*GIB.*INVOICE|UBL.?TR",
        description="Turkish e-Fatura — mandatory B2B e-invoicing via GİB platform",
        severity="high", effort_hours=4.0, tags=["turkey", "e-invoicing", "efatura"],
        fix_suggestion="Enable e-Fatura UBL-TR 1.2 generation and GİB integration in S/4HANA.",
    ),
    SimplificationRule(
        id="TR-003", category="COUNTRY_TR", country="TR",
        pattern=r"E.?ARSIV|TURKISH.*E.?ARCHIVE|TR.*E.*ARCHIVE.*INVOICE",
        description="Turkish e-Arşiv — electronic archive invoice for B2C transactions",
        severity="high", effort_hours=3.0, tags=["turkey", "e-invoicing", "e-arsiv"],
        fix_suggestion="Configure e-Arşiv invoice generation for B2C and non-registered taxpayers.",
    ),
    SimplificationRule(
        id="TR-004", category="COUNTRY_TR", country="TR",
        pattern=r"TURKISH.*PAYROLL|SGK\b.*TR|TR.*SOCIAL.*SECURITY|MUHSGK",
        description="Turkish payroll — SGK social security and MuHSGK premium reporting",
        severity="high", effort_hours=3.5, tags=["turkey", "payroll", "sgk"],
        fix_suggestion="Configure SGK premium calculations and APHB monthly reporting in S/4HANA.",
    ),
    SimplificationRule(
        id="TR-005", category="COUNTRY_TR", country="TR",
        pattern=r"E.?DEFTER|TURKISH.*E.?LEDGER|TR.*E.*BOOK|LUCA\b.*TR",
        description="Turkish e-Defter — mandatory electronic bookkeeping (e-Ledger)",
        severity="high", effort_hours=3.0, tags=["turkey", "e-ledger", "compliance"],
        fix_suggestion="Configure e-Defter XBRL-GL format export for Turkish e-Ledger compliance.",
    ),
    SimplificationRule(
        id="TR-006", category="COUNTRY_TR", country="TR",
        pattern=r"E.?IRSALIYE|TURKISH.*WAYBILL|TR.*E.*DISPATCH",
        description="Turkish e-İrsaliye — electronic dispatch note (waybill) mandate",
        severity="high", effort_hours=2.5, tags=["turkey", "e-waybill", "compliance"],
        fix_suggestion="Configure e-İrsaliye dispatch note generation for goods movements in S/4HANA.",
    ),
    SimplificationRule(
        id="TR-007", category="COUNTRY_TR", country="TR",
        pattern=r"TURKISH.*WITHHOLDING|STOPAJ|TR.*TEVKIFAT",
        description="Turkish stopaj (withholding tax) and tevkifat (VAT withholding)",
        severity="medium", effort_hours=2.5, tags=["turkey", "tax", "withholding"],
        fix_suggestion="Configure stopaj withholding tax and KDV tevkifat rates in S/4HANA.",
    ),
]

# --- Argentina (AR) ---
ARGENTINA_RULES = [
    SimplificationRule(
        id="AR-001", category="COUNTRY_AR", country="AR",
        pattern=r"ARGENTINE.*IVA|AR.*VAT|IVA.*AR|AFIP\b.*AR",
        description="Argentine IVA (VAT) — AFIP monthly reporting and Libro IVA Digital",
        severity="high", effort_hours=3.0, tags=["argentina", "tax", "vat"],
        fix_suggestion="Configure Argentine IVA tax procedure with AFIP Libro IVA Digital in S/4HANA.",
    ),
    SimplificationRule(
        id="AR-002", category="COUNTRY_AR", country="AR",
        pattern=r"FACTURA.*ELECTRONICA.*AR|AR.*E.?INVOICE|AFIP.*WSFE|CAE\b.*AR",
        description="Argentine factura electrónica — AFIP WSFE/WSFEX with CAE authorization",
        severity="high", effort_hours=4.0, tags=["argentina", "e-invoicing", "afip"],
        fix_suggestion="Configure AFIP web service (WSFE/WSFEX) integration for CAE-authorized e-invoicing.",
    ),
    SimplificationRule(
        id="AR-003", category="COUNTRY_AR", country="AR",
        pattern=r"PERCEPCIONES|RETENCIONES.*AR|SIRE\b.*AR|AR.*WITHHOLDING|SICORE",
        description="Argentine percepciones/retenciones — SIRE/SICORE withholding regime",
        severity="high", effort_hours=3.5, tags=["argentina", "tax", "withholding"],
        fix_suggestion="Configure SIRE/SICORE percepciones/retenciones calculation and reporting to AFIP.",
    ),
    SimplificationRule(
        id="AR-004", category="COUNTRY_AR", country="AR",
        pattern=r"INGRESOS.*BRUTOS|IIBB\b.*AR|AR.*GROSS.*INCOME",
        description="Argentine Ingresos Brutos — provincial gross income tax (24 jurisdictions)",
        severity="high", effort_hours=4.0, tags=["argentina", "tax", "provincial"],
        fix_suggestion="Configure IIBB rates per province and SIFERE reporting in S/4HANA.",
    ),
    SimplificationRule(
        id="AR-005", category="COUNTRY_AR", country="AR",
        pattern=r"ARGENTINE.*PAYROLL|AR.*CARGAS.*SOCIALES|ANSES\b.*AR",
        description="Argentine payroll — cargas sociales (ANSES, obra social, sindicato)",
        severity="high", effort_hours=3.5, tags=["argentina", "payroll", "social-security"],
        fix_suggestion="Configure Argentine employer/employee social security (ANSES) and union contributions.",
    ),
    SimplificationRule(
        id="AR-006", category="COUNTRY_AR", country="AR",
        pattern=r"ARGENTINE.*INFLATION|AR.*ADJUSTMENT|AJUSTE.*INFLACION|RT\s*6",
        description="Argentine inflation adjustment — RT 6 accounting adjustments for hyperinflation",
        severity="high", effort_hours=3.0, tags=["argentina", "accounting", "inflation"],
        fix_suggestion="Configure inflation adjustment accounting entries per RT 6/IAS 29 in S/4HANA.",
    ),
]

# --- Chile (CL) ---
CHILE_RULES = [
    SimplificationRule(
        id="CL-001", category="COUNTRY_CL", country="CL",
        pattern=r"CHILEAN.*IVA|CL.*VAT|IVA.*CL|SII\b.*CL",
        description="Chilean IVA (VAT) — SII monthly F29/F50 return",
        severity="high", effort_hours=3.0, tags=["chile", "tax", "vat"],
        fix_suggestion="Configure Chilean IVA tax procedure with SII F29/F50 e-filing in S/4HANA.",
    ),
    SimplificationRule(
        id="CL-002", category="COUNTRY_CL", country="CL",
        pattern=r"DTE\b.*CL|CHILEAN.*E.?INVOICE|FACTURA.*ELECTRONICA.*CL|SII.*DTE",
        description="Chilean DTE — mandatory e-invoicing via SII platform",
        severity="high", effort_hours=4.0, tags=["chile", "e-invoicing", "dte"],
        fix_suggestion="Configure SII DTE (Documento Tributario Electrónico) XML generation in S/4HANA.",
    ),
    SimplificationRule(
        id="CL-003", category="COUNTRY_CL", country="CL",
        pattern=r"CHILEAN.*PAYROLL|AFP\b.*CL|CL.*PREVISION.*SOCIAL|FONASA|ISAPRE",
        description="Chilean payroll — AFP pension, FONASA/ISAPRE health, AFC unemployment",
        severity="high", effort_hours=3.5, tags=["chile", "payroll", "social-security"],
        fix_suggestion="Configure AFP/FONASA/ISAPRE/AFC contribution rates and Previred reporting.",
    ),
    SimplificationRule(
        id="CL-004", category="COUNTRY_CL", country="CL",
        pattern=r"BOLETA.*CL|CHILEAN.*RECEIPT|CL.*BHE|BOLETA.*HONORARIOS",
        description="Chilean Boleta de Honorarios Electrónica — withholding on professional services",
        severity="medium", effort_hours=2.5, tags=["chile", "tax", "withholding"],
        fix_suggestion="Configure BHE (Boleta de Honorarios) withholding and SII reporting.",
    ),
    SimplificationRule(
        id="CL-005", category="COUNTRY_CL", country="CL",
        pattern=r"LIBRO.*COMPRA.*VENTA|RCVC\b.*CL|CL.*PURCHASE.*SALES.*LEDGER",
        description="Chilean Libro de Compra y Venta — purchase/sales ledger to SII",
        severity="medium", effort_hours=2.5, tags=["chile", "tax", "reporting"],
        fix_suggestion="Configure automatic generation of Libro de Compra y Venta for SII submission.",
    ),
]

# --- Colombia (CO) ---
COLOMBIA_RULES = [
    SimplificationRule(
        id="CO-001", category="COUNTRY_CO", country="CO",
        pattern=r"COLOMBIAN.*IVA|CO.*VAT|IVA.*CO|DIAN\b.*CO",
        description="Colombian IVA (VAT) — DIAN bimonthly return and ICA industry tax",
        severity="high", effort_hours=3.0, tags=["colombia", "tax", "vat"],
        fix_suggestion="Configure Colombian IVA/ICA tax procedure with DIAN e-filing in S/4HANA.",
    ),
    SimplificationRule(
        id="CO-002", category="COUNTRY_CO", country="CO",
        pattern=r"FACTURA.*ELECTRONICA.*CO|CO.*E.?INVOICE|DIAN.*FACTURACION|CUFE\b",
        description="Colombian factura electrónica — DIAN mandatory e-invoicing with CUFE",
        severity="high", effort_hours=4.0, tags=["colombia", "e-invoicing", "dian"],
        fix_suggestion="Configure DIAN factura electrónica with CUFE hash and XML/UBL 2.1 format.",
    ),
    SimplificationRule(
        id="CO-003", category="COUNTRY_CO", country="CO",
        pattern=r"COLOMBIAN.*PAYROLL|PILA\b.*CO|CO.*SOCIAL.*SECURITY|EPS\b.*CO",
        description="Colombian payroll — PILA social security (EPS, AFP, ARL, CCF)",
        severity="high", effort_hours=3.5, tags=["colombia", "payroll", "social-security"],
        fix_suggestion="Configure PILA integrated contribution payment (EPS/AFP/ARL/CCF) in S/4HANA.",
    ),
    SimplificationRule(
        id="CO-004", category="COUNTRY_CO", country="CO",
        pattern=r"RETENCION.*FUENTE.*CO|RETE.*ICA|RETE.*IVA|CO.*WITHHOLD",
        description="Colombian retención en la fuente — source withholding (ReteFuente/ReteICA/ReteIVA)",
        severity="high", effort_hours=3.0, tags=["colombia", "tax", "withholding"],
        fix_suggestion="Configure ReteFuente/ReteICA/ReteIVA withholding rates and DIAN reporting.",
    ),
    SimplificationRule(
        id="CO-005", category="COUNTRY_CO", country="CO",
        pattern=r"NOMINA.*ELECTRONICA.*CO|CO.*E.?PAYSLIP|DIAN.*NOMINA",
        description="Colombian nómina electrónica — mandatory electronic payslip to DIAN",
        severity="high", effort_hours=3.0, tags=["colombia", "payroll", "e-payslip"],
        fix_suggestion="Configure nómina electrónica XML generation and DIAN submission.",
    ),
]

# --- Peru (PE) ---
PERU_RULES = [
    SimplificationRule(
        id="PE-001", category="COUNTRY_PE", country="PE",
        pattern=r"PERUVIAN.*IGV|PE.*VAT|IGV.*PE|SUNAT\b.*PE",
        description="Peruvian IGV (VAT) — SUNAT monthly PDT 621 return",
        severity="high", effort_hours=3.0, tags=["peru", "tax", "vat"],
        fix_suggestion="Configure Peruvian IGV tax procedure with SUNAT PDT 621 reporting in S/4HANA.",
    ),
    SimplificationRule(
        id="PE-002", category="COUNTRY_PE", country="PE",
        pattern=r"CPE\b.*PE|PERUVIAN.*E.?INVOICE|SUNAT.*FACTURA|UBL.*PE",
        description="Peruvian CPE — mandatory e-invoicing (Comprobante de Pago Electrónico) via SUNAT",
        severity="high", effort_hours=4.0, tags=["peru", "e-invoicing", "sunat"],
        fix_suggestion="Configure SUNAT CPE (factura/boleta electrónica) UBL 2.1 integration.",
    ),
    SimplificationRule(
        id="PE-003", category="COUNTRY_PE", country="PE",
        pattern=r"PERUVIAN.*PAYROLL|ESSALUD|ONP\b.*PE|PE.*AFP|PE.*SOCIAL",
        description="Peruvian payroll — EsSalud health, ONP/AFP pension contributions",
        severity="high", effort_hours=3.5, tags=["peru", "payroll", "social-security"],
        fix_suggestion="Configure EsSalud/ONP/AFP contribution rates and PLAME reporting to SUNAT.",
    ),
    SimplificationRule(
        id="PE-004", category="COUNTRY_PE", country="PE",
        pattern=r"DETRACCION|PERCEPCION.*PE|RETENCION.*PE|PE.*SPOT.*SYSTEM",
        description="Peruvian SPOT system — detracción/percepción/retención regimes",
        severity="high", effort_hours=3.0, tags=["peru", "tax", "withholding"],
        fix_suggestion="Configure SPOT detracción rates and automated banco de la nación deposits.",
    ),
    SimplificationRule(
        id="PE-005", category="COUNTRY_PE", country="PE",
        pattern=r"LIBRO.*ELECTRONICO.*PE|PLE\b.*PE|PERUVIAN.*E.?BOOK|SUNAT.*PLE",
        description="Peruvian PLE — mandatory electronic bookkeeping (Libros Electrónicos)",
        severity="high", effort_hours=3.0, tags=["peru", "e-book", "compliance"],
        fix_suggestion="Configure PLE electronic ledger generation and SUNAT submission.",
    ),
]

# --- Nigeria (NG) ---
NIGERIA_RULES = [
    SimplificationRule(
        id="NG-001", category="COUNTRY_NG", country="NG",
        pattern=r"NIGERIAN.*VAT|NG.*VAT|FIRS\b.*NG|NG.*TAX",
        description="Nigerian VAT — FIRS monthly return and CIT (Company Income Tax)",
        severity="high", effort_hours=3.0, tags=["nigeria", "tax", "vat"],
        fix_suggestion="Configure Nigerian VAT/CIT tax procedure with FIRS TaxPro Max e-filing.",
    ),
    SimplificationRule(
        id="NG-002", category="COUNTRY_NG", country="NG",
        pattern=r"NIGERIAN.*PAYROLL|PAYE.*NG|NG.*PENSION.*CPS|NSITF\b|NHF\b.*NG",
        description="Nigerian payroll — PAYE, CPS pension, NHF (housing fund), NSITF",
        severity="high", effort_hours=3.5, tags=["nigeria", "payroll", "tax"],
        fix_suggestion="Configure Nigerian PAYE withholding, CPS pension (PenCom), NHF, NSITF.",
    ),
    SimplificationRule(
        id="NG-003", category="COUNTRY_NG", country="NG",
        pattern=r"NIGERIAN.*WITHHOLDING|WHT.*NG|NG.*WHT.*TAX",
        description="Nigerian WHT — withholding tax on vendors and contractors",
        severity="medium", effort_hours=2.5, tags=["nigeria", "tax", "withholding"],
        fix_suggestion="Configure WHT rates by income type and FIRS filing in S/4HANA.",
    ),
    SimplificationRule(
        id="NG-004", category="COUNTRY_NG", country="NG",
        pattern=r"TRANSFER.*PRICING.*NG|NG.*TP.*REPORT|FIRS.*TP",
        description="Nigerian transfer pricing — FIRS TP declarations and CBC reporting",
        severity="medium", effort_hours=2.5, tags=["nigeria", "tax", "transfer-pricing"],
        fix_suggestion="Configure transfer pricing documentation and FIRS TP return in S/4HANA.",
    ),
    SimplificationRule(
        id="NG-005", category="COUNTRY_NG", country="NG",
        pattern=r"NIGERIAN.*E.?INVOICE|NG.*FIRS.*INVOICE",
        description="Nigerian e-invoicing — FIRS planned e-invoice mandate",
        severity="medium", effort_hours=2.5, tags=["nigeria", "e-invoicing", "firs"],
        fix_suggestion="Prepare for FIRS e-invoicing mandate with structured invoice output config.",
    ),
]

# --- Kenya (KE) ---
KENYA_RULES = [
    SimplificationRule(
        id="KE-001", category="COUNTRY_KE", country="KE",
        pattern=r"KENYAN.*VAT|KE.*VAT|KRA\b.*KE|ITAX\b.*KE",
        description="Kenyan VAT — KRA iTax monthly return",
        severity="high", effort_hours=3.0, tags=["kenya", "tax", "vat"],
        fix_suggestion="Configure Kenyan VAT tax procedure with KRA iTax e-filing in S/4HANA.",
    ),
    SimplificationRule(
        id="KE-002", category="COUNTRY_KE", country="KE",
        pattern=r"TIMS\b.*KE|KRA.*TIMS|KENYAN.*E.?INVOICE|OSCU\b.*KE",
        description="Kenyan TIMS/eTIMS — KRA tax invoice management system (real-time)",
        severity="high", effort_hours=3.5, tags=["kenya", "e-invoicing", "tims"],
        fix_suggestion="Configure eTIMS/OSCU device integration for KRA real-time invoice reporting.",
    ),
    SimplificationRule(
        id="KE-003", category="COUNTRY_KE", country="KE",
        pattern=r"KENYAN.*PAYROLL|NSSF\b.*KE|NHIF\b.*KE|PAYE.*KE|KE.*NITA",
        description="Kenyan payroll — PAYE, NSSF pension, NHIF health, NITA levy",
        severity="high", effort_hours=3.5, tags=["kenya", "payroll", "tax"],
        fix_suggestion="Configure Kenyan PAYE, NSSF, NHIF (SHIF), NITA, and housing levy in S/4HANA.",
    ),
    SimplificationRule(
        id="KE-004", category="COUNTRY_KE", country="KE",
        pattern=r"KENYAN.*WITHHOLDING|WHT.*KE|KE.*WHT|KRA.*WHT",
        description="Kenyan withholding tax — KRA WHT on services, rent, dividends",
        severity="medium", effort_hours=2.0, tags=["kenya", "tax", "withholding"],
        fix_suggestion="Configure Kenyan WHT rates and KRA i-Tax withholding reports.",
    ),
]

# --- Egypt (EG) ---
EGYPT_RULES = [
    SimplificationRule(
        id="EG-001", category="COUNTRY_EG", country="EG",
        pattern=r"EGYPTIAN.*VAT|EG.*VAT|ETA\b.*EG|EG.*TAX.*AUTH",
        description="Egyptian VAT — ETA monthly return and electronic filing",
        severity="high", effort_hours=3.0, tags=["egypt", "tax", "vat"],
        fix_suggestion="Configure Egyptian VAT tax procedure with ETA e-Taxation portal filing.",
    ),
    SimplificationRule(
        id="EG-002", category="COUNTRY_EG", country="EG",
        pattern=r"EGYPTIAN.*E.?INVOICE|ETA.*E.?RECEIPT|EG.*E.?INVOICE|EINVOICE.*EG",
        description="Egyptian e-Invoice/e-Receipt — ETA mandatory B2B/B2C e-invoicing",
        severity="high", effort_hours=4.0, tags=["egypt", "e-invoicing", "eta"],
        fix_suggestion="Configure ETA e-Invoice SDK integration and digital signing in S/4HANA.",
    ),
    SimplificationRule(
        id="EG-003", category="COUNTRY_EG", country="EG",
        pattern=r"EGYPTIAN.*PAYROLL|EG.*SOCIAL.*INSUR|NOSI\b|EG.*PENSION",
        description="Egyptian payroll — NOSI social insurance and income tax withholding",
        severity="high", effort_hours=3.5, tags=["egypt", "payroll", "social-insurance"],
        fix_suggestion="Configure Egyptian social insurance (NOSI) and payroll tax tables in S/4HANA.",
    ),
    SimplificationRule(
        id="EG-004", category="COUNTRY_EG", country="EG",
        pattern=r"EGYPTIAN.*CUSTOMS|EG.*NAFEZA|ACID\b.*EG",
        description="Egyptian customs — NAFEZA single window and ACI advance cargo info",
        severity="medium", effort_hours=2.5, tags=["egypt", "customs", "trade"],
        fix_suggestion="Configure ACI/ACID customs registration for Egyptian import/export operations.",
    ),
]

# --- Croatia (HR) ---
CROATIA_RULES = [
    SimplificationRule(
        id="HR-001", category="COUNTRY_HR", country="HR",
        pattern=r"CROATIAN.*PDV|HR.*VAT|PDV.*HR|POREZNA\b",
        description="Croatian PDV (VAT) — monthly/quarterly return to Porezna uprava",
        severity="high", effort_hours=3.0, tags=["croatia", "tax", "vat"],
        fix_suggestion="Configure Croatian PDV tax procedure with e-Porezna filing in S/4HANA.",
    ),
    SimplificationRule(
        id="HR-002", category="COUNTRY_HR", country="HR",
        pattern=r"CROATIAN.*FISKALIZACIJA|HR.*FISCAL|FISKALNA.*BLAGAJNA",
        description="Croatian fiskalizacija — real-time fiscal cash register reporting",
        severity="high", effort_hours=3.0, tags=["croatia", "compliance", "fiscal"],
        fix_suggestion="Configure fiskalizacija real-time invoice reporting to Porezna uprava.",
    ),
    SimplificationRule(
        id="HR-003", category="COUNTRY_HR", country="HR",
        pattern=r"CROATIAN.*PAYROLL|HZZO\b|HZMO\b|JOPPD\b.*HR",
        description="Croatian payroll — JOPPD form, HZZO health, HZMO pension contributions",
        severity="high", effort_hours=3.5, tags=["croatia", "payroll", "social-insurance"],
        fix_suggestion="Configure Croatian JOPPD reporting, HZZO/HZMO contributions in S/4HANA payroll.",
    ),
]

# --- Bulgaria (BG) ---
BULGARIA_RULES = [
    SimplificationRule(
        id="BG-001", category="COUNTRY_BG", country="BG",
        pattern=r"BULGARIAN.*DDS|BG.*VAT|DDS.*BG|NRA\b.*BG",
        description="Bulgarian DDS (VAT) — NRA monthly return and purchase/sales ledgers",
        severity="high", effort_hours=3.0, tags=["bulgaria", "tax", "vat"],
        fix_suggestion="Configure Bulgarian DDS tax procedure with NRA VAT ledger reporting.",
    ),
    SimplificationRule(
        id="BG-002", category="COUNTRY_BG", country="BG",
        pattern=r"BULGARIAN.*PAYROLL|DOO\b.*BG|DZPO\b|NZOK\b.*BG",
        description="Bulgarian payroll — DOO pension, DZPO supplementary, NZOK health",
        severity="high", effort_hours=3.5, tags=["bulgaria", "payroll", "social-insurance"],
        fix_suggestion="Configure Bulgarian social insurance (DOO/DZPO/NZOK) and Declaration 1/6.",
    ),
    SimplificationRule(
        id="BG-003", category="COUNTRY_BG", country="BG",
        pattern=r"SAF.?T.*BG|BULGARIAN.*AUDIT|BG.*STANDARD.*AUDIT",
        description="Bulgarian SAF-T — planned standardized audit file",
        severity="medium", effort_hours=2.5, tags=["bulgaria", "audit", "compliance"],
        fix_suggestion="Prepare for Bulgarian SAF-T implementation when mandated.",
    ),
]

# --- Slovenia (SI) ---
SLOVENIA_RULES = [
    SimplificationRule(
        id="SI-001", category="COUNTRY_SI", country="SI",
        pattern=r"SLOVENIAN.*DDV|SI.*VAT|DDV.*SI|FURS\b.*SI",
        description="Slovenian DDV (VAT) — FURS monthly/quarterly return",
        severity="high", effort_hours=3.0, tags=["slovenia", "tax", "vat"],
        fix_suggestion="Configure Slovenian DDV tax procedure with FURS eDavki filing.",
    ),
    SimplificationRule(
        id="SI-002", category="COUNTRY_SI", country="SI",
        pattern=r"SLOVENIAN.*PAYROLL|SI.*SOCIAL|ZPIZ\b|ZZZS\b.*SI",
        description="Slovenian payroll — ZPIZ pension, ZZZS health insurance contributions",
        severity="high", effort_hours=3.5, tags=["slovenia", "payroll", "social-insurance"],
        fix_suggestion="Configure Slovenian ZPIZ/ZZZS contributions and REK-1 reporting.",
    ),
    SimplificationRule(
        id="SI-003", category="COUNTRY_SI", country="SI",
        pattern=r"E.?SLOG|SLOVENIAN.*E.?INVOICE|SI.*UBL|FURS.*E.*INVOICE",
        description="Slovenian e-SLOG / UBL e-invoicing for public sector",
        severity="medium", effort_hours=2.5, tags=["slovenia", "e-invoicing", "e-slog"],
        fix_suggestion="Configure e-SLOG / UBL 2.1 format for Slovenian B2G e-invoicing.",
    ),
]

# --- Lithuania (LT) ---
LITHUANIA_RULES = [
    SimplificationRule(
        id="LT-001", category="COUNTRY_LT", country="LT",
        pattern=r"LITHUANIAN.*PVM|LT.*VAT|PVM.*LT|VMI\b.*LT",
        description="Lithuanian PVM (VAT) — VMI monthly return via i.MAS",
        severity="high", effort_hours=3.0, tags=["lithuania", "tax", "vat"],
        fix_suggestion="Configure Lithuanian PVM tax procedure with VMI i.MAS e-filing.",
    ),
    SimplificationRule(
        id="LT-002", category="COUNTRY_LT", country="LT",
        pattern=r"I\.SAF|I\.VAZ|LITHUANIAN.*SAF|LT.*IMAS",
        description="Lithuanian i.SAF (e-invoice register) and i.VAZ (transport waybill)",
        severity="high", effort_hours=3.0, tags=["lithuania", "e-invoicing", "compliance"],
        fix_suggestion="Configure i.SAF invoice register and i.VAZ transport waybill for VMI.",
    ),
    SimplificationRule(
        id="LT-003", category="COUNTRY_LT", country="LT",
        pattern=r"LITHUANIAN.*PAYROLL|SODRA\b|VSD\b.*LT|LT.*SOCIAL.*INSUR",
        description="Lithuanian payroll — Sodra VSD/PSD social insurance contributions",
        severity="high", effort_hours=3.5, tags=["lithuania", "payroll", "social-insurance"],
        fix_suggestion="Configure Sodra VSD/PSD contribution rates and SAM reporting.",
    ),
]

# --- Latvia (LV) ---
LATVIA_RULES = [
    SimplificationRule(
        id="LV-001", category="COUNTRY_LV", country="LV",
        pattern=r"LATVIAN.*PVN|LV.*VAT|PVN.*LV|VID\b.*LV",
        description="Latvian PVN (VAT) — VID monthly return",
        severity="high", effort_hours=3.0, tags=["latvia", "tax", "vat"],
        fix_suggestion="Configure Latvian PVN tax procedure with VID e-filing in S/4HANA.",
    ),
    SimplificationRule(
        id="LV-002", category="COUNTRY_LV", country="LV",
        pattern=r"LATVIAN.*PAYROLL|VSAOI\b|LV.*SOCIAL.*TAX|EDS\b.*LV",
        description="Latvian payroll — VSAOI social contributions and EDS reporting",
        severity="high", effort_hours=3.5, tags=["latvia", "payroll", "social-insurance"],
        fix_suggestion="Configure Latvian VSAOI mandatory contributions and EDS monthly reports.",
    ),
    SimplificationRule(
        id="LV-003", category="COUNTRY_LV", country="LV",
        pattern=r"LATVIAN.*E.?INVOICE|LV.*PEPPOL|E.?ADRESE.*LV",
        description="Latvian e-invoicing via PEPPOL / e-Adrese platform",
        severity="medium", effort_hours=2.5, tags=["latvia", "e-invoicing", "peppol"],
        fix_suggestion="Configure PEPPOL BIS 3.0 for Latvian B2G e-invoicing.",
    ),
]

# --- Estonia (EE) ---
ESTONIA_RULES = [
    SimplificationRule(
        id="EE-001", category="COUNTRY_EE", country="EE",
        pattern=r"ESTONIAN.*KM|EE.*VAT|KM\b.*EE|EMTA\b.*EE",
        description="Estonian KM (VAT) — EMTA monthly return via e-MTA",
        severity="high", effort_hours=3.0, tags=["estonia", "tax", "vat"],
        fix_suggestion="Configure Estonian KM tax procedure with EMTA e-filing in S/4HANA.",
    ),
    SimplificationRule(
        id="EE-002", category="COUNTRY_EE", country="EE",
        pattern=r"ESTONIAN.*PAYROLL|EE.*SOCIAL.*TAX|SOTSIAALMAKS|TSD\b.*EE",
        description="Estonian payroll — sotsiaalmaks (social tax) and TSD reporting",
        severity="high", effort_hours=3.5, tags=["estonia", "payroll", "social-tax"],
        fix_suggestion="Configure Estonian social tax (33%) and TSD Annex reporting in S/4HANA.",
    ),
    SimplificationRule(
        id="EE-003", category="COUNTRY_EE", country="EE",
        pattern=r"E.?ARVELDAJA|ESTONIAN.*E.?INVOICE|EE.*PEPPOL",
        description="Estonian e-invoicing via e-arveldaja or PEPPOL for B2G",
        severity="medium", effort_hours=2.5, tags=["estonia", "e-invoicing", "peppol"],
        fix_suggestion="Configure PEPPOL BIS 3.0 for Estonian B2G e-invoicing.",
    ),
]

# --- Luxembourg (LU) ---
LUXEMBOURG_RULES = [
    SimplificationRule(
        id="LU-001", category="COUNTRY_LU", country="LU",
        pattern=r"LUXEMBOURG.*TVA|LU.*VAT|TVA.*LU|ACD\b.*LU",
        description="Luxembourg TVA (VAT) — ACD monthly/quarterly/annual return via eCDF",
        severity="high", effort_hours=3.0, tags=["luxembourg", "tax", "vat"],
        fix_suggestion="Configure Luxembourg TVA tax procedure with eCDF electronic filing.",
    ),
    SimplificationRule(
        id="LU-002", category="COUNTRY_LU", country="LU",
        pattern=r"LUXEMBOURG.*PAYROLL|CCSS\b.*LU|CNS\b.*LU|LU.*SOCIAL",
        description="Luxembourg payroll — CCSS social security and CNS health insurance",
        severity="high", effort_hours=3.5, tags=["luxembourg", "payroll", "social-security"],
        fix_suggestion="Configure CCSS/CNS contribution rates and SECUline reporting in S/4HANA.",
    ),
    SimplificationRule(
        id="LU-003", category="COUNTRY_LU", country="LU",
        pattern=r"PEPPOL.*LU|LUXEMBOURG.*E.?INVOICE|LU.*UBL",
        description="Luxembourg PEPPOL e-invoicing for B2G",
        severity="medium", effort_hours=2.5, tags=["luxembourg", "e-invoicing", "peppol"],
        fix_suggestion="Enable PEPPOL BIS 3.0 for Luxembourg public sector e-invoicing.",
    ),
]

# --- Slovakia (SK) ---
SLOVAKIA_RULES = [
    SimplificationRule(
        id="SK-001", category="COUNTRY_SK", country="SK",
        pattern=r"SLOVAK.*DPH|SK.*VAT|DPH.*SK|FINANCNA.*SPRAVA.*SK",
        description="Slovak DPH (VAT) — kontrolný výkaz (KV) and monthly/quarterly return",
        severity="high", effort_hours=3.0, tags=["slovakia", "tax", "vat"],
        fix_suggestion="Configure Slovak DPH with kontrolný výkaz XML reporting in S/4HANA.",
    ),
    SimplificationRule(
        id="SK-002", category="COUNTRY_SK", country="SK",
        pattern=r"SLOVAK.*PAYROLL|SK.*SOCIAL.*INSUR|SOCIALNA.*POISTOVNA",
        description="Slovak payroll — Sociálna poisťovňa contributions and health insurance",
        severity="high", effort_hours=3.5, tags=["slovakia", "payroll", "social-insurance"],
        fix_suggestion="Configure Slovak social/health insurance contributions and monthly RLFO report.",
    ),
    SimplificationRule(
        id="SK-003", category="COUNTRY_SK", country="SK",
        pattern=r"E.?KASA|SLOVAK.*FISCAL|SK.*CASH.*REGISTER|EKASA",
        description="Slovak eKasa — online fiscal cash register mandate",
        severity="medium", effort_hours=2.5, tags=["slovakia", "compliance", "fiscal"],
        fix_suggestion="Configure eKasa integration for Slovak point-of-sale fiscal compliance.",
    ),
]


# =============================================================================
# MASTER COLLECTION
# =============================================================================
ALL_COUNTRY_RULES = (
    INDIA_RULES +
    INDIA_EXTRA_RULES +
    US_RULES +
    US_EXTRA_RULES +
    GERMANY_RULES +
    GERMANY_EXTRA_RULES +
    BRAZIL_RULES +
    BRAZIL_EXTRA_RULES +
    CHINA_RULES +
    CHINA_EXTRA_RULES +
    UK_RULES +
    UK_EXTRA_RULES +
    MIDDLE_EAST_RULES +
    MIDDLE_EAST_EXTRA_RULES +
    JAPAN_RULES +
    JAPAN_EXTRA_RULES +
    AUSTRALIA_RULES +
    AUSTRALIA_EXTRA_RULES +
    AUSTRALIA_NEW_RULES +
    FRANCE_RULES +
    FRANCE_EXTRA_RULES +
    MEXICO_RULES +
    MEXICO_EXTRA_RULES +
    ITALY_RULES +
    ITALY_EXTRA_RULES +
    KOREA_RULES +
    KOREA_EXTRA_RULES +
    SOUTH_AFRICA_RULES +
    SOUTH_AFRICA_EXTRA_RULES +
    POLAND_RULES +
    POLAND_EXTRA_RULES +
    CANADA_RULES +
    CANADA_EXTRA_RULES +
    SINGAPORE_RULES +
    SINGAPORE_EXTRA_RULES +
    EU_RULES +
    EU_EXTRA_RULES +
    THAILAND_RULES +
    INDONESIA_RULES +
    MALAYSIA_RULES +
    PHILIPPINES_RULES +
    VIETNAM_RULES +
    TAIWAN_RULES +
    HONG_KONG_RULES +
    NEW_ZEALAND_RULES +
    SPAIN_RULES +
    NETHERLANDS_RULES +
    SWITZERLAND_RULES +
    AUSTRIA_RULES +
    BELGIUM_RULES +
    DENMARK_RULES +
    SWEDEN_RULES +
    NORWAY_RULES +
    FINLAND_RULES +
    IRELAND_RULES +
    PORTUGAL_RULES +
    CZECH_RULES +
    HUNGARY_RULES +
    ROMANIA_RULES +
    TURKEY_RULES +
    ARGENTINA_RULES +
    CHILE_RULES +
    COLOMBIA_RULES +
    PERU_RULES +
    NIGERIA_RULES +
    KENYA_RULES +
    EGYPT_RULES +
    CROATIA_RULES +
    BULGARIA_RULES +
    SLOVENIA_RULES +
    LITHUANIA_RULES +
    LATVIA_RULES +
    ESTONIA_RULES +
    LUXEMBOURG_RULES +
    SLOVAKIA_RULES
)

SUPPORTED_COUNTRIES = {
    "IN": {"name": "India", "rules": len(INDIA_RULES) + len(INDIA_EXTRA_RULES)},
    "US": {"name": "United States", "rules": len(US_RULES) + len(US_EXTRA_RULES)},
    "DE": {"name": "Germany", "rules": len(GERMANY_RULES) + len(GERMANY_EXTRA_RULES)},
    "BR": {"name": "Brazil", "rules": len(BRAZIL_RULES) + len(BRAZIL_EXTRA_RULES)},
    "CN": {"name": "China", "rules": len(CHINA_RULES) + len(CHINA_EXTRA_RULES)},
    "GB": {"name": "United Kingdom", "rules": len(UK_RULES) + len(UK_EXTRA_RULES)},
    "AE": {"name": "UAE", "rules": len([r for r in MIDDLE_EAST_RULES + MIDDLE_EAST_EXTRA_RULES if r.country == "AE"])},
    "SA": {"name": "Saudi Arabia", "rules": len([r for r in MIDDLE_EAST_RULES + MIDDLE_EAST_EXTRA_RULES if r.country == "SA"])},
    "JP": {"name": "Japan", "rules": len(JAPAN_RULES) + len(JAPAN_EXTRA_RULES)},
    "AU": {"name": "Australia", "rules": len(AUSTRALIA_RULES) + len(AUSTRALIA_EXTRA_RULES) + len(AUSTRALIA_NEW_RULES)},
    "FR": {"name": "France", "rules": len(FRANCE_RULES) + len(FRANCE_EXTRA_RULES)},
    "MX": {"name": "Mexico", "rules": len(MEXICO_RULES) + len(MEXICO_EXTRA_RULES)},
    "IT": {"name": "Italy", "rules": len(ITALY_RULES) + len(ITALY_EXTRA_RULES)},
    "KR": {"name": "South Korea", "rules": len(KOREA_RULES) + len(KOREA_EXTRA_RULES)},
    "ZA": {"name": "South Africa", "rules": len(SOUTH_AFRICA_RULES) + len(SOUTH_AFRICA_EXTRA_RULES)},
    "PL": {"name": "Poland", "rules": len(POLAND_RULES) + len(POLAND_EXTRA_RULES)},
    "CA": {"name": "Canada", "rules": len(CANADA_RULES) + len(CANADA_EXTRA_RULES)},
    "SG": {"name": "Singapore", "rules": len(SINGAPORE_RULES) + len(SINGAPORE_EXTRA_RULES)},
    "EU": {"name": "European Union (all)", "rules": len(EU_RULES) + len(EU_EXTRA_RULES)},
    "TH": {"name": "Thailand", "rules": len(THAILAND_RULES)},
    "ID": {"name": "Indonesia", "rules": len(INDONESIA_RULES)},
    "MY": {"name": "Malaysia", "rules": len(MALAYSIA_RULES)},
    "PH": {"name": "Philippines", "rules": len(PHILIPPINES_RULES)},
    "VN": {"name": "Vietnam", "rules": len(VIETNAM_RULES)},
    "TW": {"name": "Taiwan", "rules": len(TAIWAN_RULES)},
    "HK": {"name": "Hong Kong", "rules": len(HONG_KONG_RULES)},
    "NZ": {"name": "New Zealand", "rules": len(NEW_ZEALAND_RULES)},
    "ES": {"name": "Spain", "rules": len(SPAIN_RULES)},
    "NL": {"name": "Netherlands", "rules": len(NETHERLANDS_RULES)},
    "CH": {"name": "Switzerland", "rules": len(SWITZERLAND_RULES)},
    "AT": {"name": "Austria", "rules": len(AUSTRIA_RULES)},
    "BE": {"name": "Belgium", "rules": len(BELGIUM_RULES)},
    "DK": {"name": "Denmark", "rules": len(DENMARK_RULES)},
    "SE": {"name": "Sweden", "rules": len(SWEDEN_RULES)},
    "NO": {"name": "Norway", "rules": len(NORWAY_RULES)},
    "FI": {"name": "Finland", "rules": len(FINLAND_RULES)},
    "IE": {"name": "Ireland", "rules": len(IRELAND_RULES)},
    "PT": {"name": "Portugal", "rules": len(PORTUGAL_RULES)},
    "CZ": {"name": "Czech Republic", "rules": len(CZECH_RULES)},
    "HU": {"name": "Hungary", "rules": len(HUNGARY_RULES)},
    "RO": {"name": "Romania", "rules": len(ROMANIA_RULES)},
    "TR": {"name": "Turkey", "rules": len(TURKEY_RULES)},
    "AR": {"name": "Argentina", "rules": len(ARGENTINA_RULES)},
    "CL": {"name": "Chile", "rules": len(CHILE_RULES)},
    "CO": {"name": "Colombia", "rules": len(COLOMBIA_RULES)},
    "PE": {"name": "Peru", "rules": len(PERU_RULES)},
    "NG": {"name": "Nigeria", "rules": len(NIGERIA_RULES)},
    "KE": {"name": "Kenya", "rules": len(KENYA_RULES)},
    "EG": {"name": "Egypt", "rules": len(EGYPT_RULES)},
    "HR": {"name": "Croatia", "rules": len(CROATIA_RULES)},
    "BG": {"name": "Bulgaria", "rules": len(BULGARIA_RULES)},
    "SI": {"name": "Slovenia", "rules": len(SLOVENIA_RULES)},
    "LT": {"name": "Lithuania", "rules": len(LITHUANIA_RULES)},
    "LV": {"name": "Latvia", "rules": len(LATVIA_RULES)},
    "EE": {"name": "Estonia", "rules": len(ESTONIA_RULES)},
    "LU": {"name": "Luxembourg", "rules": len(LUXEMBOURG_RULES)},
    "SK": {"name": "Slovakia", "rules": len(SLOVAKIA_RULES)},
}


def get_country_rules(country_code: str) -> list:
    """Get rules for a specific country. Returns universal + country-specific."""
    return [r for r in ALL_COUNTRY_RULES if r.country == country_code or r.country == "ALL"]


def get_rules_for_countries(country_codes: list) -> list:
    """Get rules for multiple countries (for multi-country deployments)."""
    codes = set(country_codes + ["ALL"])
    return [r for r in ALL_COUNTRY_RULES if r.country in codes]


def get_all_country_rules() -> list:
    """Return all country-specific rules."""
    return ALL_COUNTRY_RULES


if __name__ == "__main__":
    print(f"\nMigrate4HANA — Global Country Rules Engine")
    print(f"{'=' * 50}")
    print(f"Total country-specific rules: {len(ALL_COUNTRY_RULES)}")
    print(f"Countries supported: {len(SUPPORTED_COUNTRIES)}")
    print(f"\nRules by country:")
    for code, info in sorted(SUPPORTED_COUNTRIES.items(), key=lambda x: -x[1]['rules']):
        print(f"  {code:4s} {info['name']:25s} {info['rules']:3d} rules")
    print(f"\n  {'ALL':4s} {'Universal (cross-country)':25s} (from simplification_rules.py)")
