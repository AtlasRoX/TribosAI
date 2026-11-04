"""AUDIT-108: ordinary tables upload; only declared or recognisable expression matrices are validated as matrices."""

from __future__ import annotations

import pytest

from tribos.datasets.validators import ValidationFailure, validate_table


def _csv(tmp_path, text, name="t.csv"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


@pytest.mark.parametrize("text", ["x,y\n1,2\n", "x,y\n1,2\n3,4\n5,6\n7,8\n9,10\n11,12\n",
                                  "load_N,deflection_mm\n100,0.2\n200,0.41\n", "material,E_GPa\nsteel,200\naluminium,69\n"])
def test_two_column_short_and_labelled_tables_are_accepted(tmp_path, text):
    summary, _ = validate_table(_csv(tmp_path, text), ".csv")
    assert summary.n_rows == text.count("\n") - 1 and summary.n_columns == 2
    assert summary.table_orientation is None and "anndata" not in summary.format


def test_missing_values_are_kept_and_reported_not_refused(tmp_path):
    summary, _ = validate_table(_csv(tmp_path, "x,y\n1,2\n2,\n3,6\n"), ".csv")
    assert summary.n_rows == 3 and any("empty cell" in w for w in summary.warnings)


def test_a_declared_expression_matrix_still_gets_the_matrix_checks(tmp_path):
    with pytest.raises(ValidationFailure) as err:
        validate_table(_csv(tmp_path, "cell,GENE1,GENE2\nc1,1,2\nc2,3,4\n"), ".csv", orientation="cells_by_genes")
    assert err.value.reason_code == "too_few_cells"


def test_a_recognisable_expression_matrix_is_converted_as_before(tmp_path):
    genes = ["ACTB", "GAPDH", "MALAT1", "CD3E", "MS4A1", "LYZ"]
    rows = "\n".join(f"AAACCTGAGAAACCAT-{i}," + ",".join(str((i + j) % 5) for j in range(len(genes))) for i in range(8))
    summary, _ = validate_table(_csv(tmp_path, "barcode," + ",".join(genes) + "\n" + rows + "\n"), ".csv")
    assert summary.table_orientation == "cells_by_genes" and summary.n_obs == 8 and summary.n_vars == len(genes)
