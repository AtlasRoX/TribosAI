"""External & Fallback Clients for Physis (OEIS, Materials Project, Wolfram|Alpha, Wikipedia)."""

from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import quote

import httpx

OEIS_SEARCH_URL = "https://oeis.org/search"
MP_SUMMARY_URL = "https://api.materialsproject.org/materials/summary/"
WOLFRAM_LLM_URL = "https://www.wolframalpha.com/api/v1/llm-api"
WIKIPEDIA_SEARCH_URL = "https://en.wikipedia.org/w/rest.php/v1/search/page"
WIKIPEDIA_SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary"

# Built-in offline reference table of 25 common engineering and semiconductor materials
BUILTIN_MATERIALS: list[dict[str, Any]] = [
    {
        "material_id": "mp-149",
        "name": "Silicon",
        "formula_pretty": "Si",
        "elements": ["Si"],
        "crystal_system": "Cubic",
        "band_gap": 1.12,
        "density": 2.329,
        "is_stable": True,
        "youngs_modulus_gpa": 165.0,
        "yield_strength_mpa": 120.0,
        "thermal_conductivity_w_mk": 148.0,
        "source": "builtin_reference",
    },
    {
        "material_id": "mp-2534",
        "name": "Gallium Arsenide",
        "formula_pretty": "GaAs",
        "elements": ["Ga", "As"],
        "crystal_system": "Cubic",
        "band_gap": 1.42,
        "density": 5.317,
        "is_stable": True,
        "youngs_modulus_gpa": 85.5,
        "yield_strength_mpa": 75.0,
        "thermal_conductivity_w_mk": 55.0,
        "source": "builtin_reference",
    },
    {
        "material_id": "mp-804",
        "name": "Gallium Nitride",
        "formula_pretty": "GaN",
        "elements": ["Ga", "N"],
        "crystal_system": "Hexagonal",
        "band_gap": 3.40,
        "density": 6.15,
        "is_stable": True,
        "youngs_modulus_gpa": 295.0,
        "yield_strength_mpa": 150.0,
        "thermal_conductivity_w_mk": 130.0,
        "source": "builtin_reference",
    },
    {
        "material_id": "mp-8062",
        "name": "Silicon Carbide (4H-SiC)",
        "formula_pretty": "SiC",
        "elements": ["Si", "C"],
        "crystal_system": "Hexagonal",
        "band_gap": 3.26,
        "density": 3.21,
        "is_stable": True,
        "youngs_modulus_gpa": 410.0,
        "yield_strength_mpa": 400.0,
        "thermal_conductivity_w_mk": 370.0,
        "source": "builtin_reference",
    },
    {
        "material_id": "mp-32",
        "name": "Germanium",
        "formula_pretty": "Ge",
        "elements": ["Ge"],
        "crystal_system": "Cubic",
        "band_gap": 0.66,
        "density": 5.323,
        "is_stable": True,
        "youngs_modulus_gpa": 103.0,
        "yield_strength_mpa": 100.0,
        "thermal_conductivity_w_mk": 60.0,
        "source": "builtin_reference",
    },
    {
        "material_id": "mp-20351",
        "name": "Indium Phosphide",
        "formula_pretty": "InP",
        "elements": ["In", "P"],
        "crystal_system": "Cubic",
        "band_gap": 1.34,
        "density": 4.81,
        "is_stable": True,
        "youngs_modulus_gpa": 61.0,
        "yield_strength_mpa": 50.0,
        "thermal_conductivity_w_mk": 68.0,
        "source": "builtin_reference",
    },
    {
        "material_id": "mp-1143",
        "name": "Aluminum Oxide (Corundum / Sapphire)",
        "formula_pretty": "Al2O3",
        "elements": ["Al", "O"],
        "crystal_system": "Trigonal",
        "band_gap": 8.80,
        "density": 3.98,
        "is_stable": True,
        "youngs_modulus_gpa": 370.0,
        "yield_strength_mpa": 300.0,
        "thermal_conductivity_w_mk": 30.0,
        "source": "builtin_reference",
    },
    {
        "material_id": "mp-6930",
        "name": "Silicon Dioxide (Quartz)",
        "formula_pretty": "SiO2",
        "elements": ["Si", "O"],
        "crystal_system": "Trigonal",
        "band_gap": 8.90,
        "density": 2.65,
        "is_stable": True,
        "youngs_modulus_gpa": 72.0,
        "yield_strength_mpa": 50.0,
        "thermal_conductivity_w_mk": 1.4,
        "source": "builtin_reference",
    },
    {
        "material_id": "mp-2657",
        "name": "Titanium Dioxide (Rutile)",
        "formula_pretty": "TiO2",
        "elements": ["Ti", "O"],
        "crystal_system": "Tetragonal",
        "band_gap": 3.03,
        "density": 4.23,
        "is_stable": True,
        "youngs_modulus_gpa": 230.0,
        "yield_strength_mpa": 180.0,
        "thermal_conductivity_w_mk": 11.7,
        "source": "builtin_reference",
    },
    {
        "material_id": "mp-13",
        "name": "Iron (alpha-Fe)",
        "formula_pretty": "Fe",
        "elements": ["Fe"],
        "crystal_system": "Cubic",
        "band_gap": 0.0,
        "density": 7.874,
        "is_stable": True,
        "youngs_modulus_gpa": 211.0,
        "yield_strength_mpa": 170.0,
        "thermal_conductivity_w_mk": 80.4,
        "source": "builtin_reference",
    },
    {
        "material_id": "mp-30",
        "name": "Copper",
        "formula_pretty": "Cu",
        "elements": ["Cu"],
        "crystal_system": "Cubic",
        "band_gap": 0.0,
        "density": 8.96,
        "is_stable": True,
        "youngs_modulus_gpa": 130.0,
        "yield_strength_mpa": 70.0,
        "thermal_conductivity_w_mk": 401.0,
        "source": "builtin_reference",
    },
    {
        "material_id": "mp-134",
        "name": "Aluminum",
        "formula_pretty": "Al",
        "elements": ["Al"],
        "crystal_system": "Cubic",
        "band_gap": 0.0,
        "density": 2.70,
        "is_stable": True,
        "youngs_modulus_gpa": 70.0,
        "yield_strength_mpa": 35.0,
        "thermal_conductivity_w_mk": 237.0,
        "source": "builtin_reference",
    },
    {
        "material_id": "mp-46",
        "name": "Titanium (alpha-Ti)",
        "formula_pretty": "Ti",
        "elements": ["Ti"],
        "crystal_system": "Hexagonal",
        "band_gap": 0.0,
        "density": 4.506,
        "is_stable": True,
        "youngs_modulus_gpa": 116.0,
        "yield_strength_mpa": 240.0,
        "thermal_conductivity_w_mk": 21.9,
        "source": "builtin_reference",
    },
    {
        "material_id": "mp-91",
        "name": "Tungsten",
        "formula_pretty": "W",
        "elements": ["W"],
        "crystal_system": "Cubic",
        "band_gap": 0.0,
        "density": 19.25,
        "is_stable": True,
        "youngs_modulus_gpa": 411.0,
        "yield_strength_mpa": 750.0,
        "thermal_conductivity_w_mk": 173.0,
        "source": "builtin_reference",
    },
    {
        "material_id": "mp-81",
        "name": "Gold",
        "formula_pretty": "Au",
        "elements": ["Au"],
        "crystal_system": "Cubic",
        "band_gap": 0.0,
        "density": 19.30,
        "is_stable": True,
        "youngs_modulus_gpa": 79.0,
        "yield_strength_mpa": 55.0,
        "thermal_conductivity_w_mk": 318.0,
        "source": "builtin_reference",
    },
    {
        "material_id": "mp-124",
        "name": "Silver",
        "formula_pretty": "Ag",
        "elements": ["Ag"],
        "crystal_system": "Cubic",
        "band_gap": 0.0,
        "density": 10.49,
        "is_stable": True,
        "youngs_modulus_gpa": 83.0,
        "yield_strength_mpa": 54.0,
        "thermal_conductivity_w_mk": 429.0,
        "source": "builtin_reference",
    },
    {
        "material_id": "mp-66",
        "name": "Diamond",
        "formula_pretty": "C",
        "elements": ["C"],
        "crystal_system": "Cubic",
        "band_gap": 5.47,
        "density": 3.515,
        "is_stable": False,
        "youngs_modulus_gpa": 1050.0,
        "yield_strength_mpa": 35000.0,
        "thermal_conductivity_w_mk": 2200.0,
        "source": "builtin_reference",
    },
    {
        "material_id": "mp-48",
        "name": "Graphite",
        "formula_pretty": "C",
        "elements": ["C"],
        "crystal_system": "Hexagonal",
        "band_gap": 0.0,
        "density": 2.26,
        "is_stable": True,
        "youngs_modulus_gpa": 11.0,
        "yield_strength_mpa": 30.0,
        "thermal_conductivity_w_mk": 140.0,
        "source": "builtin_reference",
    },
    {
        "material_id": "mp-22862",
        "name": "Sodium Chloride",
        "formula_pretty": "NaCl",
        "elements": ["Na", "Cl"],
        "crystal_system": "Cubic",
        "band_gap": 8.50,
        "density": 2.165,
        "is_stable": True,
        "youngs_modulus_gpa": 40.0,
        "yield_strength_mpa": 25.0,
        "thermal_conductivity_w_mk": 6.5,
        "source": "builtin_reference",
    },
    {
        "material_id": "mp-5986",
        "name": "Barium Titanate",
        "formula_pretty": "BaTiO3",
        "elements": ["Ba", "Ti", "O"],
        "crystal_system": "Tetragonal",
        "band_gap": 3.20,
        "density": 6.02,
        "is_stable": True,
        "youngs_modulus_gpa": 110.0,
        "yield_strength_mpa": 80.0,
        "thermal_conductivity_w_mk": 6.0,
        "source": "builtin_reference",
    },
    {
        "material_id": "mp-22526",
        "name": "Lithium Cobalt Oxide",
        "formula_pretty": "LiCoO2",
        "elements": ["Li", "Co", "O"],
        "crystal_system": "Trigonal",
        "band_gap": 2.70,
        "density": 5.05,
        "is_stable": True,
        "youngs_modulus_gpa": 191.0,
        "yield_strength_mpa": 120.0,
        "thermal_conductivity_w_mk": 5.4,
        "source": "builtin_reference",
    },
    {
        "material_id": "mp-4019",
        "name": "Calcium Titanate (Perovskite)",
        "formula_pretty": "CaTiO3",
        "elements": ["Ca", "Ti", "O"],
        "crystal_system": "Orthorhombic",
        "band_gap": 3.50,
        "density": 4.04,
        "is_stable": True,
        "youngs_modulus_gpa": 220.0,
        "yield_strength_mpa": 140.0,
        "thermal_conductivity_w_mk": 4.5,
        "source": "builtin_reference",
    },
    {
        "material_id": "mat-aisi304",
        "name": "AISI 304 Stainless Steel",
        "formula_pretty": "FeCr18Ni8",
        "elements": ["Fe", "Cr", "Ni"],
        "crystal_system": "Cubic",
        "band_gap": 0.0,
        "density": 8.00,
        "is_stable": True,
        "youngs_modulus_gpa": 193.0,
        "yield_strength_mpa": 215.0,
        "thermal_conductivity_w_mk": 16.2,
        "source": "builtin_reference",
    },
    {
        "material_id": "mat-ti6al4v",
        "name": "Ti-6Al-4V Titanium Alloy",
        "formula_pretty": "Ti6Al4V",
        "elements": ["Ti", "Al", "V"],
        "crystal_system": "Hexagonal",
        "band_gap": 0.0,
        "density": 4.43,
        "is_stable": True,
        "youngs_modulus_gpa": 113.8,
        "yield_strength_mpa": 880.0,
        "thermal_conductivity_w_mk": 6.7,
        "source": "builtin_reference",
    },
    {
        "material_id": "mat-a36",
        "name": "Structural Steel ASTM A36",
        "formula_pretty": "Fe-C",
        "elements": ["Fe", "C"],
        "crystal_system": "Cubic",
        "band_gap": 0.0,
        "density": 7.85,
        "is_stable": True,
        "youngs_modulus_gpa": 200.0,
        "yield_strength_mpa": 250.0,
        "thermal_conductivity_w_mk": 50.0,
        "source": "builtin_reference",
    },
]


