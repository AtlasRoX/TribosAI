---
name: constructions
description: Searches for objects that beat or match a bound (rulers, codes, packings, extremal sets).
triggers:
  - \b(?:construct\w*|construction)\b
  - \b(?:golomb|cap set|sidon|no[- ]three[- ]in[- ]line|packing|extremal|lower bound|upper bound|record)\b
---
1. Give the object explicitly (the list, the coordinates) and the value it achieves, and say it was checked exactly.
2. Compare with the best known value and its source; "matches", "falls short" or "exceeds": a value beyond the record is a candidate that needs independent confirmation and a literature check, never a solved problem.
3. A construction proves a bound in one direction only: say which, and do not claim optimality unless it meets a proved bound.
4. Include the program that generated it, so the reader can rerun it.
