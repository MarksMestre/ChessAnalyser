"""JSON -> a single self-contained, offline HTML report.

No CDN, no web fonts, no external assets.  Piece artwork is inlined from
chess.svg, which already embeds the SVG path data rather than referencing
external files, so the whole report is one file that works from file://.

Sections
  1. Dashboard  accuracy/ACPL trend, per-phase breakdown, best and worst games,
                a recurring-weaknesses panel, and every brilliancy found.
  2. Per game   clickable eval graph, a move table with glyphs and per-move
                loss, and a board that shows the played move in red next to the
                engine's move in green.
  3. Drill mode the answer is hidden, you pick a move, then it is revealed
                together with the engine line.  This is the part you actually
                learn from.
  4. Brilliancies
  5. Export    the annotated PGN, embedded so the download works offline.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Dict

import chess.svg

ROOT = os.path.dirname(os.path.abspath(__file__))


def _pieces_json() -> str:
    """Inline the piece paths so the board renders with no external assets."""
    pieces = {k: v for k, v in chess.svg.PIECES.items()}
    return json.dumps(pieces)


CSS = """
:root{
  --bg:#12141a; --panel:#1b1e26; --panel2:#22262f; --line:#2e3340;
  --fg:#e8eaf0; --muted:#9aa2b1; --accent:#4c8bf5; --good:#26a69a;
  --warn:#f9a825; --bad:#c62828; --purple:#7e57c2;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
  font:14px/1.5 ui-sans-serif,system-ui,"Segoe UI",Roboto,sans-serif}
a{color:var(--accent)}
header{padding:18px 22px;border-bottom:1px solid var(--line);
  display:flex;align-items:baseline;gap:16px;flex-wrap:wrap;position:sticky;top:0;
  background:rgba(18,20,26,.96);backdrop-filter:blur(6px);z-index:20}
h1{font-size:17px;margin:0;letter-spacing:.3px}
h2{font-size:15px;margin:0 0 12px}
h3{font-size:13px;margin:0 0 8px;color:var(--muted);text-transform:uppercase;
  letter-spacing:.6px}
.sub{color:var(--muted);font-size:12px}
nav{display:flex;gap:6px;margin-left:auto;flex-wrap:wrap}
nav button{background:var(--panel2);color:var(--fg);border:1px solid var(--line);
  padding:6px 12px;border-radius:6px;cursor:pointer;font-size:12px}
nav button.on{background:var(--accent);border-color:var(--accent);color:#fff}
main{padding:22px;max-width:1500px;margin:0 auto}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;
  padding:16px;margin-bottom:18px}
.grid{display:grid;gap:16px}
.g2{grid-template-columns:repeat(auto-fit,minmax(320px,1fr))}
.g3{grid-template-columns:repeat(auto-fit,minmax(240px,1fr))}
.stat{background:var(--panel2);border-radius:8px;padding:12px}
.stat .v{font-size:24px;font-weight:600}
.stat .k{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.5px}
table{border-collapse:collapse;width:100%;font-size:12px}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line)}
th{color:var(--muted);font-weight:600;font-size:11px;text-transform:uppercase}
tr.clickable{cursor:pointer}
tr.clickable:hover{background:var(--panel2)}
.bar{height:8px;background:var(--panel2);border-radius:4px;overflow:hidden}
.bar>i{display:block;height:100%;background:var(--accent)}
.tag{display:inline-block;padding:1px 7px;border-radius:10px;font-size:11px;
  background:var(--panel2);border:1px solid var(--line);margin:2px 3px 2px 0}
