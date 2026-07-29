# Organizational-unit mapping — ECC → S/4 (client 200)

_Generated 2026-07-29T13:51:23. Edit `org_mapper.json` to confirm/adjust; loaders only use `auto` or `confirmed` rows._

**Summary:** 137 decisions · 208 to review · 4 auto-mapped

## Sales organization (VKORG)

| source | → target | conf. | country | records | rationale | alternatives |
|---|---|---|---|---:|---|---|
| `2300` | `—` | 🔴 decision | ES | 391 | no target org for country ES — create one, consolidate onto an existing target org, or skip these records |  |
| `2200` | `—` | 🔴 decision | FR | 301 | no target org for country FR — create one, consolidate onto an existing target org, or skip these records |  |
| `2400` | `—` | 🔴 decision | IT | 291 | no target org for country IT — create one, consolidate onto an existing target org, or skip these records |  |
| `2500` | `—` | 🔴 decision | NL | 289 | no target org for country NL — create one, consolidate onto an existing target org, or skip these records |  |
| `2800` | `—` | 🔴 decision | CN | 261 | no target org for country CN — create one, consolidate onto an existing target org, or skip these records |  |
| `7500` | `—` | 🔴 decision | AR | 243 | no target org for country AR — create one, consolidate onto an existing target org, or skip these records |  |
| `6000` | `—` | 🔴 decision | MX | 232 | no target org for country MX — create one, consolidate onto an existing target org, or skip these records |  |
| `5000` | `—` | 🔴 decision | JP | 189 | no target org for country JP — create one, consolidate onto an existing target org, or skip these records |  |
| `2000` | `—` | 🔴 decision | GB | 147 | no target org for country GB — create one, consolidate onto an existing target org, or skip these records |  |
| `4110` | `—` | 🔴 decision | KR | 71 | no target org for country KR — create one, consolidate onto an existing target org, or skip these records |  |
| `4000` | `—` | 🔴 decision | CA | 64 | no target org for country CA — create one, consolidate onto an existing target org, or skip these records |  |
| `9000` | `—` | 🔴 decision | RU | 62 | no target org for country RU — create one, consolidate onto an existing target org, or skip these records |  |
| `8500` | `—` | 🔴 decision | AU | 51 | no target org for country AU — create one, consolidate onto an existing target org, or skip these records |  |
| `7001` | `—` | 🔴 decision | BR | 22 | no target org for country BR — create one, consolidate onto an existing target org, or skip these records |  |
| `S330` | `—` | 🔴 decision | IT | 19 | no target org for country IT — create one, consolidate onto an existing target org, or skip these records |  |
| `4300` | `—` | 🔴 decision | IN | 15 | no target org for country IN — create one, consolidate onto an existing target org, or skip these records |  |
| `2820` | `—` | 🔴 decision | CN | 13 | no target org for country CN — create one, consolidate onto an existing target org, or skip these records |  |
| `7000` | `—` | 🔴 decision | BR | 11 | no target org for country BR — create one, consolidate onto an existing target org, or skip these records |  |
| `3050` | `—` | 🔴 decision | GB | 10 | no target org for country GB — create one, consolidate onto an existing target org, or skip these records |  |
| `4510` | `—` | 🔴 decision | CA | 8 | no target org for country CA — create one, consolidate onto an existing target org, or skip these records |  |
| `3010` | `—` | 🔴 decision | BE | 7 | no target org for country BE — create one, consolidate onto an existing target org, or skip these records |  |
| `5430` | `—` | 🔴 decision | NL | 6 | no target org for country NL — create one, consolidate onto an existing target org, or skip these records |  |
| `4520` | `—` | 🔴 decision | CA | 5 | no target org for country CA — create one, consolidate onto an existing target org, or skip these records |  |
| `4530` | `—` | 🔴 decision | CA | 5 | no target org for country CA — create one, consolidate onto an existing target org, or skip these records |  |
| `IN47` | `—` | 🔴 decision | IN | 4 | no target org for country IN — create one, consolidate onto an existing target org, or skip these records |  |
| `2222` | `—` | 🔴 decision | FR | 3 | no target org for country FR — create one, consolidate onto an existing target org, or skip these records |  |
| `2700` | `—` | 🔴 decision | CH | 2 | no target org for country CH — create one, consolidate onto an existing target org, or skip these records |  |
| `5431` | `—` | 🔴 decision | NL | 2 | no target org for country NL — create one, consolidate onto an existing target org, or skip these records |  |
| `8000` | `—` | 🔴 decision | CL | 2 | no target org for country CL — create one, consolidate onto an existing target org, or skip these records |  |
| `6101` | `—` | 🔴 decision | MX | 1 | no target org for country MX — create one, consolidate onto an existing target org, or skip these records |  |
| `2220` | `—` | 🔴 decision | FR | 1 | no target org for country FR — create one, consolidate onto an existing target org, or skip these records |  |
| `8520` | `—` | 🔴 decision | AU | 1 | no target org for country AU — create one, consolidate onto an existing target org, or skip these records |  |
| `8530` | `—` | 🔴 decision | AU | 1 | no target org for country AU — create one, consolidate onto an existing target org, or skip these records |  |
| `8580` | `—` | 🔴 decision | AU | 1 | no target org for country AU — create one, consolidate onto an existing target org, or skip these records |  |
| `8590` | `—` | 🔴 decision | NZ | 1 | no target org for country NZ — create one, consolidate onto an existing target org, or skip these records |  |
| `6650` | `—` | 🔴 decision | SA | 1 | no target org for country SA — create one, consolidate onto an existing target org, or skip these records |  |
| `1000` | `1010` | 🟡 review | DE | 4706 | 2 target orgs for DE; picked S/4 best-practice | 0001,1010 |
| `3020` | `1710` | 🟡 review | US | 3667 | 4 target orgs for US; picked S/4 best-practice | 0003,1710,FOBP,FORP |
| `0001` | `1010` | 🟡 review | DE | 1719 | 2 target orgs for DE; picked S/4 best-practice | 0001,1010 |
| `3000` | `1710` | 🟡 review | US | 1412 | 4 target orgs for US; picked S/4 best-practice | 0003,1710,FOBP,FORP |
| `1020` | `1010` | 🟡 review | DE | 348 | 2 target orgs for DE; picked S/4 best-practice | 0001,1010 |
| `R300` | `1710` | 🟡 review | US | 299 | 4 target orgs for US; picked S/4 best-practice | 0003,1710,FOBP,FORP |
| `R100` | `1010` | 🟡 review | DE | 288 | 2 target orgs for DE; picked S/4 best-practice | 0001,1010 |
| `Z000` | `1010` | 🟡 review | DE | 271 | 2 target orgs for DE; picked S/4 best-practice | 0001,1010 |
| `CPF1` | `1710` | 🟡 review | US | 117 | 4 target orgs for US; picked S/4 best-practice | 0003,1710,FOBP,FORP |
| `X100` | `1010` | 🟡 review | DE | 59 | 2 target orgs for DE; picked S/4 best-practice | 0001,1010 |
| `S300` | `1710` | 🟡 review | US | 41 | 4 target orgs for US; picked S/4 best-practice | 0003,1710,FOBP,FORP |
| `0005` | `1010` | 🟡 review | DE | 37 | 2 target orgs for DE; picked S/4 best-practice | 0001,1010 |
| `I001` | `1710` | 🟡 review | US | 26 | 4 target orgs for US; picked S/4 best-practice | 0003,1710,FOBP,FORP |
| `CPB1` | `1710` | 🟡 review | US | 26 | 4 target orgs for US; picked S/4 best-practice | 0003,1710,FOBP,FORP |
| `1030` | `1010` | 🟡 review | DE | 23 | 2 target orgs for DE; picked S/4 best-practice | 0001,1010 |
| `CPC1` | `1010` | 🟡 review | DE | 17 | 2 target orgs for DE; picked S/4 best-practice | 0001,1010 |
| `I002` | `1710` | 🟡 review | US | 16 | 4 target orgs for US; picked S/4 best-practice | 0003,1710,FOBP,FORP |
| `SO01` | `1710` | 🟡 review | US | 15 | 4 target orgs for US; picked S/4 best-practice | 0003,1710,FOBP,FORP |
| `SO02` | `1010` | 🟡 review | DE | 15 | 2 target orgs for DE; picked S/4 best-practice | 0001,1010 |
| `FS01` | `1010` | 🟡 review | DE | 15 | 2 target orgs for DE; picked S/4 best-practice | 0001,1010 |
| `SL31` | `1710` | 🟡 review | US | 13 | 4 target orgs for US; picked S/4 best-practice | 0003,1710,FOBP,FORP |
| `ZBD1` | `1010` | 🟡 review | DE | 4 | 2 target orgs for DE; picked S/4 best-practice | 0001,1010 |
| `FARR` | `1710` | 🟡 review | US | 4 | 4 target orgs for US; picked S/4 best-practice | 0003,1710,FOBP,FORP |
| `CPF2` | `1710` | 🟡 review | US | 3 | 4 target orgs for US; picked S/4 best-practice | 0003,1710,FOBP,FORP |
| `2821` | `1710` | 🟡 review | US | 2 | 4 target orgs for US; picked S/4 best-practice | 0003,1710,FOBP,FORP |
| `TM2` | `1010` | 🟡 review | DE | 1 | 2 target orgs for DE; picked S/4 best-practice | 0001,1010 |
| `0006` | `1710` | 🟡 review | US | 1 | 4 target orgs for US; picked S/4 best-practice | 0003,1710,FOBP,FORP |
| `3700` | `1710` | 🟡 review | US | 1 | 4 target orgs for US; picked S/4 best-practice | 0003,1710,FOBP,FORP |
| `2822` | `1710` | 🟡 review | US | 1 | 4 target orgs for US; picked S/4 best-practice | 0003,1710,FOBP,FORP |

