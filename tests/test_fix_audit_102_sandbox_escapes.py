"""AUDIT-102 / AUDIT-103: escape primitives found by the audit stay closed, and SageMath obeys strict isolation.

Each payload below ran in the subprocess backend during the audit: native Win32 calls through numpy.ctypeslib, a file
created outside the work directory through h5py with a computed path, and an external program launched through
matplotlib's animation writer. They must now be refused by the policy or fail at run time.
"""

from __future__ import annotations

import os

import pytest

from tribos.agentic.sandbox import gateway, policy


def _run(code: str) -> dict:
    return gateway.execute(code, timeout_s=60)


@pytest.mark.parametrize("code", [
    "import numpy.ctypeslib as c\nresult = 1",
    "from numpy import ctypeslib\nresult = 1",
    "from numpy.ctypeslib import load_library\nresult = 1",
    "import numpy as np\nresult = np.ctypeslib",
    "import numpy as np\nresult = np.zeros(2).ctypes",
    "from sympy.utilities.autowrap import autowrap\nresult = 1",
    "import sympy\nresult = sympy.preview",
    "import h5py\nresult = h5py.h5f",
    "import h5py\nresult = h5py._hl",
])
def test_native_code_compilers_and_low_level_file_apis_are_refused_by_the_policy(code):
    assert policy.check_code(code), code


def test_banned_module_matches_submodules_only_by_dotted_prefix():
    assert policy.banned_module("numpy.ctypeslib") and policy.banned_module("numpy.f2py.crackfortran")
    assert not policy.banned_module("numpy") and not policy.banned_module("numpy.linalg")


def test_sagemath_is_refused_under_strict_isolation(monkeypatch):
    monkeypatch.setenv("TRIBOS_SANDBOX_STRICT_LIMITS", "1")
    monkeypatch.delenv("TRIBOS_SANDBOX_ALLOW_UNISOLATED", raising=False)
    backend, reason = gateway._select_backend(gateway.ENGINE_SAGE)
    assert backend is None and "strict isolation" in reason
    monkeypatch.setenv("TRIBOS_SANDBOX_ALLOW_UNISOLATED", "1")
    backend, reason = gateway._select_backend(gateway.ENGINE_SAGE)
    assert backend is not None and reason is None


@pytest.fixture
def subprocess_backend(monkeypatch):
    monkeypatch.setenv("TRIBOS_SANDBOX", "on")
    monkeypatch.setenv("TRIBOS_SANDBOX_BACKEND", "subprocess")
    monkeypatch.delenv("TRIBOS_SANDBOX_STRICT_LIMITS", raising=False)


def test_h5py_cannot_create_a_file_outside_the_work_directory_through_a_computed_path(subprocess_backend, tmp_path):
    pytest.importorskip("h5py")
    target = (tmp_path / "escape.h5").as_posix()
    head, tail = target[:6], target[6:]
    rep = _run(f"import h5py\np = '{head}' + '{tail}'\nf = h5py.File(p, 'w')\nf.close()\nresult = 'created'")
    assert rep["status"] != "ok" and not os.path.exists(target), rep
    ok = _run("import h5py\nimport numpy as np\nname = 'in' + 'side.h5'\nwith h5py.File(name, 'w') as f:\n"
              "    f['x'] = np.arange(3)\nwith h5py.File(name, 'r') as f:\n    result = int(f['x'][2])")
    assert ok["status"] == "ok" and ok["result"] == 2, ok  # inside the work directory it still works


def test_programs_cannot_be_launched_through_library_features(subprocess_backend):
    exe = "C:/Windows/System32/where.exe" if os.name == "nt" else "/bin/true"
    code = ("import matplotlib\nmatplotlib.use('Agg')\nimport matplotlib.pyplot as plt\nimport matplotlib.animation as an\n"
            f"matplotlib.rcParams['animation.ffmpeg_path'] = '{exe[:5]}' + '{exe[5:]}'\n"
            "fig = plt.figure()\nw = an.FFMpegWriter(fps=1)\n"
            "try:\n    w.setup(fig, 'out.mp4')\n    w.grab_frame()\n    w.finish()\n    result = 'launched'\n"
            "except Exception as e:\n    result = str(e)\n")
    rep = _run(code)
    assert "starting programs is disabled" in str(rep.get("result")) + str(rep.get("error")), rep


def test_ordinary_analysis_still_runs(subprocess_backend):
    rep = _run("import numpy as np\nimport scipy.stats as st\nimport pandas as pd\n"
               "df = pd.DataFrame({'x': np.arange(10.0)})\nresult = float(st.norm.cdf(0)) + float(df['x'].sum())")
    assert rep["status"] == "ok" and abs(rep["result"] - 45.5) < 1e-12, rep
