"""
KMK Firmware — Custom 89-key keyboard (RP2040, built-in)
=========================================================
Matrix : 7 rows (ROW_0..ROW_6) × 15 cols (COL_0..COL_14)
SPI    : MASTER — receives key event strings FROM the macropad Pico.

The main keyboard is the USB HID device. The macropad Pico is a SPI slave;
it scans its own matrix and sends key events back to this board as SPI
messages, which are then injected as HID keystrokes here.

SPI wiring (connect these four wires between the two boards):
  This board (Master)      Macropad Pico (Slave)
  ────────────────────     ─────────────────────
  GP18  SCK         ───►  GP18  SCK
  GP19  MOSI        ───►  GP19  MOSI  (unused by slave, tie low or leave)
  GP16  MISO (RX)   ◄───  GP16  MISO  (slave sends here)
  GP17  CS          ───►  GP17  CS    (active LOW)
  GND               ───   GND         (MUST be common ground)

Protocol (newline-terminated strings sent by macropad over MISO):
  Keybind   → "CTRL+C\\n", "CTRL+SHIFT+T\\n", "ALT+F4\\n"
  Plain text → "Hello\\n"
  Numpad key → "P7\\n", "PPLS\\n", "PENT\\n"  (named key tokens)
  Idle byte  → 0xFF  (macropad sends this when no key is pending)

Keyboard matrix wiring assumptions (adjust GP numbers to match your PCB):
  ROW_0..ROW_6  →  GP0..GP6
  COL_0..COL_14 →  GP7–GP15, GP20–GP22, GP26–GP28
"""

import board
import busio
import digitalio

from kmk.kmk_keyboard import KMKKeyboard
from kmk.keys import KC
from kmk.scanners import DiodeOrientation
from kmk.scanners.keypad import MatrixScanner
from kmk.modules.layers import Layers

# ──────────────────────────────────────────────
# 1. KEYBOARD OBJECT
# ──────────────────────────────────────────────
keyboard = KMKKeyboard()

# ──────────────────────────────────────────────
# 2. MATRIX PINS
# ──────────────────────────────────────────────
keyboard.matrix = MatrixScanner(
    column_pins=(
        board.GP7,  board.GP8,  board.GP9,  board.GP10, board.GP11,
        board.GP12, board.GP13, board.GP14, board.GP15, board.GP20,
        board.GP21, board.GP22, board.GP26, board.GP27, board.GP28,
    ),
    row_pins=(
        board.GP0, board.GP1, board.GP2, board.GP3,
        board.GP4, board.GP5, board.GP6,
    ),
    diode_orientation=DiodeOrientation.COL2ROW,
)

# ──────────────────────────────────────────────
# 3. MODULES
# ──────────────────────────────────────────────
keyboard.modules.append(Layers())

# ──────────────────────────────────────────────
# 4. KEYMAP
# ──────────────────────────────────────────────
XXXXXXX = KC.NO

