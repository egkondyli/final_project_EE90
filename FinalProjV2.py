# pip install packages as necessary
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

DP9_ADDRESS = 0b0101100
DP10_ADDRESS = 0b0101111
DP11_ADDRESS = 0b0101010
DP12_ADDRESS = 0b0101011
DP13_ADDRESS = 0b0101110


# digital potentiometer addresses
DP0_ADDRESS = DP11_ADDRESS # 11 #0b0100000
DP1_ADDRESS = DP12_ADDRESS # 12 #0b0101100
DP2_ADDRESS = DP13_ADDRESS # 13 #0b0101111

# pot instructions
UPDATE_INSTRUCTION_BYTE = b'\x10' # Used to indicate that you are writing a new value to a digital pot.
SAVE_INSTRUCTION_BYTE = b'\x80' # Used to save last loaded value as default resistance value of digital pot.
READ_INSTRUCTION_BYTE = b'\x30' # Used to read the value of the digital pot directly from the digital pot.
READ_DATA_BYTE = b'\x10' # Data that must be sent when reading the value of the digital pot

# Measured in Ohms
MAX_DIGITAL_POT_RESISTANCE = 10 * (10**3)
MAX_DIGITAL_POT_BYTE = 255

# Value input to set_gp_pins to indicate that the voltage of a given pin should
# not be modified
NULL_VOLTAGE = -1

# Value input to set_digital_pots to indicate that a given digital pot's value
# should not be modified
NULL_RESISTANCE = -1

# Cap bank values
C35 = 1 * (10**-6)
C37 = 3.3 * (10**-9)
C38 = 100 * (10**-9)
C39 = 2 * (10**-9)

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

# Use G0-G3 pins on MCP2221 to set GPO pins on Lab 3 board
g0 = digitalio.DigitalInOut(board.G0)
g1 = digitalio.DigitalInOut(board.G1)
g2 = digitalio.DigitalInOut(board.G2)
g3 = digitalio.DigitalInOut(board.G3)

def set_gp_pins(gp0=NULL_VOLTAGE, gp1=NULL_VOLTAGE, gp2=NULL_VOLTAGE, gp3=NULL_VOLTAGE):
    """
    Sets voltage of GP pins on MCP2221. A passed value of True will set the
    corresponding pin high, and a passed value of False will set the
    corresponding pin low. All arguments are optional.

    INPUTS
        gp0: sets GP0 on EE 90 Shield (i.e. the LDO enable pin on the lab 3 board)
        gp1: sets GP1 on EE 90 Shield
        gp2: sets GP2 on EE 90 Shield
        gp3: sets GP3 on EE 90 Shield
    """

    if (gp2 != NULL_VOLTAGE):
        g0.direction = digitalio.Direction.OUTPUT
        g0.value = gp2 # board.G0 sets GP2 on EE 90 Shield (i.e. the LDO enable pin on the lab 3 board)
    if (gp3 != NULL_VOLTAGE):
        g1.direction = digitalio.Direction.OUTPUT
        g1.value = gp3 # board.G1 sets GP3 on EE 90 Shield
    if (gp0 != NULL_VOLTAGE):
        g2.direction = digitalio.Direction.OUTPUT
        g2.value = gp0 # board.G2 sets GP0 on EE 90 Shield (i.e. cap bank SW_0 on the lab 3 board)
    if (gp1 != NULL_VOLTAGE):
        g3.direction = digitalio.Direction.OUTPUT
        g3.value = gp1 # board.G3 sets GP1 on EE 90 Shield (i.e. cap bank SW_1 on the lab 3 board)

def resistance_to_byte(r):
    fraction = r / MAX_DIGITAL_POT_RESISTANCE

    r_byte = math.floor(fraction * MAX_DIGITAL_POT_BYTE)

    return int(r_byte)

def resistance_to_byte_max(r, max_r):
    fraction = r / max_r

    r_byte = math.floor(fraction * MAX_DIGITAL_POT_BYTE)

    return int(r_byte)

def byte_to_resistance(byte):
    fraction = byte[0] / MAX_DIGITAL_POT_BYTE #int.from_bytes(byte[0], 'big')

    r = math.floor(fraction * MAX_DIGITAL_POT_RESISTANCE)

    return r

def byte_to_resistance_max(byte, max_r):
    fraction = byte[0] / MAX_DIGITAL_POT_BYTE #int.from_bytes(byte[0], 'big')

    r = math.floor(fraction * max_r)

    return r