def _parse_oeis_terms(data_str: str) -> list[int]:
    terms: list[int] = []
    for part in (data_str or "").split(","):
        p = part.strip()
        if not p:
            continue
        try:
            terms.append(int(p))
        except ValueError:
            continue
    return terms


def normalize_oeis_response(payload: Any, limit: int = 5) -> list[dict[str, Any]]:
    """Normalize OEIS JSON response (supports both bare list `[...]` and legacy `{'results': [...]}`)."""
    if isinstance(payload, list):
        raw_items = payload
    elif isinstance(payload, dict):
        raw_items = payload.get("results") or []
    else:
        raw_items = []

    if not isinstance(raw_items, list):
        return []

    sequences: list[dict[str, Any]] = []
    for entry in raw_items[: max(1, int(limit))]:
        if not isinstance(entry, dict):
            continue
        num = entry.get("number")
        if num is None:
            continue
        try:
            seq_id = f"A{int(num):06d}"
        except (TypeError, ValueError):
            seq_id = str(num)
        data_str = str(entry.get("data") or "")
        sequences.append(
            {
                "id": seq_id,
                "number": int(num) if str(num).isdigit() else num,
                "name": str(entry.get("name") or ""),
                "data": data_str,
                "terms": _parse_oeis_terms(data_str),
                "formula": [str(f) for f in (entry.get("formula") or [])[:8]],
                "comment": [str(c) for c in (entry.get("comment") or [])[:5]],
                "reference": [str(r) for r in (entry.get("reference") or [])[:5]],
                "xref": [str(x) for x in (entry.get("xref") or [])[:5]],
                "keyword": str(entry.get("keyword") or ""),
                "url": f"https://oeis.org/{seq_id}",
            }
        )
    return sequences