## Plant (WERKS)

| source | → target | conf. | country | records | rationale | alternatives |
|---|---|---|---|---:|---|---|
| `2300` | `—` | 🔴 decision | ES | 1068 | no target org for country ES — create one, consolidate onto an existing target org, or skip these records |  |
| `2800` | `—` | 🔴 decision | CN | 669 | no target org for country CN — create one, consolidate onto an existing target org, or skip these records |  |
| `SG01` | `—` | 🔴 decision | SG | 592 | no target org for country SG — create one, consolidate onto an existing target org, or skip these records |  |
| `5000` | `—` | 🔴 decision | JP | 499 | no target org for country JP — create one, consolidate onto an existing target org, or skip these records |  |
| `7500` | `—` | 🔴 decision | AR | 409 | no target org for country AR — create one, consolidate onto an existing target org, or skip these records |  |
| `2400` | `—` | 🔴 decision | IT | 342 | no target org for country IT — create one, consolidate onto an existing target org, or skip these records |  |
| `2500` | `—` | 🔴 decision | NL | 340 | no target org for country NL — create one, consolidate onto an existing target org, or skip these records |  |
| `7000` | `—` | 🔴 decision | BR | 297 | no target org for country BR — create one, consolidate onto an existing target org, or skip these records |  |
| `6000` | `—` | 🔴 decision | MX | 286 | no target org for country MX — create one, consolidate onto an existing target org, or skip these records |  |
| `2200` | `—` | 🔴 decision | FR | 282 | no target org for country FR — create one, consolidate onto an existing target org, or skip these records |  |
| `3010` | `—` | 🔴 decision | BE | 226 | no target org for country BE — create one, consolidate onto an existing target org, or skip these records |  |
| `9000` | `—` | 🔴 decision | RU | 214 | no target org for country RU — create one, consolidate onto an existing target org, or skip these records |  |
| `2810` | `—` | 🔴 decision | CN | 180 | no target org for country CN — create one, consolidate onto an existing target org, or skip these records |  |
| `2000` | `—` | 🔴 decision | GB | 152 | no target org for country GB — create one, consolidate onto an existing target org, or skip these records |  |
| `7510` | `—` | 🔴 decision | AR | 149 | no target org for country AR — create one, consolidate onto an existing target org, or skip these records |  |
| `9100` | `—` | 🔴 decision | RU | 104 | no target org for country RU — create one, consolidate onto an existing target org, or skip these records |  |
| `4110` | `—` | 🔴 decision | KR | 96 | no target org for country KR — create one, consolidate onto an existing target org, or skip these records |  |
| `4300` | `—` | 🔴 decision | IN | 79 | no target org for country IN — create one, consolidate onto an existing target org, or skip these records |  |
| `4000` | `—` | 🔴 decision | CA | 69 | no target org for country CA — create one, consolidate onto an existing target org, or skip these records |  |
| `8500` | `—` | 🔴 decision | AU | 52 | no target org for country AU — create one, consolidate onto an existing target org, or skip these records |  |
| `4100` | `—` | 🔴 decision | CN | 45 | no target org for country CN — create one, consolidate onto an existing target org, or skip these records |  |
| `ZFOX` | `—` | 🔴 decision | CN | 41 | no target org for country CN — create one, consolidate onto an existing target org, or skip these records |  |
| `6100` | `—` | 🔴 decision | MX | 38 | no target org for country MX — create one, consolidate onto an existing target org, or skip these records |  |
| `2820` | `—` | 🔴 decision | CN | 33 | no target org for country CN — create one, consolidate onto an existing target org, or skip these records |  |
| `6702` | `—` | 🔴 decision | EG | 29 | no target org for country EG — create one, consolidate onto an existing target org, or skip these records |  |
| `2840` | `—` | 🔴 decision | HK | 29 | no target org for country HK — create one, consolidate onto an existing target org, or skip these records |  |
| `7530` | `—` | 🔴 decision | AR | 28 | no target org for country AR — create one, consolidate onto an existing target org, or skip these records |  |
| `7010` | `—` | 🔴 decision | BR | 27 | no target org for country BR — create one, consolidate onto an existing target org, or skip these records |  |
| `2010` | `—` | 🔴 decision | GB | 27 | no target org for country GB — create one, consolidate onto an existing target org, or skip these records |  |
| `6710` | `—` | 🔴 decision | EG | 23 | no target org for country EG — create one, consolidate onto an existing target org, or skip these records |  |
| `IN47` | `—` | 🔴 decision | IN | 22 | no target org for country IN — create one, consolidate onto an existing target org, or skip these records |  |
| `7520` | `—` | 🔴 decision | AR | 22 | no target org for country AR — create one, consolidate onto an existing target org, or skip these records |  |
| `7011` | `—` | 🔴 decision | BR | 20 | no target org for country BR — create one, consolidate onto an existing target org, or skip these records |  |
| `S330` | `—` | 🔴 decision | IT | 19 | no target org for country IT — create one, consolidate onto an existing target org, or skip these records |  |
| `6700` | `—` | 🔴 decision | EG | 17 | no target org for country EG — create one, consolidate onto an existing target org, or skip these records |  |
| `C100` | `—` | 🔴 decision | CN | 16 | no target org for country CN — create one, consolidate onto an existing target org, or skip these records |  |
| `CPC3` | `—` | 🔴 decision | FR | 16 | no target org for country FR — create one, consolidate onto an existing target org, or skip these records |  |
| `2100` | `—` | 🔴 decision | PT | 13 | no target org for country PT — create one, consolidate onto an existing target org, or skip these records |  |
| `6650` | `—` | 🔴 decision | SA | 13 | no target org for country SA — create one, consolidate onto an existing target org, or skip these records |  |
| `S331` | `—` | 🔴 decision | IT | 13 | no target org for country IT — create one, consolidate onto an existing target org, or skip these records |  |
| `6651` | `—` | 🔴 decision | SA | 11 | no target org for country SA — create one, consolidate onto an existing target org, or skip these records |  |
| `6652` | `—` | 🔴 decision | SA | 11 | no target org for country SA — create one, consolidate onto an existing target org, or skip these records |  |
| `2210` | `—` | 🔴 decision | FR | 11 | no target org for country FR — create one, consolidate onto an existing target org, or skip these records |  |
| `7540` | `—` | 🔴 decision | CL | 11 | no target org for country CL — create one, consolidate onto an existing target org, or skip these records |  |
| `8522` | `—` | 🔴 decision | AU | 11 | no target org for country AU — create one, consolidate onto an existing target org, or skip these records |  |
| `2505` | `—` | 🔴 decision | NL | 11 | no target org for country NL — create one, consolidate onto an existing target org, or skip these records |  |
| `3050` | `—` | 🔴 decision | GB | 10 | no target org for country GB — create one, consolidate onto an existing target org, or skip these records |  |
| `2830` | `—` | 🔴 decision | IN | 10 | no target org for country IN — create one, consolidate onto an existing target org, or skip these records |  |
| `7550` | `—` | 🔴 decision | CO | 10 | no target org for country CO — create one, consolidate onto an existing target org, or skip these records |  |
| `5410` | `—` | 🔴 decision | NL | 9 | no target org for country NL — create one, consolidate onto an existing target org, or skip these records |  |
| `6712` | `—` | 🔴 decision | EG | 8 | no target org for country EG — create one, consolidate onto an existing target org, or skip these records |  |
| `2220` | `—` | 🔴 decision | FR | 7 | no target org for country FR — create one, consolidate onto an existing target org, or skip these records |  |
| `5100` | `—` | 🔴 decision | JP | 7 | no target org for country JP — create one, consolidate onto an existing target org, or skip these records |  |
| `DC04` | `—` | 🔴 decision | IT | 7 | no target org for country IT — create one, consolidate onto an existing target org, or skip these records |  |
| `DC05` | `—` | 🔴 decision | FR | 7 | no target org for country FR — create one, consolidate onto an existing target org, or skip these records |  |
| `S332` | `—` | 🔴 decision | IT | 7 | no target org for country IT — create one, consolidate onto an existing target org, or skip these records |  |
| `6750` | `—` | 🔴 decision | AE | 6 | no target org for country AE — create one, consolidate onto an existing target org, or skip these records |  |
| `6751` | `—` | 🔴 decision | AE | 6 | no target org for country AE — create one, consolidate onto an existing target org, or skip these records |  |
| `6752` | `—` | 🔴 decision | AE | 6 | no target org for country AE — create one, consolidate onto an existing target org, or skip these records |  |
| `6753` | `—` | 🔴 decision | AE | 6 | no target org for country AE — create one, consolidate onto an existing target org, or skip these records |  |
| `6754` | `—` | 🔴 decision | AE | 6 | no target org for country AE — create one, consolidate onto an existing target org, or skip these records |  |
| `2240` | `—` | 🔴 decision | FR | 6 | no target org for country FR — create one, consolidate onto an existing target org, or skip these records |  |
| `4510` | `—` | 🔴 decision | CA | 6 | no target org for country CA — create one, consolidate onto an existing target org, or skip these records |  |
| `DC06` | `—` | 🔴 decision | GB | 6 | no target org for country GB — create one, consolidate onto an existing target org, or skip these records |  |
| `6755` | `—` | 🔴 decision | AE | 5 | no target org for country AE — create one, consolidate onto an existing target org, or skip these records |  |
| `2230` | `—` | 🔴 decision | FR | 5 | no target org for country FR — create one, consolidate onto an existing target org, or skip these records |  |
| `4520` | `—` | 🔴 decision | CA | 5 | no target org for country CA — create one, consolidate onto an existing target org, or skip these records |  |
| `4530` | `—` | 🔴 decision | CA | 5 | no target org for country CA — create one, consolidate onto an existing target org, or skip these records |  |
| `4540` | `—` | 🔴 decision | CA | 5 | no target org for country CA — create one, consolidate onto an existing target org, or skip these records |  |
| `6101` | `—` | 🔴 decision | MX | 4 | no target org for country MX — create one, consolidate onto an existing target org, or skip these records |  |
| `S333` | `—` | 🔴 decision | IT | 4 | no target org for country IT — create one, consolidate onto an existing target org, or skip these records |  |
| `S334` | `—` | 🔴 decision | IT | 4 | no target org for country IT — create one, consolidate onto an existing target org, or skip these records |  |
| `S335` | `—` | 🔴 decision | IT | 4 | no target org for country IT — create one, consolidate onto an existing target org, or skip these records |  |
| `7031` | `—` | 🔴 decision | BR | 3 | no target org for country BR — create one, consolidate onto an existing target org, or skip these records |  |
| `6701` | `—` | 🔴 decision | EG | 3 | no target org for country EG — create one, consolidate onto an existing target org, or skip these records |  |
| `CHD7` | `—` | 🔴 decision | BR | 3 | no target org for country BR — create one, consolidate onto an existing target org, or skip these records |  |
| `2222` | `—` | 🔴 decision | FR | 3 | no target org for country FR — create one, consolidate onto an existing target org, or skip these records |  |
| `IN48` | `—` | 🔴 decision | IN | 2 | no target org for country IN — create one, consolidate onto an existing target org, or skip these records |  |
| `1901` | `—` | 🔴 decision |  | 2 | no target org for country (unknown) — create one, consolidate onto an existing target org, or skip these records |  |
| `7100` | `—` | 🔴 decision | BR | 2 | no target org for country BR — create one, consolidate onto an existing target org, or skip these records |  |
| `5420` | `—` | 🔴 decision | NL | 2 | no target org for country NL — create one, consolidate onto an existing target org, or skip these records |  |
| `8533` | `—` | 🔴 decision | AU | 2 | no target org for country AU — create one, consolidate onto an existing target org, or skip these records |  |
| `2835` | `—` | 🔴 decision | CN | 2 | no target org for country CN — create one, consolidate onto an existing target org, or skip these records |  |
| `7535` | `—` | 🔴 decision | AR | 2 | no target org for country AR — create one, consolidate onto an existing target org, or skip these records |  |
| `6711` | `—` | 🔴 decision | EG | 2 | no target org for country EG — create one, consolidate onto an existing target org, or skip these records |  |
| `REST` | `—` | 🔴 decision |  | 2 | no target org for country (unknown) — create one, consolidate onto an existing target org, or skip these records |  |
| `6703` | `—` | 🔴 decision | EG | 1 | no target org for country EG — create one, consolidate onto an existing target org, or skip these records |  |
| `6102` | `—` | 🔴 decision | MX | 1 | no target org for country MX — create one, consolidate onto an existing target org, or skip these records |  |
| `2730` | `—` | 🔴 decision | CH | 1 | no target org for country CH — create one, consolidate onto an existing target org, or skip these records |  |
| `6201` | `—` | 🔴 decision | MX | 1 | no target org for country MX — create one, consolidate onto an existing target org, or skip these records |  |
| `SCA1` | `—` | 🔴 decision | HK | 1 | no target org for country HK — create one, consolidate onto an existing target org, or skip these records |  |
| `SCL1` | `—` | 🔴 decision | AR | 1 | no target org for country AR — create one, consolidate onto an existing target org, or skip these records |  |
| `ZDC2` | `—` | 🔴 decision |  | 1 | no target org for country (unknown) — create one, consolidate onto an existing target org, or skip these records |  |
| `8524` | `—` | 🔴 decision | AU | 1 | no target org for country AU — create one, consolidate onto an existing target org, or skip these records |  |
| `8536` | `—` | 🔴 decision | AU | 1 | no target org for country AU — create one, consolidate onto an existing target org, or skip these records |  |
| `8581` | `—` | 🔴 decision | AU | 1 | no target org for country AU — create one, consolidate onto an existing target org, or skip these records |  |
| `8591` | `—` | 🔴 decision | NZ | 1 | no target org for country NZ — create one, consolidate onto an existing target org, or skip these records |  |
| `8592` | `—` | 🔴 decision | NZ | 1 | no target org for country NZ — create one, consolidate onto an existing target org, or skip these records |  |
| `4310` | `—` | 🔴 decision | IN | 1 | no target org for country IN — create one, consolidate onto an existing target org, or skip these records |  |
| `4200` | `—` | 🔴 decision | JP | 1 | no target org for country JP — create one, consolidate onto an existing target org, or skip these records |  |
| `9099` | `—` | 🔴 decision |  | 1 | no target org for country (unknown) — create one, consolidate onto an existing target org, or skip these records |  |
| `1000` | `1010` | 🟡 review | DE | 6654 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `3000` | `1710` | 🟡 review | US | 4468 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `1200` | `1010` | 🟡 review | DE | 3125 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `1100` | `1010` | 🟡 review | DE | 2931 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `0001` | `1010` | 🟡 review | DE | 2275 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `3200` | `1710` | 🟡 review | US | 1929 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `0002` | `1010` | 🟡 review | DE | 1332 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `3800` | `1710` | 🟡 review | US | 1256 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `3100` | `1710` | 🟡 review | US | 905 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `1300` | `1010` | 🟡 review | DE | 310 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `3500` | `1710` | 🟡 review | US | 240 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `3400` | `1710` | 🟡 review | US | 154 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `3700` | `1710` | 🟡 review | US | 143 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `RFDC` | `1710` | 🟡 review | US | 102 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `RFST` | `1710` | 🟡 review | US | 101 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `3300` | `1710` | 🟡 review | US | 90 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `3600` | `1710` | 🟡 review | US | 85 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `1400` | `1010` | 🟡 review | DE | 77 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `0005` | `1010` | 🟡 review | DE | 74 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `R100` | `1010` | 🟡 review | DE | 65 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `R314` | `1710` | 🟡 review | US | 61 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `R101` | `1010` | 🟡 review | DE | 60 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `R310` | `1710` | 🟡 review | US | 60 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `R311` | `1710` | 🟡 review | US | 60 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `R312` | `1710` | 🟡 review | US | 60 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `R313` | `1710` | 🟡 review | US | 60 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `R315` | `1710` | 🟡 review | US | 60 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `R316` | `1710` | 🟡 review | US | 60 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `XLP1` | `1010` | 🟡 review | DE | 59 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `CPF3` | `1710` | 🟡 review | US | 57 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `CPF2` | `1710` | 🟡 review | US | 57 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `R300` | `1710` | 🟡 review | US | 51 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `R301` | `1710` | 🟡 review | US | 51 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `CHP1` | `1010` | 🟡 review | DE | 47 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `R110` | `1010` | 🟡 review | DE | 47 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `R111` | `1010` | 🟡 review | DE | 47 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `R112` | `1010` | 🟡 review | DE | 47 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `S300` | `1710` | 🟡 review | US | 41 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `CHP2` | `1010` | 🟡 review | DE | 40 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `0006` | `1710` | 🟡 review | US | 35 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `CPF1` | `1710` | 🟡 review | US | 29 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `CPC2` | `1010` | 🟡 review | DE | 28 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `R320` | `1710` | 🟡 review | US | 27 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `CPB1` | `1710` | 🟡 review | US | 26 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `CPF4` | `1710` | 🟡 review | US | 25 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `1500` | `1010` | 🟡 review | DE | 24 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `R120` | `1010` | 🟡 review | DE | 22 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `R121` | `1010` | 🟡 review | DE | 22 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `CPC1` | `1010` | 🟡 review | DE | 20 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `0007` | `1010` | 🟡 review | DE | 18 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `0008` | `1710` | 🟡 review | US | 18 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `SL31` | `1710` | 🟡 review | US | 17 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `PL01` | `1710` | 🟡 review | US | 17 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `PL02` | `1010` | 🟡 review | DE | 17 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `CHD2` | `1010` | 🟡 review | DE | 16 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `CHD3` | `1010` | 🟡 review | DE | 15 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `CPF5` | `1710` | 🟡 review | US | 13 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `S360` | `1710` | 🟡 review | US | 13 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `CHD1` | `1010` | 🟡 review | DE | 11 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `CHP3` | `1010` | 🟡 review | DE | 9 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `3350` | `1710` | 🟡 review | US | 9 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `CHP4` | `1710` | 🟡 review | US | 8 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `S320` | `1710` | 🟡 review | US | 8 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `3150` | `1710` | 🟡 review | US | 8 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `AC00` | `1010` | 🟡 review | DE | 7 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `3105` | `1710` | 🟡 review | US | 7 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `DC01` | `1710` | 🟡 review | US | 7 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `DC02` | `1710` | 🟡 review | US | 7 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `PL05` | `1710` | 🟡 review | US | 7 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `1600` | `1010` | 🟡 review | DE | 6 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `DC03` | `1710` | 🟡 review | US | 6 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `S361` | `1710` | 🟡 review | US | 6 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `ZCBM` | `1010` | 🟡 review | DE | 4 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `CHD4` | `1710` | 🟡 review | US | 4 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `FARR` | `1710` | 🟡 review | US | 4 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `ZBP1` | `1010` | 🟡 review | DE | 3 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `ZCMU` | `1710` | 🟡 review | US | 3 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `2821` | `1010` | 🟡 review | DE | 2 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `BRF1` | `1710` | 🟡 review | US | 2 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `ZBRF` | `1710` | 🟡 review | US | 2 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `SCU1` | `1710` | 🟡 review | US | 2 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `3110` | `1710` | 🟡 review | US | 2 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `3999` | `1710` | 🟡 review | US | 2 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `ZTEW` | `1710` | 🟡 review | US | 2 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `3850` | `1710` | 🟡 review | US | 2 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `SL39` | `1710` | 🟡 review | US | 1 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `3111` | `1710` | 🟡 review | US | 1 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `3112` | `1710` | 🟡 review | US | 1 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `C_P1` | `1710` | 🟡 review | US | 1 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `3997` | `1710` | 🟡 review | US | 1 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `3998` | `1710` | 🟡 review | US | 1 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `PL04` | `1010` | 🟡 review | DE | 1 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `HANA` | `1010` | 🟡 review | DE | 1 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `SCE1` | `1010` | 🟡 review | DE | 1 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `3750` | `1710` | 🟡 review | US | 1 | 7 target orgs for US; picked S/4 best-practice | 0003,1710,1711,1712,1720,FOBP,FORP |
| `AC01` | `1010` | 🟡 review | DE | 1 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `AC02` | `1010` | 🟡 review | DE | 1 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `AC03` | `1010` | 🟡 review | DE | 1 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `AC04` | `1010` | 🟡 review | DE | 1 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `AC05` | `1010` | 🟡 review | DE | 1 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `AC06` | `1010` | 🟡 review | DE | 1 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `AC07` | `1010` | 🟡 review | DE | 1 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `AC08` | `1010` | 🟡 review | DE | 1 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `AC09` | `1010` | 🟡 review | DE | 1 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `AC10` | `1010` | 🟡 review | DE | 1 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `AC11` | `1010` | 🟡 review | DE | 1 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `AC12` | `1010` | 🟡 review | DE | 1 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `AC13` | `1010` | 🟡 review | DE | 1 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `AC14` | `1010` | 🟡 review | DE | 1 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `AC15` | `1010` | 🟡 review | DE | 1 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `AC16` | `1010` | 🟡 review | DE | 1 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `AC17` | `1010` | 🟡 review | DE | 1 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `AC18` | `1010` | 🟡 review | DE | 1 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `AC19` | `1010` | 🟡 review | DE | 1 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `AC20` | `1010` | 🟡 review | DE | 1 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `AC21` | `1010` | 🟡 review | DE | 1 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `AC22` | `1010` | 🟡 review | DE | 1 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `AC23` | `1010` | 🟡 review | DE | 1 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `AC24` | `1010` | 🟡 review | DE | 1 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `AC25` | `1010` | 🟡 review | DE | 1 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `AC26` | `1010` | 🟡 review | DE | 1 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `AC27` | `1010` | 🟡 review | DE | 1 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `AC28` | `1010` | 🟡 review | DE | 1 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `AC29` | `1010` | 🟡 review | DE | 1 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `AC30` | `1010` | 🟡 review | DE | 1 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |
| `2822` | `1010` | 🟡 review | DE | 1 | 5 target orgs for DE; picked S/4 best-practice | 0001,1010,1011,1012,1020 |

