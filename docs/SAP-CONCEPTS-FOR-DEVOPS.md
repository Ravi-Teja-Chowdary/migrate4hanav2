# SAP Concepts for DevOps Engineers

A practical translation guide from SAP-speak to concepts you already know.

## The Big Picture

SAP ECC is like a giant monolithic application that handles ALL business processes
(finance, HR, sales, procurement, manufacturing) in a single system. Think of it as
if someone put your entire company's operations into one enormous legacy app.

S/4HANA is SAP's modern rewrite — still monolithic, but running on an in-memory
database (HANA) with a modern UI layer (Fiori). The migration is essentially
a major version upgrade with breaking changes to the data model.

## Core Concepts Mapped

### System Architecture

| SAP Concept | DevOps Equivalent | Details |
|---|---|---|
| SAP Instance | Application server | A running copy of SAP |
| Client (100, 200, etc.) | Environment (prod, staging) | Logical partition within one instance |
| System Landscape | CI/CD environments | DEV → QAS → PRD (development, quality, production) |
| Transport Request | Git commit + deploy | Packages changes for promotion between systems |
| Transport Route | CI/CD pipeline | Defines the path DEV→QAS→PRD |
| Basis Administrator | SRE / Platform Engineer | Manages SAP infrastructure |

### Data & Storage

| SAP Concept | DevOps Equivalent | Details |
|---|---|---|
| HANA Database | In-memory DB (like Redis + PostgreSQL combined) | Column-store, in-memory, with disk persistence |
| Transparent Table | Database table | Standard relational table |
| Cluster Table | Serialized blob storage | Multiple logical tables stored in one physical table (legacy, removed in S/4) |
| Data Dictionary (SE11/DDIC) | Database schema + ORM | Defines all table structures, data types, domains |
| CDS View | Database view + API definition | S/4HANA's way of defining data models; exposes OData automatically |

### Programming

| SAP Concept | DevOps Equivalent | Details |
|---|---|---|
| ABAP | The programming language | Like Java/Python but SAP-specific |
| Z-program / Y-program | Custom code | Z/Y prefix = customer namespace (your custom code) |
| Function Module | Function/method | Reusable code unit, can be called remotely (RFC) |
| BAPI | REST API endpoint | Business API — the official way to integrate |
| BAdI / User Exit | Webhook / Plugin | Extension points where you inject custom logic |
| Enhancement | Middleware / interceptor | Way to modify SAP standard behavior without touching SAP code |
| Class (OO ABAP) | Regular OOP class | SAP added OOP to ABAP; newer code uses this |

### Communication

| SAP Concept | DevOps Equivalent | Details |
|---|---|---|
| RFC (Remote Function Call) | gRPC / REST call | SAP's native protocol for system-to-system calls |
| IDoc (Intermediate Document) | Message queue message (Service Bus / Web PubSub) | Asynchronous document exchange format |
| PI/PO | Azure API Management (APIM) + Message broker | SAP's middleware for routing integrations |
| Cloud Integration (CPI) | Modern API gateway | Cloud-native replacement for PI/PO |
| OData Service | REST API | Standard HTTP API, auto-generated from CDS views |

### Security

| SAP Concept | DevOps Equivalent | Details |
|---|---|---|
| PFCG Role | Azure RBAC Role | Bundle of permissions assigned to users |
| Authorization Object | RBAC Action | e.g., "S_TCODE" controls which transactions you can run |
| Authorization Field | RBAC Resource/Condition | Limits within an auth object (e.g., which company codes) |
| Composite Role | Managed Identity with role assignments | A role containing other roles |
| User Master Record (SU01) | Azure AD User | The user account with all its role assignments |
| Single Sign-On (SAML) | SSO (same thing) | SAP supports SAML 2.0, OAuth 2.0 |

### UI

| SAP Concept | DevOps Equivalent | Details |
|---|---|---|
| SAP GUI | Desktop thick client | The classic SAP interface (looks like it's from 1995, because it is) |
| Transaction Code (T-code) | CLI command | e.g., "VA01" launches "Create Sales Order" |
| Fiori | Modern web UI (React-like) | HTML5/JavaScript apps, runs in browser |
| Fiori Launchpad | Application portal/dashboard | The home screen where users launch Fiori apps |
| Fiori Catalog | App permission group | Controls which apps users can see |
| Fiori Group | Visual tile group | How apps are organized on the launchpad |

## What Changes in S/4HANA (The Important Stuff)

### 1. Finance — The Biggest Change
**Before (ECC):** Financial data spread across ~12 tables (BKPF, BSEG, BSID, BSAD, etc.)
**After (S/4):** Everything in ONE table called ACDOCA (Universal Journal)

Why? HANA is an in-memory database — it can handle massive single tables.
The old design split data for performance on disk-based databases.

### 2. Materials — Table Merge
**Before:** Material document header (MKPF) + items (MSEG) = 2 tables
**After:** Single table MATDOC

### 3. Business Partner — The Most Disruptive Change
**Before:** Customers in KNA1, Vendors in LFA1 (completely separate)
**After:** Both become Business Partners in BUT000

This means a company that is BOTH your customer AND vendor
becomes ONE record instead of two. Sounds simple, but the
downstream impact on every report, interface, and custom
program that references KNA1 or LFA1 is enormous.

### 4. Custom Code — Must Be Remediated
Any custom ABAP program that references the old tables must be updated.
SAP publishes a "Simplification List" (basically a breaking changes doc)
with every S/4HANA release.

### 5. UI — From SAP GUI to Fiori
Classic transactions (T-codes) still work, but SAP expects you to
move to Fiori apps. This means:
- Roles need Fiori catalog assignments (new concept)
- Users get a web browser instead of SAP GUI
- Custom reports need Fiori equivalents

## Azure Infrastructure for SAP

SAP on Azure is a well-established pattern. Here's what you need:

### Compute
- **Azure VM Mv2-series instances** — SAP HANA certified, high memory
- **Standard_M128s (128 vCPU, 256 GB)** — 256 GB RAM, good for mid-size systems
- **Standard_M208ms_v2 (208 vCPU, 512 GB)** — 512 GB RAM, for larger systems
- **Standard_M416ms_v2 (6 TB RAM)** — 6 TB RAM, for the biggest enterprise systems

### Storage
- **Azure Ultra Disk** — For HANA data volume (high IOPS)
- **Azure Premium SSD v2** — For HANA log volume and OS
- **Blob Storage** — For backups and data staging

### Network
- **VNet** with private subnets (SAP should never be public)
- **Azure VPN Gateway** or **ExpressRoute** — To reach on-prem ECC
- **Azure Virtual WAN** — If connecting multiple VNets

### Management
- **Azure Center for SAP Solutions** — Automates initial deployment
- **Azure Update Manager** — For patching and maintenance
- **Azure Monitor** — Monitoring (plus SAP Solution Manager)
- **Azure Backup for SAP HANA** — Native HANA backup to Blob Storage

## Key SAP Transactions You'll See Referenced

| T-code | What it does | DevOps equivalent |
|---|---|---|
| SE38 | ABAP program editor | Code editor |
| SE11 | Data dictionary editor | Schema editor |
| SM59 | RFC destination config | Service endpoint config |
| SM37 | Background job monitor | Cron job monitor |
| SU01 | User management | Azure AD user management |
| PFCG | Role management | Azure RBAC role editor |
| STMS | Transport Management | Deployment pipeline |
| ST22 | Runtime error dumps | Error log / crash dumps |
| SM21 | System log | Application log |
| SPRO | Customizing (all config) | Config management portal |
| WE20 | IDoc partner profiles | Integration partner config |
