## Unreleased

### Features

- **agents**: A chemistry agent for organic-chemistry questions: it works the reaction step by step as structures,
  code checks every structure and matches the compound asked about to the answer options, and a mismatch is sent back
  once for repair

- **physis**: Organic structures checked by code: formula, degree of unsaturation, stereocentres with their
  descriptors, chirality and meso forms, stereoisomer counts and distinct hydrogen and carbon environments

- **physis**: Stereodescriptors read as geometry: for each candidate structure, which groups share a face of each ring
  (cis or trans, syn or anti, endo or exo)

- **physis**: Answer options named as substituted chains and rings are built from their names before the answer is
  written, so their descriptors are compared as geometry rather than assigned by hand

- **physis**: Real-fluid properties from reference equations of state: state properties, throttling,
  isentropic expansion and saturation for 130+ fluids, planned when a question names a fluid process

- **agents**: Field conventions an exercise assumes, stated in the answer: bond quoting, annualised term rates, Lah
  numbers for ordered subsets, the IUPAC sign of work and the textbook TCP latency model

- **agents**: Opt-in independent cross-check of a problem's answer (`TRIBOS_CROSS_CHECK`, off by default)

- **website**: This homepage and changelog

### Bug Fixes

- **routing**: Words that narrate a multiple-choice question ("preliminary studies", "typically", "measured") no longer
  send it to literature search; explicit requests for sources still do

- **physis**: A numbered atom written without its hydrogens is read with them, not as a radical

- **routing**: Words that narrate an exercise ("published", "according to", "a recent graduate") no longer send a
  self-contained calculation to literature search

- **planner**: The answer options of a multiple-choice question are never read as a request to run a simulation

- **planner**: Letters in a question's stem ("compound B.") are no longer taken for answer options

- **verify**: No false "Verification found errors" notice for congruence chains, unit-prefix conversions or lists of
  cases

- **evals**: The grader reads LaTeX spacing commands, the normal CDF and list answers stated in prose
