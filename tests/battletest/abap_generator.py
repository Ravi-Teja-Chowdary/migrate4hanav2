"""
Battle-test synthetic ABAP code generator.

Produces synthetic Z-programs with realistic legacy patterns to exercise the
code-analyzer pipeline end-to-end at scale. Sized for a real-environment
battletest: 100-1000 programs of mixed difficulty.

Difficulty mix (default 60/30/10)
---------------------------------
- AUTO_FIXABLE       : deterministic AST engine handles these without escalation
- AST_PASS_FLAGGED   : parse fine but with deprecated patterns the ATC gate flags
- BROKEN             : deliberately malformed; AI fallback (Claude) has to step in

Realistic patterns embedded
---------------------------
- Native SQL (EXEC SQL ... ENDEXEC)
- Obsolete FMs (DOWNLOAD / UPLOAD / WS_DOWNLOAD)
- CALL SCREEN (Dynpro)
- SELECT * without WHERE
- LOOP AT internal-table without END handling
- Database hints (%_HINTS)
- Sensitive data inline (passwords, IPs, emails) - tests pseudonymizer
- Macro abuse + nested FORM definitions
- Old-style WRITE statements

CLI:
    python abap_generator.py --count 100   --out tests/battletest/abap-suite/
    python abap_generator.py --count 1000  --out tests/battletest/abap-suite/  # stress
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import List


# ─────────────────────────────────────────────────────────────────────────────
#  Templates by difficulty
# ─────────────────────────────────────────────────────────────────────────────
AUTO_FIXABLE_TEMPLATES = [
    """REPORT z{name}.
DATA lt_mara TYPE STANDARD TABLE OF mara.
SELECT * FROM mara INTO TABLE lt_mara WHERE mtart = '{mtart}'.
LOOP AT lt_mara INTO DATA(ls_mara).
  WRITE: / ls_mara-matnr, ls_mara-mtart.
ENDLOOP.
""",
    """REPORT z{name}.
DATA: lt_kna1 TYPE STANDARD TABLE OF kna1,
      ls_kna1 TYPE kna1.
SELECT * FROM kna1 INTO TABLE lt_kna1 WHERE land1 = '{country}'.
LOOP AT lt_kna1 INTO ls_kna1.
  WRITE: / ls_kna1-kunnr, ls_kna1-name1.
ENDLOOP.
""",
    """REPORT z{name}.
PERFORM process_customers.
FORM process_customers.
  DATA lt_kna1 TYPE STANDARD TABLE OF kna1.
  SELECT * FROM kna1 INTO TABLE lt_kna1.
  LOOP AT lt_kna1 ASSIGNING FIELD-SYMBOL(<fs>).
    WRITE / <fs>-kunnr.
  ENDLOOP.
ENDFORM.
""",
    """REPORT z{name}.
DATA: lv_today TYPE sy-datum,
      lv_yest  TYPE sy-datum.
lv_today = sy-datum.
lv_yest  = lv_today - 1.
WRITE: / 'today:', lv_today, '/ yesterday:', lv_yest.
""",
]

AST_PASS_FLAGGED_TEMPLATES = [
    """REPORT z{name}.
DATA lt TYPE STANDARD TABLE OF mara.
SELECT * FROM mara INTO TABLE lt.   " SELECT * - ATC flag (priority 3)
LOOP AT lt INTO DATA(ls).
  WRITE: / ls-matnr.
ENDLOOP.
""",
    """REPORT z{name}.
DATA lv_count TYPE i.
EXEC SQL.
  SELECT COUNT(*) FROM mara INTO :lv_count
ENDEXEC.
WRITE: / 'Count: ', lv_count.
""",
    """REPORT z{name}.
DATA lv_input TYPE string.
CALL SCREEN 100.
MODULE status_0100 OUTPUT.
  SET PF-STATUS 'STATUS_100'.
ENDMODULE.
MODULE user_command_0100 INPUT.
  CASE sy-ucomm.
    WHEN 'EXIT'.
      LEAVE PROGRAM.
  ENDCASE.
ENDMODULE.
""",
    """REPORT z{name}.
DATA: lt_data TYPE STANDARD TABLE OF string,
      lv_file TYPE string VALUE '{filename}'.
CALL FUNCTION 'DOWNLOAD'
  EXPORTING
    filename = lv_file
  TABLES
    data_tab = lt_data.
""",
    """REPORT z{name}.
DATA: lv_url   TYPE string VALUE 'https://internal.example.com/api',
      lv_user  TYPE string VALUE 'sapuser',
      lv_pass  TYPE string VALUE 'P@ssw0rd123',
      lv_email TYPE string VALUE 'admin@example.com',
      lv_ip    TYPE string VALUE '10.0.0.42'.
SELECT * FROM mara INTO TABLE @DATA(lt_mara).
WRITE: / 'Loaded from', lv_url.
""",
    """REPORT z{name}.
