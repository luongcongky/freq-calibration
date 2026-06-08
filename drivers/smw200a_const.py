"""
SCPI Command Constants for R&S SMW200A Vector Signal Generator

This file stores the official SCPI command system for SMW200A signal generator
for persistent storage and future code generation.
"""

# Common IEEE 488.2 Commands
COMMON_COMMANDS = {
    "CLEAR_STATUS": "*CLS",
    "EVENT_STATUS_ENABLE": "*ESE",
    "EVENT_STATUS_READ": "*ESR?",
    "IDENTIFY": "*IDN?",
    "OPERATION_COMPLETE": "*OPC",
    "OPERATION_COMPLETE_QUERY": "*OPC?",
    "OPTIONS_QUERY": "*OPT?",
    "RESET": "*RST",
    "SAVE": "*SAV",
    "RECALL": "*RCL",
    "STATUS_BYTE_QUERY": "*STB?",
    "TRIGGER": "*TRG",
    "SELF_TEST": "*TST?",
    "WAIT": "*WAI",
}

# MMEMory Subsystem (File Management)
MMEM_SYSTEM = {
    "CATALOG": "MMEM:CAT?",
    "CDIR": "MMEM:CDIR",
    "COPY": "MMEM:COPY",
    "DATA": "MMEM:DATA",
    "DELETE": "MMEM:DEL",
    "MDIR": "MMEM:MDIR",
    "MOVE": "MMEM:MOVE",
    "STORE_STATE": "MMEM:STOR:STAT",
    "LOAD_STATE": "MMEM:LOAD:STAT",
}

# SCONfiguration Subsystem (System Configuration)
SCONFIG_SYSTEM = {
    "MODE": "SCON:MODE",
    "FADING_MODE": "SCON:FAD",
    "APPLY": "SCON:APPL",
    "OUTPUT_MAPPING": "SCON:OUTP:MAPP:RF{ch}:STR{st}:STAT",
    "REMOTE_SCAN": "SCON:EXT:REM:SCAN",
    "REMOTE_ADD": "SCON:EXT:REM:ADD",
}

# SOURce Subsystem (Signal Generation)
SOURCE_SYSTEM = {
    "FREQUENCY": "SOUR{hw}:FREQ",
    "POWER": "SOUR{hw}:POW",
    "LTE_STATE": "SOUR{hw}:BB:EUTR:STAT",
    "ARB_WAVEFORM": "SOUR{hw}:BB:ARB:WAV:SEL",
    "IQ_STATE": "SOUR{hw}:IQ:STAT",
}

# OUTPut Subsystem (Output Routing)
OUTPUT_SYSTEM = {
    "STATE": "OUTP{hw}",
    "ALL_STATE": "OUTP:ALL",
    "PROTECTION_CLEAR": "OUTP{hw}:PROT:CLE",
}

# HUMS & DIAGnostic (Monitoring/Diagnostics)
DIAG_SYSTEM = {
    "HUMS_STATE": "DIAG:HUMS:STAT",
    "HUMS_HISTORY": "DIAG:HUMS:DEV:HIST?",
    "OPERATING_TIME": "DIAG:INFO:OTIM?",
    "HARDWARE_INFO": "DIAG{hw}:BGIN?",
}

# DISPlay & HCOPy (Display/Screenshot)
DISPLAY_SYSTEM = {
    "UPDATE": "DISP:UPD",
    "DIALOG_OPEN": "DISP:DIAL:OPEN",
    "SCREENSHOT": "HCOP:EXEC",
}

# Measurement Subsystem (Power Sensor)
MEAS_SYSTEM = {
    "POWER_CONT": "INIT{hw}:POW:CONT",
    "POWER_READ": "READ{ch}:POW?",
    "SENSOR_SCAN": "SLIS:SCAN:STAT",
}

# Mapping of all subsystems
SMW200A_COMMANDS = {
    "COMMON": COMMON_COMMANDS,
    "MMEM": MMEM_SYSTEM,
    "SCONFIG": SCONFIG_SYSTEM,
    "SOURCE": SOURCE_SYSTEM,
    "OUTPUT": OUTPUT_SYSTEM,
    "DIAG": DIAG_SYSTEM,
    "DISPLAY": DISPLAY_SYSTEM,
    "MEAS": MEAS_SYSTEM,
}