def set_digital_pot(dp_resistance, pot_address):
    """
    Sets the value of a single digital potentiometer
    """

    # Compute value for setting potentiometer
    r_byte = resistance_to_byte(dp_resistance).to_bytes(1,'big')
    data_byte = UPDATE_INSTRUCTION_BYTE + r_byte

    # Set the potentiometer value
    i2c.writeto(pot_address, bytearray(data_byte)) # load new resistance value for pot
    i2c.writeto(pot_address, bytearray(SAVE_INSTRUCTION_BYTE + r_byte)) # save value as default resistance for pot

    # Print out potentiometer value to ensure correct value was set
    returned_byte = r_byte #bytearray(2) # Potentiometer value is stored into this variable
    #i2c.writeto_then_readfrom(pot_address, READ_INSTRUCTION_BYTE + READ_DATA_BYTE, returned_byte) # read back resistance value as a byte
    print("Resistance: ", byte_to_resistance(returned_byte), " Ohms; ", data_byte.hex()) # print out resistance value

def set_digital_pot_max(dp_fraction, max_dp_resistance, pot_address):
    """
    Sets the value of a single digital potentiometer
    """

    # Compute value for setting potentiometer
    r_byte = resistance_to_byte_max(max_dp_resistance * dp_fraction, max_dp_resistance).to_bytes(1,'big')
    data_byte = UPDATE_INSTRUCTION_BYTE + r_byte

    # Set the potentiometer value
    i2c.writeto(pot_address, bytearray(data_byte)) # load new resistance value for pot
    i2c.writeto(pot_address, bytearray(SAVE_INSTRUCTION_BYTE + r_byte)) # save value as default resistance for pot

    # Print out potentiometer value to ensure correct value was set
    returned_byte = r_byte #bytearray(2) # Potentiometer value is stored into this variable
    #i2c.writeto_then_readfrom(pot_address, READ_INSTRUCTION_BYTE + READ_DATA_BYTE, returned_byte) # read back resistance value as a byte
    print("Resistance: ", byte_to_resistance_max(returned_byte, max_dp_resistance), " Ohms; ", data_byte.hex()) # print out resistance value

def set_digital_pot_with_bytes()

def set_digital_pots(dp0=NULL_RESISTANCE, dp1=NULL_RESISTANCE, dp2=NULL_RESISTANCE):
    """
    Sets multiple digital pot resistances.

    INPUTS
        dp0 = resistance value for digital pot 0
        dp1 = resistance value for digital pot 1
        dp2 = resistance value for digital pot 2
    """

    # Data bytes format: b'\x10\x##'
    #                    where ## is the hex value that you want to use to set the given pot.
    

    if (dp0 != NULL_RESISTANCE):
        set_digital_pot(dp0, DP0_ADDRESS)
    if (dp1 != NULL_RESISTANCE):
        set_digital_pot(dp1, DP1_ADDRESS)
    if (dp2 != NULL_RESISTANCE):
        set_digital_pot(dp2, DP2_ADDRESS)

def set_cap_bank(sw0, sw1):
    if (sw1==False):
        sw1_cap = C37 # L input sets B1 as output
    else:
        sw1_cap = C35

    if (sw0==False):
        sw0_cap = C39 # L input sets B1 as output
    else:
        sw0_cap = C38

    parallel_bank_cap = sw1_cap + sw0_cap

    print("Triangle/Square Oscillator Capacitance", parallel_bank_cap)

    set_gp_pins(gp0=sw0, gp1=sw1)

def step_digital_pots_max(duration, steps, pot_code, max_r):
    step_duration = MAX_DIGITAL_POT_BYTE

    for step in range(steps):
        current_resistance = (max_r / steps) * step
        
        if (pot_code==0):
            set_digital_pots(dp0=current_resistance)
        elif (pot_code==1):
            set_digital_pots(dp1=current_resistance)
        elif (pot_code==2):
            set_digital_pots(dp2=current_resistance)

        time.sleep(step_duration)

def step_digital_pots(duration, steps, pot_code):
    step_duration = duration / steps

    for step in range(steps):
        current_resistance = (MAX_DIGITAL_POT_RESISTANCE / steps) * step
        
        if (pot_code==0):
            set_digital_pots(dp0=current_resistance)
        elif (pot_code==1):
            set_digital_pots(dp1=current_resistance)
        elif (pot_code==2):
            set_digital_pots(dp2=current_resistance)

        time.sleep(step_duration)

def step_up_digital_pots_bounded(duration, steps, pot_code, start, end):
    step_duration = duration / steps

    for step in range(steps):
        current_resistance_offset = ((end - start) / steps) * step
        current_resistance = start + current_resistance_offset
        
        if (pot_code==0):
            set_digital_pots(dp0=current_resistance)
        elif (pot_code==1):
            set_digital_pots(dp1=current_resistance)
        elif (pot_code==2):
            set_digital_pots(dp2=current_resistance)

        time.sleep(step_duration)


def step_down_digital_pots_bounded(duration, steps, pot_code, end, start):
    step_duration = duration / steps

    for step in reversed(range(steps)):
        current_resistance_offset = ((start - end) / steps) * step
        current_resistance = end + current_resistance_offset
        
        if (pot_code==0):
            set_digital_pots(dp0=current_resistance)
        elif (pot_code==1):
            set_digital_pots(dp1=current_resistance)
        elif (pot_code==2):
            set_digital_pots(dp2=current_resistance)

        time.sleep(step_duration)