keyboard.keymap = [
    # ── Layer 0 — Base ──────────────────────────────────────────────────────
    [
        # ROW_0  (15 keys)
        KC.ESC,  KC.F1,   KC.F2,   KC.F3,   KC.F4,   KC.F5,   KC.F6,
        KC.F7,   KC.F8,   KC.F9,   KC.F10,  KC.F11,  KC.F12,  KC.DEL,  KC.DEL,

        # ROW_1  (15 keys)
        KC.GRV,  KC.N1,   KC.N2,   KC.N3,   KC.N4,   KC.N5,   KC.N6,
        KC.N7,   KC.N8,   KC.N9,   KC.N0,   KC.MINS, KC.EQL,  KC.BSPC, KC.BSPC,

        # ROW_2  (14 keys; col14 unpopulated)
        KC.TAB,  KC.Q,    KC.W,    KC.E,    KC.R,    KC.T,    KC.Y,
        KC.U,    KC.I,    KC.O,    KC.P,    KC.LBRC, KC.RBRC, KC.BSLS, XXXXXXX,

        # ROW_3  (14 keys; col14 unpopulated)
        KC.CAPS, KC.A,    KC.S,    KC.D,    KC.F,    KC.G,    KC.H,
        KC.J,    KC.K,    KC.L,    KC.SCLN, KC.QUOT, KC.ENT,  KC.ENT,  XXXXXXX,

        # ROW_4  (12 keys; cols 12-14 unpopulated)
        KC.LSFT, KC.Z,    KC.X,    KC.C,    KC.V,    KC.B,    KC.N,
        KC.M,    KC.COMM, KC.DOT,  KC.SLSH, KC.RSFT, XXXXXXX, XXXXXXX, XXXXXXX,

        # ROW_5  (13 keys; cols 13-14 unpopulated)
        KC.MO(1), KC.LCTL, KC.LALT, KC.LGUI,
        KC.SPC,  KC.SPC,  KC.SPC,  KC.SPC,
        KC.RGUI, KC.RALT, KC.PGUP, KC.UP,   KC.PGDN, XXXXXXX, XXXXXXX,

        # ROW_6  (3 keys; only cols 9-11 populated)
        XXXXXXX, XXXXXXX, XXXXXXX, XXXXXXX, XXXXXXX, XXXXXXX, XXXXXXX,
        XXXXXXX, XXXXXXX, KC.LEFT, KC.DOWN, KC.RGHT, XXXXXXX, XXXXXXX, XXXXXXX,
    ],

    # ── Layer 1 — Fn ────────────────────────────────────────────────────────
    [
        # ROW_0 — media / brightness on Fn
        KC.TRNS, KC.BRID, KC.BRIU, KC.TRNS, KC.TRNS, KC.TRNS, KC.TRNS,
        KC.MPRV, KC.MPLY, KC.MNXT, KC.MUTE, KC.VOLD, KC.VOLU, KC.TRNS, KC.TRNS,

        *[KC.TRNS] * 15,  # ROW_1
        *[KC.TRNS] * 15,  # ROW_2
        *[KC.TRNS] * 15,  # ROW_3
        *[KC.TRNS] * 15,  # ROW_4
        *[KC.TRNS] * 15,  # ROW_5
        *[KC.TRNS] * 15,  # ROW_6
    ],
]

# ──────────────────────────────────────────────
# 5. SPI MASTER — receives key events from macropad Pico
# ──────────────────────────────────────────────

_SPI_BAUDRATE = 500_000  # 500 kHz — conservative for bit-bang slave

# Hardware SPI1: SCK=GP18, MOSI=GP19 (unused), MISO=GP16
_spi = busio.SPI(clock=board.GP18, MOSI=board.GP19, MISO=board.GP16)
_cs  = digitalio.DigitalInOut(board.GP17)
_cs.direction = digitalio.Direction.OUTPUT
_cs.value = True  # idle HIGH

_spi_rx_buf = []  # accumulate characters until newline

# ── Key name → KC lookup (includes numpad keys for macropad) ────────────────
_MOD_MAP = {
    "CTRL": KC.LCTL, "CONTROL": KC.LCTL,
    "SHIFT": KC.LSFT,
    "ALT": KC.LALT, "OPTION": KC.LALT,
    "GUI": KC.LGUI, "CMD": KC.LGUI, "WIN": KC.LGUI,
    "RCTRL": KC.RCTL, "RSHIFT": KC.RSFT, "RALT": KC.RALT, "RGUI": KC.RGUI,
}

_KEY_NAME_MAP = {
    # Navigation / editing
    "ESC": KC.ESC,       "TAB": KC.TAB,      "ENTER": KC.ENT,   "RETURN": KC.ENT,
    "SPACE": KC.SPC,     "BSPC": KC.BSPC,    "BACKSPACE": KC.BSPC,
    "DEL": KC.DEL,       "DELETE": KC.DEL,
    "UP": KC.UP,         "DOWN": KC.DOWN,    "LEFT": KC.LEFT,   "RIGHT": KC.RGHT,
    "PGUP": KC.PGUP,     "PGDN": KC.PGDN,    "HOME": KC.HOME,   "END": KC.END,
    "INS": KC.INS,       "INSERT": KC.INS,
    "CAPS": KC.CAPS,     "CAPSLOCK": KC.CAPS,
    "PRTSC": KC.PSCR,    "PRINTSCREEN": KC.PSCR,
    # Function keys
    "F1": KC.F1,  "F2": KC.F2,  "F3": KC.F3,  "F4": KC.F4,
    "F5": KC.F5,  "F6": KC.F6,  "F7": KC.F7,  "F8": KC.F8,
    "F9": KC.F9,  "F10": KC.F10, "F11": KC.F11, "F12": KC.F12,
    # Media
    "MUTE": KC.MUTE,  "VOLU": KC.VOLU,  "VOLD": KC.VOLD,
    "MPLY": KC.MPLY,  "MNXT": KC.MNXT,  "MPRV": KC.MPRV,
    "BRID": KC.BRID,  "BRIU": KC.BRIU,  "PSCR": KC.PSCR,
    # Numpad keys (sent by macropad)
    "NLCK": KC.NLCK,  "NUMLOCK": KC.NLCK,
    "PSLS": KC.PSLS,  "PAST": KC.PAST,  "PMNS": KC.PMNS,
    "PPLS": KC.PPLS,  "PENT": KC.PENT,  "PDOT": KC.PDOT,
    "P0": KC.P0, "P1": KC.P1, "P2": KC.P2, "P3": KC.P3, "P4": KC.P4,
    "P5": KC.P5, "P6": KC.P6, "P7": KC.P7, "P8": KC.P8, "P9": KC.P9,
}