DATA lt TYPE STANDARD TABLE OF kna1.
SELECT * FROM kna1 INTO TABLE lt %_HINTS ORACLE 'INDEX("KNA1" "KNA1~Z01")'.
LOOP AT lt INTO DATA(ls).
  WRITE / ls-kunnr.
ENDLOOP.
""",
]

BROKEN_TEMPLATES = [
    """REPORT z{name}.
DATA lt TYPE STANDARD TABLE OF mara.
SELECT * FROM mara INTO TABLE lt.
LOOP AT lt INTO DATA(ls).
  WRITE: / ls-matnr.
* missing ENDLOOP - deliberate
WRITE 'after loop'.
""",
    """REPORT z{name}.
DATA lv_x TYPE i.
IF lv_x > 0.
  WRITE 'positive'.
ELSEIF lv_x < 0.
  WRITE 'negative'.
* missing ENDIF
WRITE 'always runs'.
""",
    """REPORT z{name}.
PERFORM compute_total.
FORM compute_total
* missing trailing dot + USING - parser crash
  DATA lv_total TYPE i.
  lv_total = 1 + 2.
ENDFORM.
""",
    """REPORT z{name}.
DATA: lv_a TYPE i,
      lv_b TYPE string.
MOVE lv_a TO lv_b lv_a.   " too many operands - parser dies
WRITE lv_b.
""",
]


# ─────────────────────────────────────────────────────────────────────────────
#  Generator
# ─────────────────────────────────────────────────────────────────────────────
def gen_program(idx: int, difficulty: str, rng: random.Random) -> dict:
    if difficulty == "AUTO_FIXABLE":
        tmpl = rng.choice(AUTO_FIXABLE_TEMPLATES)
    elif difficulty == "AST_PASS_FLAGGED":
        tmpl = rng.choice(AST_PASS_FLAGGED_TEMPLATES)
    elif difficulty == "BROKEN":
        tmpl = rng.choice(BROKEN_TEMPLATES)
    else:
        raise ValueError(f"unknown difficulty: {difficulty}")

    name = f"BATTLETEST_{idx:04d}"
    src = tmpl.format(
        name=name.lower(),
        mtart=rng.choice(["FERT", "HALB", "ROH"]),
        country=rng.choice(["DE", "US", "GB", "FR"]),
        filename=f"C:\\\\temp\\\\export_{idx}.txt",
    )

    return {
        "name": name,
        "difficulty": difficulty,
        "abap_source": src,
        "line_count": src.count("\n") + 1,
        "expected_outcome": {
            "AUTO_FIXABLE":      "deterministic_remediate_pass",
            "AST_PASS_FLAGGED":  "deterministic_pass_with_atc_warnings",
            "BROKEN":            "ai_fallback_invoked",
        }[difficulty],
    }


def generate_suite(count: int, out_dir: Path, seed: int = 42) -> dict:
    rng = random.Random(seed)
    out_dir.mkdir(parents=True, exist_ok=True)

    auto = int(count * 0.60)
    flagged = int(count * 0.30)
    broken = count - auto - flagged

    programs: List[dict] = []
    for i in range(auto):
        programs.append(gen_program(i, "AUTO_FIXABLE", rng))
    for i in range(auto, auto + flagged):
        programs.append(gen_program(i, "AST_PASS_FLAGGED", rng))
    for i in range(auto + flagged, count):
        programs.append(gen_program(i, "BROKEN", rng))
    rng.shuffle(programs)

    for p in programs:
        (out_dir / f"{p['name']}.abap").write_text(p["abap_source"], encoding="utf-8")

    catalog = {
        "count": len(programs),
        "split": {"AUTO_FIXABLE": auto, "AST_PASS_FLAGGED": flagged, "BROKEN": broken},
        "programs": [{k: v for k, v in p.items() if k != "abap_source"}
                     for p in programs],
    }
    (out_dir / "catalog.json").write_text(
        json.dumps(catalog, indent=2), encoding="utf-8")
    return catalog


def main():
    ap = argparse.ArgumentParser(description="Generate synthetic ABAP suite for battletest.")
    ap.add_argument("--count", type=int, default=100)
    ap.add_argument("--out", default="tests/battletest/abap-suite")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    catalog = generate_suite(args.count, Path(args.out), seed=args.seed)
    print(f"Generated {catalog['count']} synthetic Z-programs in {args.out}/")
    print(f"  AUTO_FIXABLE:      {catalog['split']['AUTO_FIXABLE']:>4d}  (AST engine handles)")
    print(f"  AST_PASS_FLAGGED:  {catalog['split']['AST_PASS_FLAGGED']:>4d}  (parses but ATC flags)")
    print(f"  BROKEN:            {catalog['split']['BROKEN']:>4d}  (AI fallback expected)")
    print(f"Catalog: {args.out}/catalog.json")


if __name__ == "__main__":
    main()