def search_builtin_materials(
    formula: str | None = None,
    material_id: str | None = None,
    elements: list[str] | None = None,
    query: str | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Search the built-in 25 engineering and semiconductor materials reference table."""
    matches: list[dict[str, Any]] = []
    mid_norm = (material_id or "").strip().lower()
    form_norm = (formula or "").strip().lower()
    q_norm = (query or "").strip().lower()
    elem_set = {e.strip().lower() for e in (elements or []) if e and e.strip()}

    for item in BUILTIN_MATERIALS:
        if mid_norm and item["material_id"].lower() == mid_norm:
            matches.append(dict(item))
            continue
        if form_norm and (
            item["formula_pretty"].lower() == form_norm
            or item["name"].lower() == form_norm
            or form_norm in item["name"].lower()
        ):
            matches.append(dict(item))
            continue
        if elem_set:
            item_elems = {e.lower() for e in item.get("elements") or []}
            if elem_set.issubset(item_elems):
                matches.append(dict(item))
                continue
        if q_norm and (
            q_norm == item["material_id"].lower()
            or q_norm == item["formula_pretty"].lower()
            or q_norm in item["name"].lower()
            or q_norm in item["formula_pretty"].lower()
        ):
            matches.append(dict(item))
            continue

    return matches[: max(1, int(limit))]


class PhysisClients:
    """Async HTTP clients for OEIS, Materials Project, Wolfram|Alpha, and Wikipedia."""

    def __init__(
        self,
        *,
        mp_api_key: str | None = None,
        wolfram_appid: str | None = None,
        contact_email: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 15.0,
    ) -> None:
        self.mp_api_key = (
            mp_api_key
            if mp_api_key is not None
            else (os.getenv("TRIBOS_MP_API_KEY") or "").strip()
        )
        self.wolfram_appid = (
            wolfram_appid
            if wolfram_appid is not None
            else (os.getenv("TRIBOS_WOLFRAM_APPID") or "").strip()
        )
        self.contact_email = (
            contact_email
            if contact_email is not None
            else (os.getenv("TRIBOS_CONTACT_EMAIL") or "contact@tribos.science").strip()
        )
        self._transport = transport
        self._timeout = timeout

    def _make_client(self, headers: dict[str, str] | None = None) -> httpx.AsyncClient:
        base_headers = {
            "User-Agent": f"Tribos/1.0 (https://tribos.science; mailto:{self.contact_email})",
            "Accept": "application/json",
        }
        if headers:
            base_headers.update(headers)
        return httpx.AsyncClient(
            headers=base_headers,
            timeout=self._timeout,
            transport=self._transport,
            follow_redirects=True,
        )

    async def search_oeis(self, query: str, limit: int = 5) -> dict[str, Any]:
        """Query the On-Line Encyclopedia of Integer Sequences (OEIS)."""
        q = (query or "").strip()
        limit = max(1, min(int(limit or 5), 25))
        if not q:
            return {
                "query": q,
                "count": 0,
                "sequences": [],
                "canonical_id": "",
                "canonical_ids": {"oeis_ids": []},
            }
        async with self._make_client() as client:
            resp = await client.get(OEIS_SEARCH_URL, params={"q": q, "fmt": "json"})
            resp.raise_for_status()
            payload = resp.json()

        sequences = normalize_oeis_response(payload, limit=limit)
        oeis_ids = [s["id"] for s in sequences if s.get("id")]
        return {
            "query": q,
            "count": len(sequences),
            "sequences": sequences,
            "canonical_id": oeis_ids[0] if oeis_ids else "",
            "canonical_ids": {"oeis_ids": oeis_ids},
        }

    async def search_materials(
        self,
        formula: str | None = None,
        material_id: str | None = None,
        elements: list[str] | None = None,
        query: str | None = None,
        limit: int = 5,
    ) -> dict[str, Any]:
        """Query the Materials Project API v2, falling back to the 25-material reference table when unconfigured."""
        limit = max(1, min(int(limit or 5), 25))
        if not self.mp_api_key:
            materials = search_builtin_materials(
                formula=formula,
                material_id=material_id,
                elements=elements,
                query=query,
                limit=limit,
            )
            mids = [m["material_id"] for m in materials]
            return {
                "formula": formula,
                "material_id": material_id,
                "elements": elements,
                "query": query,
                "count": len(materials),
                "materials": materials,
                "source": "builtin_reference",
                "note": "TRIBOS_MP_API_KEY not set; using built-in reference table of 25 common engineering/semiconductor materials.",
                "canonical_id": mids[0] if mids else "",
                "canonical_ids": {"mp_ids": mids},
            }

        params: dict[str, Any] = {
            "_limit": limit,
            "_fields": "material_id,formula_pretty,band_gap,density,is_stable,symmetry,energy_above_hull,formation_energy_per_atom,volume",
        }
        if material_id:
            params["material_ids"] = material_id.strip()
        if formula:
            params["formula"] = formula.strip()
        elif query and not material_id and not elements:
            if query.strip().lower().startswith("mp-"):
                params["material_ids"] = query.strip()
            else:
                params["formula"] = query.strip()
        if elements:
            params["elements"] = ",".join(e.strip() for e in elements if e.strip())

        async with self._make_client(headers={"X-API-KEY": self.mp_api_key}) as client:
            resp = await client.get(MP_SUMMARY_URL, params=params)
            resp.raise_for_status()
            payload = resp.json()

        data_items = payload.get("data") if isinstance(payload, dict) else []
        materials: list[dict[str, Any]] = []
        for item in (data_items or [])[:limit]:
            if not isinstance(item, dict):
                continue
            sym = item.get("symmetry") if isinstance(item.get("symmetry"), dict) else {}
            materials.append(
                {
                    "material_id": str(item.get("material_id") or ""),
                    "formula_pretty": str(item.get("formula_pretty") or ""),
                    "band_gap": item.get("band_gap"),
                    "density": item.get("density"),
                    "is_stable": item.get("is_stable"),
                    "crystal_system": sym.get("crystal_system"),
                    "space_group_symbol": sym.get("symbol"),
                    "energy_above_hull": item.get("energy_above_hull"),
                    "formation_energy_per_atom": item.get("formation_energy_per_atom"),
                    "volume": item.get("volume"),
                    "source": "materials_project",
                }
            )
        mids = [m["material_id"] for m in materials if m.get("material_id")]
        return {
            "formula": formula,
            "material_id": material_id,
            "elements": elements,
            "query": query,
            "count": len(materials),
            "materials": materials,
            "source": "materials_project",
            "canonical_id": mids[0] if mids else "",
            "canonical_ids": {"mp_ids": mids},
        }

    async def query_wolfram(self, query: str) -> dict[str, Any]:
        """Query the Wolfram|Alpha LLM API when TRIBOS_WOLFRAM_APPID is configured."""
        q = (query or "").strip()
        if not self.wolfram_appid:
            return {
                "query": q,
                "skipped": True,
                "skipped_reason": "TRIBOS_WOLFRAM_APPID is not set",
                "result": None,
                "source": "wolfram_alpha",
                "canonical_id": "",
                "canonical_ids": {},
            }

        async with self._make_client(headers={"Accept": "text/plain, application/json"}) as client:
            resp = await client.get(
                WOLFRAM_LLM_URL,
                params={"input": q, "appid": self.wolfram_appid},
            )
            resp.raise_for_status()
            text = resp.text.strip()

        return {
            "query": q,
            "skipped": False,
            "result": text,
            "source": "wolfram_alpha",
            "canonical_id": f"wolfram:{q[:40]}",
            "canonical_ids": {},
        }

    async def search_encyclopedia(self, query: str, limit: int = 3) -> dict[str, Any]:
        """Search Wikipedia REST API v1 for mathematical, physical, and engineering definitions/theorems."""
        q = (query or "").strip()
        limit = max(1, min(int(limit or 3), 10))
        if not q:
            return {
                "query": q,
                "count": 0,
                "entries": [],
                "canonical_id": "",
                "canonical_ids": {},
            }

        entries: list[dict[str, Any]] = []
        async with self._make_client() as client:
            search_resp = await client.get(
                WIKIPEDIA_SEARCH_URL,
                params={"q": q, "limit": limit},
            )
            search_resp.raise_for_status()
            search_data = search_resp.json()
            pages = search_data.get("pages") if isinstance(search_data, dict) else []

            for page in (pages or [])[:limit]:
                if not isinstance(page, dict):
                    continue
                key = str(page.get("key") or page.get("title") or "").strip()
                title = str(page.get("title") or key)
                desc = str(page.get("description") or "")
                excerpt = re.sub(r"<[^>]+>", "", str(page.get("excerpt") or "")).strip()
                extract = excerpt
                url = f"https://en.wikipedia.org/wiki/{quote(key.replace(' ', '_'))}"

                if key:
                    try:
                        sum_resp = await client.get(f"{WIKIPEDIA_SUMMARY_URL}/{quote(key)}")
                        if sum_resp.status_code == 200:
                            sum_json = sum_resp.json()
                            if isinstance(sum_json, dict):
                                extract = str(sum_json.get("extract") or extract)
                                desc = str(sum_json.get("description") or desc)
                                content_urls = sum_json.get("content_urls") or {}
                                desktop = content_urls.get("desktop") or {}
                                if desktop.get("page"):
                                    url = str(desktop["page"])
                    except httpx.HTTPError:
                        pass

                entries.append(
                    {
                        "title": title,
                        "key": key,
                        "description": desc,
                        "extract": extract,
                        "url": url,
                        "source": "wikipedia",
                    }
                )

        return {
            "query": q,
            "count": len(entries),
            "entries": entries,
            "canonical_id": f"wiki:{entries[0]['key']}" if entries else "",
            "canonical_ids": {},
        }


__all__ = [
    "BUILTIN_MATERIALS",
    "MP_SUMMARY_URL",
    "OEIS_SEARCH_URL",
    "PhysisClients",
    "WIKIPEDIA_SEARCH_URL",
    "WIKIPEDIA_SUMMARY_URL",
    "WOLFRAM_LLM_URL",
    "normalize_oeis_response",
    "search_builtin_materials",
]
