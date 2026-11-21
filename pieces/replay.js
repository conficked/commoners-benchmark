/*
 * replay: a terminal that types out what an agent said, then what the tests said.
 * An ascii.rest piece (https://ascii.rest, MIT).
 *
 * options.title:   window title
 * options.text:    the agent's words, typed after the prompt
 * options.verdict: the line the tests print afterwards
 */

export const meta = {
  name: "replay",
  category: "ui",
  note: "an agent's last words typed into a terminal, then the test verdict",
  cols: 64,
  rows: 13,
  fps: 30,
  options: { title: "agent", text: "all checks passed.", verdict: "tests: 0 of 1 passed" },
};

const CPS = 55; // characters typed a second
const AFTER = 0.9; // seconds before the verdict
const HOLD = 5; // seconds the finished screen stays
const CURSOR = "▌";

function wrap(text, width) {
  const out = [];
  for (const para of String(text).split("\n")) {
    let line = "";
    for (const word of para.split(/\s+/).filter(Boolean)) {
      if ((line + " " + word).trim().length > width) {
        if (line) out.push(line);
        line = word.length > width ? word.slice(0, width) : word;
      } else line = (line + " " + word).trim();
    }
    out.push(line);
  }
  return out;
}

export default function replay({ title = meta.options.title, text = meta.options.text, verdict = meta.options.verdict } = {}) {
  const { cols, rows } = meta;
  const inner = cols - 4;
  const body = rows - 3; // lines between the title bar and the bottom edge
  const said = wrap("$ " + text, inner - 2);
  const ruling = wrap("> " + verdict, inner - 2);
  const total = said.join("").length;
  const typing = total / CPS;
  const loop = typing + AFTER + HOLD;
  const frame = (lines) => {
    const top = "╭─ " + String(title).slice(0, cols - 7) + " ";
    const out = [top + "─".repeat(Math.max(0, cols - 1 - [...top].length)) + "╮", "│" + " ".repeat(cols - 2) + "│"];
    const shown = lines.slice(-body);
    for (let i = 0; i < body; i++) {
      const l = shown[i] || "";
      out.push("│ " + l + " ".repeat(Math.max(0, inner - [...l].length)) + " │");
    }
    out.push("╰" + "─".repeat(cols - 2) + "╯");
    return out.join("\n");
  };

  return (t) => {
    const s = t % loop;
    let left = Math.floor(s * CPS);
    const lines = [];
    for (const l of said) {
      if (left <= 0) break;
      lines.push(l.slice(0, left));
      left -= l.length;
    }
    const blink = Math.floor(t * 2) % 2 === 0;
    if (s < typing) {
      if (!lines.length) lines.push("");
      lines[lines.length - 1] += blink ? CURSOR : " ";
    } else if (s >= typing + AFTER) {
      lines.push("", ...ruling);
      lines[lines.length - 1] += blink ? " " + CURSOR : "";
    }
    return frame(lines);
  };
}
