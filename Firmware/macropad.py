"""
KMK Firmware — Macropad (Pi Pico, separate MCU)
================================================
Matrix : 5 rows (NUMPAD_ROW_0..4) × 5 cols (NUMPAD_COL_0..4)
         24 keys total (ROW_4/COL_3 unpopulated)
SPI    : SLAVE — sends key event strings TO the main keyboard RP2040.

The macropad does NOT enumerate as a USB HID device for keystrokes —
the main keyboard handles all HID. When a key is pressed here, this
firmware encodes it as a newline-terminated string and transmits it
over SPI MISO back to the master.

SPI wiring (same four wires, macropad side):
  Macropad Pico (Slave)     Main keyboard (Master)
  ─────────────────────     ──────────────────────
  GP18  SCK           ◄───  GP18  SCK
  GP19  MOSI          ◄───  GP19  MOSI  (not used, tie/leave)
  GP16  MISO (TX)     ───►  GP16  MISO  (master reads here)
  GP17  CS            ◄───  GP17  CS    (active LOW)
  GND                 ───   GND

Protocol this board sends (over MISO, newline-terminated):
  Numpad key  → "P7\\n", "PPLS\\n", "PENT\\n", "NLCK\\n" …
  Keybind     → "CTRL+C\\n", "MUTE\\n", "BRIU\\n" …

Because CircuitPython has no hardware SPI slave mode, this firmware
uses a software (bit-bang) SPI slave on the same pins.
MISO is driven as an output; SCK and CS are inputs.

Matrix wiring assumptions (adjust GP numbers to match your PCB):
  NUMPAD_ROW_0..4  →  GP0..GP4
  NUMPAD_COL_0..4  →  GP5..GP9
"""

import board
import digitalio
import time

from kmk.kmk_keyboard import KMKKeyboard
from kmk.keys import KC
from kmk.scanners import DiodeOrientation
from kmk.scanners.keypad import MatrixScanner
from kmk.modules.layers import Layers
from kmk.handlers.sequences import send_string

# ──────────────────────────────────────────────
# 1. KEYBOARD OBJECT
#    The Pico still uses KMK for clean matrix scanning.
#    Key "actions" are SPI transmissions rather than HID reports,
#    achieved via custom KC.make_key handlers below.
# ──────────────────────────────────────────────
keyboard = KMKKeyboard()

# ──────────────────────────────────────────────
# 2. MATRIX PINS
# ──────────────────────────────────────────────
keyboard.matrix = MatrixScanner(
    column_pins=(
        board.GP5,   # NUMPAD_COL_0
        board.GP6,   # NUMPAD_COL_1
        board.GP7,   # NUMPAD_COL_2
        board.GP8,   # NUMPAD_COL_3
        board.GP9,   # NUMPAD_COL_4
    ),
    row_pins=(
        board.GP0,   # NUMPAD_ROW_0
        board.GP1,   # NUMPAD_ROW_1
        board.GP2,   # NUMPAD_ROW_2
        board.GP3,   # NUMPAD_ROW_3
        board.GP4,   # NUMPAD_ROW_4
    ),
    diode_orientation=DiodeOrientation.COL2ROW,
)

# ──────────────────────────────────────────────
# 3. MODULES
# ──────────────────────────────────────────────
keyboard.modules.append(Layers())

# ──────────────────────────────────────────────
# 4. SOFTWARE SPI SLAVE TRANSMITTER
#    Drives MISO out, samples SCK and CS as inputs.
#    Sends one byte per SCK rising edge (MSB first, Mode 0).
# ──────────────────────────────────────────────
_MISO_PIN = board.GP16   # output → master MISO
_SCK_PIN  = board.GP18   # input  ← master SCK
_CS_PIN   = board.GP17   # input  ← master CS (active LOW)

_miso = digitalio.DigitalInOut(_MISO_PIN)
_miso.direction = digitalio.Direction.OUTPUT
_miso.value = True   # idle HIGH (MISO idles high)

_sck_in = digitalio.DigitalInOut(_SCK_PIN)
_sck_in.direction = digitalio.Direction.INPUT
_sck_in.pull = digitalio.Pull.UP

_cs_in = digitalio.DigitalInOut(_CS_PIN)
_cs_in.direction = digitalio.Direction.INPUT
_cs_in.pull = digitalio.Pull.UP

# Queue of strings waiting to be sent to the master
_tx_queue = []

def _spi_send_byte(b: int):
    """
    Clock out one byte MSB-first on MISO, synchronised to master SCK.
    Blocks until all 8 bits are sent or CS deasserts.
    """
    for bit_pos in range(7, -1, -1):
        _miso.value = bool(b & (1 << bit_pos))
        # Wait for SCK rising edge
        while _sck_in.value:   # wait for LOW first
            if _cs_in.value: return
        while not _sck_in.value:  # wait for HIGH (rising edge)
            if _cs_in.value: return
    _miso.value = True  # return MISO high after byte

