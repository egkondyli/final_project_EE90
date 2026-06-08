import board
import adafruit_mcp4728
import numpy as np
import time
import adafruit_ads1x15.ads1015 as ADS
from adafruit_ads1x15 import ads1x15
from adafruit_ads1x15.analog_in import AnalogIn

from datetime import datetime
import os
import math

import digitalio

from adafruit_mcp230xx.mcp23017 import MCP23017

os.environ["BLINKA_MCP2221"] = "1"

# constants
MCP4728_DEFAULT_ADDRESS = 0x60  # i2C address of DAC
MCP23017_DEFAULT_ADDRESS = 0x20 # i2C address of GPIO Expander

# Full-scale resistance values (Ohms)
R_100K = 100 * (10**3)
R_10K  = 10 * (10**3)
MAX_DIGITAL_POT_BYTE = 255

# Per-pot configuration: I2C address + full-scale resistance.
#   - 100k pots: DP0, DP1, DP2, DP3, DP4, DP5, DP7, DP11, DP12
#   - 10k  pots: DP6, DP8, DP9, DP10, DP13
DIGITAL_POTS = {
    0:  {"address": 0b0100000, "max_resistance": R_100K},
    1:  {"address": 0b0100010, "max_resistance": R_100K},
    2:  {"address": 0b0100011, "max_resistance": R_100K},
    3:  {"address": 0b0101000, "max_resistance": R_100K},
    4:  {"address": 0b0101010, "max_resistance": R_100K},
    5:  {"address": 0b0101011, "max_resistance": R_100K},
    6:  {"address": 0b0101100, "max_resistance": R_10K},
    7:  {"address": 0b0101110, "max_resistance": R_100K},
    8:  {"address": 0b0101111, "max_resistance": R_10K},
    9:  {"address": 0b0101100, "max_resistance": R_10K},
    10: {"address": 0b0101111, "max_resistance": R_10K},
    11: {"address": 0b0101010, "max_resistance": R_100K},
    12: {"address": 0b0101011, "max_resistance": R_100K},
    13: {"address": 0b0101110, "max_resistance": R_10K},
}

# pot instructions
UPDATE_INSTRUCTION_BYTE = b'\x10' # Used to indicate that you are writing a new value to a digital pot.
SAVE_INSTRUCTION_BYTE = b'\x80' # Used to save last loaded value as default resistance value of digital pot.
READ_INSTRUCTION_BYTE = b'\x30' # Used to read the value of the digital pot directly from the digital pot.
READ_DATA_BYTE = b'\x10' # Data that must be sent when reading the value of the digital pot

# Value input to set_gp_pins to indicate that the voltage of a given pin should
# not be modified
NULL_VOLTAGE = -1

# Value input to set_digital_pots to indicate that a given digital pot's value
# should not be modified
NULL_RESISTANCE = -1

# ------------------------------------------------------------------------
#                          CAP BANK CONFIG
# ------------------------------------------------------------------------
# Each switch (U31/U32/U33 driven by SW_0/SW_1/SW_2) is an SPDT that selects
# one of two caps. The selected caps from all three switches sit in PARALLEL
# between W SW CAP IN and W SW CAP OUT, so total C = c(sw0) + c(sw1) + c(sw2).
#
# Switch select polarity (from board switch behavior):
#   SW Low  (False) -> B1 (pin 3)
#   SW High (True)  -> B2 (pin 1)

# --- Bank 2 = "Wein capacitor bank" (values read from schematic), Farads ---
C58 = 1.4 * (10**-6)   # U31 B2
C59 = 200 * (10**-9)   # U31 B1
C60 = 200 * (10**-9)   # U32 B2
C61 = 25 * (10**-9)    # U32 B1
C62 = 4 * (10**-9)     # U33 B2
C63 = 0.5 * (10**-9)   # U33 B1

