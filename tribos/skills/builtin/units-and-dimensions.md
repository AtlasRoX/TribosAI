---
name: units-and-dimensions
description: Engineering and physics calculations with units.
triggers:
  - \b(?:units?|dimension\w*|SI)\b
  - \b\d+(?:\.\d+)?\s*(?:kg|N|Pa|MPa|GPa|J|W|kW|m/s|rad/s|Hz|K|mol|V|A|Ω|ohm)\b
---
1. Carry units through every line; convert to SI before combining quantities.
2. Check each final formula for dimensional consistency and say that it was checked.
3. Give an order-of-magnitude sanity check against a familiar value when one exists.
4. Report the result with a sensible number of significant figures and its unit.
