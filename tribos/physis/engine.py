"""Physis Engine — Physical Constants, Dimensional Analysis, OEIS, Materials, and Encyclopedia Reference."""

from __future__ import annotations

from typing import Any

from .clients import PhysisClients
from .constants import search_constants
from .units import convert_units


class PhysisEngine:
    """Unified physical, mathematical, and materials reference engine."""

    def __init__(self, clients: PhysisClients | None = None) -> None:
        self.clients = clients or PhysisClients()

    def lookup_constants(self, query: str, limit: int = 10) -> dict[str, Any]:
        """Lookup NIST CODATA 2022 physical constants."""
        return search_constants(query=query, limit=limit)

    def convert_units(
        self,
        value: float = 1.0,
        from_unit: str = "",
        to_unit: str | None = None,
        check_equation: str | None = None,
    ) -> dict[str, Any]:
        """Convert physical quantities between units or check dimensional homogeneity."""
        return convert_units(
            value=value,
            from_unit=from_unit,
            to_unit=to_unit,
            check_equation=check_equation,
        )

    async def lookup_oeis(self, query: str, limit: int = 5) -> dict[str, Any]:
        """Search the On-Line Encyclopedia of Integer Sequences (OEIS)."""
        return await self.clients.search_oeis(query=query, limit=limit)

    async def lookup_materials(
        self,
        formula: str | None = None,
        material_id: str | None = None,
        elements: list[str] | None = None,
        query: str | None = None,
        limit: int = 5,
    ) -> dict[str, Any]:
        """Query Materials Project API v2 or the 25-material reference table."""
        return await self.clients.search_materials(
            formula=formula,
            material_id=material_id,
            elements=elements,
            query=query,
            limit=limit,
        )

    async def query_wolfram(self, query: str) -> dict[str, Any]:
        """Query Wolfram|Alpha LLM API when TRIBOS_WOLFRAM_APPID is configured."""
        return await self.clients.query_wolfram(query=query)

    async def lookup_encyclopedia(self, query: str, limit: int = 3) -> dict[str, Any]:
        """Search Wikipedia REST API for mathematical, physical, and engineering entries."""
        return await self.clients.search_encyclopedia(query=query, limit=limit)


__all__ = ["PhysisEngine"]
