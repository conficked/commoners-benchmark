/*
 * scoreboard: a split-flap board whose value column flips through one measure after another.
 * An ascii.rest piece (https://ascii.rest, MIT), adapted from its split-flap board.
 *
 * options.rows:  [[track, harness], ...]          fixed labels, one per row
 * options.pages: [{ label, values: [...] }, ...]  one value per row, page by page
 */

export const meta = {
  name: "scoreboard",
  category: "type",
  note: "a split-flap board flipping between measures of a benchmark",
  cols: 54,
  rows: 14,
  fps: 15,
  options: {
    title: "scoreboard",
    rows: [["clean", "hermes"], ["clean", "openbot"]],
    pages: [{ label: "solved", values: ["65/89", "58/89"] }],
  },
};

const TEXT = " ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.,-/'&$%:+";
const STEP = 3.4;
const LEAD = 0.8;
const RATE = 30;

const hash = (a, b, c) => {
  let h = Math.imul(a, 374761393) + Math.imul(b, 668265263) + Math.imul(c, 2246822519);
  h = Math.imul(h ^ (h >>> 13), 1274126177);
  return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
};
const clean = (s) => [...String(s ?? "").toUpperCase()].map((ch) => (TEXT.includes(ch) ? ch : " ")).join("");

export default function scoreboard({ title = meta.options.title, rows: list = meta.options.rows, pages = meta.options.pages } = {}) {
  const { cols, rows } = meta;
  const lines = (list || []).slice(0, 4).map((r) => r.map(clean));
  const book = (pages && pages.length ? pages : meta.options.pages).map((p) => ({ label: clean(p.label), values: (p.values || []).map(clean) }));
  const page = (s) => book[((s % book.length) + book.length) % book.length];

  // [row, first column, tiles, text on board s]
  const fields = [[1, 30, 11, (s) => page(s).label.padStart(11)]];
  lines.forEach((line, i) => {
    const r = 5 + i * 2;
    fields.push(
      [r, 2, 5, () => line[0]],
      [r, 14, 7, () => line[1]],
      [r, 30, 11, (s) => (page(s).values[i] || "").padStart(11)],
    );
  });

  const base = [];
  for (let r = 0; r < rows; r++) base.push(("│" + " ".repeat(cols - 2) + "│").split(""));
  base[0] = ("╭" + "─".repeat(cols - 2) + "╮").split("");
  base[3] = ("├" + "─".repeat(cols - 2) + "┤").split("");
  base[rows - 1] = ("╰" + "─".repeat(cols - 2) + "╯").split("");
  const put = (r, c, s) => [...s].forEach((ch, i) => c + i < cols - 1 && (base[r][c + i] = ch));
  put(1, 2, [...clean(title).slice(0, 12)].join(" "));
  put(4, 2, "track");
  put(4, 14, "harness");
  for (const [r, c, len] of fields) for (let i = 0; i < len; i++) base[r + 1][c + 2 * i] = "¯";

  return (t) => {
    const v = t - LEAD + STEP;
    const k = Math.floor(v / STEP);
    const since = v - k * STEP;
    const grid = base.map((row) => row.slice());
    for (const [r, c, len, text] of fields) {
      const to = text(k).padEnd(len).slice(0, len);
      const from = text(k - 1).padEnd(len).slice(0, len);
      for (let i = 0; i < len; i++) {
        const a = Math.max(0, TEXT.indexOf(from[i])), b = Math.max(0, TEXT.indexOf(to[i]));
        let ch = TEXT[b];
        if (a !== b) {
          const begin = r * 0.02 + (c + 2 * i) * 0.004 + hash(r, c + i, k) * 0.12;
          const flips = Math.floor(Math.max(0, since - begin) * RATE);
          const need = (b - a + TEXT.length) % TEXT.length;
          if (flips < need) {
            ch = TEXT[(a + flips) % TEXT.length];
            if (since >= begin) grid[r + 1][c + 2 * i] = "▀";
          }
        }
        grid[r][c + 2 * i] = ch;
      }
    }
    return grid.map((row) => row.join("")).join("\n");
  };
}
