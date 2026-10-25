import assert from "node:assert/strict";
import test from "node:test";
import {
  arrows,
  bifurcationScatter,
  createLatestRunner,
  exploredSpec,
  firstDoubling,
  fromSlider,
  inferRange,
  phasePath,
  timeCourse,
  toSlider,
} from "../src/lib/simulationExplore.ts";
import { shownError, simulateErrorMessage } from "../src/services/simulateService.ts";
import { ApiError } from "../src/services/apiClient.ts";

test("T6: slider ranges are 0-2x the value, log for tiny or huge values", () => {
  assert.deepEqual(inferRange(0.5), { min: 0, max: 1, log: false });
  assert.deepEqual(inferRange(-3), { min: -6, max: 0, log: false });
  assert.deepEqual(inferRange(0), { min: -1, max: 1, log: false });
  assert.deepEqual(inferRange(1e-4), { min: 1e-6, max: 1e-2, log: true });
  assert.deepEqual(inferRange(5e4), { min: 500, max: 5e6, log: true });
});

test("T6: slider positions round-trip on linear and log scales", () => {
  const lin = inferRange(2);
  assert.equal(toSlider(2, lin), 500);
  assert.equal(fromSlider(500, lin), 2);
  const log = inferRange(1e-4);
  assert.equal(toSlider(1e-4, log), 500);
  assert.equal(fromSlider(500, log), 1e-4);
  assert.equal(toSlider(99, lin), 1000); // clamped to the track
});

test("T6: the explored spec overrides values without touching the stored one", () => {
  const base = { rhs: { x: "-k*x" }, parameters: { k: 1, m: 2 }, initial_state: { x: 1 }, t_span: [0, 10] };
  const frozen = JSON.stringify(base);
  const spec = exploredSpec(base, { k: 3 }, { x: 5 }, 20);
  assert.deepEqual(spec.parameters, { k: 3, m: 2 });
  assert.deepEqual(spec.initial_state, { x: 5 });
  assert.deepEqual(spec.t_span, [0, 20]);
  assert.equal(JSON.stringify(base), frozen);
  assert.deepEqual(exploredSpec(base, {}, {}, -1).t_span, [0, 10]); // an end before the start keeps the stored one
});

function fakeTimers() {
  let now = 0;
  const queue: { at: number; fn: () => void; id: number }[] = [];
  let next = 1;
  return {
    timers: {
      setTimeout: (fn: () => void, ms: number) => {
        const id = next++;
        queue.push({ at: now + ms, fn, id });
        return id;
      },
      clearTimeout: (id: unknown) => {
        const i = queue.findIndex((q) => q.id === id);
        if (i >= 0) queue.splice(i, 1);
      },
    },
    advance(ms: number) {
      now += ms;
      for (const q of queue.filter((q) => q.at <= now)) {
        queue.splice(queue.indexOf(q), 1);
        q.fn();
      }
    },
  };
}

test("T6: changes are debounced by 250 ms and a newer run aborts the older", async () => {
  const clock = fakeTimers();
  const calls: { args: number; signal: AbortSignal; resolve: (v: number) => void }[] = [];
  const results: number[] = [];
  const runner = createLatestRunner<number, number>(
    (args, signal) => new Promise((resolve) => calls.push({ args, signal, resolve })),
    { onResult: (r) => results.push(r), onError: () => {} },
    250,
    clock.timers,
  );
  runner.schedule(1);
  clock.advance(100);
  runner.schedule(2);
  clock.advance(249);
  assert.equal(calls.length, 0, "nothing is sent while the slider still moves");
  clock.advance(1);
  assert.deepEqual(calls.map((c) => c.args), [2]);
  runner.schedule(3);
  clock.advance(250);
  assert.equal(calls[0].signal.aborted, true, "the request in flight is aborted");
  calls[0].resolve(20); // a stale response arriving late is dropped
  calls[1].resolve(30);
  await new Promise((r) => setImmediate(r));
  assert.deepEqual(results, [30]);
  runner.cancel();
  assert.equal(calls[1].signal.aborted, true);
});

test("T6: responses are shaped for the charts", () => {
  const course = timeCourse({ t: [0, 1, 2], trajectories: { x: [1, 2, 3], y: [0, 1, 0], bad: [1] } });
  assert.deepEqual(course, { t: [0, 1, 2], series: { x: [1, 2, 3], y: [0, 1, 0] } });
  assert.equal(timeCourse({ t: [0], trajectories: { x: [1] } }), null);
  assert.deepEqual(phasePath(course, "x", "y"), [[1, 0], [2, 1], [3, 0]]);

  const orbit = {
    points: [
      { value: 2.5, maxima: [3.1], steady: false },
      { value: 3.5, maxima: [2.9, 4.2], steady: false },
      { value: 1.0, maxima: [], steady: true, final: 0.4 },
    ],
  };
  assert.deepEqual(bifurcationScatter(orbit).map((p) => [p.p, p.y, p.kind]), [
    [2.5, 3.1, "max"], [3.5, 2.9, "max"], [3.5, 4.2, "max"], [1.0, 0.4, "steady"],
  ]);
  assert.equal(firstDoubling(orbit), 3.5);
  assert.equal(firstDoubling({ points: [{ value: 1, maxima: [1] }] }), null);

  const field = arrows({ x: [0, 1], y: [0, 1], u: [[1, 0], [0, 0]], v: [[0, 2], [0, 0]] });
  assert.equal(field.length, 4);
  assert.deepEqual(field[1], [1, 0, 0, 0.9]); // the longest arrow spans 0.9 of a cell
});

test("T6: errors read well for rate limits, timeouts and missing endpoints; aborts are silent", () => {
  assert.match(simulateErrorMessage(429), /Too many/);
  assert.match(simulateErrorMessage(504), /too long/);
  assert.match(simulateErrorMessage(404), /no interactive simulation endpoint/);
  assert.match(simulateErrorMessage(422, "t_span end must be greater"), /rejected: t_span/);
  assert.equal(shownError(Object.assign(new Error("x"), { name: "AbortError" })), null);
  assert.equal(shownError(new ApiError(429, simulateErrorMessage(429))), simulateErrorMessage(429));
});