.brilliant{color:var(--good);font-weight:700}
.great{color:var(--purple);font-weight:700}
.inaccuracy{color:var(--warn);font-weight:600}
.mistake{color:#ef6c00;font-weight:600}
.blunder{color:var(--bad);font-weight:700}
.miss{color:#1565c0;font-weight:600}
.win{color:var(--good)} .loss{color:var(--bad)} .draw{color:var(--muted)}
.chart{width:100%;height:190px;display:block;cursor:crosshair}
.moves{max-height:520px;overflow:auto}
.moves td{padding:3px 7px;font-variant-numeric:tabular-nums}
.moves .san{font-weight:600;width:64px}
.moves tr.sel{background:#2b3a52}
.moves tr:hover{background:var(--panel2)}
.boardwrap{display:flex;gap:18px;flex-wrap:wrap;align-items:flex-start}
#board{width:380px;height:380px;flex:0 0 auto}
#board svg{width:100%;height:100%;display:block;border-radius:6px}
.legend{font-size:11px;color:var(--muted);margin-top:8px;max-width:380px}
.legend b{color:var(--fg)}
.pill{display:inline-block;padding:2px 8px;border-radius:6px;background:var(--panel2);
  border:1px solid var(--line);font-size:11px;margin:2px 0}
.pill.hi{border-color:var(--good);color:var(--good)}
.pill.bad{border-color:var(--bad);color:var(--bad)}
.pill.warn{border-color:var(--warn);color:var(--warn)}
input[type=text],select{background:var(--panel2);color:var(--fg);
  border:1px solid var(--line);border-radius:6px;padding:6px 8px;font-size:12px}
.drill{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:12px}
.legend-chips button{background:var(--panel2);border:1px solid var(--line);
  color:var(--fg);padding:7px 13px;border-radius:6px;cursor:pointer;font-weight:600}
.legend-chips button.ok{border-color:var(--good);color:var(--good)}
.legend-chips button.bad{border-color:var(--bad);color:var(--bad)}
pre.pgn{max-height:420px;overflow:auto;background:#0e1014;border:1px solid var(--line);
  border-radius:8px;padding:12px;font-size:11px;white-space:pre-wrap;word-break:break-word}
.hidden{display:none!important}
.muted{color:var(--muted)}
.small{font-size:11px}
kbd{background:var(--panel2);border:1px solid var(--line);border-bottom-width:2px;
  border-radius:4px;padding:0 5px;font-size:11px;font-family:ui-monospace,monospace}
.toolbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:12px}
a.btn{display:inline-block;background:var(--accent);color:#fff;padding:7px 13px;
  border-radius:6px;text-decoration:none;font-size:12px}
"""

JS = r"""
const DATA = window.__REPORT__;
const PIECES = window.__PIECES__;
const GLYPH_CLASS = {
  brilliant:'brilliant', great:'great', inaccuracy:'inaccuracy',
  mistake:'mistake', blunder:'blunder', miss:'miss'
};
const ORDER = ['brilliant','great','book','best','excellent','good',
  'inaccuracy','mistake','blunder','miss'];

function el(tag, attrs, ...kids){
  const n = document.createElement(tag);
  for(const [k,v] of Object.entries(attrs||{})){
    if(k === 'class') n.className = v;
    else if(k === 'html') n.innerHTML = v;
    else if(k.startsWith('on')) n.addEventListener(k.slice(2), v);
    else if(v !== null && v !== undefined) n.setAttribute(k, v);
  }
  for(const kid of kids.flat()){
    if(kid === null || kid === undefined) continue;
    n.appendChild(typeof kid === 'object' ? kid : document.createTextNode(String(kid)));
  }
  return n;
}
const $ = s => document.querySelector(s);
const gamesByIndex = {};
DATA.games.forEach(g => gamesByIndex[g.index] = g);
const fmtEval = cp => {
  if(cp === null || cp === undefined) return '';
  if(Math.abs(cp) >= 90000) return (cp>0?'#':'-#') + Math.round(Math.abs(cp)/100000);
  return (cp >= 0 ? '+' : '') + (cp/100).toFixed(2);
};

/* ---------------- board rendering ---------------- */
function renderBoard(fen, arrows){
  const b = chessParse(fen);
  const N = 8, sq = 45, pad = 12;
  const w = N*sq + pad*2;
  const svg = document.createElementNS('http://www.w3.org/2000/svg','svg');
  svg.setAttribute('viewBox', `0 0 ${w} ${w}`);
  svg.setAttribute('width', w); svg.setAttribute('height', w);

  for(let rank=8; rank>=1; rank--){
    for(let file=0; file<8; file++){
      const dark = (rank + file) % 2 === 0;
      const rect = document.createElementNS('http://www.w3.org/2000/svg','rect');
      const x = pad + file*sq, y = pad + (8-rank)*sq;
      rect.setAttribute('x',x); rect.setAttribute('y',y);
      rect.setAttribute('width',sq); rect.setAttribute('height',sq);
      rect.setAttribute('fill', dark ? '#7a9a6d' : '#e8e8e0');
      rect.setAttribute('stroke','#00000022');
      svg.appendChild(rect);
    }
  }
  const files='abcdefgh';
  for(let rank=8; rank>=1; rank--){
    for(let file=0; file<8; file++){
      const piece = b.pieceAt(files[file] + rank);
      if(!piece) continue;
      const g = document.createElementNS('http://www.w3.org/2000/svg','g');
      g.innerHTML = PIECES[piece.symbol()];
      const x = pad + file*sq, y = pad + (8-rank)*sq;
      g.setAttribute('transform', `translate(${x},${y}) scale(${sq/45},${sq/45})`);
      g.setAttribute('id','sq-'+files[file]+rank);
      svg.appendChild(g);
    }
  }
  for(const [from,to,colour] of (arrows||[])){
    const f = fileIndex(from[0]), r = 8 - parseInt(from[1],10);
    const t = fileIndex(to[0]), rt = 8 - parseInt(to[1],10);
    const x1 = pad + (f+0.5)*sq, y1 = pad + (r+0.5)*sq;
    const x2 = pad + (t+0.5)*sq, y2 = pad + (rt+0.5)*sq;
    const line = document.createElementNS('http://www.w3.org/2000/svg','line');
    line.setAttribute('x1',x1); line.setAttribute('y1',y1);
    line.setAttribute('x2',x2); line.setAttribute('y2',y2);
    line.setAttribute('stroke',colour); line.setAttribute('stroke-width',7);
    line.setAttribute('stroke-linecap','round');
    line.setAttribute('opacity','0.85');
    svg.appendChild(line);
    const ang = Math.atan2(y2-y1, x2-x1);
    const head = document.createElementNS('http://www.w3.org/2000/svg','polygon');
    const L = 13, Wd = 8;
    const pts = [
      [x2, y2],
      [x2 - L*Math.cos(ang) + Wd*Math.sin(ang), y2 - L*Math.sin(ang) - Wd*Math.cos(ang)],
      [x2 - L*Math.cos(ang) - Wd*Math.sin(ang), y2 - L*Math.sin(ang) + Wd*Math.cos(ang)]
    ].map(p => p.join(',')).join(' ');
    head.setAttribute('points', pts);
    head.setAttribute('fill', colour);
    svg.appendChild(head);
  }
  return svg;
}
function fileIndex(f){ return 'abcdefgh'.indexOf(f); }

/* a deliberately tiny FEN reader: enough to draw a board */
function chessParse(fen){
  const rows = fen.split(' ')[0].split('/');
  const board = {};
  rows.forEach((row, i) => {
    const rank = 8 - i;
    let file = 0;
    for(const ch of row){
      if(/[0-9]/.test(ch)){ file += parseInt(ch,10); continue; }
      board['abcdefgh'[file] + rank] = ch;
      file++;
    }
  });
  return { pieceAt: sq => board[sq] ? { symbol: () => board[sq] } : null };
}

function uciToArrows(uci){
  if(!uci || uci.length < 4) return [];
  return [[uci.slice(0,2), uci.slice(2,4)]];
}

/* ---------------- eval graph ---------------- */
function evalGraph(curve, onPick, selected, labels){
  const W = 1000, H = 190, P = 14;
  const svg = document.createElementNS('http://www.w3.org/2000/svg','svg');
  svg.setAttribute('class','chart');
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.setAttribute('preserveAspectRatio','none');
  const n = curve.length;
  if(!n) return svg;

  // Scale to the game, in pawns. Values arrive in centipawns and a forced mate
  // is stored as a 10000 sentinel, which would clamp the whole graph to one edge
  // and hide the actual shape -- so only non-mate values set the range, and the
  // result is capped at 12 pawns so one runaway spike cannot flatten the rest.
  const real = curve.filter(v => Math.abs(v) < 9000).map(v => Math.abs(v) / 100);
  const peak = Math.max(1.5, Math.min(12, real.length ? Math.max(...real) : 1.5));
  const lo = -peak, hi = peak;
  const X = i => P + i * (W - 2*P) / Math.max(1, n - 1);
  const Y = v => {
    const pawns = Math.max(lo, Math.min(hi, v / 100));
    return P + (hi - pawns) / (hi - lo) * (H - 2*P);
  };

  const midY = Y(0);
  const zero = document.createElementNS('http://www.w3.org/2000/svg','line');
  zero.setAttribute('x1',P); zero.setAttribute('x2',W-P);
  zero.setAttribute('y1',midY); zero.setAttribute('y2',midY);
  zero.setAttribute('stroke','#4a5162'); zero.setAttribute('stroke-width',1);
  svg.appendChild(zero);

  let d = '', area = `M ${X(0)} ${midY}`;
  curve.forEach((v,i) => {
    const y = Y(v);
    d += (i ? ' L ' : 'M ') + X(i) + ' ' + y;
    area += ' L ' + X(i) + ' ' + y;
  });
  area += ` L ${X(n-1)} ${midY} Z`;

  const fill = document.createElementNS('http://www.w3.org/2000/svg','path');
  fill.setAttribute('d', area); fill.setAttribute('fill','#4c8bf533');
  svg.appendChild(fill);
  const path = document.createElementNS('http://www.w3.org/2000/svg','path');
  path.setAttribute('d', d); path.setAttribute('fill','none');
  path.setAttribute('stroke','#4c8bf5'); path.setAttribute('stroke-width',1.6);
  svg.appendChild(path);

  (labels||[]).forEach((lab,i) => {
    const cls = GLYPH_CLASS[lab];
    if(!cls || i >= n) return;
    const dot = document.createElementNS('http://www.w3.org/2000/svg','circle');
    dot.setAttribute('cx', X(i)); dot.setAttribute('cy', Y(curve[i])); dot.setAttribute('r',3);
    dot.setAttribute('fill', MARK[cls] || '#fff');
    svg.appendChild(dot);
  });

  if(selected !== undefined && selected >= 0 && selected < n){
    const line = document.createElementNS('http://www.w3.org/2000/svg','line');
    line.setAttribute('x1',X(selected)); line.setAttribute('x2',X(selected));
    line.setAttribute('y1',P); line.setAttribute('y2',H-P);
    line.setAttribute('stroke','#e8eaf0'); line.setAttribute('stroke-width',1);
    line.setAttribute('opacity','0.7');
    svg.appendChild(line);
  }

  svg.addEventListener('click', ev => {
    const r = svg.getBoundingClientRect();
    const rel = (ev.clientX - r.left) / r.width;
    const i = Math.round((rel * W - P) / ((W - 2*P) / Math.max(1, n-1)));
    if(i >= 0 && i < n) onPick(i);
  });
  return svg;
}
const MARK = {brilliant:'#26a69a',great:'#7e57c2',inaccuracy:'#f9a825',
  mistake:'#ef6c00',blunder:'#c62828',miss:'#1565c0'};

/* ---------------- dashboard ---------------- */
function showDashboard(){
  const d = DATA.dashboard, t = d.totals;
  const root = el('div');

  const stat = (k,v,cls) => el('div',{class:'stat'},
    el('div',{class:'v ' + (cls||'')}, v), el('div',{class:'k'}, k));

  root.appendChild(el('div',{class:'panel'},
    el('h2',{},'Overview'),
    el('div',{class:'grid g3'},
      stat('Games analysed', d.games),
      stat('Mean accuracy', t.accuracy_mean.toFixed(1)),
      stat('Mean ACPL', t.acpl_mean.toFixed(1)),
      stat('Record', `${t.wins}W ${t.losses}L ${t.draws}D`),
      stat('Brilliant', t.counts.brilliant, 'brilliant'),
      stat('Great', t.counts.great, 'great'),
      stat('Inaccuracies', t.counts.inaccuracy, 'inaccuracy'),
      stat('Mistakes', t.counts.mistake, 'mistake'),
      stat('Blunders', t.counts.blunder, 'blunder'),
      stat('Missed wins', t.counts.miss, 'miss')
    )));

  // phase table
  const phaseRows = Object.entries(d.phases).map(([name, s]) => el('tr',{},
    el('td',{}, name),
    el('td',{}, s.moves),
    el('td',{}, s.accuracy.toFixed(1)),
    el('td',{}, s.acpl.toFixed(1)),
    el('td',{class:'inaccuracy'}, s.inaccuracy),
    el('td',{class:'mistake'}, s.mistake),
    el('td',{class:'blunder'}, s.blunder),
    el('td',{class:'brilliant'}, s.brilliant)
  ));
  root.appendChild(el('div',{class:'panel'},
    el('h2',{},'Accuracy by phase'),
    el('p',{class:'sub'}, 'This is where the weak phase shows up: the lowest accuracy column is the part of the game to work on.'),
    el('table',{},
      el('thead',{}, el('tr',{},
        ...['Phase','Moves','Win%','ACPL','?!','?','??','!!'].map(h => el('th',{},h)))),
      el('tbody',{}, ...phaseRows))));

  // weaknesses
  if(d.weaknesses.length){
    const items = d.weaknesses.map(w => el('div',{style:'padding:6px 0;border-bottom:1px solid var(--line)'},
      el('div',{}, el('b',{}, w.label), ' ',
        el('span',{class:'tag'}, w.count + '×'),
        el('span',{class:'tag'}, w.game_count + (w.game_count===1?' game':' games'))),
      el('div',{class:'small muted'}, w.examples.join('  •  '))
    ));
    root.appendChild(el('div',{class:'panel'},
      el('h2',{},'Recurring weaknesses'),
      el('p',{class:'sub'},'Counted across the whole archive. Every row is checkable against the move tables.'),
      ...items));
  }

  // brilliancies
  if(d.brilliancies.length){
    const items = d.brilliancies.map(br => el('div',{style:'padding:6px 0;border-bottom:1px solid var(--line)'},
      el('div',{}, el('span',{class:'brilliant'}, `!! ${br.move_number}.${br.san}`),
        ' ', el('span',{class:'muted small'}, br.title)),
      el('div',{class:'small muted'},
        `sacrificed ${br.sacrifice} points of material • loss only ${br.loss_pp.toFixed(1)}pp • `,
        'engine line: ', (br.pv||[]).join(' ')),
      el('a',{class:'small', href:'#', onclick:ev => { ev.preventDefault();
          switchView('game'); renderGame(br.game, br.move_number*2-2); }}, 'open →')
    ));
    root.appendChild(el('div',{class:'panel'},
      el('h2',{},'Your brilliancies'),
      el('p',{class:'sub'},'Sacrifices you played that the engine still approved of.'),
      ...items));
  } else {
    root.appendChild(el('div',{class:'panel'},
      el('h2',{},'Your brilliancies'),
      el('p',{class:'muted'},'None found in this set. A brilliant label needs a real sacrifice that the engine still rates as no worse than the alternatives.')));
  }

  // best / worst
  const list = (arr, title) => el('div',{class:'panel'},
    el('h2',{}, title),
    el('table',{}, el('tbody',{}, ...arr.map(g => el('tr',{class:'clickable',
      onclick:() => { switchView('game'); renderGame(g.index, -1); }},
      el('td',{style:'width:60px'}, g.accuracy.toFixed(1)),
      el('td',{}, g.title),
      el('td',{class:'muted small'}, g.opening || ''),
      el('td',{class:g.result}, g.result))))));
  root.appendChild(el('div',{class:'grid g2'},
    list(d.best_games,'Best games'), list(d.worst_games,'Games to review')));

  // per-game table
  const rows = d.trend.map(g => {
    const c = g.counts;
    const tr = el('tr',{class:'clickable',
      onclick:() => { switchView('game'); renderGame(g.index, -1); }},
      el('td',{class:g.result}, g.result),
      el('td',{}, g.title),
      el('td',{class:'muted small'}, g.opening || ''),
      el('td',{}, g.accuracy.toFixed(1)),
      el('td',{}, g.acpl.toFixed(1)),
      el('td',{class:'brilliant'}, c.brilliant || ''),
      el('td',{class:'great'}, c.great || ''),
      el('td',{class:'inaccuracy'}, c.inaccuracy || ''),
      el('td',{class:'mistake'}, c.mistake || ''),
      el('td',{class:'blunder'}, c.blunder || ''));
    tr.appendChild(el('td',{class:'muted small'}, evChartMini(g.eval_curve)));
    return tr;
  });
  root.appendChild(el('div',{class:'panel'},
    el('h2',{},'All games'),
    el('table',{}, el('thead',{}, el('tr',{},
      ...['Res','Game','Opening','Acc','ACPL','!!','!','?!','?','??','Eval'].map(h => el('th',{},h)))),
      el('tbody',{}, ...rows))));

  return root;
}

function evChartMini(curve){
  if(!curve || !curve.length) return '';
  const W=90,H=20;
  const real = curve.filter(v => Math.abs(v) < 9000).map(v => Math.abs(v)/100);
  const peak = Math.max(1.5, Math.min(12, real.length ? Math.max(...real) : 1.5));
  const lo=-peak, hi=peak;
  const Y = v => {
    const p = Math.max(lo, Math.min(hi, v/100));
    return Math.max(0, Math.min(H, (hi-p)/(hi-lo)*H));
  };
  let d='';
  curve.forEach((v,i)=>{
    const x = i*(W/Math.max(1,curve.length-1));
    d += (i?' L ':'M ')+x.toFixed(1)+' '+Y(v).toFixed(1);
  });
  return `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">
    <line x1="0" y1="${Y(0)}" x2="${W}" y2="${Y(0)}" stroke="#4a5162"/>
    <path d="${d}" fill="none" stroke="#4c8bf5" stroke-width="1"/></svg>`;
}

/* ---------------- per game ---------------- */
let currentGame = null, currentSel = -1;

function renderGame(index, ply){
  const g = gamesByIndex[index];
  if(!g){ $('#content').appendChild(el('p',{},'Game not found.')); return; }
  currentGame = g;
  const content = $('#content');
  content.innerHTML = '';
  if(ply !== undefined && ply !== null && ply >= 0) currentSel = ply;
  if(currentSel < 0) currentSel = 0;

  const moves = g.moves;
  const head = el('div',{class:'panel'},
    el('div',{style:'display:flex;gap:14px;align-items:baseline;flex-wrap:wrap'},
      el('h2',{}, g.headers.Event || 'Game'),
      el('span',{class:'pill ' + (g.player_result==='win'?'hi':g.player_result==='loss'?'bad':'')},
        g.player_result),
      el('span',{class:'pill'}, 'acc ' + g.accuracy.toFixed(1)),
      el('span',{class:'pill'}, 'ACPL ' + g.acpl.toFixed(1)),
      g.opening ? el('span',{class:'pill'}, (g.eco||'') + ' ' + g.opening) : null,
      g.book_end_ply ? el('span',{class:'pill'}, 'left book theory on '
                              + book_exit_text(g)) : null
    ),
    el('div',{class:'toolbar'},
      el('button',{class:'btn', onclick:() => { switchView('drill'); startDrill(g.index); }},
        'Drill this game'),
      el('button',{class:'', onclick:() => { switchView('game'); renderGame(index, -1); }}, 'Reset')
    ),
    evalGraph(g.eval_curve, i => { selectPly(g, i); }, currentSel, g.moves.map(m => m.label))
  );
  content.appendChild(head);

  const boardBox = el('div',{id:'board'});
  const info = el('div',{style:'flex:1 1 380px;min-width:320px'});
  content.appendChild(el('div',{class:'panel'},
    el('div',{class:'boardwrap'}, boardBox, info)));
  content.appendChild(moveTable(g, i => selectPly(g, i)));
  selectPly(g, currentSel);
}

function selectPly(g, i){
  currentSel = i;
  const m = g.moves[i];
  const boardBox = $('#board');
  if(!m || !boardBox) return;
  boardBox.innerHTML = '';

  const arrows = [];
  if(m.uci) arrows.push([...uciToArrows(m.uci), '#d32f2f']);
  if(m.best_uci && m.best_uci !== m.uci) arrows.push([...uciToArrows(m.best_uci), '#2e7d32']);
  boardBox.appendChild(renderBoard(m.fen, arrows));

  const cls = GLYPH_CLASS[m.label] || '';
  const info = boardBox.parentElement.querySelector('div:nth-child(2)');
  info.innerHTML = '';
  info.appendChild(el('h3',{}, `Move ${m.move_number}${m.color==='black'?'...':''} ${m.san} `,
    el('span',{class:cls}, m.glyph || '')));
  info.appendChild(el('div',{style:'margin-bottom:10px'},
    el('span',{class:'pill'}, `phase: ${m.phase}`),
    el('span',{class:'pill'}, `eval ${fmtEval(m.eval_before)} → ${fmtEval(m.eval_after)}`),
    m.loss_pp >= 0.5 ? el('span',{class:'pill warn'}, `loss ${m.loss_pp.toFixed(1)}pp`) : null,
    el('span',{class:'pill'}, `accuracy ${m.accuracy.toFixed(1)}`),
    m.verified ? el('span',{class:'pill hi'}, `verified d${m.depth}`) : null,
    m.in_book ? el('span',{class:'pill'}, 'book') : null,
    m.left_book ? el('span',{class:'pill warn'}, 'left book theory here') : null
  ));
  info.appendChild(el('div',{class:'legend'},
    el('b',{}, 'Best: '), (m.best_san || '—'),
    m.gap_pp !== null && m.gap_pp !== undefined ? el('span',{},
      `  (${m.gap_pp.toFixed(0)}pp better than the next best, so ${m.gap_pp>=10?'it was the only good move':'alternatives existed'})`) : null));
  if((m.best_pv||[]).length)
    info.appendChild(el('div',{class:'legend'}, el('b',{}, 'Engine line: '), m.best_pv.join(' ')));
  if(m.sacrifice)
    info.appendChild(el('div',{class:'legend'}, el('b',{}, 'Sacrifice: '),
      `${m.sacrifice} points of material given up, and the engine still approves`));
  if(m.lc0_best_san)
    info.appendChild(el('div',{class:'legend'}, el('b',{}, 'Lc0: '),
      m.lc0_best_san, m.lc0_agrees ? ' (agrees with your move)' : ''));
  (m.notes||[]).forEach(n => info.appendChild(el('div',{class:'legend muted'}, n)));
  if(!m.is_players_turn)
    info.appendChild(el('div',{class:'legend muted'}, "This was your opponent's move."));

  const table = $('#movetable tbody');
  if(table){
    [...table.querySelectorAll('tr')].forEach(tr => {
      tr.classList.toggle('sel', Number(tr.dataset.ply) === i);
    });
    const sel = table.querySelector('tr.sel');
    if(sel) sel.scrollIntoView({block:'nearest'});
  }
  const chart = document.querySelector('.chart');
  if(chart){
    const fresh = evalGraph(g.eval_curve, k => selectPly(g, k), currentSel,
                            g.moves.map(mm => mm.label));
    chart.parentElement.replaceChild(fresh, chart);
  }
}

function moveTable(g, onPick){
  const tbody = el('tbody');
  g.moves.forEach((m, i) => {
    const cls = GLYPH_CLASS[m.label] || '';
    const tr = el('tr',{'data-ply':i, class:'clickable', onclick:() => onPick(i)},
      el('td',{class:'muted'}, m.move_number + (m.color==='black'?'...':'')),
      el('td',{class:'san'}, m.san, ' ', el('span',{class:cls}, m.glyph||'')),
      el('td',{class:cls}, m.label),
      el('td',{}, fmtEval(m.eval_before)),
      el('td',{}, fmtEval(m.eval_after)),
      el('td',{class: m.loss_pp>10?'blunder':m.loss_pp>5?'mistake':m.loss_pp>2?'inaccuracy':''},
        m.loss_pp.toFixed(1)),
      el('td',{}, m.accuracy.toFixed(0)),
      el('td',{class:'muted'}, m.best_san || ''),
      el('td',{class:'muted'}, m.phase),
      el('td',{class:'muted small'}, m.lc0_best_san || ''));
    tbody.appendChild(tr);
  });
  const t = el('table',{id:'movetable', class:'moves'},
    el('thead',{}, el('tr',{},
      ...['#','Move','Label','Before','After','Loss','Acc','Best','Phase','Lc0'].map(h => el('th',{},h)))),
    tbody);
  return el('div',{class:'panel'}, t);
}

/* ---------------- drill ---------------- */
let drill = null;

function startDrill(index){
  const g = gamesByIndex[index];
  if(!g) return;
  const content = $('#content');
  content.innerHTML = '';
  const plies = g.moves.map((m,i) => ({m, i})).filter(x => x.m.is_players_turn);
  drill = { g, plies, at: 0, picked: null, revealed: false };
  content.appendChild(el('div',{class:'panel'}, el('div',{id:'drillbox'})));
  renderDrill();
}

function renderDrill(){
  const box = $('#drillbox');
  if(!box || !drill) return;
  const { g, plies } = drill;
  if(drill.at >= plies.length){
    box.innerHTML = '';
    box.appendChild(el('h2',{},'Drill complete'),
      el('p',{class:'muted'},`You went through all ${plies.length} of your moves in this game.`),
      el('button',{class:'btn', onclick:() => { switchView('game'); renderGame(g.index, -1); }}, 'Back to the game'));
    return;
  }
  const { m, i } = plies[drill.at];
  const legal = legalMoves(m);
  box.innerHTML = '';
  box.appendChild(el('h2',{},`Drill — move ${m.move_number}${m.color==='black'?'...':''} of ${g.headers.Event || ''}`));
  box.appendChild(el('p',{class:'sub'},
    `Which move would you play? ${drill.at+1} of ${plies.length}. `,
    el('kbd',{},'←'),' / ',el('kbd',{},'→'),' to change move, ',
    el('kbd',{},'Enter'),' to reveal.'));
  box.appendChild(el('div',{class:'boardwrap'},
    el('div',{id:'board'}, renderBoard(m.fen, [])),
    el('div',{id:'drillinfo'})
  ));

  const info = $('#drillinfo');
  info.appendChild(el('div',{class:'drill', id:'chips'}));
  const chips = $('#chips');
  legal.forEach((mv, idx) => {
    const btn = el('button',{
      onclick:() => {
        if(drill.revealed) return;
        drill.picked = mv.uci;
        if(idx >= 0 && idx < legal.length - 1) return;
        reveal();
      }
    }, mv.san);
    if(drill.picked === mv.uci) btn.classList.add('ok');
    chips.appendChild(btn);
  });
  chips.appendChild(el('button',{class:'btn', onclick:reveal}, drill.revealed ? 'shown' : 'Reveal'));

  if(drill.revealed){
    const board = $('#board');
    board.innerHTML = '';
    const arrows = [];
    if(m.uci) arrows.push([...uciToArrows(m.uci), '#d32f2f']);
    if(m.best_uci && m.best_uci !== m.uci) arrows.push([...uciToArrows(m.best_uci), '#2e7d32']);
    board.appendChild(renderBoard(m.fen, arrows));

    const right = drill.picked === m.uci;
    const res = el('div',{},
      el('div',{style:'margin-top:10px'},
        el('span',{class:'pill ' + (right?'hi':'bad')}, right ? 'Your move matched the game' : 'You played ' + (legal.find(x=>x.uci===drill.picked)||{san:'?'}).san)),
      el('div',{class:'legend', style:'margin-top:8px'},
        el('b',{}, 'Played: '), m.san,
        el('span',{}, `  eval ${fmtEval(m.eval_before)} → ${fmtEval(m.eval_after)}`)),
      el('div',{class:'legend'}, el('b',{}, 'Engine: '), m.best_san || '—',
        m.best_san !== m.san ? `  (${m.gap_pp ? m.gap_pp.toFixed(0)+'pp better' : 'preferred'})` : ' (you found it)'),
      (m.best_pv||[]).length ? el('div',{class:'legend'}, el('b',{}, 'Line: '), m.best_pv.join(' ')) : null,
      el('div',{class:'legend'}, el('b',{}, 'Label: '),
        el('span',{class:GLYPH_CLASS[m.label]||''}, (m.label||'')+' '+(m.glyph||''))),
      el('div',{style:'margin-top:12px'},
        el('button',{class:'btn', onclick:() => { drill.at++; drill.revealed=false; drill.picked=null; renderDrill(); }}, 'Next move →'))
    );
    $('#drillinfo').appendChild(res);
  }
}

function reveal(){
  if(!drill || drill.revealed) return;
  if(!drill.picked) drill.picked = drill.plies[drill.at].m.uci;
  drill.revealed = true;
  renderDrill();
}

function legalMoves(rec){
  // The analyser stored every legal move for the player's own plies, so drill
  // mode can offer the genuine choice without shipping a rules engine.
  return (rec.legal || []).map(s => {
    const [uci, san] = s.split(':');
    return { uci, san };
  });
}

/* ---------------- export ---------------- */
function showExport(){
  const root = el('div');
  const pgn = window.__PGN__ || '';
  root.appendChild(el('div',{class:'panel'},
    el('h2',{},'Annotated PGN'),
    el('p',{class:'sub'},'Import this into Lichess, En Croissant, SCID or any chess GUI. Every move carries its label, evaluation and the engine line.'),
    el('p',{}, el('a',{class:'btn', download:'annotated.pgn',
      href:'data:text/plain;charset=utf-8,' + encodeURIComponent(pgn)}, 'Download annotated.pgn')),
    el('p',{class:'small muted'}, 'Or copy it from below.')));
  root.appendChild(el('div',{class:'panel'},
    el('h3',{},'PGN'),
    el('pre',{class:'pgn'}, pgn)));
  root.appendChild(el('div',{class:'panel'},
    el('h2',{},'Settings used'),
    el('table',{}, el('tbody',{}, ...Object.entries(DATA.settings).map(([k,v]) =>
      el('tr',{}, el('td',{style:'width:180px'}, k), el('td',{}, String(v))))))));
  return root;
}

/* ---------------- shell ---------------- */
function switchView(name){
  const content = $('#content');
  content.innerHTML = '';
  document.querySelectorAll('nav button').forEach(b =>
    b.classList.toggle('on', b.dataset.view === name));
  if(name === 'dashboard') content.appendChild(showDashboard());
  else if(name === 'games') content.appendChild(showGameList());
  else if(name === 'game') {
    if(!currentGame) currentGame = DATA.games[0];
    if(currentGame) renderGame(currentGame.index, -1);
    else content.appendChild(el('p',{},'No games.'));
  }
  else if(name === 'drill') {
    if(drill) { content.appendChild(el('div',{class:'panel', id:'drillbox'})); renderDrill(); }
    else showDrillPicker();
  }
  else if(name === 'export') content.appendChild(showExport());
}

function showGameList(){
  const root = el('div',{class:'panel'}, el('h2',{},'Pick a game'));
  const t = el('table',{}, el('tbody',{}));
  DATA.dashboard.trend.forEach(g => {
    t.appendChild(el('tr',{class:'clickable',
      onclick:() => { switchView('game'); renderGame(g.index, -1); }},
      el('td',{class:g.result}, g.result),
      el('td',{}, g.title),
      el('td',{class:'muted small'}, g.opening || ''),
      el('td',{}, g.accuracy.toFixed(1)),
      el('td',{}, g.acpl.toFixed(1))));
  });
  root.appendChild(t);
  return root;
}

function showDrillPicker(){
  const root = el('div',{class:'panel'},
    el('h2',{},'Drill mode'),
    el('p',{class:'sub'},'The answer is hidden. You pick a move, then the engine line is revealed. ' +
      'This is the part that actually teaches you something.'));
  const t = el('table',{}, el('tbody',{}));
  DATA.dashboard.trend.forEach(g => {
    t.appendChild(el('tr',{class:'clickable',
      onclick:() => { startDrill(g.index); }},
      el('td',{class:g.result}, g.result),
      el('td',{}, g.title),
      el('td',{class:'muted small'}, g.opening || ''),
      el('td',{}, g.accuracy.toFixed(1)),
      el('td',{}, g.counts.blunder + g.counts.mistake + g.counts.inaccuracy + ' weak moves')));
  });
  root.appendChild(t);
  return root;
}

document.addEventListener('keydown', ev => {
  if(!drill || ev.target.tagName === 'INPUT') return;
  if(ev.key === 'Enter'){ ev.preventDefault(); reveal(); }
  if(ev.key === 'ArrowRight' && drill.revealed){
    ev.preventDefault(); drill.at++; drill.revealed=false; drill.picked=null; renderDrill();
  }
  if(ev.key === 'ArrowLeft'){
    ev.preventDefault();
    if(drill.revealed){ drill.revealed=false; }
    else { drill.at = Math.max(0, drill.at-1); drill.picked=null; }
    renderDrill();
  }
});

switchView('dashboard');
"""


def book_exit_text(game: Dict) -> str:
    """``3. g3`` -- the move on which the game left opening theory.

    ``book_end_ply`` is the ply of the move that *left* the book (analyze.py sets it
    from the first record flagged ``left_book``), so the move number is
    ``ply // 2 + 1``.  The previous rendering used ``ceil(ply / 2)``, which is the
    *last* book move, and labelled it "book ended at move N" -- while move N was
    itself book theory.  A game that stayed in book for four plies was therefore
    reported as leaving it on move 2.

    Kept in step with ``ui/src/lib/book.ts``, which does the same arithmetic for the
    React report; both read the same field and both describe the leaving move.
    """
    ply = int(game.get("book_end_ply") or 0)
    move_no = ply // 2 + 1
    moves = game.get("moves") or []
    san = ""
    if 0 <= ply < len(moves):
        san = (moves[ply].get("san") or "").strip()
    return f"{move_no}. {san}" if san else f"move {move_no}"


def ensure_ratings(data: Dict, *, verbose: bool = True) -> Dict:
    """Fill in ``dashboard.ratings`` if the data predates it.

    ``analyze.py`` writes the rating series, but a ``data.json`` produced by an
    older version will not have it, and the Overview page is built around it.
    Recomputing it here is idempotent and costs milliseconds, so re-rendering an
    existing report does not require re-running the engines -- which is the whole
    point of this module.
    """
    import analyze

    dashboard = data.setdefault("dashboard", {})
    if dashboard.get("ratings"):
        return data

    # build_ratings() works on GameResult objects, so reconstruct just enough of
    # one per game from the serialised form.
    results = []
    for game in data.get("games") or []:
        result = analyze.GameResult(
            headers=dict(game.get("headers") or {}),
            index=game.get("index", 0),
            player_color=game.get("player_color"),
            player_name=game.get("player_name", ""),
            result=(game.get("headers") or {}).get("Result", "*"),
        )
        result.accuracy = game.get("accuracy", 0.0)
        result.player_result = game.get("player_result", "*")
        # A non-empty move list is what "this game was actually analysed" means
        # to build_ratings, and it avoids reconstructing thousands of records.
        result.moves = [analyze.MoveRecord(
            ply=0, move_number=1, color="white", san="", uci="", fen="",
            is_players_turn=True,
        )] if game.get("moves") else []
        results.append(result)

    dashboard["ratings"] = analyze.build_ratings(results)
    if verbose and not dashboard["ratings"].get("games_rated"):
        print("  note: no rated games in this set, so the ELO chart has no points")
    return data


def write_pack(data: Dict, out_dir: str, *, embed_limit: int = 0,
               verbose: bool = True) -> str:
    """Split data.json into the pack the React app loads incrementally.

    data.json is ~70 KB per game, so a 3089-game archive is ~216 MB -- far too
    large to inline into one page.  The pack keeps a light index in report.json
    and one file per game, fetched when the game is opened.
    """
    import pack as pack_mod

    ensure_ratings(data, verbose=verbose)
    pack_mod.write_pack(data, out_dir, embed_limit=embed_limit)
    if verbose:
        sizes = pack_mod.pack_size(out_dir)
        print(f"  pack: {out_dir}")
        print(f"        report.json {sizes['report'] / 1024:.0f} KB"
              f" + {sizes['games_count']} game file(s) {sizes['games'] / 1024:.0f} KB")
    return out_dir


def write_standalone(data: Dict, pack_dir: str, path: str, *,
                     embed_games: int = 0, verbose: bool = True) -> str:
    """Build the React app and fold it, plus the data, into one HTML file.

    The existing report is one file that opens from ``file://`` and that
    guarantee is load-bearing, so the single-file build keeps it: the bundle, the
    stylesheet, the piece artwork and the data are all inlined, and the app
    switches to hash routing when it detects a ``file://`` origin.
    """
    import shutil
    import subprocess

    ui_dir = os.path.join(ROOT, "ui")
    if not os.path.isdir(ui_dir):
        raise FileNotFoundError(
            f"no {ui_dir} -- the React frontend is not present in this checkout"
        )

    # The pack decides which games carry their move data; embed_games only ever
    # lowers that cap, so the rule lives in exactly one place.
    if embed_games:
        write_pack(data, pack_dir, embed_limit=embed_games, verbose=verbose)
    else:
        write_pack(data, pack_dir, verbose=verbose)

    for args in (["npm", "install"], ["npm", "run", "build"]):
        if verbose:
            print(f"> npm {' '.join(args)}", flush=True)
        result = subprocess.run(args, cwd=ui_dir, shell=(os.name == "nt"))
        if result.returncode != 0:
            raise RuntimeError(f"npm {' '.join(args)} failed")

    script = os.path.join(ui_dir, "scripts", "inline-assets.mjs")
    # Absolute paths, because the node process runs with cwd=ui_dir: a relative
    # --out would be re-interpreted against ui/ and quietly write ui/out/... .
    result = subprocess.run(
        [
            "node", script,
            "--pack", os.path.abspath(pack_dir),
            "--out", os.path.abspath(path),
        ],
        cwd=ui_dir, shell=(os.name == "nt"),
    )
    if result.returncode != 0:
        raise RuntimeError("the standalone build failed")
    return path


def write_report(data: Dict, path: str, *, verbose: bool = True) -> str:
    """Render data.json into a single self-contained HTML file."""
    pgn_path = os.path.join(os.path.dirname(os.path.abspath(path)), "annotated.pgn")
    try:
        with open(pgn_path, "r", encoding="utf-8") as fh:
            annotated = fh.read()
    except OSError:
        annotated = ""

    settings = data.get("settings", {})
    dashboard = data.get("dashboard", {})
    games = len(dashboard.get("trend", []))
    acc = dashboard.get("totals", {}).get("accuracy_mean", 0)

    title = f"chess-coach — {data.get('player') or 'analysis'} ({games} games, {acc}% avg)"

    engine_names = [settings.get("stockfish") or "Stockfish"]
    if settings.get("lc0"):
        engine_names.append(settings["lc0"])
    engines_line = " + ".join(_esc(n) for n in engine_names if n)
    depth_line = f"depth {settings.get('depth')}/{settings.get('focus_depth')}"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)}</title>
<style>{CSS}</style>
</head>
<body>
<header>
  <h1>chess-coach</h1>
  <span class="sub">{engines_line}
    &middot; {depth_line}
    &middot; {_esc(data.get('generated', ''))}</span>
  <nav>
    <button data-view="dashboard" class="on">Dashboard</button>
    <button data-view="games">Games</button>
    <button data-view="game">Current game</button>
    <button data-view="drill">Drill</button>
    <button data-view="export">Export</button>
  </nav>
</header>
<main id="content"></main>
<script>window.__REPORT__ = {json.dumps(data)};</script>
<script>window.__PIECES__ = {_pieces_json()};</script>
<script>window.__PGN__ = {json.dumps(annotated)};</script>
<script>{JS}</script>
</body>
</html>
"""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)
    if verbose:
        size = os.path.getsize(path)
        print(f"  report: {path} ({size / 1024:.0f} KB)")
    return path


def _esc(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Render a report from data.json")
    ap.add_argument("--data", default=os.path.join("out", "data.json"))
    ap.add_argument("--out", default=os.path.join("out", "report.html"))
    ap.add_argument("--pack", action="store_true",
                    help="write the report pack for the React app instead of the "
                         "single-file report. --out names the directory.")
    ap.add_argument("--standalone", action="store_true",
                    help="build the React app and fold it, with the data, into one "
                         "self-contained HTML file that opens from file://")
    ap.add_argument("--pack-dir", default=os.path.join(ROOT, "out", "pack"),
                    help="where the standalone build keeps its pack")
    ap.add_argument("--embed-games", type=int, default=0, metavar="N",
                    help="how many games carry their move data into the output. "
                         "At ~70 KB per game the practical ceiling is a few dozen")
    args = ap.parse_args()
    with open(args.data, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    if args.standalone:
        write_standalone(data, args.pack_dir, args.out, embed_games=args.embed_games)
    elif args.pack:
        write_pack(data, args.out, embed_limit=args.embed_games)
    else:
        # The legacy single-file report reads the same dashboard, so it gets the
        # rating series too rather than silently showing an older shape.
        ensure_ratings(data)
        write_report(data, args.out)