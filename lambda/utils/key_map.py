"""
key_map — the source->target key registry (first-class migration artifact).

When a migration can't retain a source key (internal number assignment for BPs, or a
collision remap for materials), the target key differs from the source. Every dependent
object must then follow that translation: a sales order's customer KUNNR -> the new BP
partner; a BOM's component MATNR -> its remapped material; an open item's vendor LIFNR
-> the new BP. And auditors must be able to read exactly what became what.

This registry is that single source of truth. Loaders emit per-record key_mappings
(source, target, disposition); the run persists them here as a queryable CSV + JSON, and
later stages reload it to resolve referenced keys. Namespaced per object so Customer 100
and Vendor 100 never clash.

Dispositions: created | matched_existing | remapped | remapped_matched | collision_skipped ...
"""
from __future__ import annotations
from collections import Counter


class KeyMap:
    def __init__(self):
        self._m = {}   # object -> { source_key -> {"target":.., "disposition":..} }

    def add(self, obj: str, source, target, disposition: str = "") -> None:
        if obj is None or source is None or str(source).strip() == "":
            return
        self._m.setdefault(obj, {})[str(source).strip()] = {
            "target": (str(target).strip() if target is not None else None),
            "disposition": disposition or "",
        }

    def add_many(self, obj: str, mappings: list) -> None:
        for km in mappings or []:
            self.add(obj, km.get("source"), km.get("target"), km.get("disposition"))

    def resolve(self, obj: str, source, default=None):
        """Target key for a source key. default=None lets callers decide whether an
        unmapped reference is a hard error or a pass-through."""
        entry = self._m.get(obj, {}).get(str(source).strip())
        return entry["target"] if entry else default

    def disposition(self, obj: str, source):
        entry = self._m.get(obj, {}).get(str(source).strip())
        return entry["disposition"] if entry else None

    # ── serialize / rebuild ──────────────────────────────────────────────────
    def to_dict(self) -> dict:
        return self._m

    def to_rows(self) -> list:
        rows = []
        for obj, d in self._m.items():
            for src, e in d.items():
                rows.append({"OBJECT": obj, "SOURCE_KEY": src,
                             "TARGET_KEY": e.get("target") or "",
                             "DISPOSITION": e.get("disposition") or ""})
        return rows

    def to_csv(self) -> str:
        lines = ["OBJECT,SOURCE_KEY,TARGET_KEY,DISPOSITION"]
        lines += [f"{r['OBJECT']},{r['SOURCE_KEY']},{r['TARGET_KEY']},{r['DISPOSITION']}"
                  for r in self.to_rows()]
        return "\n".join(lines) + "\n"

    @classmethod
    def from_dict(cls, d: dict) -> "KeyMap":
        km = cls()
        km._m = d or {}
        return km

    @classmethod
    def from_rows(cls, rows: list) -> "KeyMap":
        km = cls()
        for r in rows:
            km.add(r.get("OBJECT"), r.get("SOURCE_KEY"), r.get("TARGET_KEY"), r.get("DISPOSITION"))
        return km

    def stats(self) -> dict:
        by_disp = Counter()
        remapped = 0
        for d in self._m.values():
            for e in d.values():
                by_disp[e.get("disposition")] += 1
                if "remap" in (e.get("disposition") or ""):
                    remapped += 1
        return {"objects": sorted(self._m.keys()),
                "total_mappings": sum(len(d) for d in self._m.values()),
                "remapped": remapped,
                "by_disposition": dict(by_disp)}
