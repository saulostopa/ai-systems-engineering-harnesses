const events = JSON.parse(document.getElementById("event-data").textContent);
const get = id => document.getElementById(id);
const buttons = [...get("timeline").querySelectorAll("button")];
const nodes = [...get("flow").querySelectorAll(".flow-node")];
const motion = matchMedia("(prefers-reduced-motion: reduce)");
const control = Object.fromEntries(["play", "back", "next", "restart", "track", "position"].map(id => [id, get(id)]));
const playedNodes = new Set();
let index = 0;
let timer;
let activeNode;
let signal;

function pause() {
  clearTimeout(timer);
  timer = undefined;
  control.play.textContent = "Reproduzir";
  control.play.setAttribute("aria-pressed", "false");
}

function moveSignal(from, to) {
  signal?.remove();
  if (!from || !to || from === to || motion.matches) return;
  signal = document.createElement("span");
  signal.className = "signal";
  get("flow").append(signal);
  const panel = get("flow").getBoundingClientRect();
  const point = node => {
    const rect = node.getBoundingClientRect();
    return {left: rect.left + rect.width / 2 - panel.left + "px", top: rect.top + rect.height / 2 - panel.top + "px"};
  };
  const marker = signal;
  marker.animate([point(from), point(to)], {duration: 440, easing: "cubic-bezier(.25,.65,.3,1)"}).finished
    .then(() => marker.remove(), () => marker.remove());
}

function select(target) {
  index = Math.max(0, Math.min(events.length - 1, target));
  const event = events[index];
  const previous = activeNode;
  playedNodes.clear();
  for (const prior of events.slice(0, index)) playedNodes.add(prior.node);
  nodes.forEach(node => {
    const selected = node.dataset.node === event.node;
    node.classList.toggle("is-active", selected);
    node.classList.toggle("is-past", playedNodes.has(node.dataset.node));
    if (selected) {
      activeNode = node;
      node.dataset.tone = event.tone;
    }
  });
  moveSignal(previous, activeNode);
  buttons.forEach((button, i) => {
    if (i === index) button.setAttribute("aria-current", "step");
    else button.removeAttribute("aria-current");
  });
  const timeline = get("timeline");
  const selected = buttons[index].getBoundingClientRect();
  const viewport = timeline.getBoundingClientRect();
  if (selected.bottom > viewport.bottom) timeline.scrollTop += selected.bottom - viewport.bottom + 4;
  if (selected.top < viewport.top) timeline.scrollTop -= viewport.top - selected.top + 4;
  get("detail-title").textContent = event.title;
  const tag = get("detail-state");
  tag.textContent = event.status;
  tag.dataset.tone = event.tone;
  tag.hidden = false;
  get("detail").replaceChildren(...event.details.map(([label, value]) => {
    const row = document.createElement("div");
    const dt = document.createElement("dt");
    const dd = document.createElement("dd");
    dt.textContent = label;
    dd.textContent = value;
    row.append(dt, dd);
    return row;
  }));
  const inspector = get("inspector");
  inspector.classList.remove("flash");
  void inspector.offsetWidth;
  inspector.classList.add("flash");
  control.track.value = index;
  control.track.setAttribute("aria-valuetext", event.title + " · " + event.status);
  control.position.textContent = (index + 1) + " / " + events.length;
  control.back.disabled = index === 0;
  control.next.disabled = index === events.length - 1;
  if (control.next.disabled) pause();
  control.play.disabled = control.next.disabled || motion.matches;
}

function seek(target) {
  pause();
  select(target);
}

function advance() {
  const next = events[index + 1];
  if (!next) return pause();
  const sourceDelay = next.offset - events[index].offset;
  timer = setTimeout(() => {
    select(index + 1);
    if (!control.next.disabled) advance();
  }, Math.max(650, Math.min(1800, sourceDelay)));
}

control.back.onclick = () => seek(index - 1);
control.next.onclick = () => seek(index + 1);
control.restart.onclick = () => seek(0);
control.play.onclick = () => {
  if (timer) return pause();
  control.play.textContent = "Pausar";
  control.play.setAttribute("aria-pressed", "true");
  advance();
};
control.track.max = events.length - 1;
control.track.oninput = () => seek(Number(control.track.value));
buttons.forEach((button, i) => button.onclick = () => seek(i));
motion.addEventListener("change", () => {
  pause();
  signal?.remove();
  control.play.disabled = motion.matches || control.next.disabled;
});
get("controls").hidden = false;
select(0);