# --- Bank 1 = triangle/square cap bank, Farads ---
C34 = 10 * (10**-6)   # B2  (placeholder)
C35 = 0    # B1  (placeholder)
C37 = 680 * (10**-9)    # B2  (placeholder)
C38 = 0  # B1  (placeholder)
C40 = 100 * (10**-9)     # B2  (placeholder)
C41 = 10 * (10**-9)   # B1  (placeholder)

# Per-bank lookup. For each switch: "low" -> B1 cap, "high" -> B2 cap.
CAP_BANKS = {
    2: {  # Wein cap bank (from schematic)
        0: {"low": C59, "high": C58},  # SW_0 / U31
        1: {"low": C61, "high": C60},  # SW_1 / U32
        2: {"low": C63, "high": C62},  # SW_2 / U33
    },
    1: {  # !!! TODO: PLACEHOLDER values -- replace with real Bank 1 caps
        0: {"low": C35, "high": C34},
        1: {"low": C38, "high": C37},
        2: {"low": C41, "high": C40},
    },
}

V_REF = 4095 # adafruit mcp4728 reference voltage, in 16 bit

i2c = board.I2C()  # uses board.SCL and board.SDA

# Create the ADC object using the I2C bus
ads = ADS.ADS1015(i2c)

# Create GPIO Expander
mcp23017 = MCP23017(i2c, address=MCP23017_DEFAULT_ADDRESS)

# Create single-ended inputs
chan0 = AnalogIn(ads, ads1x15.Pin.A0)
chan1 = AnalogIn(ads, ads1x15.Pin.A1)
chan2 = AnalogIn(ads, ads1x15.Pin.A2)
chan3 = AnalogIn(ads, ads1x15.Pin.A3)

# Use G0-G3 pins on MCP2221 to set GPO pins on Lab board
g0 = digitalio.DigitalInOut(board.G0)
g1 = digitalio.DigitalInOut(board.G1)
g2 = digitalio.DigitalInOut(board.G2)
g3 = digitalio.DigitalInOut(board.G3)

def set_gp_pins(gp0=NULL_VOLTAGE, gp1=NULL_VOLTAGE, gp2=NULL_VOLTAGE, gp3=NULL_VOLTAGE):
    """
    Sets voltage of GP pins on MCP2221. A passed value of True will set the
    corresponding pin high, and a passed value of False will set the
    corresponding pin low. All arguments are optional.

    Pin roles on the new board:
        GP0 = cap-bank SW1
        GP1 = cap-bank SW0
        GP2 = cap-bank SW2
        GP3 = LDO_enb (LDO enable)

    INPUTS
        gp0: sets GP0 on EE 90 Shield (cap-bank SW1)
        gp1: sets GP1 on EE 90 Shield (cap-bank SW0)
        gp2: sets GP2 on EE 90 Shield (cap-bank SW2)
        gp3: sets GP3 on EE 90 Shield (LDO_enb)
    """

    if (gp2 != NULL_VOLTAGE):
        g0.direction = digitalio.Direction.OUTPUT
        g0.value = gp2 # board.G0 sets GP2 on EE 90 Shield (cap-bank SW2)
    if (gp3 != NULL_VOLTAGE):
        g1.direction = digitalio.Direction.OUTPUT
        g1.value = gp3 # board.G1 sets GP3 on EE 90 Shield (LDO_enb)
    if (gp0 != NULL_VOLTAGE):
        g2.direction = digitalio.Direction.OUTPUT
        g2.value = gp0 # board.G2 sets GP0 on EE 90 Shield (cap-bank SW1)
    if (gp1 != NULL_VOLTAGE):
        g3.direction = digitalio.Direction.OUTPUT
        g3.value = gp1 # board.G3 sets GP1 on EE 90 Shield (cap-bank SW0)

def set_ldo_enable(enable):
    """
    Enable/disable the LDO. LDO_enb is on GP3 on the new board, so this is
    independent of the cap bank (which uses GP0/GP1/GP2).
    """
    set_gp_pins(gp3=enable)