## Distribution channel (VTWEG)

| source | → target | conf. | country | records | rationale | alternatives |
|---|---|---|---|---:|---|---|
| `30` | `10` | 🟡 review |  | 2420 | not on target; collapse to canonical channel 10 | 01,10 |
| `14` | `10` | 🟡 review |  | 1477 | not on target; collapse to canonical channel 10 | 01,10 |
| `12` | `10` | 🟡 review |  | 1199 | not on target; collapse to canonical channel 10 | 01,10 |
| `Z0` | `10` | 🟡 review |  | 271 | not on target; collapse to canonical channel 10 | 01,10 |
| `24` | `10` | 🟡 review |  | 248 | not on target; collapse to canonical channel 10 | 01,10 |
| `R1` | `10` | 🟡 review |  | 152 | not on target; collapse to canonical channel 10 | 01,10 |
| `R5` | `10` | 🟡 review |  | 152 | not on target; collapse to canonical channel 10 | 01,10 |
| `R4` | `10` | 🟡 review |  | 135 | not on target; collapse to canonical channel 10 | 01,10 |
| `R6` | `10` | 🟡 review |  | 134 | not on target; collapse to canonical channel 10 | 01,10 |
| `C1` | `10` | 🟡 review |  | 120 | not on target; collapse to canonical channel 10 | 01,10 |
| `22` | `10` | 🟡 review |  | 72 | not on target; collapse to canonical channel 10 | 01,10 |
| `20` | `10` | 🟡 review |  | 61 | not on target; collapse to canonical channel 10 | 01,10 |
| `X1` | `10` | 🟡 review |  | 59 | not on target; collapse to canonical channel 10 | 01,10 |
| `40` | `10` | 🟡 review |  | 53 | not on target; collapse to canonical channel 10 | 01,10 |
| `S3` | `10` | 🟡 review |  | 41 | not on target; collapse to canonical channel 10 | 01,10 |
| `R2` | `10` | 🟡 review |  | 40 | not on target; collapse to canonical channel 10 | 01,10 |
| `16` | `10` | 🟡 review |  | 36 | not on target; collapse to canonical channel 10 | 01,10 |
| `CB` | `10` | 🟡 review |  | 26 | not on target; collapse to canonical channel 10 | 01,10 |
| `C2` | `10` | 🟡 review |  | 20 | not on target; collapse to canonical channel 10 | 01,10 |
| `S1` | `10` | 🟡 review |  | 19 | not on target; collapse to canonical channel 10 | 01,10 |
| `L1` | `10` | 🟡 review |  | 15 | not on target; collapse to canonical channel 10 | 01,10 |
| `BD` | `10` | 🟡 review |  | 4 | not on target; collapse to canonical channel 10 | 01,10 |
| `Z1` | `10` | 🟡 review |  | 1 | not on target; collapse to canonical channel 10 | 01,10 |
| `10` | `10` | ✅ auto |  | 7080 | same value exists on target |  |
| `01` | `01` | ✅ auto |  | 2045 | same value exists on target |  |

