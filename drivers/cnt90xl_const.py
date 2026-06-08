"""
SCPI Command Constants for Pendulum CNT-90XL 

This file stores the official SCPI command system for the CNT-90XL frequency 
counter for persistent storage and future code generation.
"""

# Measurement System Commands
MEAS_SYSTEM = {
    "MEASURE": "MEAS",
    "CONFIGURE": "CONF",
    "READ": "READ",
    "FETCH": "FETC",
}

# Measurement Function Commands
MEAS_FUNCTIONS = {
    "FREQUENCY": "FREQ",
    "PERIOD": "PER",
    "TIME_INTERVAL": "TINT",
    "PHASE": "PHAS",
    "RISE_TIME": "RTIM",
    "FALL_TIME": "FTIM",
    "POS_PWIDTH": "PWID",
    "NEG_PWIDTH": "NWID",
    "DUTY_CYCLE": "PDUT",
    "BACK_TO_BACK": "BTB",
    "TI_ERROR": "TIE",
}

# Input System Commands
INPUT_SYSTEM = {
    "INPUT": "INP",
    "ATTENUATION": "ATT",
    "COUPLING": "COUP",
    "IMPEDANCE": "IMP",
    "FILTER": "FILT",
    "LEVEL": "LEV",
}

# Trigger System Commands
TRIGGER_SYSTEM = {
    "ARM": "ARM",
    "TRIGGER": "TRIG",
    "COUNT": "COUN",
    "DELAY": "DEL",
    "SOURCE": "SOUR",
}

# Calculation System Commands
CALC_SYSTEM = {
    "CALCULATE": "CALC",
    "AVERAGE": "AVER",
    "LIMIT": "LIM",
    "MATH": "MATH",
}

# General System Commands
GENERAL_SYSTEM = {
    "SYSTEM": "SYST",
    "COMMUNICATE": "COMM",
    "ERROR": "ERR",
    "DISPLAY": "DISP",
    "FORMAT": "FORM",
}

# Mapping of all subsystems
CNT90XL_COMMANDS = {
    "MEAS_SYSTEM": MEAS_SYSTEM,
    "MEAS_FUNCTIONS": MEAS_FUNCTIONS,
    "INPUT_SYSTEM": INPUT_SYSTEM,
    "TRIGGER_SYSTEM": TRIGGER_SYSTEM,
    "CALC_SYSTEM": CALC_SYSTEM,
    "GENERAL_SYSTEM": GENERAL_SYSTEM,
}
