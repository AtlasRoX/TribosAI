"""
Interactive simulation for the result cards' Explore panel (T6): re-run an ODE with new parameters, sweep a parameter
for a bifurcation (orbit) diagram, or sample the vector field of a phase plane.

Routes (authenticated; each call is rate-limited per user and runs in a worker thread under a time limit):
- POST /api/simulate {model_name?, rhs?, parameters?, initial_state?, t_span?, num_points<=2000, method?}
  -> the dynamis_simulate_ode result shape, with the resolved spec. Without an rhs, model_name names an ODE preset
  (results stored before the spec was recorded carry only the preset's name).
- POST /api/simulate/bifurcation {spec, parameter, start, stop, steps<=200, observable?, transient_fraction?}
  -> {parameter, values, points: [{value, maxima, minima, ...}], ...}
- POST /api/simulate/vector_field {spec, x_var, y_var, x_range, y_range, n<=25} -> {x, y, u, v, ...}

Every expression goes through the allowlist parser (tribos/dynamis/interactive.py); nothing is evaluated directly.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import time
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.backend.auth import get_current_user
from app.backend.limits import UserConcurrencyLimiter, UserRateLimiter
from tribos.config.settings import get_float, get_int
from tribos.dynamis import interactive
from tribos.dynamis.interactive import DeadlineExceeded, SpecError

logger = logging.getLogger("tribos.backend.simulate")
router = APIRouter(prefix="/api/simulate", tags=["simulate"])

_rate = UserRateLimiter(int(get_int("TRIBOS_SIMULATE_RATE_PER_MIN")), 60.0)
_slots = UserConcurrencyLimiter(int(get_int("TRIBOS_SIMULATE_MAX_CONCURRENT")))

Numbers = dict[str, float]


class SimulateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_name: str | None = Field(default=None, max_length=64)
    rhs: dict[str, str] | None = Field(default=None, description="State variable -> derivative expression")
    parameters: Numbers | None = None
    initial_state: Numbers | None = None
    t_span: list[float] | None = Field(default=None, min_length=2, max_length=2)
    num_points: int = Field(default=400, ge=2, le=interactive.MAX_NUM_POINTS)
    method: str | None = Field(default=None, max_length=16)
    step_size: float | None = Field(default=None, gt=0)
    num_steps: int | None = Field(default=None, ge=1, le=9999)


class Spec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_name: str | None = Field(default=None, max_length=64)
    rhs: dict[str, str] | None = None
    parameters: Numbers | None = None
    initial_state: Numbers | None = None
    t_span: list[float] | None = Field(default=None, min_length=2, max_length=2)
    method: str | None = Field(default=None, max_length=16)
    step_size: float | None = Field(default=None, gt=0)
    num_steps: int | None = Field(default=None, ge=1, le=9999)


class BifurcationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec: Spec
    parameter: str = Field(..., min_length=1, max_length=64)
    start: float
    stop: float
    steps: int = Field(default=100, ge=2, le=interactive.MAX_BIFURCATION_STEPS)
    observable: str | None = Field(default=None, max_length=64)
    transient_fraction: float = Field(default=0.5, ge=0.0, le=0.95)


class VectorFieldRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec: Spec
    x_var: str = Field(..., min_length=1, max_length=64)
    y_var: str = Field(..., min_length=1, max_length=64)
    x_range: list[float] = Field(..., min_length=2, max_length=2)
    y_range: list[float] = Field(..., min_length=2, max_length=2)
    n: int = Field(default=15, ge=2, le=interactive.MAX_VECTOR_FIELD_N)
    t: float | None = None
    fixed: Numbers | None = None


def _spec(model: BaseModel) -> dict[str, Any]:
    return {k: v for k, v in model.model_dump().items() if v is not None and k != "num_points"}


async def _run(user_id: str, work: Callable[..., dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
    """Run one computation in a worker thread under the time limit, holding one of the user's slots until it ends.

    The computation also gets the deadline itself, so a sweep stops cooperatively; a call that cannot stop (one ODE
    integration) keeps its slot until it finishes, so timed-out calls cannot pile up threads.
    """
    _rate.acquire_or_429(user_id, "Too many simulation requests; wait a moment before trying again.")
    _slots.acquire_or_429(user_id, "Another simulation of yours is still running; wait for it to finish.")
    timeout = float(get_float("TRIBOS_SIMULATE_TIMEOUT_S"))
    loop = asyncio.get_running_loop()
    future = loop.run_in_executor(None, functools.partial(work, deadline=time.monotonic() + timeout, **kwargs))
    future.add_done_callback(lambda _f: _slots.release(user_id))
    try:
        return await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
    except (TimeoutError, DeadlineExceeded) as exc:
        raise HTTPException(
            status_code=504,
            detail=f"The simulation took longer than {timeout:g} s. Shorten the time span, use fewer points or steps, "
                   "or try a stiff method (BDF, Radau).",
        ) from exc
    except SpecError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)[:500]) from exc
    except Exception as exc:
        logger.exception("Interactive simulation failed")
        raise HTTPException(status_code=500, detail="The simulation failed on the server.") from exc


@router.post("")
async def simulate(req: SimulateRequest, user_id: str = Depends(get_current_user)) -> dict[str, Any]:
    return await _run(user_id, interactive.simulate, spec=_spec(req), num_points=req.num_points)


@router.post("/bifurcation")
async def bifurcation(req: BifurcationRequest, user_id: str = Depends(get_current_user)) -> dict[str, Any]:
    return await _run(
        user_id, interactive.bifurcation, spec=_spec(req.spec), parameter=req.parameter, start=req.start,
        stop=req.stop, steps=req.steps, observable=req.observable, transient_fraction=req.transient_fraction,
    )


@router.post("/vector_field")
async def vector_field(req: VectorFieldRequest, user_id: str = Depends(get_current_user)) -> dict[str, Any]:
    return await _run(
        user_id, interactive.vector_field, spec=_spec(req.spec), x_var=req.x_var, y_var=req.y_var,
        x_range=req.x_range, y_range=req.y_range, n=req.n, t=req.t, fixed=req.fixed,
    )
