# Migration preflight — target client 100

_Generated 2026-08-02 14:08. Read-only. Resolve every BLOCKED item (and review WARNs) before the real run — this turns mid-run failures into a fix-list._

**10 ready · 3 warnings · 1 blocked**

| bucket | check | status | detail | fix if not ready |
|---|---|---|---|---|
| Master data | Bank keys pass target length rules | 🔴 BLOCKED | 17097 bank keys (CA/AU) may violate the target country length rule | Set T005-BNKEY external for the affected countries (governed switch) or cleanse the keys. |
| Mapping | Key map 'gl_account' decisions resolved | 🟡 WARN | 1725 keys, 1677 still need a decision | Run key_mapper.py gl_account and confirm the open decisions in KEY_MAPPING.md. |
| Mapping | Org-unit map decisions resolved | 🟡 WARN | 137 org-unit decisions open | Resolve org decisions in ORG_MAPPING.md. |
| Master data | Customers have a name | 🟡 WARN | 2 of 19575 customers have no NAME1 | Cleanse blank customer names before BP creation. |
| Balances | Operating chart of accounts present (YCOA) | ✅ READY | 1133 accounts in YCOA |  |
| Balances | Posting-period variants configured (T001B) | ✅ READY | 39 posting-period ranges |  |
| Balances / Assets | FI-AA legacy transfer phase open | ✅ READY | transfer-open company codes: ['1010', '1710'] |  |
| Balances / CO | Primary cost elements in A000 | ✅ READY | 372 primary cost elements |  |
| Mapping | Key map 'customer' decisions resolved | ✅ READY | 17 keys, 0 still need a decision |  |
| Mapping | Key map 'vendor' decisions resolved | ✅ READY | 6 keys, 0 still need a decision |  |
| Mapping | Key map 'material' decisions resolved | ✅ READY | not generated yet |  |
| Master data / Logistics | Materials extended to plants (MARC) | ✅ READY | 3203 plant-extended materials on target |  |
| Open transactions | Notification types configured (TQ80) | ✅ READY | 57 notification types |  |
| Sales | Materials with sales views (MVKE) | ✅ READY | 803 sales-view materials on target |  |

> A **BLOCKED** check means a real migration will fail or be incomplete until it is resolved (customizing the client's Basis/functional team does, or a source-data cleanse). A **WARN** is a governed decision or a partial-data situation to confirm. All checks are read-only; nothing here changes the systems.