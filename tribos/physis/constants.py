"""Physical Constants Reference (NIST CODATA 2022 via scipy.constants + NIST allascii parser)."""

from __future__ import annotations

import re
from typing import Any

import scipy.constants as _sc

# Mapping from standard physics symbols / common aliases to canonical scipy.constants.physical_constants keys
_SYMBOL_TO_CODATA_KEY: dict[str, tuple[str, str]] = {
    "c": ("speed of light in vacuum", "c"),
    "c_0": ("speed of light in vacuum", "c"),
    "speed of light": ("speed of light in vacuum", "c"),
    "h": ("Planck constant", "h"),
    "planck": ("Planck constant", "h"),
    "planck constant": ("Planck constant", "h"),
    "hbar": ("reduced Planck constant", "hbar"),
    "h-bar": ("reduced Planck constant", "hbar"),
    "reduced planck constant": ("reduced Planck constant", "hbar"),
    "dirac constant": ("reduced Planck constant", "hbar"),
    "G": ("Newtonian constant of gravitation", "G"),
    "gravitational constant": ("Newtonian constant of gravitation", "G"),
    "newton constant": ("Newtonian constant of gravitation", "G"),
    "k_B": ("Boltzmann constant", "k_B"),
    "k_b": ("Boltzmann constant", "k_B"),
    "kb": ("Boltzmann constant", "k_B"),
    "boltzmann": ("Boltzmann constant", "k_B"),
    "boltzmann constant": ("Boltzmann constant", "k_B"),
    "e": ("elementary charge", "e"),
    "q_e": ("elementary charge", "e"),
    "elementary charge": ("elementary charge", "e"),
    "m_e": ("electron mass", "m_e"),
    "electron mass": ("electron mass", "m_e"),
    "m_p": ("proton mass", "m_p"),
    "proton mass": ("proton mass", "m_p"),
    "m_n": ("neutron mass", "m_n"),
    "neutron mass": ("neutron mass", "m_n"),
    "u": ("atomic mass constant", "u"),
    "amu": ("atomic mass constant", "u"),
    "dalton": ("atomic mass constant", "u"),
    "N_A": ("Avogadro constant", "N_A"),
    "n_a": ("Avogadro constant", "N_A"),
    "avogadro": ("Avogadro constant", "N_A"),
    "avogadro constant": ("Avogadro constant", "N_A"),
    "R": ("molar gas constant", "R"),
    "gas constant": ("molar gas constant", "R"),
    "universal gas constant": ("molar gas constant", "R"),
    "F": ("Faraday constant", "F"),
    "faraday constant": ("Faraday constant", "F"),
    "g": ("standard acceleration of gravity", "g_0"),
    "g_0": ("standard acceleration of gravity", "g_0"),
    "standard gravity": ("standard acceleration of gravity", "g_0"),
    "sigma": ("Stefan-Boltzmann constant", "sigma"),
    "stefan-boltzmann": ("Stefan-Boltzmann constant", "sigma"),
    "stefan boltzmann": ("Stefan-Boltzmann constant", "sigma"),
    "stefan-boltzmann constant": ("Stefan-Boltzmann constant", "sigma"),
    "alpha": ("fine-structure constant", "alpha"),
    "fine structure constant": ("fine-structure constant", "alpha"),
    "fine-structure constant": ("fine-structure constant", "alpha"),
    "epsilon_0": ("vacuum electric permittivity", "epsilon_0"),
    "eps_0": ("vacuum electric permittivity", "epsilon_0"),
    "permittivity of free space": ("vacuum electric permittivity", "epsilon_0"),
    "vacuum permittivity": ("vacuum electric permittivity", "epsilon_0"),
    "mu_0": ("vacuum mag. permeability", "mu_0"),
    "permeability of free space": ("vacuum mag. permeability", "mu_0"),
    "vacuum permeability": ("vacuum mag. permeability", "mu_0"),
    "Z_0": ("characteristic impedance of vacuum", "Z_0"),
    "R_inf": ("Rydberg constant", "R_inf"),
    "rydberg": ("Rydberg constant", "R_inf"),
    "rydberg constant": ("Rydberg constant", "R_inf"),
    "a_0": ("Bohr radius", "a_0"),
    "bohr radius": ("Bohr radius", "a_0"),
    "mu_B": ("Bohr magneton", "mu_B"),
    "bohr magneton": ("Bohr magneton", "mu_B"),
    "mu_N": ("nuclear magneton", "mu_N"),
    "nuclear magneton": ("nuclear magneton", "mu_N"),
    "Phi_0": ("mag. flux quantum", "Phi_0"),
    "flux quantum": ("mag. flux quantum", "Phi_0"),
    "G_0": ("conductance quantum", "G_0"),
    "K_J": ("Josephson constant", "K_J"),
    "R_K": ("von Klitzing constant", "R_K"),
    "b": ("Wien wavelength displacement law constant", "b"),
    "wien constant": ("Wien wavelength displacement law constant", "b"),
}

# Reverse map from CODATA name to canonical symbol
_CODATA_KEY_TO_SYMBOL: dict[str, str] = {}
for _alias, (_codata_key, _sym) in _SYMBOL_TO_CODATA_KEY.items():
    _CODATA_KEY_TO_SYMBOL.setdefault(_codata_key, _sym)