def _spi_transmit(msg: str):
    """
    Transmit a newline-terminated string to the master when CS is LOW.
    Waits up to ~5 ms for CS to assert; drops message if master isn't ready.
    """
    # Wait for master to assert CS
    deadline = time.monotonic() + 0.005
    while _cs_in.value:
        if time.monotonic() > deadline:
            return   # master not ready, drop
    for ch in (msg + "\n"):
        _spi_send_byte(ord(ch))
    # Send idle byte so master clock cycle completes cleanly
    _spi_send_byte(0xFF)

def _queue_key(msg: str):
    """Add a key message to the transmit queue."""
    _tx_queue.append(msg)

def _flush_tx():
    """Send one queued message per call (called each main loop iteration)."""
    if _tx_queue:
        _spi_transmit(_tx_queue.pop(0))

# ──────────────────────────────────────────────
# 5. CUSTOM KEY FACTORY
#    make_spi_key("P7") creates a KC-compatible key that, on press,
#    queues "P7\n" for SPI transmission to the master.
# ──────────────────────────────────────────────
def make_spi_key(token: str):
    """Return a KMK key object that sends `token` over SPI on press."""
    return KC.make_key(
        names=(f"SPI_{token}",),
        on_press=lambda key, keyboard, *args: _queue_key(token),
    )

# Pre-build all the keys we need
_NLCK  = make_spi_key("NLCK")
_PSLS  = make_spi_key("PSLS")
_PAST  = make_spi_key("PAST")
_PMNS  = make_spi_key("PMNS")
_P7    = make_spi_key("P7")
_P8    = make_spi_key("P8")
_P9    = make_spi_key("P9")
_PPLS  = make_spi_key("PPLS")
_P4    = make_spi_key("P4")
_P5    = make_spi_key("P5")
_P6    = make_spi_key("P6")
_P1    = make_spi_key("P1")
_P2    = make_spi_key("P2")
_P3    = make_spi_key("P3")
_PENT  = make_spi_key("PENT")
_P0    = make_spi_key("P0")
_PDOT  = make_spi_key("PDOT")

# Custom row macros (Layer 0 last key, and all of Layer 1)
_TG1   = KC.TG(1)
_MUTE  = make_spi_key("MUTE")
_VOLD  = make_spi_key("VOLD")
_VOLU  = make_spi_key("VOLU")
_MPLY  = make_spi_key("MPLY")
_MPRV  = make_spi_key("MPRV")
_MNXT  = make_spi_key("MNXT")
_BRID  = make_spi_key("BRID")
_BRIU  = make_spi_key("BRIU")
_PSCR  = make_spi_key("PSCR")
_COPY  = make_spi_key("CTRL+C")
_CUT   = make_spi_key("CTRL+X")
_PASTE = make_spi_key("CTRL+V")
_UNDO  = make_spi_key("CTRL+Z")

XXXXXXX = KC.NO

# ──────────────────────────────────────────────
# 6. KEYMAP
#
#        COL_0   COL_1   COL_2   COL_3   COL_4
# ROW_0: NumLk   /       *       -       [empty]
# ROW_1: 7       8       9       +       [empty]
# ROW_2: 4       5       6       +*      [empty]   * tall key, same switch row
# ROW_3: 1       2       3       Enter   [empty]
# ROW_4: 0       0*      .       Enter*  CUSTOM    ← edit COL_4 freely
# ──────────────────────────────────────────────
keyboard.keymap = [
    # ── Layer 0 — Numpad ────────────────────────────────────────────────────
    [
        # ROW_0
        _NLCK,  _PSLS,  _PAST,  _PMNS,  XXXXXXX,
        # ROW_1
        _P7,    _P8,    _P9,    _PPLS,  XXXXXXX,
        # ROW_2
        _P4,    _P5,    _P6,    _PPLS,  XXXXXXX,
        # ROW_3
        _P1,    _P2,    _P3,    _PENT,  XXXXXXX,
        # ROW_4  — CUSTOM: edit these five keys! (COL_4 = layer toggle)
        _P0,    _P0,    _PDOT,  _PENT,  _TG1,
    ],

    # ── Layer 1 — Macro / media (toggled by ROW_4 COL_4) ───────────────────
    [
        # ROW_0 — volume / playback
        _MUTE,  _VOLD,  _VOLU,  _MPLY,  XXXXXXX,
        # ROW_1 — track + brightness
        _MPRV,  _MNXT,  _BRID,  _BRIU,  XXXXXXX,
        # ROW_2 — screenshot / spare
        _PSCR,  XXXXXXX, XXXXXXX, XXXXXXX, XXXXXXX,
        # ROW_3 — clipboard
        _COPY,  _CUT,   _PASTE, _UNDO,  XXXXXXX,
        # ROW_4 — back to numpad layer
        XXXXXXX, XXXXXXX, XXXXXXX, XXXXXXX, _TG1,
    ],
]

# ──────────────────────────────────────────────
# 7. MAIN LOOP
# ──────────────────────────────────────────────
if __name__ == "__main__":
    keyboard._init()
    while True:
        keyboard._main_task()   # scan matrix, fire key handlers
        _flush_tx()             # transmit any queued SPI message