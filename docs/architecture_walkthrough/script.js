"use strict";
(() => {
  const canvas = document.getElementById("canvas");
  const nodes = [...document.querySelectorAll(".node, .control-plane, .research-ledger")];
  const routes = [...document.querySelectorAll(".routes path")];
  const memoryLayer = document.getElementById("ledger-connections");
  const toggle = document.getElementById("walkthrough-toggle");
  const controls = document.getElementById("walkthrough-controls");
  const caption = document.getElementById("walkthrough-caption");
  const previous = document.getElementById("previous");
  const next = document.getElementById("next");
  const svgNS = "http://www.w3.org/2000/svg";
  let scale = 1;
  let selected = null;
  let hovered = null;
  let walking = false;
  let step = 0;

  const steps = [
    { nodes: ["charter"], title: "Research Charter" },
    { nodes: ["planner", "control"], title: "PI / Planner" },
    { nodes: ["evidence"], title: "Gather Evidence" },
    { nodes: ["hypothesis"], title: "Generate Hypotheses" },
    { nodes: ["critic", "hypothesis"], title: "Scientific Critic · Checkpoint ①" },
    { nodes: ["designer", "critic", "planner", "spec", "feasibility"], title: "Design & Select an Experiment" },
    { nodes: ["spec", "feasibility", "approval"], title: "Mandatory Human Approval" },
    { nodes: ["preparation", "manifest"], title: "Prepare Resources" },
    { nodes: ["readiness", "manifest"], title: "Independent Readiness Audit" },
    { nodes: ["implementation", "validators"], title: "Implement the Scientific Contract" },
    { nodes: ["code-auditor", "validators"], title: "Independent Code Audit" },
    { nodes: ["runner", "code-auditor"], title: "Deterministic Experiment Runner" },
    { nodes: ["metrics"], title: "Deterministic Metrics" },
    { nodes: ["analysis", "metrics"], title: "Scientific Interpretation" },
    { nodes: ["analysis", "critic", "reviewed"], title: "Scientific Critic · Checkpoint ③" },
    { nodes: ["reviewed", "planner", "control", "ledger"], title: "Result → Next Scientific Decision" }
  ];

  function fitCanvas() {
    scale = Math.min(window.innerWidth / 1920, window.innerHeight / 1080);
    canvas.style.transform = `scale(${scale})`;
    canvas.style.left = `${(window.innerWidth - 1920 * scale) / 2}px`;
    canvas.style.top = `${(window.innerHeight - 1080 * scale) / 2}px`;
  }

  // Every major component persists structured records to the same ledger.
  for (const node of nodes.filter(node => node.classList.contains("node"))) {
    const x = Number(node.style.getPropertyValue("--x")) + Number(node.style.getPropertyValue("--w")) / 2;
    const y = Number(node.style.getPropertyValue("--y")) + Number(node.style.getPropertyValue("--h"));
    const line = document.createElementNS(svgNS, "path");
    line.setAttribute("d", `M${x} ${y}V1011`);
    line.setAttribute("class", "memory-line");
    line.dataset.from = node.id;
    line.dataset.to = "ledger";
    memoryLayer.append(line);
    const dot = document.createElementNS(svgNS, "circle");
    dot.setAttribute("cx", x);
    dot.setAttribute("cy", 1011);
    dot.setAttribute("r", 2);
    dot.setAttribute("class", "memory-dot");
    memoryLayer.append(dot);
  }
  const memoryLines = [...memoryLayer.querySelectorAll("path")];

  function updateHighlights() {
    let primary = walking ? steps[step].nodes : selected ? [selected] : [];
    if (hovered) primary = [...primary, hovered];
    const emphasized = new Set(primary);
    const hasFocus = walking || selected !== null;
    // In focus mode, retain directly connected nodes for architectural context.
    if (selected && !walking) {
      for (const route of routes) {
        if (primary.includes(route.dataset.from) || primary.includes(route.dataset.to)) {
          emphasized.add(route.dataset.from);
          emphasized.add(route.dataset.to);
        }
      }
      emphasized.add("ledger");
    }
    for (const node of nodes) {
      node.classList.toggle("is-highlighted", primary.includes(node.id));
      node.classList.toggle("is-selected", selected === node.id && !walking);
      node.setAttribute("aria-pressed", String(selected === node.id && !walking));
      node.classList.toggle("is-dimmed", hasFocus && !emphasized.has(node.id));
    }
    for (const route of [...routes, ...memoryLines]) {
      const linked = primary.includes(route.dataset.from) || primary.includes(route.dataset.to);
      route.classList.toggle("is-highlighted", linked);
      route.classList.toggle("is-dimmed", hasFocus && !linked);
    }
    document.querySelector(".feedback-label").classList.toggle("is-dimmed", hasFocus && !emphasized.has("reviewed") && !emphasized.has("planner"));
    const criticReference = document.getElementById("critic-checkpoint");
    criticReference.classList.toggle("is-dimmed", hasFocus && !emphasized.has("critic") && !emphasized.has("analysis"));
    criticReference.classList.toggle("is-highlighted", primary.includes("critic"));
  }

  for (const node of nodes) {
    const enter = () => {
      hovered = node.id;
      updateHighlights();
    };
    const leave = () => {
      if (hovered === node.id) hovered = null;
      updateHighlights();
    };
    node.addEventListener("pointerenter", enter);
    node.addEventListener("pointerleave", leave);
    node.addEventListener("focus", enter);
    node.addEventListener("blur", leave);
    node.addEventListener("click", () => {
      if (walking) return;
      selected = selected === node.id ? null : node.id;
      updateHighlights();
    });
    node.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        node.click();
      }
    });
  }

  // This annotation references the existing critic, rather than adding an agent.
  const criticReference = document.getElementById("critic-checkpoint");
  criticReference.addEventListener("pointerenter", () => { hovered = "critic"; updateHighlights(); });
  criticReference.addEventListener("pointerleave", () => { hovered = null; updateHighlights(); });
  criticReference.addEventListener("focus", () => { hovered = "critic"; updateHighlights(); });
  criticReference.addEventListener("blur", () => { hovered = null; updateHighlights(); });
  criticReference.addEventListener("click", () => {
    if (!walking) { selected = selected === "critic" ? null : "critic"; updateHighlights(); }
  });

  function renderStep() {
    document.getElementById("step-count").textContent = `${String(step + 1).padStart(2, "0")} / 16`;
    caption.replaceChildren();
    const title = document.createElement("b");
    title.textContent = steps[step].title;
    caption.append(title);
    previous.disabled = step === 0;
    next.disabled = step === steps.length - 1;
    updateHighlights();
  }

  function setWalkthrough(enabled) {
    walking = enabled;
    selected = null;
    hovered = null;
    toggle.setAttribute("aria-pressed", String(enabled));
    controls.hidden = !enabled;
    caption.hidden = !enabled;
    if (enabled) { step = 0; renderStep(); }
    else updateHighlights();
  }
  toggle.addEventListener("click", () => setWalkthrough(!walking));
  previous.addEventListener("click", () => { if (step > 0) { step--; renderStep(); } });
  next.addEventListener("click", () => { if (step < steps.length - 1) { step++; renderStep(); } });
  document.addEventListener("keydown", event => {
    if (event.key === "Escape") { setWalkthrough(false); document.activeElement?.blur(); }
    if (walking && ["ArrowRight", "ArrowLeft"].includes(event.key)) {
      event.preventDefault();
      if (event.key === "ArrowRight" && step < steps.length - 1) step++;
      if (event.key === "ArrowLeft" && step > 0) step--;
      renderStep();
    }
  });
  canvas.addEventListener("click", event => {
    if (!event.target.closest(".node, .control-plane, .research-ledger, button") && !walking) {
      selected = null;
      updateHighlights();
    }
  });
  window.addEventListener("resize", fitCanvas);
  fitCanvas();
})();