def parse_nist_ascii_value(raw: str) -> float:
    """Parse a NIST allascii.txt numeric string (which may contain spaces and '...') into a float.

    Examples:
        '6.644 657 3450 e-27' -> 6.644657345e-27
        '299 792 458' -> 299792458.0
        '12.566 370 614... e-7' -> 1.2566370614e-6
        '(exact)' -> 0.0
    """
    s = (raw or "").strip()
    if not s or s.lower() == "(exact)":
        return 0.0
    cleaned = s.replace(" ", "").replace("...", "")
    return float(cleaned)


def parse_nist_allascii(text: str) -> list[dict[str, Any]]:
    """Parse NIST's fixed-column allascii.txt table into structured constant dictionaries."""
    results: list[dict[str, Any]] = []
    lines = (text or "").splitlines()
    in_table = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("-----"):
            in_table = True
            continue
        if not in_table:
            continue
        # NIST allascii columns are separated by 2+ spaces: Quantity | Value | Uncertainty | Unit
        cols = [c.strip() for c in re.split(r"\s{2,}", stripped) if c.strip()]
        if len(cols) < 3:
            continue
        name = cols[0]
        try:
            value = parse_nist_ascii_value(cols[1])
            uncertainty = parse_nist_ascii_value(cols[2])
        except ValueError:
            continue
        unit = cols[3] if len(cols) >= 4 else ""
        rel_unc = abs(uncertainty / value) if value != 0.0 else 0.0
        results.append(
            {
                "name": name,
                "symbol": _CODATA_KEY_TO_SYMBOL.get(name, ""),
                "value": value,
                "unit": unit,
                "uncertainty": uncertainty,
                "rel_uncertainty": rel_unc,
                "source": "NIST CODATA 2022",
            }
        )
    return results


def _make_entry(codata_key: str, symbol: str | None = None) -> dict[str, Any] | None:
    tup = _sc.physical_constants.get(codata_key)
    if tup is None:
        return None
    val, unit, unc = tup
    val_f = float(val)
    unc_f = float(unc)
    rel_unc = abs(unc_f / val_f) if val_f != 0.0 else 0.0
    sym = symbol if symbol is not None else _CODATA_KEY_TO_SYMBOL.get(codata_key, "")
    return {
        "name": codata_key,
        "symbol": sym,
        "value": val_f,
        "unit": str(unit or ""),
        "uncertainty": unc_f,
        "rel_uncertainty": rel_unc,
        "source": "NIST CODATA 2022",
    }


def search_constants(query: str, limit: int = 10) -> dict[str, Any]:
    """Search NIST CODATA 2022 physical constants by name, symbol, or keyword."""
    q_raw = (query or "").strip()
    limit = max(1, min(int(limit or 10), 50))
    if not q_raw:
        return {
            "query": q_raw,
            "count": 0,
            "constants": [],
            "canonical_id": "NIST:CODATA",
            "canonical_ids": {"nist_constants": []},
        }

    seen_names: set[str] = set()
    results: list[dict[str, Any]] = []

    def _add(codata_key: str, sym: str | None = None) -> None:
        if codata_key in seen_names:
            return
        entry = _make_entry(codata_key, sym)
        if entry is not None:
            seen_names.add(codata_key)
            results.append(entry)

    # 1. Exact symbol or alias match (case-sensitive first, then case-insensitive)
    if q_raw in _SYMBOL_TO_CODATA_KEY:
        ck, sym = _SYMBOL_TO_CODATA_KEY[q_raw]
        _add(ck, sym)
    q_low = q_raw.lower()
    if q_low in _SYMBOL_TO_CODATA_KEY:
        ck, sym = _SYMBOL_TO_CODATA_KEY[q_low]
        _add(ck, sym)

    # 2. Exact CODATA name match
    if q_raw in _sc.physical_constants:
        _add(q_raw)

    # 3. Substring and token matching across physical_constants
    tokens = [t for t in re.split(r"[\s_\-,;()]+", q_low) if len(t) >= 2 and t not in {"constant", "the", "of", "in"}]
    scored: list[tuple[float, str]] = []
    for name in _sc.physical_constants:
        if name in seen_names:
            continue
        name_low = name.lower()
        score = 0.0
        if q_low == name_low:
            score += 100.0
        elif q_low in name_low:
            score += 50.0 - 0.2 * len(name_low)
        elif tokens:
            matched = sum(1 for tok in tokens if tok in name_low)
            if matched == len(tokens):
                score += 30.0 - 0.1 * len(name_low)
            elif matched > 0:
                score += 10.0 * (matched / len(tokens)) - 0.05 * len(name_low)
        if score > 0:
            scored.append((score, name))

    # Also check alias keys if tokens match an alias
    for alias, (ck, sym) in _SYMBOL_TO_CODATA_KEY.items():
        if ck in seen_names:
            continue
        if tokens and all(tok in alias.lower() for tok in tokens):
            _add(ck, sym)

    scored.sort(key=lambda pair: (-pair[0], len(pair[1]), pair[1]))
    for _, name in scored:
        if len(results) >= limit:
            break
        _add(name)

    results = results[:limit]
    primary_id = f"NIST:CODATA:{results[0]['name']}" if results else "NIST:CODATA"
    return {
        "query": q_raw,
        "count": len(results),
        "constants": results,
        "canonical_id": primary_id,
        "canonical_ids": {"nist_constants": [f"NIST:CODATA:{r['name']}" for r in results]},
    }


__all__ = [
    "parse_nist_allascii",
    "parse_nist_ascii_value",
    "search_constants",
]
