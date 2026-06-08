"""
unit_test/test_connectivity.py
==============================
Hardware Connectivity and Command Verification Tool.
Checks SMW200A and CNT-90XL identification and basic SCPI I/O.
"""

import sys
import argparse
import logging
import random
from pathlib import Path

# Add project root to sys.path to allow importing from drivers
sys.path.insert(0, str(Path(__file__).parent.parent))

from drivers.smw200a import SMW200A, SMW200AError
from drivers.cnt90xl import CNT90XL, CNT90XLError

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger("HardwareTest")

def test_smw200a(inst):
    """Test SMW200A Signal Generator."""
    print(f"\n[ TESTING SMW200A GENERATOR ]")
    print("-" * 40)
    try:
        idn = inst.identify()
        print(f" [+] IDN? : {idn.strip()}")
        
        test_f = random.uniform(100e6, 10e9)
        print(f" [>] Setting Frequency to {test_f/1e6:.3f} MHz...")
        inst.set_frequency(test_f)
        
        read_f = inst.get_frequency()
        print(f" [<] Readback Freq : {read_f/1e6:.3f} MHz")
        
        if abs(read_f - test_f) < 1.0:
            print(" [PASS] Generator Communication OK.")
            return True
        else:
            print(" [FAIL] Mismatch in readback.")
            return False
    except Exception as e:
        print(f" [ERROR] {e}")
        return False

def test_cnt90xl(inst):
    """Test CNT-90XL Frequency Counter."""
    print(f"\n[ TESTING CNT-90XL COUNTER ]")
    print("-" * 40)
    try:
        idn = inst.identify()
        print(f" [+] IDN? : {idn.strip()}")
        
        gate = 0.1 # 100ms for quick test
        print(f" [>] Configuring Frequency measurement (gate={gate}s)...")
        inst.configure_frequency(gate_time=gate)
        
        # If in mock mode, we manually set a 'fake input' to verify readback
        if getattr(inst, "_mock", False):
            print(" [MOCK] Injecting 1.2345 GHz fake signal into driver core...")
            inst._write("FAKE:FREQ 1234500000.0")
        
        print(" [>] Triggering Measurement...")
        res = inst.measure_frequency()
        print(f" [<] Measured : {res.value/1e9:.9f} GHz")
        
        if res.value > 0:
            print(" [PASS] Counter Communication OK.")
            return True
        else:
            print(" [FAIL] No signal measured (result = 0). Check RF cable.")
            return False
    except Exception as e:
        print(f" [ERROR] {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Instrument Connectivity Test")
    parser.add_argument("--gen_addr", default="GPIB0::28::INSTR", help="Generator VISA address")
    parser.add_argument("--cnt_addr", default="GPIB0::7::INSTR", help="Counter VISA address")
    parser.add_argument("--mock", action="store_true", help="Run with simulated drivers")
    
    args = parser.parse_args()
    
    print(f"\n" + "="*50)
    print(f" CONNECTIVITY & COMMAND VERIFICATION ")
    print(f" Mode: {'MOCK (NO HARDWARE)' if args.mock else 'REAL HARDWARE'}")
    print("="*50)
    
    results = {}
    
    # 1. SMW200A
    try:
        with SMW200A(args.gen_addr, mock=args.mock) as smw:
            results["SMW200A"] = test_smw200a(smw)
    except Exception as e:
        print(f" [FATAL] SMW200A Init Error: {e}")
        results["SMW200A"] = False
        
    # 2. CNT-90XL
    try:
        with CNT90XL(args.cnt_addr, mock=args.mock) as cnt:
            results["CNT-90XL"] = test_cnt90xl(cnt)
    except Exception as e:
        print(f" [FATAL] CNT-90XL Init Error: {e}")
        results["CNT-90XL"] = False
        
    print("\n" + "="*50)
    print(" FINAL SUMMARY ")
    print("="*50)
    all_ok = True
    for name, status in results.items():
        print(f" {name:<12}: {'[ OK ]' if status else '[ FAILED ]'}")
        if not status: all_ok = False
        
    if all_ok:
        print("\nAll tests completed successfully. Hardware is ready.")
        sys.exit(0)
    else:
        print("\nHardware verification failed. Review logs above.")
        sys.exit(1)

if __name__ == "__main__":
    main()
