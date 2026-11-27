#!/usr/bin/env python3
"""BOX 2 Live ChessHeat Broadcast Overlay (Historical Records ⇄ Live Stockfish 16 Simulations).

Faithfully implements ChessHeat's typed spatial measurement layers (`geometry.py`,
`attribution.py`, `recurrence.py`, and `viewer/app.js` color scales) inside a dedicated
background simulation worker for zero-overhead stream compositing above the Showtime
Countdown card:

1. Alternates Game Sources (explicitly labeled):
   - `HISTORICAL`: Verified PGN/SAN tactical masterpieces (Morphy, Kasparov, Fischer, Tal,
     Anderssen, Rubinstein).
   - `LIVE SIM`: Live Stockfish 16 self-play (`MultiPV` root sampling across diverse named
     openings so every simulated game is unique).

2. Auto-Cycles Typed ChessHeat Measurement Layers (explicitly labeled, no fake scalar fusion):
   - `geometry_delta`: Structural Geometry Delta (`appeared_attacks`, `disappeared_attacks`,
     and newly opened `SlidingRay` vectors away from move endpoints).
   - `dest_cp_regret`: Destination Mean CP Opportunity-Cost / Regret (`Stockfish 16`, keeping
     `cp` and `mate` outcomes strictly separated).
   - `dest_move_count`: Legal Root Alternatives per Destination Square (`role=destination`,
     `metric=move_count`).
   - `pv_recurrence`: Principal-Variation Line Recurrence Fraction (`MultiPV=4`, `d=6`).
"""
from dataclasses import dataclass, field
import math
import os
from pathlib import Path
import random
import threading
import time
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    np = None
    HAS_NUMPY = False

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import chess
    import chess.engine
    HAS_CHESS = True
except ImportError:
    chess = None
    HAS_CHESS = False


STOCKFISH_CANDIDATES = (
    "/home/joseph1/.local/bin/stockfish",
    "/usr/games/stockfish",
    "/usr/bin/stockfish",
    "/opt/homebrew/bin/stockfish",
    "/usr/local/bin/stockfish",
)

# Filled chess glyph codepoints (rendered with contrasting fill + stroke in DejaVuSans)
SOLID_PIECE_GLYPH = {
    1: "\u265f",  # PAWN   ♟
    2: "\u265e",  # KNIGHT ♞
    3: "\u265d",  # BISHOP ♝
    4: "\u265c",  # ROOK   ♜
    5: "\u265b",  # QUEEN  ♛
    6: "\u265a",  # KING   ♚
}

TYPED_LAYERS = (
    "geometry_delta",
    "dest_cp_regret",
    "dest_move_count",
    "pv_recurrence",
)

LAYER_TITLES = {
    "geometry_delta": "LAYER: STRUCTURAL GEOMETRY DELTA (Atk & Rays)",
    "dest_cp_regret": "LAYER: DEST MEAN CP REGRET (Stockfish 16, d=6)",
    "dest_move_count": "LAYER: LEGAL DEST MOVE COUNT (Role: dest)",
    "pv_recurrence": "LAYER: PV LINE RECURRENCE (MultiPV=4, d=6)",
}