def resistance_to_byte(r, max_resistance):
    """Convert a resistance (Ohms) to an 8-bit pot code, clamped to 0..255."""
    fraction = r / max_resistance
    r_byte = math.floor(fraction * MAX_DIGITAL_POT_BYTE)

    # Clamp so a value above full-scale (or below 0) can't overflow the byte
    r_byte = max(0, min(MAX_DIGITAL_POT_BYTE, r_byte))

    return int(r_byte)

def byte_to_resistance(byte, max_resistance):
    """Convert an 8-bit pot code back to a resistance (Ohms)."""
    fraction = byte[0] / MAX_DIGITAL_POT_BYTE
    r = math.floor(fraction * max_resistance)

    return r

def set_digital_pot(pot_num, dp_resistance):
    """
    Sets the value of a single digital potentiometer.

    INPUTS
        pot_num:       index 0-13 into DIGITAL_POTS
        dp_resistance: desired resistance in Ohms
    """

    cfg = DIGITAL_POTS[pot_num]
    pot_address = cfg["address"]
    max_resistance = cfg["max_resistance"]

    if pot_address is None:
        raise ValueError(
            f"DP{pot_num} has no I2C address set yet -- fill it into DIGITAL_POTS."
        )

    # Compute value for setting potentiometer
    r_byte = resistance_to_byte(dp_resistance, max_resistance).to_bytes(1, 'big')
    data_byte = UPDATE_INSTRUCTION_BYTE + r_byte

    # Set the potentiometer value
    i2c.writeto(pot_address, bytearray(data_byte)) # load new resistance value for pot
    i2c.writeto(pot_address, bytearray(SAVE_INSTRUCTION_BYTE + r_byte)) # save value as default resistance for pot

    # Print out potentiometer value to ensure correct value was set
    returned_byte = r_byte # bytearray(2) # Potentiometer value is stored into this variable
    #i2c.writeto_then_readfrom(pot_address, READ_INSTRUCTION_BYTE + READ_DATA_BYTE, returned_byte) # read back resistance value as a byte
    print(f"DP{pot_num} Resistance: ", byte_to_resistance(returned_byte, max_resistance),
          " Ohms; ", data_byte.hex()) # print out resistance value

def set_digital_pots(**pots):
    """
    Sets multiple digital pot resistances.

    Pass any of dp0 .. dp13 as keyword arguments, e.g.
        set_digital_pots(dp0=50000, dp7=20000, dp13=5000)

    A value of NULL_RESISTANCE leaves that pot unchanged.
    """

    # Data bytes format: b'\x10\x##'
    #                    where ## is the hex value used to set the given pot.

    for key, resistance in pots.items():
        if not key.startswith("dp"):
            raise ValueError(f"Unexpected argument '{key}'; expected dp0..dp13.")

        pot_num = int(key[2:])
        if pot_num not in DIGITAL_POTS:
            raise ValueError(f"DP{pot_num} is not a valid pot (0-13).")

        if resistance != NULL_RESISTANCE:
            set_digital_pot(pot_num, resistance)

def set_digital_pots_frac(**pots):
    """
    Like set_digital_pots, but each value is a FRACTION (0.0 to 1.0) of that
    pot's full-scale resistance, instead of an absolute resistance in ohms.
    This handles the 100k vs 10k pots automatically: 0.5 is half of whatever
    that particular pot's max is.

    Example:
        set_digital_pots_frac(dp0=0.5, dp13=0.8)
        # DP0 -> 50% of 100k = 50 kohm ; DP13 -> 80% of 10k = 8 kohm

    Fractions are clamped to 0.0..1.0. A value of NULL_RESISTANCE (-1) leaves
    that pot unchanged.
    """

    for key, frac in pots.items():
        if not key.startswith("dp"):
            raise ValueError(f"Unexpected argument '{key}'; expected dp0..dp13.")

        pot_num = int(key[2:])
        if pot_num not in DIGITAL_POTS:
            raise ValueError(f"DP{pot_num} is not a valid pot (0-13).")

        if frac == NULL_RESISTANCE:
            continue

        frac = max(0.0, min(1.0, frac))
        resistance = frac * DIGITAL_POTS[pot_num]["max_resistance"]
        set_digital_pot(pot_num, resistance)