def _ascii_to_kc(ch):
    if ch in ("\n", "\r"): return KC.ENT
    if ch == "\t":         return KC.TAB
    if ch == " ":          return KC.SPC
    if ch.isupper():
        k = getattr(KC, ch, None)
        return KC.LSFT(k) if k else None
    if ch.islower():       return getattr(KC, ch.upper(), None)
    if ch.isdigit():       return getattr(KC, "N" + ch, None)
    return {
        "!": KC.LSFT(KC.N1),  "@": KC.LSFT(KC.N2),  "#": KC.LSFT(KC.N3),
        "$": KC.LSFT(KC.N4),  "%": KC.LSFT(KC.N5),  "^": KC.LSFT(KC.N6),
        "&": KC.LSFT(KC.N7),  "*": KC.LSFT(KC.N8),  "(": KC.LSFT(KC.N9),
        ")": KC.LSFT(KC.N0),  "-": KC.MINS,          "_": KC.LSFT(KC.MINS),
        "=": KC.EQL,          "+": KC.LSFT(KC.EQL),  "[": KC.LBRC,
        "{": KC.LSFT(KC.LBRC),"]": KC.RBRC,          "}": KC.LSFT(KC.RBRC),
        "\\": KC.BSLS,        "|": KC.LSFT(KC.BSLS), ";": KC.SCLN,
        ":": KC.LSFT(KC.SCLN),"'": KC.QUOT,          '"': KC.LSFT(KC.QUOT),
        ",": KC.COMM,         "<": KC.LSFT(KC.COMM), ".": KC.DOT,
        ">": KC.LSFT(KC.DOT), "/": KC.SLSH,          "?": KC.LSFT(KC.SLSH),
        "`": KC.GRV,          "~": KC.LSFT(KC.GRV),
    }.get(ch, None)

def _parse_command(raw):
    text = raw.strip()
    if not text:
        return []
    upper = text.upper()
    parts = upper.split("+")
    if len(parts) > 1:
        mods, key = [], None
        for p in parts:
            p = p.strip()
            if p in _MOD_MAP:        mods.append(_MOD_MAP[p])
            elif p in _KEY_NAME_MAP: key = _KEY_NAME_MAP[p]
            elif len(p) == 1:        key = _ascii_to_kc(p.lower())
        if key is not None:
            for mod in reversed(mods):
                key = mod(key)
            return [key]
    # Single named key (e.g. "P7", "PPLS", "PENT")
    if upper in _KEY_NAME_MAP:
        return [_KEY_NAME_MAP[upper]]
    # Plain ASCII string
    return [kc for ch in text if (kc := _ascii_to_kc(ch)) is not None]

def _inject_keys(key_list):
    for key in key_list:
        keyboard.hid.register_key(key)
        keyboard.hid.send()
        keyboard.hid.unregister_key(key)
        keyboard.hid.send()

def _poll_spi():
    """Read one byte from macropad per call. 0xFF = slave idle (skip)."""
    try:
        if not _spi.try_lock():
            return
        _spi.configure(baudrate=_SPI_BAUDRATE, phase=0, polarity=0)
        _cs.value = False
        rx = bytearray(1)
        _spi.readinto(rx, write_value=0xFF)
        _cs.value = True
        _spi.unlock()

        b = rx[0]
        if b == 0xFF:   # idle
            return
        ch = chr(b)
        if ch in ("\n", "\r"):
            line = "".join(_spi_rx_buf)
            _spi_rx_buf.clear()
            if line:
                _inject_keys(_parse_command(line))
        else:
            _spi_rx_buf.append(ch)
    except Exception:
        _cs.value = True
        try:   _spi.unlock()
        except Exception: pass

# ──────────────────────────────────────────────
# 6. MAIN LOOP
# ──────────────────────────────────────────────
if __name__ == "__main__":
    keyboard._init()
    while True:
        keyboard._main_task()
        _poll_spi()