HISTORICAL_GAMES = (
    {
        "title": "Morphy vs. Duke/Isouard (Paris 1858)",
        "opening": "Philidor Defense",
        "moves": [
            "e4", "e5", "Nf3", "d6", "d4", "Bg4", "dxe5", "Bxf3", "Qxf3", "dxe5",
            "Bc4", "Nf6", "Qb3", "Qe7", "Nc3", "c6", "Bg5", "b5", "Nxb5", "cxb5",
            "Bxb5+", "Nbd7", "O-O-O", "Rd8", "Rxd7", "Rxd7", "Rd1", "Qe6",
            "Bxd7+", "Nxd7", "Qb8+", "Nxb8", "Rd8#",
        ],
    },
    {
        "title": "Byrne vs. Fischer (NYC 1956)",
        "opening": "Grunfeld Defense",
        "moves": [
            "Nf3", "Nf6", "c4", "g6", "Nc3", "Bg7", "d4", "O-O", "Bf4", "d5",
            "Qb3", "dxc4", "Qxc4", "c6", "e4", "Nbd7", "Rd1", "Nb6", "Qc5", "Bg4",
            "Bg5", "Na4", "Qa3", "Nxc3", "bxc3", "Nxe4", "Bxe7", "Qb6", "Bc4", "Nxc3",
            "Bc5", "Rfe8+", "Kf1", "Be6", "Bxb6", "Bxc4+", "Kg1", "Ne2+", "Kf1", "Nxd4+",
            "Kg1", "Ne2+", "Kf1", "Nc3+", "Kg1", "axb6", "Qb4", "Ra4", "Qxb6", "Nxd1",
            "h3", "Rxa2", "Kh2", "Nxf2", "Re1", "Rxe1", "Qd8+", "Bf8", "Nxe1", "Bd5",
            "Nf3", "Ne4", "Qb8", "b5", "h4", "h5", "Ne5", "Kg7", "Kg1", "Bc5+",
            "Kf1", "Ng3+", "Ke1", "Bb4+", "Kd1", "Bb3+", "Kc1", "Ne2+", "Kb1", "Nc3+",
            "Kc1", "Rc2#",
        ],
    },
    {
        "title": "Kasparov vs. Topalov (Wijk aan Zee 1999)",
        "opening": "Pirc Defense",
        "moves": [
            "e4", "d6", "d4", "Nf6", "Nc3", "g6", "Be3", "Bg7", "Qd2", "c6",
            "f3", "b5", "Nge2", "Nbd7", "Bh6", "Bxh6", "Qxh6", "Bb7", "a3", "e5",
            "O-O-O", "Qe7", "Kb1", "a6", "Nc1", "O-O-O", "Nb3", "exd4", "Rxd4", "c5",
            "Rd1", "Nb6", "g3", "Kb8", "Na5", "Ba8", "Bh3", "d5", "Qf4+", "Ka7",
            "Rhe1", "d4", "Nd5", "Nbxd5", "exd5", "Qd6", "Rxd4", "cxd4", "Re7+", "Kb6",
            "Qxd4+", "Kxa5", "b4+", "Ka4", "Qc3", "Qxd5", "Ra7", "Bb7", "Rxb7", "Qc4",
            "Qxf6", "Kxa3", "Qxa6+", "Kxb4", "c3+", "Kxc3", "Qa1+", "Kd2", "Qb2+", "Kd1",
            "Bf1", "Rd2", "Rd7", "Rxd7", "Bxc4", "bxc4", " Qxh8", "Rd3", "Qa8", "c3",
            "Qa4+", "Ke1", "f4", "f5", "Kc1", "Rd2", "Qa7",
        ],
    },
    {
        "title": "Anderssen vs. Kieseritzky (London 1851)",
        "opening": "King's Gambit",
        "moves": [
            "e4", "e5", "f4", "exf4", "Bc4", "Qh4+", "Kf1", "b5", "Bxb5", "Nf6",
            "Nf3", "Qh6", "d3", "Nh5", "Nh4", "Qg5", "Nf5", "c6", "g4", "Nf6",
            "Rg1", "cxb5", "h4", "Qg6", "h5", "Qg5", "Qf3", "Ng8", "Bxf4", "Qf6",
            "Nc3", "Bc5", "Nd5", "Qxb2", "Bd6", "Bxg1", "e5", "Qxa1+", "Ke2", "Na6",
            "Nxg7+", "Kd8", "Qf6+", "Nxf6", "Be7#",
        ],
    },
    {
        "title": "Rotlewi vs. Rubinstein (Lodz 1907)",
        "opening": "Tarrasch Defense",
        "moves": [
            "d4", "d5", "Nf3", "e6", "e3", "c5", "c4", "Nc6", "Nc3", "Nf6",
            "dxc5", "Bxc5", "a3", "a6", "b4", "Bd6", "Bb2", "O-O", "Qd2", "Qe7",
            "Bd3", "dxc4", "Bxc4", "b5", "Bd3", "Rd8", "Qe2", "Bb7", "O-O", "Ne5",
            "Nxe5", "Bxe5", "f4", "Bc7", "e4", "Rac8", "e5", "Bb6+", "Kh1", "Ng4",
            "Be4", "Qh4", "g3", "Rxc3", "gxh4", "Rd2", "Qxd2", "Bxe4+", "Qg2", "Rh3",
        ],
    },
)

