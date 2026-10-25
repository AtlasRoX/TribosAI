import { test } from "node:test";
import assert from "node:assert/strict";
import { generateDynamicTitle } from "../src/lib/dynamicTitle.ts";

test("generateDynamicTitle extracts clean titles from conversational prompts", () => {
  // Preamble stripping & capitalization
  assert.equal(
    generateDynamicTitle("Can you please explain what are the common failure modes of bolted joints?"),
    "Common Failure Modes of Bolted Joints"
  );

  // STEM acronyms keep their casing, even when typed in lower case
  assert.equal(generateDynamicTitle("What is the role of the fft in solving a pde?"), "Role of the FFT in Solving a PDE");
  assert.equal(generateDynamicTitle("Tell me about LQR and PID control of a 2d gantry"), "LQR and PID Control of a 2D Gantry");

  // Mixed-case names stay as typed
  assert.equal(generateDynamicTitle("integrate the Lorenz system with SciPy"), "Integrate the Lorenz System with SciPy");

  // Ordinary words that look like old biomedical acronyms are not upper-cased
  assert.equal(generateDynamicTitle("all modes met the damping target"), "All Modes Met the Damping Target");

  // Direct questions
  assert.equal(
    generateDynamicTitle("How does Runge-Kutta compare to implicit Euler?"),
    "Runge-Kutta Compare to Implicit Euler"
  );

  // Short prompts
  assert.equal(generateDynamicTitle("RLC resonance"), "RLC Resonance");

  // Empty or invalid inputs
  assert.equal(generateDynamicTitle(""), "Investigation");
  assert.equal(generateDynamicTitle("   ??? "), "Investigation");
});

test("generateDynamicTitle drops punctuation left at the cut", () => {
  const title = generateDynamicTitle(
    "For a simply supported steel beam under a uniform load, compare Euler-Bernoulli and Timoshenko theory: summarize the deflection"
  );
  assert.ok(!/[,.:;]$/.test(title), title);
});