## Division (SPART)

| source | → target | conf. | country | records | rationale | alternatives |
|---|---|---|---|---:|---|---|
| `07` | `00` | 🟡 review |  | 2913 | not on target; collapse to canonical division 00 | 00,01 |
| `02` | `00` | 🟡 review |  | 535 | not on target; collapse to canonical division 00 | 00,01 |
| `13` | `00` | 🟡 review |  | 409 | not on target; collapse to canonical division 00 | 00,01 |
| `10` | `00` | 🟡 review |  | 198 | not on target; collapse to canonical division 00 | 00,01 |
| `04` | `00` | 🟡 review |  | 194 | not on target; collapse to canonical division 00 | 00,01 |
| `06` | `00` | 🟡 review |  | 161 | not on target; collapse to canonical division 00 | 00,01 |
| `08` | `00` | 🟡 review |  | 133 | not on target; collapse to canonical division 00 | 00,01 |
| `20` | `00` | 🟡 review |  | 115 | not on target; collapse to canonical division 00 | 00,01 |
| `17` | `00` | 🟡 review |  | 109 | not on target; collapse to canonical division 00 | 00,01 |
| `15` | `00` | 🟡 review |  | 108 | not on target; collapse to canonical division 00 | 00,01 |
| `R1` | `00` | 🟡 review |  | 101 | not on target; collapse to canonical division 00 | 00,01 |
| `18` | `00` | 🟡 review |  | 83 | not on target; collapse to canonical division 00 | 00,01 |
| `05` | `00` | 🟡 review |  | 62 | not on target; collapse to canonical division 00 | 00,01 |
| `XL` | `00` | 🟡 review |  | 59 | not on target; collapse to canonical division 00 | 00,01 |
| `30` | `00` | 🟡 review |  | 59 | not on target; collapse to canonical division 00 | 00,01 |
| `03` | `00` | 🟡 review |  | 58 | not on target; collapse to canonical division 00 | 00,01 |
| `09` | `00` | 🟡 review |  | 53 | not on target; collapse to canonical division 00 | 00,01 |
| `12` | `00` | 🟡 review |  | 42 | not on target; collapse to canonical division 00 | 00,01 |
| `S3` | `00` | 🟡 review |  | 30 | not on target; collapse to canonical division 00 | 00,01 |
| `I1` | `00` | 🟡 review |  | 21 | not on target; collapse to canonical division 00 | 00,01 |
| `S1` | `00` | 🟡 review |  | 19 | not on target; collapse to canonical division 00 | 00,01 |
| `AM` | `00` | 🟡 review |  | 17 | not on target; collapse to canonical division 00 | 00,01 |
| `16` | `00` | 🟡 review |  | 13 | not on target; collapse to canonical division 00 | 00,01 |
| `50` | `00` | 🟡 review |  | 7 | not on target; collapse to canonical division 00 | 00,01 |
| `40` | `00` | 🟡 review |  | 5 | not on target; collapse to canonical division 00 | 00,01 |
| `14` | `00` | 🟡 review |  | 3 | not on target; collapse to canonical division 00 | 00,01 |
| `28` | `00` | 🟡 review |  | 1 | not on target; collapse to canonical division 00 | 00,01 |
| `A1` | `00` | 🟡 review |  | 1 | not on target; collapse to canonical division 00 | 00,01 |
| `Z1` | `00` | 🟡 review |  | 1 | not on target; collapse to canonical division 00 | 00,01 |
| `19` | `00` | 🟡 review |  | 1 | not on target; collapse to canonical division 00 | 00,01 |
| `01` | `01` | ✅ auto |  | 4042 | same value exists on target |  |
| `00` | `00` | ✅ auto |  | 1797 | same value exists on target |  |