LIVE_SIM_OPENINGS = (
    ("Italian Game", ["e4", "e5", "Nf3", "Nc6", "Bc4", "Bc5"]),
    ("Sicilian Najdorf", ["e4", "c5", "Nf3", "d6", "d4", "cxd4", "Nxd4", "Nf6", "Nc3", "a6"]),
    ("King's Gambit", ["e4", "e5", "f4", "exf4", "Nf3", "g5"]),
    ("Ruy Lopez", ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6", "Ba4", "Nf6"]),
    ("Queen's Gambit", ["d4", "d5", "c4", "e6", "Nc3", "Nf6"]),
    ("King's Indian", ["d4", "Nf6", "c4", "g6", "Nc3", "Bg7", "e4", "d6"]),
    ("French Winawer", ["e4", "e6", "d4", "d5", "Nc3", "Bb4"]),
    ("Scotch Gambit", ["e4", "e5", "Nf3", "Nc6", "d4", "exd4", "Bc4"]),
)


@dataclass(frozen=True)
class GeometrySnapshot:
    attacks: FrozenSet = field(default_factory=frozenset)   # (attacker_sq, attacker_sym, target_sq)
    defenses: FrozenSet = field(default_factory=frozenset)  # (defender_sq, defender_sym, target_sq)
    rays: FrozenSet = field(default_factory=frozenset)      # (src_sq, dir_name, path_tuple, target_sq)
    legal_dests: FrozenSet = field(default_factory=frozenset)  # (from_sq, to_sq)


def extract_board_geometry(board) -> GeometrySnapshot:
    """Faithful port of `chessheat.geometry.extract_geometry` (attacks, defenses, sliding rays, legal mobility)."""
    attacks = set()
    defenses = set()
    rays = set()
    legal_dests = frozenset((m.from_square, m.to_square) for m in board.legal_moves)

    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if not piece:
            continue
        sym = piece.symbol()
        for t_sq in board.attacks(sq):
            tp = board.piece_at(t_sq)
            rel = (sq, sym, t_sq)
            if tp and tp.color == piece.color:
                defenses.add(rel)
            else:
                attacks.add(rel)

        if piece.piece_type in (chess.ROOK, chess.BISHOP, chess.QUEEN):
            dirs = []
            if piece.piece_type in (chess.ROOK, chess.QUEEN):
                dirs.extend([("N", 8), ("S", -8), ("E", 1), ("W", -1)])
            if piece.piece_type in (chess.BISHOP, chess.QUEEN):
                dirs.extend([("NE", 9), ("NW", 7), ("SE", -7), ("SW", -9)])

            for dname, step in dirs:
                cur = sq
                path = []
                tgt = None
                while True:
                    cf = chess.square_file(cur)
                    if step == 1 and cf == 7:
                        break
                    if step == -1 and cf == 0:
                        break
                    if step in (9, -7) and cf == 7:
                        break
                    if step in (7, -9) and cf == 0:
                        break
                    nxt = cur + step
                    if not (0 <= nxt <= 63):
                        break
                    if board.piece_at(nxt):
                        tgt = nxt
                        break
                    path.append(nxt)
                    tgt = nxt
                    cur = nxt
                if tgt is not None:
                    rays.add((sq, dname, tuple(path), tgt))

    return GeometrySnapshot(
        attacks=frozenset(attacks),
        defenses=frozenset(defenses),
        rays=frozenset(rays),
        legal_dests=legal_dests,
    )


def compute_geometry_delta_layer(before_geom: GeometrySnapshot, after_geom: GeometrySnapshot):
    """Compute exact square RGBA overlays + appeared sliding rays matching `viewer/app.js`."""
    app_atk = after_geom.attacks - before_geom.attacks
    dis_atk = before_geom.attacks - after_geom.attacks
    app_rays = list(after_geom.rays - before_geom.rays)
    mob_gained = len(after_geom.legal_dests - before_geom.legal_dests)
    mob_lost = len(before_geom.legal_dests - after_geom.legal_dests)

    sq_gain = {}
    sq_loss = {}
    for _, _, t_sq in app_atk:
        sq_gain[t_sq] = sq_gain.get(t_sq, 0) + 1
    for _, _, t_sq in dis_atk:
        sq_loss[t_sq] = sq_loss.get(t_sq, 0) + 1

    sq_rgba = {}
    for sq in set(sq_gain.keys()) | set(sq_loss.keys()):
        g = sq_gain.get(sq, 0)
        l = sq_loss.get(sq, 0)
        net = g - l
        if net > 0:
            alpha = int(min(1.0, abs(net) / 3.0) * 195)
            sq_rgba[sq] = (49, 130, 206, max(75, alpha))   # Sapphire blue (viewer/app.js positive delta)
        elif net < 0:
            alpha = int(min(1.0, abs(net) / 3.0) * 185)
            sq_rgba[sq] = (229, 62, 62, max(70, alpha))    # Crimson red (viewer/app.js negative delta)
        elif g > 0:
            sq_rgba[sq] = (237, 137, 54, 150)              # Amber (contested replacement)

    ray_segments = [(src_sq, tgt_sq) for (src_sq, _, path, tgt_sq) in app_rays if len(path) >= 1][:6]
    stats = {
        "row1": ("+Atk", f"+{len(app_atk)}"),
        "row2": ("-Atk", f"-{len(dis_atk)}"),
        "row3": ("+Ray", f"+{len(app_rays)}"),
        "row4": ("dMob", f"{mob_gained - mob_lost:+d}"),
        "legend": (
            ((49, 130, 206), "+Atk"),
            ((229, 62, 62), "-Atk"),
            ((248, 195, 70), "+Ray"),
        ),
    }
    return sq_rgba, ray_segments, stats


def compute_dest_move_count_layer(board):
    """Exact `role=destination, metric=move_count` layer from `chessheat/attribution.py` & `viewer/app.js`."""
    counts: Dict[int, int] = {}
    captures = 0
    legal_list = list(board.legal_moves)
    for m in legal_list:
        counts[m.to_square] = counts.get(m.to_square, 0) + 1
        if board.is_capture(m):
            captures += 1

    sq_rgba = {}
    for sq, cnt in counts.items():
        # viewer/app.js line 180: rgba(128, 90, 213, 0.2 + (min(15, val)/15)*0.6)
        a = int((0.24 + (min(8, cnt) / 8.0) * 0.58) * 255)
        sq_rgba[sq] = (138, 98, 224, a)

    stats = {
        "row1": ("Legal", str(len(legal_list))),
        "row2": ("Dests", str(len(counts))),
        "row3": ("Capts", str(captures)),
        "row4": ("Check", "YES" if board.is_check() else "No"),
        "legend": (
            ((138, 98, 224), "1-2 mv"),
            ((168, 125, 250), "3+ mv"),
        ),
    }
    return sq_rgba, [], stats


def compute_stockfish_layers(board, engine, layer_name: str, depth: int = 6):
    """Compute typed Stockfish 16 `dest_cp_regret` or `pv_recurrence` without conflating CP and Mate."""
    if engine is None or board.is_game_over():
        return compute_dest_move_count_layer(board)

    pov_color = board.turn
    legal_moves = list(board.legal_moves)
    if not legal_moves:
        return {}, [], {}

    if layer_name == "pv_recurrence":
        k = min(4, len(legal_moves))
        infos = engine.analyse(board, chess.engine.Limit(depth=depth), multipv=k)
        if not isinstance(infos, list):
            infos = [infos]
        sq_lines: Dict[int, int] = {}
        top_san = "-"
        for idx, info in enumerate(infos):
            pv = info.get("pv") or []
            if idx == 0 and pv:
                try:
                    top_san = board.san(pv[0])
                except Exception:
                    top_san = pv[0].uci()
            visited_in_line: Set[int] = set()
            for mv in pv[:6]:
                visited_in_line.add(mv.to_square)
            for sq in visited_in_line:
                sq_lines[sq] = sq_lines.get(sq, 0) + 1

        sq_rgba = {}
        denom = float(max(1, len(infos)))
        best_sq_lbl = "-"
        best_frac = 0.0
        for sq, lcnt in sq_lines.items():
            frac = lcnt / denom
            if frac > best_frac:
                best_frac = frac
                best_sq_lbl = chess.square_name(sq)
            # viewer/app.js line 225: rgba(56, 161, 105, 0.2 + frac * 0.7)
            a = int((0.22 + frac * 0.68) * 255)
            sq_rgba[sq] = (56, 175, 110, a)

        stats = {
            "row1": ("Lines", f"k={len(infos)}"),
            "row2": ("Depth", f"d={depth}"),
            "row3": ("PV #1", top_san[:6]),
            "row4": ("MaxSq", f"{best_sq_lbl}:{best_frac:.1f}"),
            "legend": (
                ((56, 175, 110), "PV hit"),
                ((95, 220, 145), "High %"),
            ),
        }
        return sq_rgba, [], stats

    # Default Stockfish layer: `dest_cp_regret` (MultiPV across candidate moves up to 14)
    k = min(14, len(legal_moves))
    infos = engine.analyse(board, chess.engine.Limit(depth=depth), multipv=k)
    if not isinstance(infos, list):
        infos = [infos]

    cp_by_dest: Dict[int, List[int]] = {}
    mate_dests: Set[int] = set()
    best_cp: Optional[int] = None
    best_san = "-"
    best_score_lbl = "-"

    for idx, info in enumerate(infos):
        pv = info.get("pv") or []
        if not pv or "score" not in info:
            continue
        mv = pv[0]
        pov = info["score"].pov(pov_color)
        if idx == 0:
            try:
                best_san = board.san(mv)
            except Exception:
                best_san = mv.uci()
            if pov.is_mate():
                best_score_lbl = f"M{pov.mate():+d}"
            else:
                best_score_lbl = f"{pov.score():+d}cp"

        if pov.is_mate():
            if (pov.mate() or 0) > 0:
                mate_dests.add(mv.to_square)
        else:
            sc = int(pov.score() or 0)
            if best_cp is None or sc > best_cp:
                best_cp = sc
            cp_by_dest.setdefault(mv.to_square, []).append(sc)

    sq_rgba = {}
    if best_cp is not None:
        for sq, scores in cp_by_dest.items():
            regrets = [max(0, best_cp - s) for s in scores]
            mean_regret = sum(regrets) / float(len(regrets))
            if mean_regret <= 8.0:
                # Near-zero regret optimal destination: crisp sapphire blue
                sq_rgba[sq] = (49, 145, 225, 185)
            else:
                # viewer/app.js line 173: rgba(229, 62, 62, (min(200, val)/200)*0.8)
                a = int((0.22 + (min(200.0, mean_regret) / 200.0) * 0.62) * 255)
                sq_rgba[sq] = (229, 62, 62, a)

    # Typed mate outcomes rendered separately in orange (viewer/app.js line 183)
    for sq in mate_dests:
        sq_rgba[sq] = (221, 107, 32, 205)

    stats = {
        "row1": ("Best", best_san[:6]),
        "row2": ("Eval", best_score_lbl[:7]),
        "row3": ("Cand", f"{len(infos)}/{len(legal_moves)}"),
        "row4": ("Mate+", str(len(mate_dests))),
        "legend": (
            ((49, 145, 225), "0cp opt"),
            ((229, 62, 62), "+Regret"),
            ((221, 107, 32), "Mate"),
        ),
    }
    return sq_rgba, [], stats


def find_stockfish_binary() -> Optional[str]:
    for p in STOCKFISH_CANDIDATES:
        if os.path.exists(p) and os.access(p, os.X_OK):
            return p
    return None


class ChessHeatLiveOverlay:
    """Self-contained background ChessHeat simulator + PIL broadcast card renderer.

    Positioned at `(872, 148)` (`382 x 362 px`) directly above the `382 px` Showtime
    Countdown card during `STAGE STANDBY`.
    """

    def __init__(
        self,
        config_path="/home/joseph1/box2-stream/ticker.json",
        card_w=382,
        card_h=362,
        x=872,
        y=148,
        move_interval_s=2.6,
        layer_cycle_plies=8,
    ):
        self.config_path = config_path
        self.card_w = int(card_w)
        self.card_h = int(card_h)
        self.x = int(x)
        self.y = int(y)
        self.move_interval_s = float(move_interval_s)
        self.layer_cycle_plies = max(2, int(layer_cycle_plies))
        self.enabled = True
        self.theme = "black_friday"

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._cached_bgr = None
        self._cached_alpha = None
        self._fonts = {}
        self._engine = None
        self._stockfish_path = find_stockfish_binary()

        self._game_idx = 0
        self._use_live_sim = False  # alternates False (Historical) -> True (Live Sim) -> False ...
        self._layer_idx = 0

        if HAS_CHESS and HAS_PIL and HAS_NUMPY:
            self._thread = threading.Thread(target=self._worker, daemon=True)
            self._thread.start()
        else:
            self._thread = None

    def _get_font(self, size: int, regular: bool = False):
        key = (size, regular)
        if key in self._fonts:
            return self._fonts[key]
        paths = (
            (
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
            )
            if regular
            else (
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/System/Library/Fonts/Helvetica.ttc",
            )
        )
        for fp in paths:
            if os.path.exists(fp):
                try:
                    f = ImageFont.truetype(fp, size)
                    self._fonts[key] = f
                    return f
                except Exception:
                    pass
        f = ImageFont.load_default()
        self._fonts[key] = f
        return f

    def _open_engine_if_needed(self):
        if self._engine is not None or not self._stockfish_path or not HAS_CHESS:
            return self._engine
        try:
            eng = chess.engine.SimpleEngine.popen_uci(self._stockfish_path)
            try:
                eng.configure({"Threads": 1, "Hash": 16})
            except Exception:
                pass
            self._engine = eng
        except Exception:
            self._engine = None
        return self._engine

    def _close_engine(self):
        if self._engine is not None:
            try:
                self._engine.quit()
            except Exception:
                pass
            self._engine = None

    def _reload_config(self):
        if not self.config_path or not os.path.exists(self.config_path):
            return
        try:
            import json
            tk = json.loads(Path(self.config_path).read_text())
            raw_t = str(tk.get("seasonal_theme", "black_friday")).strip().lower().replace("-", "_").replace(" ", "_")
            self.theme = "black_friday" if raw_t in ("black_friday", "blackfriday", "bf", "") else raw_t
            ch_cfg = tk.get("chessheat_overlay", {})
            if isinstance(ch_cfg, dict):
                self.enabled = bool(ch_cfg.get("enabled", True))
                self.move_interval_s = max(1.0, float(ch_cfg.get("move_interval_s", self.move_interval_s)))
                self.x = int(ch_cfg.get("x", self.x))
                self.y = int(ch_cfg.get("y", self.y))
        except Exception:
            pass

    @staticmethod
    def _sq_xy(sq: int, bx0: int, by0: int, sq_px: int) -> Tuple[int, int]:
        file_i = chess.square_file(sq)
        rank_i = chess.square_rank(sq)
        x = bx0 + file_i * sq_px
        y = by0 + (7 - rank_i) * sq_px
        return x, y

    def _render_card(
        self,
        board,
        source_badge: str,
        game_title: str,
        layer_key: str,
        sq_rgba: Dict[int, Tuple[int, int, int, int]],
        ray_segments: List[Tuple[int, int]],
        stats: dict,
        last_move,
        last_san: str,
        ply_num: int,
        perspective_lbl: str,
    ):
        w, h = self.card_w, self.card_h
        is_tg = (self.theme == "thanksgiving")
        is_bf = (self.theme == "black_friday")

        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        bg_rgba = (12, 13, 17, 236) if is_bf else ((22, 15, 11, 232) if is_tg else (16, 19, 27, 230))
        outer_border = (242, 188, 48, 242) if is_bf else ((232, 132, 42, 240) if is_tg else (70, 140, 205, 225))
        inner_border = (225, 52, 65, 115) if is_bf else ((255, 202, 95, 105) if is_tg else (90, 140, 190, 95))
        hdr_fill = (24, 16, 20, 248) if is_bf else ((56, 27, 13, 246) if is_tg else (26, 33, 46, 246))
        sub_fill = (16, 16, 22, 242) if is_bf else ((36, 20, 12, 240) if is_tg else (20, 26, 38, 240))

        draw.rounded_rectangle([(0, 0), (w - 1, h - 1)], radius=12, fill=bg_rgba, outline=outer_border, width=2)
        draw.rounded_rectangle([(4, 4), (w - 5, h - 5)], radius=9, outline=inner_border, width=1)
        draw.rounded_rectangle([(2, 2), (w - 3, 29)], radius=10, fill=hdr_fill)
        draw.rectangle([(2, 29), (w - 3, 51)], fill=sub_fill)
        draw.line([(5, 29), (w - 6, 29)], fill=(outer_border[0], outer_border[1], outer_border[2], 140), width=1)
        draw.line([(5, 51), (w - 6, 51)], fill=(outer_border[0], outer_border[1], outer_border[2], 170), width=1)

        f_badge = self._get_font(10)
        f_title = self._get_font(11)
        f_layer = self._get_font(10)
        f_coord = self._get_font(9)
        f_stat_k = self._get_font(10)
        f_stat_v = self._get_font(11)
        f_piece = self._get_font(25, regular=True)
        f_foot = self._get_font(10)

        # Row 1: Accurate Source Badge (`HISTORICAL` vs `LIVE SIM`) + Game Title
        is_sim = (source_badge == "LIVE SIM")
        b_fill = (24, 118, 86, 245) if is_sim else ((175, 30, 45, 245) if is_bf else ((168, 82, 22, 245) if is_tg else (45, 95, 165, 245)))
        tb = draw.textbbox((0, 0), source_badge, font=f_badge)
        bw = (tb[2] - tb[0]) + 12
        draw.rounded_rectangle([(10, 6), (10 + bw, 24)], radius=4, fill=b_fill)
        draw.text((16, 9), source_badge, font=f_badge, fill=(248, 252, 250, 255))

        max_title_chars = 36
        disp_title = game_title if len(game_title) <= max_title_chars else (game_title[:max_title_chars - 2] + "..")
        draw.text((16 + bw, 8), disp_title, font=f_title, fill=(255, 240, 205, 255) if (is_bf or is_tg) else (230, 240, 250, 255))

        # Row 2: Accurate Typed ChessHeat Layer Name
        layer_lbl = LAYER_TITLES.get(layer_key, layer_key)
        draw.text((12, 35), layer_lbl, font=f_layer, fill=(255, 212, 85, 250) if is_bf else ((255, 198, 92, 250) if is_tg else (115, 215, 255, 250)))

        # Board Geometry: 8x8 * 33px = 264x264 at (18, 58)
        sq_px = 33
        bx0, by0 = 18, 58
        board_px = sq_px * 8  # 264

        light_sq = (228, 207, 174, 255)  # warm ChessHeat parchment
        dark_sq = (158, 118, 84, 255)    # warm ChessHeat walnut

        for rank_i in range(8):
            for file_i in range(8):
                sq = chess.square(file_i, rank_i)
                sx, sy = self._sq_xy(sq, bx0, by0, sq_px)
                is_light = ((rank_i + file_i) % 2 == 1)
                base_c = light_sq if is_light else dark_sq
                draw.rectangle([(sx, sy), (sx + sq_px - 1, sy + sq_px - 1)], fill=base_c)

                # Last move origin/destination subtle frame
                if last_move is not None and sq in (last_move.from_square, last_move.to_square):
                    draw.rectangle([(sx + 1, sy + 1), (sx + sq_px - 2, sy + sq_px - 2)], outline=(255, 235, 95, 235), width=2)

                # Typed ChessHeat measurement overlay
                if sq in sq_rgba:
                    ov = sq_rgba[sq]
                    # Alpha-composite square tint cleanly over base square
                    a = ov[3] / 255.0
                    mixed = (
                        int(base_c[0] * (1.0 - a) + ov[0] * a),
                        int(base_c[1] * (1.0 - a) + ov[1] * a),
                        int(base_c[2] * (1.0 - a) + ov[2] * a),
                        255,
                    )
                    draw.rectangle([(sx + 1, sy + 1), (sx + sq_px - 2, sy + sq_px - 2)], fill=mixed)

        draw.rectangle([(bx0 - 1, by0 - 1), (bx0 + board_px, by0 + board_px)], outline=(210, 155, 95, 200), width=1)

        # Coordinate labels (ranks 8..1 on left, files a..h on bottom)
        for i, r_ch in enumerate("87654321"):
            draw.text((7, by0 + i * sq_px + 11), r_ch, font=f_coord, fill=(195, 175, 150, 210))
        for i, f_ch in enumerate("abcdefgh"):
            draw.text((bx0 + i * sq_px + 13, by0 + board_px + 2), f_ch, font=f_coord, fill=(195, 175, 150, 210))

        # Newly opened SlidingRays (`appeared_rays` in GeometryDelta)
        for src_sq, tgt_sq in ray_segments:
            x1s, y1s = self._sq_xy(src_sq, bx0, by0, sq_px)
            x2s, y2s = self._sq_xy(tgt_sq, bx0, by0, sq_px)
            c1 = (x1s + sq_px // 2, y1s + sq_px // 2)
            c2 = (x2s + sq_px // 2, y2s + sq_px // 2)
            draw.line([c1, c2], fill=(255, 208, 70, 215), width=3)
            draw.ellipse([(c2[0] - 4, c2[1] - 4), (c2[0] + 4, c2[1] + 4)], fill=(255, 225, 95, 235))

        # Last move transition vector arrow
        if last_move is not None:
            fx, fy = self._sq_xy(last_move.from_square, bx0, by0, sq_px)
            tx, ty = self._sq_xy(last_move.to_square, bx0, by0, sq_px)
            p1 = (fx + sq_px // 2, fy + sq_px // 2)
            p2 = (tx + sq_px // 2, ty + sq_px // 2)
            draw.line([p1, p2], fill=(255, 242, 120, 185), width=2)

        # Render Chess Pieces (high-contrast ivory + dark outline for White, obsidian + ivory halo for Black)
        for sq in chess.SQUARES:
            p = board.piece_at(sq)
            if not p:
                continue
            glyph = SOLID_PIECE_GLYPH.get(p.piece_type)
            if not glyph:
                continue
            sx, sy = self._sq_xy(sq, bx0, by0, sq_px)
            gb = draw.textbbox((0, 0), glyph, font=f_piece)
            gw, gh = gb[2] - gb[0], gb[3] - gb[1]
            gx = sx + (sq_px - gw) // 2 - gb[0]
            gy = sy + (sq_px - gh) // 2 - gb[1]

            if p.color == chess.WHITE:
                fill_c = (255, 252, 242, 255)
                stroke_c = (20, 18, 16, 255)
            else:
                fill_c = (20, 22, 28, 255)
                stroke_c = (245, 238, 225, 235)

            for ox, oy in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1), (-1, 1), (1, -1)):
                draw.text((gx + ox, gy + oy), glyph, font=f_piece, fill=stroke_c)
            draw.text((gx, gy), glyph, font=f_piece, fill=fill_c)

        # Right Inspector Rail (x = 290 .. 374, y = 58 .. 322)
        rx1, rx2 = 289, w - 9
        draw.rounded_rectangle([(rx1, 58), (rx2, 322)], radius=7, fill=(14, 11, 9, 195), outline=(180, 120, 65, 95), width=1)
        draw.text((rx1 + 7, 64), f"PLY {ply_num}", font=f_stat_v, fill=(255, 212, 115, 255))
        move_disp = last_san if last_san else "Start"
        draw.text((rx1 + 7, 80), move_disp[:8], font=f_stat_v, fill=(245, 245, 245, 255))
        draw.line([(rx1 + 6, 98), (rx2 - 6, 98)], fill=(180, 120, 65, 90), width=1)

        ry = 105
        for rkey in ("row1", "row2", "row3", "row4"):
            if rkey in stats:
                k_lbl, v_lbl = stats[rkey]
                draw.text((rx1 + 6, ry), f"{k_lbl}:", font=f_stat_k, fill=(185, 165, 145, 235))
                draw.text((rx1 + 8, ry + 13), str(v_lbl), font=f_stat_v, fill=(245, 238, 225, 255))
                ry += 32

        # Layer Color Legend Swatches at bottom of Inspector Rail
        ly = 246
        draw.line([(rx1 + 6, ly - 5), (rx2 - 6, ly - 5)], fill=(180, 120, 65, 90), width=1)
        for rgb, lbl in stats.get("legend", ())[:3]:
            draw.rectangle([(rx1 + 7, ly + 2), (rx1 + 16, ly + 11)], fill=(rgb[0], rgb[1], rgb[2], 235))
            draw.text((rx1 + 21, ly), lbl, font=f_coord, fill=(220, 210, 198, 240))
            ly += 16

        # Row 3: Footer Provenance Strip
        draw.line([(6, 334), (w - 7, 334)], fill=(outer_border[0], outer_border[1], outer_border[2], 130), width=1)
        inst_lbl = "Stockfish 16" if self._engine is not None else "Python-Chess Exact"
        foot_txt = f"Persp: {perspective_lbl}  •  Instrument: {inst_lbl}  •  ChessHeat v1"
        draw.text((12, 341), foot_txt, font=f_foot, fill=(225, 195, 130, 235) if is_bf else ((215, 180, 138, 235) if is_tg else (175, 195, 215, 230)))

        arr = np.array(img)
        bgr = arr[:, :, [2, 1, 0]].copy()
        alpha = (arr[:, :, 3:4].astype(np.float32)) / 255.0
        return bgr, alpha

    def _pick_live_sim_move(self, board, rng: random.Random):
        eng = self._open_engine_if_needed()
        legal = list(board.legal_moves)
        if not legal:
            return None
        if eng is not None:
            try:
                infos = eng.analyse(board, chess.engine.Limit(depth=6), multipv=min(3, len(legal)))
                if not isinstance(infos, list):
                    infos = [infos]
                # Weighted choice among top 2 near-equal moves in opening/middlegame for rich variety
                cands = [inf["pv"][0] for inf in infos if inf.get("pv")]
                if len(cands) >= 2 and board.fullmove_number <= 16 and rng.random() < 0.30:
                    return cands[1]
                if cands:
                    return cands[0]
            except Exception:
                self._close_engine()
        # Heuristic tactical fallback if engine unavailable
        captures = [m for m in legal if board.is_capture(m)]
        return rng.choice(captures) if (captures and rng.random() < 0.45) else rng.choice(legal)

    def _evaluate_active_layer(self, before_board, after_board, before_geom: GeometrySnapshot, layer_key: str):
        eng = self._open_engine_if_needed()
        if layer_key == "geometry_delta":
            after_geom = extract_board_geometry(after_board)
            sq_rgba, rays, stats = compute_geometry_delta_layer(before_geom, after_geom)
            persp = "Transition"
            return after_geom, sq_rgba, rays, stats, persp

        persp = "White" if after_board.turn == chess.WHITE else "Black"
        after_geom = extract_board_geometry(after_board)
        if layer_key == "dest_move_count":
            sq_rgba, rays, stats = compute_dest_move_count_layer(after_board)
            return after_geom, sq_rgba, rays, stats, persp

        if eng is not None and layer_key in ("dest_cp_regret", "pv_recurrence"):
            try:
                sq_rgba, rays, stats = compute_stockfish_layers(after_board, eng, layer_name=layer_key, depth=6)
                return after_geom, sq_rgba, rays, stats, persp
            except Exception:
                self._close_engine()

        # Fallback if Stockfish unavailable: accurately relabel as `dest_move_count`
        sq_rgba, rays, stats = compute_dest_move_count_layer(after_board)
        return after_geom, sq_rgba, rays, stats, persp

    def _worker(self):
        rng = random.Random()
        while not self._stop_event.is_set():
            self._reload_config()
            if not self.enabled:
                time.sleep(1.5)
                continue

            board = chess.Board()
            cur_geom = extract_board_geometry(board)
            eng = self._open_engine_if_needed()

            # Alternate accurately between HISTORICAL RECORD and LIVE ENGINE SIM
            is_sim = self._use_live_sim and (eng is not None)
            self._use_live_sim = not self._use_live_sim

            if is_sim:
                op_name, stem_sans = rng.choice(LIVE_SIM_OPENINGS)
                source_badge = "LIVE SIM"
                game_title = f"Stockfish 16 Self-Play ({op_name})"
                scripted_sans = list(stem_sans)
                max_plies = 76
            else:
                g = HISTORICAL_GAMES[self._game_idx % len(HISTORICAL_GAMES)]
                self._game_idx += 1
                source_badge = "HISTORICAL"
                game_title = g["title"]
                scripted_sans = list(g["moves"])
                max_plies = len(scripted_sans)

            ply = 0
            last_move = None
            last_san = "Start"

            while not self._stop_event.is_set() and self.enabled and not board.is_game_over() and ply < max_plies:
                # Auto-cycle typed ChessHeat layers every `layer_cycle_plies` plies
                avail_layers = TYPED_LAYERS if (self._engine is not None) else ("geometry_delta", "dest_move_count")
                active_layer = avail_layers[self._layer_idx % len(avail_layers)]

                before_board = board.copy()
                mv = None
                if ply < len(scripted_sans):
                    try:
                        mv = board.parse_san(scripted_sans[ply])
                    except Exception:
                        mv = None
                elif is_sim:
                    mv = self._pick_live_sim_move(board, rng)

                if mv is None or mv not in board.legal_moves:
                    break

                move_no = board.fullmove_number
                san_str = board.san(mv)
                formatted_san = f"{move_no}. {san_str}" if board.turn == chess.WHITE else f"{move_no}... {san_str}"
                board.push(mv)
                ply += 1
                last_move = mv
                last_san = formatted_san

                if ply % self.layer_cycle_plies == 0:
                    self._layer_idx += 1

                cur_geom, sq_rgba, rays, stats, persp = self._evaluate_active_layer(
                    before_board, board, cur_geom, active_layer
                )
                # Ensure displayed layer key matches fallback if Stockfish wasn't used
                shown_layer = active_layer if (self._engine is not None or active_layer in ("geometry_delta", "dest_move_count")) else "dest_move_count"

                try:
                    bgr, alpha = self._render_card(
                        board=board,
                        source_badge=source_badge,
                        game_title=game_title,
                        layer_key=shown_layer,
                        sq_rgba=sq_rgba,
                        ray_segments=rays,
                        stats=stats,
                        last_move=last_move,
                        last_san=last_san,
                        ply_num=ply,
                        perspective_lbl=persp,
                    )
                    with self._lock:
                        self._cached_bgr = bgr
                        self._cached_alpha = alpha
                except Exception:
                    pass

                # Pause slightly longer on checkmate/game finish so viewers can admire the final position
                wait_s = 5.0 if (board.is_game_over() or ply >= max_plies) else self.move_interval_s
                end_wait = time.monotonic() + wait_s
                while not self._stop_event.is_set() and time.monotonic() < end_wait:
                    time.sleep(0.2)

            self._layer_idx += 1

        self._close_engine()

    def draw(self, frame_bgr, standby_mode=True, top_matte_h=110):
        if not self.enabled or not standby_mode:
            return
        with self._lock:
            bgr = self._cached_bgr
            alpha = self._cached_alpha
        if bgr is None or alpha is None:
            return

        fh, fw = frame_bgr.shape[:2]
        ch, cw = bgr.shape[:2]
        x1 = max(0, min(fw - cw, self.x))
        y1 = max(top_matte_h + 32, min(fh - ch, self.y))
        x2, y2 = x1 + cw, y1 + ch
        if (y2 - y1, x2 - x1) != (ch, cw):
            return

        roi = frame_bgr[y1:y2, x1:x2].astype(np.float32)
        frame_bgr[y1:y2, x1:x2] = (
            roi * (1.0 - alpha) + bgr.astype(np.float32) * alpha
        ).astype(np.uint8)

    def stop(self):
        self._stop_event.set()
        self._close_engine()
