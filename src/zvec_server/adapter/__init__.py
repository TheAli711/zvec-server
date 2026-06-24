"""Adapter layer: the only package that imports the ``zvec`` SDK directly.

Everything Zvec-specific (engine init, schema/doc/query translation, enum
mapping) lives here so the rest of the application depends on plain Python types
and our own models rather than on SDK internals.
"""
