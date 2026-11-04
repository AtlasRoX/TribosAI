"""
Structural validation of uploaded files. Uploaded content is only parsed as data: nothing is executed,
imported or unpickled, HDF5 links that point outside the file are rejected, MAT files are inspected via
scipy.io/h5py, and tables (.csv, .tsv, .xlsx, .parquet, .json) are checked for bounds and readability.
"""

from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path

from .models import ValidationSummary

HDF5_SIGNATURE = b"\x89HDF\r\n\x1a\n"
MIN_OBS = 5
MIN_VARS = 2
MAX_CELLS_X_GENES = 2_000_000_000
MAX_TABLE_ROWS = 200_000
MAX_TABLE_COLUMNS = 100_000
MAX_HDF5_OBJECTS = 200_000
MAX_ZARR_FILES = 200_000
MAX_SBML_ELEMENTS = 500_000

_SBML_NS_PREFIX = "{http://www.sbml.org/sbml/"
_XINCLUDE_NS = "{http://www.w3.org/2001/XInclude}"

_PHI_COLUMN_RE = re.compile(
    r"(?:^|[_\W])(name|first_?name|last_?name|surname|dob|birth_?date|date_?of_?birth|mrn|ssn|"
    r"social_?security|address|street|phone|email|zip_?code|postcode)(?:$|[_\W])",
    re.IGNORECASE,
)
_UNS_HINT_KEYS = ("organism", "species", "tissue", "disease", "technology", "assay")


class ValidationFailure(Exception):
    """A file that cannot be accepted; reason_code is stable and shown to the uploader."""

    def __init__(self, reason_code: str, detail: str) -> None:
        super().__init__(detail)
        self.reason_code = reason_code
        self.detail = detail


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def _check_dims(n_obs: int, n_vars: int) -> None:
    if n_obs < MIN_OBS:
        raise ValidationFailure("too_few_cells", f"The matrix has {n_obs} cells; at least {MIN_OBS} are needed.")
    if n_vars < MIN_VARS:
        raise ValidationFailure("too_few_genes", f"The matrix has {n_vars} genes; at least {MIN_VARS} are needed.")
    if n_obs * n_vars > MAX_CELLS_X_GENES:
        raise ValidationFailure(
            "matrix_too_large", f"{n_obs} cells × {n_vars} genes exceeds the {MAX_CELLS_X_GENES:.0e} cell-gene limit."
        )


def _phi_warnings(columns: list[str]) -> list[str]:
    return [
        f"obs column '{c}' may contain direct identifiers; confirm it is de-identified"
        for c in columns
        if _PHI_COLUMN_RE.search(c)
    ]


