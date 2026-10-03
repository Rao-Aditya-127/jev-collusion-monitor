import functools

import pytest

from jevmon.loaders.core import load_core
from jevmon.loaders.narcbench import MODELS
from jevmon.paths import data_root


@functools.cache
def _core(model):
    return load_core(model)


@pytest.fixture(params=MODELS)
def core_runs(request):
    if not (data_root() / "scenarios" / request.param / "core").is_dir():
        pytest.skip(f"NARCBench data not downloaded for {request.param} (see README.md)")
    return _core(request.param)
