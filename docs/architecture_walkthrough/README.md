# AutoLab architecture walkthrough

A minimal light-theme diagram: component names, connections, and the adaptive feedback loop. No build, dependencies, backend, or external assets.

From the repository root:

```sh
python3 -m http.server 8000 --bind 127.0.0.1 --directory docs/architecture_walkthrough
```

Open **http://localhost:8000**, or open `index.html` directly in your browser.

- The 1920 × 1080 canvas scales uniformly to fit the viewport. No scrolling or mobile rearrangement.
- Hover or keyboard-focus a component to highlight connections. Click it to focus its neighborhood. Click again, click the background, or press Escape to reset.
- **Walkthrough** highlights 16 stages without moving the diagram. Use Previous/Next or left/right arrows. Escape exits.
- Violet borders distinguish reasoning agents; mint distinguishes deterministic infrastructure; amber distinguishes human input/approval; blue distinguishes persistent memory.
- **Scientific Critic ↺** on the analysis-to-result connection references the same critic shown above. Hover or click that reference to highlight the existing role.
- Dotted downward connections terminate at the Research Ledger. Dashed horizontal links indicate evidence grounding, review returns, or bounded repair.

Arrows describe logical flow through AutoLab's deterministic controls; they do not represent unrestricted agent-to-agent messaging. Human approval and independent audits remain explicit. This is an architecture explanation, not a live run status, approval interface, or experiment runner.
