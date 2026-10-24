"""Who published a source, from the record's own URL fields: one policy for prompts, citations, the verifier and exports.

Consolidates trusted domain registries for mathematics, physics, engineering, and computational science:
- Standards & metrology bodies (NIST, ISO, IEEE, ASME, ASTM, BIPM, CODATA, NASA, CERN)
- Preprint & mathematical/scientific repositories (arXiv, zbMATH, MathSciNet, OEIS, Materials Project, NASA ADS, OpenAlex)
- Peer-reviewed STEM publishers & learned societies (AMS, APS, SIAM, ACM, Springer, Nature, Science, Elsevier, Wiley, IOP, AIP, OUP, CUP)
- University & national research domains (.edu, .ac.uk, etc.)

Retains legacy export aliases (`REGULATORY_HOSTS`, `FDA_HOSTS`, `REGISTRY_HOSTS`, `MANUFACTURER_HOSTS`,
`is_fda_url`, `is_regulatory_url`) so downstream callers and tests never break on import.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import urlsplit

STANDARDS_HOSTS = (
    "nist.gov",
    "physics.nist.gov",
    "webbook.nist.gov",
    "dlmf.nist.gov",
    "iso.org",
    "iec.ch",
    "ieee.org",
    "standards.ieee.org",
    "asme.org",
    "astm.org",
    "bipm.org",
    "codata.org",
    "iupac.org",
    "iupap.org",
    "ansi.org",
    "din.de",
    "bsigroup.com",
    "sae.org",
    "ashrae.org",
    "aiaa.org",
    "nasa.gov",
    "ntrs.nasa.gov",
    "esa.int",
    "cern.ch",
    "iter.org",
    "nrel.gov",
    "osti.gov",
)

REPOSITORY_HOSTS = (
    "arxiv.org",
    "export.arxiv.org",
    "zbmath.org",
    "mathscinet.ams.org",
    "oeis.org",
    "materialsproject.org",
    "next-gen.materialsproject.org",
    "ui.adsabs.harvard.edu",
    "adsabs.harvard.edu",
    "harvard.edu",
    "semanticscholar.org",
    "openalex.org",
    "crossref.org",
    "lmfdb.org",
    "stacks.math.columbia.edu",
    "ncatlab.org",
    "encyclopediaofmath.org",
    "mathworld.wolfram.com",
    "functions.wolfram.com",
    "zenodo.org",
)

LITERATURE_HOSTS = (
    "ams.org",
    "aps.org",
    "journals.aps.org",
    "siam.org",
    "epubs.siam.org",
    "acm.org",
    "dl.acm.org",
    "ieeexplore.ieee.org",
    "aip.org",
    "pubs.aip.org",
    "iop.org",
    "iopscience.iop.org",
    "doi.org",
    "nature.com",
    "science.org",
    "sciencedirect.com",
    "elsevier.com",
    "springer.com",
    "link.springer.com",
    "wiley.com",
    "onlinelibrary.wiley.com",
    "academic.oup.com",
    "oup.com",
    "cambridge.org",
    "royalsocietypublishing.org",
    "ems.press",
    "projecteuclid.org",
    "jstor.org",
    "numdam.org",
    "eudml.org",
    "frontiersin.org",
    "mdpi.com",
    "tandfonline.com",
    "sagepub.com",
    "plos.org",
    "ncbi.nlm.nih.gov",
    "europepmc.org",
    "biorxiv.org",
)

VENDOR_HOSTS = (
    "prnewswire.com",
    "businesswire.com",
    "globenewswire.com",
    "accesswire.com",
)

# Backwards-compatible host tuple aliases
REGULATORY_HOSTS = STANDARDS_HOSTS
FDA_HOSTS = ("nist.gov", "iso.org", "ieee.org", "asme.org", "astm.org")
REGISTRY_HOSTS = REPOSITORY_HOSTS
MANUFACTURER_HOSTS = VENDOR_HOSTS

SOURCE_AUTHORITY_LABELS = {
    "standards": "standards or national metrology body (NIST, ISO, IEEE, ASME, ASTM, CODATA)",
    "repository": "scientific or mathematical repository (arXiv, zbMATH, MathSciNet, OEIS, Materials Project, ADS)",
    "literature": "peer-reviewed journal, learned society, or university press",
    "academic": "university or national research institution (.edu, .ac.uk)",
    "vendor": "commercial vendor or press-wire announcement",
    "web": "other web page",
    # Legacy keys retained for compatibility
    "regulatory": "standards or national metrology body (NIST, ISO, IEEE, ASME, ASTM, CODATA)",
    "trial_registry": "scientific or mathematical repository (arXiv, zbMATH, OEIS, Materials Project, ADS)",
    "manufacturer": "commercial vendor or press-wire announcement",
}

URL_FIELDS = ("final_url", "canonical_url", "url", "link", "source_url")
_HOST_LABEL_RE = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")


def host_of(url: Any) -> str | None:
    """The validated, lowercased DNS host of an http(s) URL, or None."""
    text = str(url or "").strip()
    if not text:
        return None
    try:
        parts = urlsplit(text)
        host = parts.hostname
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not host:
        return None
    if "@" in (parts.netloc or ""):
        return None
    host = host.lower().rstrip(".")
    try:
        ipaddress.ip_address(host)
        return None
    except ValueError:
        pass
    labels = host.split(".")
    if len(labels) < 2 or not all(_HOST_LABEL_RE.match(label) for label in labels):
        return None
    return host


def _on(host: str | None, domains: Iterable[str]) -> bool:
    return bool(host) and any(host == d or host.endswith("." + d) for d in domains)  # type: ignore[union-attr]


def is_academic_host(host: str | None) -> bool:
    if not host:
        return False
    return (
        host.endswith(".edu")
        or host.endswith(".ac.uk")
        or host.endswith(".ac.jp")
        or host.endswith(".edu.au")
        or host.endswith(".ethz.ch")
        or host.endswith(".epfl.ch")
        or host.endswith(".mpg.de")
        or host.endswith(".cnrs.fr")
    )


FDA_HOSTS = ("fda.gov", "accessdata.fda.gov")
REGULATORY_HOSTS = (*STANDARDS_HOSTS, *FDA_HOSTS)


def source_authority(url: Any) -> str:
    """Classify a page URL by its host into 'standards' | 'repository' | 'literature' | 'academic' | 'vendor' | 'web'."""
    host = host_of(url)
    if _on(host, FDA_HOSTS):
        return "regulatory"
    if _on(host, STANDARDS_HOSTS):
        return "standards"
    if _on(host, REPOSITORY_HOSTS):
        return "repository"
    if _on(host, LITERATURE_HOSTS):
        return "literature"
    if is_academic_host(host):
        return "academic"
    if _on(host, VENDOR_HOSTS):
        return "vendor"
    return "web"


def is_standards_url(url: Any) -> bool:
    """True if url belongs to a recognized standards or national metrology organization."""
    return _on(host_of(url), STANDARDS_HOSTS)


def is_scholarly_url(url: Any) -> bool:
    """True if url belongs to a peer-reviewed STEM publisher, repository, or university."""
    host = host_of(url)
    return _on(host, REPOSITORY_HOSTS) or _on(host, LITERATURE_HOSTS) or is_academic_host(host)


def is_authoritative_url(url: Any) -> bool:
    """True if url belongs to a standards body, repository, STEM publisher, or university."""
    return is_standards_url(url) or is_scholarly_url(url) or _on(host_of(url), FDA_HOSTS)


# Backward-compatible aliases
def is_fda_url(url: Any) -> bool:
    return _on(host_of(url), FDA_HOSTS) or is_standards_url(url)


def is_regulatory_url(url: Any) -> bool:
    return _on(host_of(url), REGULATORY_HOSTS)


def record_url(record: Any) -> str | None:
    """The document's own URL from a retrieval record: final URL after redirects, else canonical, else requested."""
    if not isinstance(record, Mapping):
        return None
    hops = record.get("redirects")
    if isinstance(hops, (list, tuple)) and hops and isinstance(hops[-1], str) and hops[-1].strip():
        return hops[-1].strip()
    for field in URL_FIELDS:
        value = record.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


__all__ = [
    "FDA_HOSTS",
    "LITERATURE_HOSTS",
    "MANUFACTURER_HOSTS",
    "REGISTRY_HOSTS",
    "REGULATORY_HOSTS",
    "REPOSITORY_HOSTS",
    "SOURCE_AUTHORITY_LABELS",
    "STANDARDS_HOSTS",
    "URL_FIELDS",
    "VENDOR_HOSTS",
    "host_of",
    "is_academic_host",
    "is_authoritative_url",
    "is_fda_url",
    "is_regulatory_url",
    "is_scholarly_url",
    "is_standards_url",
    "record_url",
    "source_authority",
]
