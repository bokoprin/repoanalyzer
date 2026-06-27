from __future__ import annotations

from .models import UnknownFact


def missing_index(message: str = "Index is missing or not initialized.") -> UnknownFact:
    return UnknownFact("missing_index", message, severity="high")


def definition_not_found(symbol: str) -> UnknownFact:
    return UnknownFact("definition_not_found", f"No definition found for symbol '{symbol}'.", severity="medium")


def call_graph_incomplete(message: str) -> UnknownFact:
    return UnknownFact("call_graph_incomplete", message, severity="medium", affects=["call_path"])