def set_cap_bank(bank, sw0, sw1, sw2):
    """
    Selects a cap bank and sets its three switches.

    INPUTS
        bank: 2 -> Wein cap bank (real values from schematic)
              1 -> main cap bank
        sw0, sw1, sw2: switch states (True = High = B2, False = Low = B1)

    Returns the total (parallel) capacitance in Farads.

    Switch -> GP pin mapping (new board):
        SW0 = GPO_1
        SW1 = GPO_0
        SW2 = GPO_2
    LDO_enb is on GPO_3 and is NOT touched here -- control it via
    set_ldo_enable() / set_gp_pins(gp3=...).
    """

    if bank not in CAP_BANKS:
        raise ValueError(f"bank must be 1 or 2, got {bank}.")

    caps = CAP_BANKS[bank]

    # High (True) -> B2 cap, Low (False) -> B1 cap
    c0 = caps[0]["high"] if sw0 else caps[0]["low"]
    c1 = caps[1]["high"] if sw1 else caps[1]["low"]
    c2 = caps[2]["high"] if sw2 else caps[2]["low"]

    parallel_bank_cap = c0 + c1 + c2

    print(f"Cap bank {bank}: SW0={c0:.3e} F, SW1={c1:.3e} F, SW2={c2:.3e} F "
          f"-> parallel total = {parallel_bank_cap:.3e} F")

    # ---- Pin control ----
    # SW0 -> GPO_1, SW1 -> GPO_0, SW2 -> GPO_2
    set_gp_pins(gp0=sw1, gp1=sw0, gp2=sw2)

    return parallel_bank_cap

def step_digital_pots(duration, steps, pot_code):
    step_duration = duration / steps
    max_resistance = DIGITAL_POTS[pot_code]["max_resistance"]

    for step in range(steps):
        current_resistance = (max_resistance / steps) * step
        set_digital_pots(**{f"dp{pot_code}": current_resistance})
        time.sleep(step_duration)

def step_up_digital_pots_bounded(duration, steps, pot_code, start, end):
    step_duration = duration / steps

    for step in range(steps):
        current_resistance_offset = ((end - start) / steps) * step
        current_resistance = start + current_resistance_offset
        set_digital_pots(**{f"dp{pot_code}": current_resistance})
        time.sleep(step_duration)

def step_down_digital_pots_bounded(duration, steps, pot_code, end, start):
    step_duration = duration / steps

    for step in reversed(range(steps)):
        current_resistance_offset = ((start - end) / steps) * step
        current_resistance = end + current_resistance_offset
        set_digital_pots(**{f"dp{pot_code}": current_resistance})
        time.sleep(step_duration)

# ------------------------------------------------------------------------
#                          POT / SWITCH ROLES
# ------------------------------------------------------------------------
# Triangle / Square oscillator
TRI_SQ_FREQ_POTS     = [8]        # frequency
TRI_SQ_AMP_POTS      = [4, 5]     # amplitude
TRI_SQ_BIAS_POT      = 6          # bias
TRI_SQ_OVERSHOOT_POT = 7          # overshoot
TRI_SQ_CAP_BANK      = 1          # cap bank feeding this oscillator

# Wein (sine) oscillator
WEIN_FREQ_POTS = [11, 12, 13]     # frequency
WEIN_AMP_POTS  = [9, 10]          # amplitude
WEIN_CAP_BANK  = 2                # Wein cap bank

