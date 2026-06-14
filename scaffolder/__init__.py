"""
Migrate4HANA Object Scaffolder
==============================

Deterministic code generator that turns a single JSON object definition into a
drop-in spine orchestrator + unit tests + integration test + lane templates.

The scaffolder is the multiplier called out in design/SCAFFOLDER_SPEC.md: it
collapses each new SAP migration object from ~1 week of hand-coding to ~half
a day of authoring a JSON definition.

Entry point: ``python -m scaffolder.build <object_name>``
"""
__version__ = "1.0.0"