# ------------------------------------------------------------------------
#                          C.2 DIGITAL CONTROL
# ------------------------------------------------------------------------

# Step 3: arguments gp0, gp1, and gp2 were all set to True first, the script was executed,
#         and finally the output voltage at each pin was measured on the board via header P2.
# Step 4: arguments gp0, gp1, and gp2 were then each set to False in isolation while leaving
#         the other two True. Each time, the voltages at each pin were measured.
#set_gp_pins(gp0=True, gp1=True, gp2=True)

# Step 7
# Uncomment the bottom two lines to scan for devices
#scan = i2c.scan()
#print(scan)

# Step 8
# All wipers set to midscale for initial testing.
# Uncomment the line below to set wipers to midscale.
#set_digital_pots(dp0=5000, dp1=5000, dp2=5000)

# ------------------------------------------------------------------------
#                          D.1 SINE WAVE
# ------------------------------------------------------------------------

# Steps 1 through 5
# Uncomment the line below to scan through different potentiometer values.
#step_digital_pots(50, MAX_DIGITAL_POT_BYTE, 0)

# Step 7
# Uncomment the line below to set the potentiometer U2 at the
# value where the output sine wave stops railing.
#set_digital_pots(dp0=3154) # minimum pot resistance without railing
#set_digital_pots(dp0=9524) # maxmimum pot resistance before oscillations stop

# Step 8
# Uncomment the first line below to scan from the smallest pot resistance where
# the output signal is railing to the point where it starts to oscillate from a cold start.
# Uncomment the second line below to scan from the largest pot resistance where
# the output signal is railing to the point where it start to oscillate from a cold start.
#step_up_digital_pots_bounded(50, MAX_DIGITAL_POT_BYTE, 0, 0, 9254) # 9254 ohms is maximum pot resistance with oscillations
#step_down_digital_pots_bounded(20, 20, 0, 9254, 10000) 

# ------------------------------------------------------------------------
#                          D.2 SQUARE/TRIANGLE WAVE
# ------------------------------------------------------------------------

# Step 1
# Uncomment first line to set U3 to minimum value
#set_digital_pots(dp1=0) # minimum pot resistance





# --- Bank 2 = "Wein capacitor bank" (values read from schematic), Farads ---
C58 = 1.4 * (10**-6)   # U31 B2
C59 = 200 * (10**-9)   # U31 B1
C60 = 0   # U32 B2
C61 = 25 * (10**-9)    # U32 B1
C62 = 4 * (10**-9)     # U33 B2
C63 = 0.5 * (10**-9)   # U33 B1

# --- Bank 1 = triangle/square cap bank, Farads ---
C34 = 1.4 * (10**-6)   # U31 B2
C35 = 200 * (10**-9)   # U31 B1
C37 = 0   # U32 B2
C38 = 25 * (10**-9)    # U32 B1
C40 = 4 * (10**-9)     # U33 B2
C41 = 0.5 * (10**-9)   # U33 B1

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

set_cap_bank(1,sw0=True, sw1=True, sw2=True)
set_cap_bank(2,sw0=True, sw1=True, sw2=True)

pin = mcp23017.get_pin(12)
pin.switch_to_output(value=True)

# High DP11/12/13 => Higher frequency
# Lower DP9/DP10 => diminished MHz parasitic frequencies
set_digital_pot_max(0.001,10000,DP9_ADDRESS) 
time.sleep(.1)
set_digital_pot_max(0.001,10000,DP10_ADDRESS) 
time.sleep(.1)
set_digital_pot_max(0.005,100000,DP11_ADDRESS)
time.sleep(.1)
set_digital_pot_max(0.005,100000,DP12_ADDRESS)
time.sleep(.1)
set_digital_pot_max(0.01,10000,DP13_ADDRESS)








# Step 2-5
# Uncomment the first line below to select a capacitance.
# Uncomment the second line below to loop through different
# values for potentiometer U13.
#set_cap_bank(True,True) # (True, True) corresponds to 570 nF
#step_digital_pots(30, MAX_DIGITAL_POT_BYTE, 2) # Scroll through DP2 resistance

# Step 6-7
# Uncomment the first line below to select a different capacitance
# - Change argument 1 of set_cap_bank to choose the value of SW_0
# - Change argument 2 of set_cap_bank to choose the value of SW_1
# Uncomment the second line below to set the value of U13
# Uncomment the third line below and comment out the fourth line
# below if U3 is to be set to its minimum resistance value.
# Uncomment the fourth line below and comment out the third line 
# below if U3 is to be set to its maximum resistance value.
#set_cap_bank(False, True) # Set capacitor bank switches
#set_digital_pots(dp2=7777) # Set U13 digital pot
#set_digital_pots(dp1=0) # minimum pot resistance, U3
#set_digital_pots(dp1=10000) # maximum pot resistance, U3