def _decode(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def check_hdf5_structure(f: object, max_objects: int = MAX_HDF5_OBJECTS) -> int:
    """Reject HDF5 soft/external links, virtual or externally stored datasets and object-count bombs."""
    import h5py

    offending: list[str] = []
    count = 0

    def check_link(name: str, link: object) -> bool | None:
        nonlocal count
        count += 1
        if count > max_objects:
            return True
        if isinstance(link, (h5py.ExternalLink, h5py.SoftLink)):
            offending.append(f"{name} ({type(link).__name__})")
        return None

    try:
        f.visititems_links(check_link)  # type: ignore[attr-defined]
    except Exception as exc:
        raise ValidationFailure("hdf5_unreadable", f"The HDF5 structure could not be traversed ({type(exc).__name__}).") from exc
    if count > max_objects:
        raise ValidationFailure("hdf5_too_complex", f"The HDF5 file has more than {max_objects:,} objects.")
    if offending:
        raise ValidationFailure(
            "hdf5_external_link",
            f"The file contains HDF5 links, which are not allowed in uploads: {', '.join(offending[:5])}.",
        )

    elements = 0

    def check_dataset(name: str, obj: object) -> None:
        nonlocal elements
        if isinstance(obj, h5py.Dataset):
            if obj.is_virtual or obj.external:
                offending.append(name)
            elements += int(obj.size or 0)

    f.visititems(check_dataset)  # type: ignore[attr-defined]
    if offending:
        raise ValidationFailure(
            "hdf5_external_link",
            f"The file contains virtual or externally stored datasets, which are not allowed: {', '.join(offending[:5])}.",
        )
    return elements


def validate_hdf5(path: Path) -> ValidationSummary:
    """Validate a generic scientific HDF5 (.h5 / .hdf5) file."""
    import h5py

    with open(path, "rb") as fh:
        if fh.read(8) != HDF5_SIGNATURE:
            raise ValidationFailure("not_hdf5", "Not an HDF5 file (missing HDF5 signature).")
    try:
        f = h5py.File(path, "r")
    except Exception as exc:
        raise ValidationFailure("hdf5_unreadable", f"The HDF5 file could not be read; it may be truncated ({type(exc).__name__}).") from exc

    try:
        check_hdf5_structure(f)
        datasets: list[str] = []
        shapes: dict[str, list[int]] = {}
        dtypes: dict[str, str] = {}

        def _collect(name: str, obj: object) -> None:
            if isinstance(obj, h5py.Dataset) and len(datasets) < 200:
                datasets.append(name)
                shapes[name] = [int(s) for s in obj.shape]
                dtypes[name] = str(obj.dtype)

        f.visititems(_collect)
        if not datasets:
            raise ValidationFailure("hdf5_empty", "The HDF5 file contains no datasets.")
        first_shape = shapes[datasets[0]]
        n_rows = first_shape[0] if len(first_shape) >= 1 else None
        n_cols = first_shape[1] if len(first_shape) >= 2 else None
        return ValidationSummary(
            format="hdf5",
            n_rows=n_rows,
            n_columns=n_cols,
            datasets=datasets,
            shapes=shapes,
            dtypes=dtypes,
        )
    finally:
        f.close()


def validate_pdf(path: Path) -> ValidationSummary:
    """Validate a paper (.pdf): the %PDF- signature, readable by pypdf, not encrypted, within the page cap."""
    from tribos.config.settings import get_int

    with open(path, "rb") as fh:
        head = fh.read(1024)
    if b"%PDF-" not in head:
        raise ValidationFailure("not_pdf", "The file is not a PDF (no %PDF- header).")
    from pypdf import PdfReader

    try:
        reader = PdfReader(str(path))
        encrypted = reader.is_encrypted
    except Exception as exc:
        raise ValidationFailure("pdf_unreadable", f"The PDF could not be read ({type(exc).__name__}).") from exc
    if encrypted:
        raise ValidationFailure(
            "pdf_encrypted", "The PDF is encrypted (password-protected); save an unencrypted copy and upload that."
        )
    try:
        n_pages = len(reader.pages)
        title = str((reader.metadata or {}).get("/Title") or "").strip()[:300] or None
    except Exception as exc:
        raise ValidationFailure("pdf_unreadable", f"The PDF could not be read ({type(exc).__name__}).") from exc
    cap = int(get_int("TRIBOS_UPLOAD_MAX_PDF_PAGES"))
    if n_pages > cap:
        raise ValidationFailure("pdf_too_many_pages", f"The PDF has {n_pages} pages; at most {cap} are read.")
    if n_pages == 0:
        raise ValidationFailure("pdf_unreadable", "The PDF has no pages.")
    return ValidationSummary(format="pdf", n_pages=n_pages, title=title)


def validate_mat(path: Path) -> ValidationSummary:
    """Validate a MATLAB (.mat) file (v4/v5 via scipy.io.whosmat or v7.3 via HDF5)."""
    with open(path, "rb") as fh:
        head = fh.read(140)
    if head.startswith(HDF5_SIGNATURE) or (len(head) >= 136 and head[128:136] == HDF5_SIGNATURE):
        summary = validate_hdf5(path)
        return summary.model_copy(update={"format": "mat-v7.3"})

    from scipy import io as spio

    try:
        entries = spio.whosmat(str(path))
    except Exception as exc:
        raise ValidationFailure("mat_unreadable", f"The MATLAB .mat file could not be parsed ({type(exc).__name__}).") from exc
    if not entries:
        raise ValidationFailure("mat_empty", "The MATLAB .mat file contains no variables.")
    datasets = [str(name) for name, _, _ in entries[:200]]
    shapes = {str(name): [int(s) for s in shape] for name, shape, _ in entries[:200]}
    dtypes = {str(name): str(dt) for name, _, dt in entries[:200]}
    first_shape = shapes[datasets[0]]
    n_rows = first_shape[0] if len(first_shape) >= 1 else None
    n_cols = first_shape[1] if len(first_shape) >= 2 else None
    return ValidationSummary(
        format="mat",
        n_rows=n_rows,
        n_columns=n_cols,
        datasets=datasets,
        shapes=shapes,
        dtypes=dtypes,
    )


def preflight_h5ad(path: Path) -> dict[str, int]:
    """Cheap structural read of an .h5ad before it is loaded for analysis."""
    import h5py

    with open(path, "rb") as fh:
        if fh.read(8) != HDF5_SIGNATURE:
            raise ValidationFailure("not_hdf5", "Not an HDF5/AnnData file (missing HDF5 signature).")
    try:
        f = h5py.File(path, "r")
    except Exception as exc:
        raise ValidationFailure("hdf5_unreadable", f"The HDF5 file could not be read; it may be truncated ({type(exc).__name__}).") from exc
    try:
        elements = check_hdf5_structure(f)
        if "X" not in f:
            raise ValidationFailure("not_anndata", "The AnnData file has no X matrix.")
        x = f["X"]
        if isinstance(x, h5py.Dataset):
            shape = tuple(int(s) for s in x.shape)
        else:
            raw_shape = x.attrs.get("shape", x.attrs.get("h5sparse_shape"))
            if raw_shape is None:
                raise ValidationFailure("not_anndata", "The sparse X matrix has no shape attribute.")
            shape = tuple(int(s) for s in raw_shape)
        if len(shape) != 2:
            raise ValidationFailure("not_anndata", f"X must be a 2-D matrix, found shape {shape}.")
        return {"n_obs": shape[0], "n_vars": shape[1], "stored_elements": int(elements)}
    finally:
        f.close()


def _zarr_shape(meta_dir: Path) -> tuple[int, ...] | None:
    import json

    for name, keys in ((".zarray", ("shape",)), (".zattrs", ("shape", "h5sparse_shape")), ("zarr.json", ("shape",))):
        meta = meta_dir / name
        if not meta.is_file() or meta.stat().st_size > 1_000_000:
            continue
        try:
            doc = json.loads(meta.read_text(encoding="utf-8"))
        except ValueError:
            continue
        for container in (doc, doc.get("attributes") or {}):
            for key in keys:
                value = container.get(key) if isinstance(container, dict) else None
                if isinstance(value, list) and all(isinstance(v, int) for v in value):
                    return tuple(value)
    return None


def preflight_zarr(path: Path, max_files: int = MAX_ZARR_FILES) -> dict[str, int]:
    import os

    if not path.is_dir():
        raise ValidationFailure("not_anndata", "A .zarr dataset must be a directory store.")
    root = os.path.normcase(os.path.realpath(path))
    n_files = 0
    total_bytes = 0
    for dirpath, dirnames, filenames in os.walk(path, followlinks=False):
        for name in [*dirnames, *filenames]:
            full = os.path.join(dirpath, name)
            if os.path.islink(full):
                real = os.path.normcase(os.path.realpath(full))
                try:
                    inside = os.path.commonpath([real, root]) == root
                except ValueError:
                    inside = False
                if not inside:
                    raise ValidationFailure("zarr_external_link", f"The zarr store links outside itself ({name}).")
        n_files += len(filenames)
        if n_files > max_files:
            raise ValidationFailure("zarr_too_complex", f"The zarr store has more than {max_files:,} files.")
        for name in filenames:
            try:
                total_bytes += os.path.getsize(os.path.join(dirpath, name))
            except OSError:
                pass
    shape = _zarr_shape(path / "X")
    if shape is None or len(shape) != 2:
        raise ValidationFailure("not_anndata", "The zarr store has no recognisable 2-D AnnData X matrix.")
    return {"n_obs": int(shape[0]), "n_vars": int(shape[1]), "stored_bytes": int(total_bytes)}


def validate_h5ad(path: Path) -> ValidationSummary:
    raise ValidationFailure("unsupported_format", "h5ad format is not supported; upload table, HDF5, or MAT.")


_BARCODE_RE = re.compile(r"^[ACGTN]{8,}(?:[-_.][A-Za-z0-9]+)*$", re.IGNORECASE)
_CELL_ID_RE = re.compile(r"^(?:cells?|bc|barcodes?|obs|c)[_\-.:]?\d+$|^[A-Za-z0-9]+[_:][ACGTN]{8,}(?:-\d+)?$", re.IGNORECASE)
_GENE_RE = re.compile(
    r"^(?:ENS[A-Z]*G\d{6,}(?:\.\d+)?|MT-[A-Za-z0-9]+|[A-Za-z][A-Za-z0-9]{0,14}(?:[-.][A-Za-z0-9]{1,12}){0,2}|"
    r"[A-Za-z][A-Za-z0-9]*orf\d+)$"
)
_ORIENTATION_SAMPLE = 500


def _label_fractions(labels: list[str]) -> tuple[float, float]:
    if not labels:
        return 0.0, 0.0
    step = max(1, len(labels) // _ORIENTATION_SAMPLE)
    sample = labels[::step][:_ORIENTATION_SAMPLE]
    cells = sum(1 for x in sample if _BARCODE_RE.match(x) or _CELL_ID_RE.match(x))
    genes = sum(1 for x in sample if not (_BARCODE_RE.match(x) or _CELL_ID_RE.match(x)) and _GENE_RE.match(x))
    return genes / len(sample), cells / len(sample)


def infer_table_orientation(row_names: list[str], col_names: list[str]) -> tuple[str | None, str]:
    row_gene, row_cell = _label_fractions(row_names)
    col_gene, col_cell = _label_fractions(col_names)
    basis = (
        f"rows: {row_gene:.0%} gene-like, {row_cell:.0%} cell-id-like; "
        f"columns: {col_gene:.0%} gene-like, {col_cell:.0%} cell-id-like"
    )
    if (row_gene >= 0.6 and col_cell >= 0.6) or (row_gene >= 0.8 and col_gene <= 0.2 and row_cell <= 0.1):
        return "genes_by_cells", basis
    if (row_cell >= 0.6 and col_gene >= 0.6) or (col_gene >= 0.8 and row_gene <= 0.2 and col_cell <= 0.1):
        return "cells_by_genes", basis
    return None, basis


def _generic_table(df: object, ext: str, path: Path, out_path: Path | None) -> tuple[ValidationSummary, str | None]:
    """An ordinary table: bounds checked, columns and types recorded, missing cells reported (not refused)."""
    import pandas as pd

    assert isinstance(df, pd.DataFrame)
    if len(df) > MAX_TABLE_ROWS:
        raise ValidationFailure("matrix_too_large", f"Tables are limited to {MAX_TABLE_ROWS:,} rows.")
    if df.shape[1] > MAX_TABLE_COLUMNS:
        raise ValidationFailure("matrix_too_large", f"Tables are limited to {MAX_TABLE_COLUMNS:,} columns.")
    if df.shape[0] == 0 or df.shape[1] == 0:
        raise ValidationFailure("table_unreadable", "The table has no data rows or columns.")
    warnings: list[str] = []
    missing = int(df.isna().sum().sum())
    if missing:
        warnings.append(f"{missing} empty cell(s); they are kept as missing values, not zeros")
    derived_sha: str | None = None
    if out_path is not None:
        shutil.copyfile(path, out_path)
        derived_sha = sha256_file(out_path)
    return (
        ValidationSummary(format=ext.lstrip("."), n_rows=int(df.shape[0]), n_columns=int(df.shape[1]),
                          columns=[str(c) for c in df.columns][:200],
                          dtypes={str(c): str(t) for c, t in list(df.dtypes.items())[:200]}, warnings=warnings),
        derived_sha,
    )


def validate_table(
    path: Path,
    extension: str,
    orientation: str | None = None,
    out_path: Path | None = None,
) -> tuple[ValidationSummary, str | None]:
    """Validate a tabular dataset (.csv, .tsv, .xlsx, .parquet, .json)."""
    import numpy as np
    import pandas as pd

    ext = extension.lower()
    if ext in (".xlsx", ".parquet", ".json"):
        try:
            if ext == ".xlsx":
                df = pd.read_excel(path, nrows=MAX_TABLE_ROWS + 1)
            elif ext == ".parquet":
                df = pd.read_parquet(path)
            else:
                df = pd.read_json(path)
        except Exception as exc:
            raise ValidationFailure("table_unreadable", f"The table could not be parsed ({type(exc).__name__}).") from exc
        if len(df) > MAX_TABLE_ROWS:
            raise ValidationFailure("matrix_too_large", f"Tables are limited to {MAX_TABLE_ROWS:,} rows.")
        if df.shape[1] > MAX_TABLE_COLUMNS:
            raise ValidationFailure("matrix_too_large", f"Tables are limited to {MAX_TABLE_COLUMNS:,} columns.")
        if df.shape[1] == 0 or df.shape[0] == 0:
            raise ValidationFailure("table_unreadable", "The table has no data rows or columns.")
        cols = [str(c) for c in df.columns][:200]
        dtypes = {str(c): str(t) for c, t in list(df.dtypes.items())[:200]}
        derived_sha: str | None = None
        if out_path is not None:
            shutil.copyfile(path, out_path)
            derived_sha = sha256_file(out_path)
        return (
            ValidationSummary(
                format=ext.lstrip("."),
                n_rows=int(df.shape[0]),
                n_columns=int(df.shape[1]),
                columns=cols,
                dtypes=dtypes,
            ),
            derived_sha,
        )

    sep = "\t" if ext == ".tsv" else ","
    # Measurement tables retain their time column and signed states; they are not expression matrices.
    try:
        timecourse = pd.read_csv(path, sep=sep, nrows=MAX_TABLE_ROWS + 1)
        has_time = any(str(c).strip().lower() in ("t", "time", "elapsed", "elapsed_time", "seconds", "time_s")
                       for c in timecourse.columns)
        if has_time:
            if len(timecourse) > MAX_TABLE_ROWS or len(timecourse.columns) > MAX_TABLE_COLUMNS:
                raise ValidationFailure("matrix_too_large", "The measurement table exceeds the upload limits.")
            if len(timecourse) < 2 or len(timecourse.columns) < 2:
                raise ValidationFailure("table_unreadable", "A time course needs at least two rows and two columns.")
            if not all(pd.api.types.is_numeric_dtype(timecourse[c]) for c in timecourse):
                raise ValidationFailure("non_numeric_values", "Measurement columns must contain numeric values.")
            if not np.isfinite(timecourse.to_numpy(dtype=float)).all():
                raise ValidationFailure("non_finite_values", "Measurements contain missing or non-finite values.")
            return ValidationSummary(format=ext.lstrip("."), n_rows=len(timecourse), n_columns=len(timecourse.columns),
                                     columns=[str(c) for c in timecourse],
                                     dtypes={str(c): str(t) for c, t in timecourse.dtypes.items()}), None
    except ValidationFailure:
        raise
    except Exception as exc:
        raise ValidationFailure("table_unreadable", "The measurement table could not be parsed.") from exc
    # A table is an ordinary table (x, y measurements, results, a few rows): only a declared expression-matrix
    # orientation, or gene and cell labels, make it a cells-by-genes matrix (audit AUDIT-108: a two-column `x,y`
    # table was refused as "1 genes", a short one as "2 cells").
    if orientation is None:
        row_labels = [str(v) for v in timecourse.iloc[:500, 0].tolist()] if len(timecourse.columns) else []
        col_labels = [str(c) for c in timecourse.columns[1:]]
        inferred_matrix, _basis = infer_table_orientation(row_labels, col_labels)
        # A matrix has many genes: one gene-like header ("y", "E_GPa") is not a reason to treat a table as one.
        gene_axis = col_labels if inferred_matrix == "cells_by_genes" else row_labels
        if inferred_matrix is None or len(gene_axis) < 5:
            table = timecourse
            if len(table.columns) > 1 and str(table.columns[0]).startswith("Unnamed: 0"):
                table = table.set_index(table.columns[0])  # a written DataFrame index, not a data column
            return _generic_table(table, ext, path, out_path)
    try:
        header = pd.read_csv(path, sep=sep, index_col=0, nrows=0, engine="c")
    except Exception as exc:
        raise ValidationFailure("table_unreadable", f"The table could not be parsed ({type(exc).__name__}).") from exc
    if header.shape[1] > MAX_TABLE_COLUMNS:
        raise ValidationFailure("matrix_too_large", f"Tables are limited to {MAX_TABLE_COLUMNS:,} columns.")
    try:
        df = pd.read_csv(path, sep=sep, index_col=0, nrows=MAX_TABLE_ROWS + 1, engine="c")
    except Exception as exc:
        raise ValidationFailure("table_unreadable", f"The table could not be parsed ({type(exc).__name__}).") from exc
    if len(df) > MAX_TABLE_ROWS:
        raise ValidationFailure("matrix_too_large", f"Tables are limited to {MAX_TABLE_ROWS:,} rows.")
    if df.shape[1] == 0 or df.shape[0] == 0:
        raise ValidationFailure("table_unreadable", "The table has no data rows or columns.")
    non_numeric = [str(c) for c in df.columns if not pd.api.types.is_numeric_dtype(df[c])]
    if non_numeric:
        raise ValidationFailure(
            "non_numeric_values",
            f"Every value must be numeric; non-numeric column(s): {', '.join(non_numeric[:5])}.",
        )
    matrix = df.to_numpy(dtype="float64")
    if not np.all(np.isfinite(matrix)):
        raise ValidationFailure("non_finite_values", "The table contains empty, NaN or infinite values.")

    row_names = [str(i) for i in df.index]
    col_names = [str(c) for c in df.columns]
    warnings: list[str] = []
    inferred, basis = infer_table_orientation(row_names, col_names)
    if orientation and inferred and orientation != inferred:
        raise ValidationFailure(
            "orientation_mismatch",
            f"The table was declared {orientation.replace('_', ' ')} but its labels indicate "
            f"{inferred.replace('_', ' ')} ({basis}). Re-upload with orientation '{inferred}' if that is correct.",
        )
    if orientation is None:
        if inferred:
            orientation = inferred
            warnings.append(f"orientation not declared; inferred {inferred.replace('_', ' ')} from the labels ({basis})")
        else:
            orientation = "cells_by_genes"
            warnings.append("orientation not declared and not recognisable from the labels; assumed cells by genes")
    elif inferred is None:
        warnings.append(f"the declared orientation ({orientation.replace('_', ' ')}) could not be checked against the labels ({basis})")
    if orientation == "genes_by_cells":
        matrix = matrix.T
        obs_names, var_names = col_names, row_names
    else:
        obs_names, var_names = row_names, col_names
    n_obs, n_vars = matrix.shape
    _check_dims(int(n_obs), int(n_vars))

    derived_sha = None
    if out_path is not None:
        try:
            import anndata as ad

            adata = ad.AnnData(
                X=matrix.astype(np.float32),
                obs=pd.DataFrame(index=pd.Index(obs_names, dtype=str)),
                var=pd.DataFrame(index=pd.Index(var_names, dtype=str)),
            )
            if not adata.obs_names.is_unique:
                adata.obs_names_make_unique()
                warnings.append("duplicate cell names were made unique")
            if not adata.var_names.is_unique:
                adata.var_names_make_unique()
                warnings.append("duplicate gene names were made unique")
            if bool(np.any(matrix < 0)):
                warnings.append("the matrix contains negative values; Lumicell expects raw or normalized counts")
            adata.write_h5ad(out_path)
            derived_sha = sha256_file(out_path)
        except ImportError:
            shutil.copyfile(path, out_path)
            derived_sha = sha256_file(out_path)

    summary = ValidationSummary(
        format=f"{ext.lstrip('.')}->anndata",
        n_obs=int(n_obs),
        n_vars=int(n_vars),
        n_rows=int(df.shape[0]),
        n_columns=int(df.shape[1]),
        columns=col_names[:200],
        x_encoding="array",
        table_orientation=orientation,
        warnings=warnings,
    )
    return summary, derived_sha


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def validate_sbml(path: Path) -> ValidationSummary:
    raise ValidationFailure("unsupported_format", "SBML format is not supported; upload table, HDF5, or MAT.")



def validate_dataset_upload(
    path: Path | str,
    original_filename: str | None = None,
    *,
    orientation: str | None = None,
    out_path: Path | None = None,
) -> ValidationSummary:
    """Validate a file in any format the upload store accepts (.csv, .tsv, .xlsx, .parquet, .json, .h5, .hdf5, .mat, .h5ad, .xml, .sbml)."""
    p = Path(path)
    fn = original_filename or p.name
    suffix = Path(fn).suffix.lower()
    if suffix in (".h5", ".hdf5"):
        return validate_hdf5(p)
    if suffix == ".mat":
        return validate_mat(p)
    if suffix in (".csv", ".tsv", ".xlsx", ".parquet", ".json"):
        if out_path is not None:
            return validate_table(p, suffix, orientation, Path(out_path))[0]
        import tempfile

        with tempfile.TemporaryDirectory(prefix="tribos_table_") as tmp:
            return validate_table(p, suffix, orientation, Path(tmp) / "data.h5ad")[0]
    raise ValidationFailure(
        "unsupported_format",
        f"Unsupported file extension: {suffix or '(none)'}; upload table (.csv, .tsv, .xlsx, .json, .parquet), HDF5 (.h5, .hdf5), or MAT (.mat).",
    )