# ------------------------------------------------------------------------
#                          FREQUENCY SWEEP
# ------------------------------------------------------------------------
def _bands_by_cap(bank):
    """The 8 switch combos of `bank`, ordered largest C (lowest freq) first."""
    caps = CAP_BANKS[bank]
    combos = []
    for sw0 in (False, True):
        for sw1 in (False, True):
            for sw2 in (False, True):
                c = ((caps[0]["high"] if sw0 else caps[0]["low"]) +
                     (caps[1]["high"] if sw1 else caps[1]["low"]) +
                     (caps[2]["high"] if sw2 else caps[2]["low"]))
                combos.append(((sw0, sw1, sw2), c))
    combos.sort(key=lambda x: x[1], reverse=True)   # big C first -> low f first
    return [sw for sw, c in combos]

def sweep_frequency(freq_pots, cap_bank, steps_per_band, dwell_s):
    """
    Frequency sweep for the Rigol scan. For each cap band, step the frequency
    pot(s) from 0 -> full scale (by fraction, so 100k and 10k pots move
    together), pausing dwell_s at each step so the scan can record Vpp.
    Covers all 8 bands of the given cap bank.

    INPUTS
        freq_pots:      list of DP#s that set frequency (stepped together)
        cap_bank:       which cap bank provides the frequency bands (1 or 2)
        steps_per_band: pot steps within each band
        dwell_s:        seconds to hold at each step
    """
    for sw in _bands_by_cap(cap_bank):
        set_cap_bank(cap_bank, *sw)
        for step in range(steps_per_band):
            frac = step / (steps_per_band - 1) if steps_per_band > 1 else 0.0
            set_digital_pots_frac(**{f"dp{p}": frac for p in freq_pots})
            time.sleep(dwell_s)

def sweep_sine(steps_per_band=20, dwell_s=0.2):
    """Sweep the Wein/sine output across all bands of the Wein cap bank."""
    sweep_frequency(WEIN_FREQ_POTS, WEIN_CAP_BANK, steps_per_band, dwell_s)

def sweep_tri_sq(steps_per_band=20, dwell_s=0.2):
    """Sweep the triangle/square output across all bands of its cap bank."""
    sweep_frequency(TRI_SQ_FREQ_POTS, TRI_SQ_CAP_BANK, steps_per_band, dwell_s)

# ------------------------------------------------------------------------
#                  TRIANGLE vs SQUARE SELECT (SW_AMP1 / SW_AMP2)
# ------------------------------------------------------------------------
def set_amp_switches(triangle):
    """
    Select triangle vs square using SW_AMP1 and SW_AMP2.
        triangle=True  -> triangle
        triangle=False -> square

    TODO (not sure of these yet): fill in the two switch states for each case,
    and how SW_AMP1 / SW_AMP2 are actually driven -- e.g. set_gp_pins(...) if
    they are MCP2221 GP pins, or an expander pin if they are on the MCP23017.
    """
    if triangle:
        sw_amp1 = None   # TODO
        sw_amp2 = None   # TODO
    else:
        sw_amp1 = None   # TODO
        sw_amp2 = None   # TODO

    # TODO: actually drive the switches here, e.g.:
    #   set_gp_pins(...)                # if SW_AMP1/SW_AMP2 are GP pins
    # (left blank on purpose -- fill in once you know the wiring)

    print(f"AMP switches -> SW_AMP1={sw_amp1}, SW_AMP2={sw_amp2} "
          f"({'triangle' if triangle else 'square'})")

# set_gp_pins(gp0=True, gp1=True, gp2=True)
# scan = i2c.scan()
# e.g. set_digital_pots_frac(dp13 = 0.5, dp0 = 0.1)
# e.g. sweep_tri_sq(steps_per_band=20, dwell_s=0.2)
# e.g. sweep_sine(steps_per_band=20, dwell_s=0.2)

# extra stuff w/ sweep, not totally done? not sure need to look together
