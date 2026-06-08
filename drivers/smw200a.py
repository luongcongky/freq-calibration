"""
Driver for R&S SMW200A Vector Signal Generator
Controlled via GPIB over VISA (local or remote via Tailscale/VPN)

Usage:
    from drivers.smw200a import SMW200A

    with SMW200A("GPIB0::28::INSTR") as gen:
        gen.set_frequency(1e9)
        gen.set_power(-10)
        gen.rf_on()
        print(gen.get_frequency())
        gen.rf_off()
"""

import time
import logging
from typing import Optional

import pyvisa

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class SMW200AError(Exception):
    """Base exception for SMW200A driver."""


class SMW200AConnectionError(SMW200AError):
    """Raised when connection to instrument fails."""


class SMW200ACommandError(SMW200AError):
    """Raised when an instrument command returns an error."""


class SMW200AValueError(SMW200AError):
    """Raised when a parameter value is out of the allowed range."""


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FREQ_MIN_HZ     = 100e3        # 100 kHz
FREQ_MAX_HZ     = 20e9         # 20 GHz (model-dependent)
POWER_MIN_DBM   = -130.0
POWER_MAX_DBM   = 30.0
DEFAULT_TIMEOUT = 10_000       # ms


# ---------------------------------------------------------------------------
# Driver class
# ---------------------------------------------------------------------------

class SMW200A:
    """
    Driver for R&S SMW200A Vector Signal Generator.

    Supports:
      - Single-tone CW signal generation
      - Frequency / power control (RF1 and RF2)
      - Modulation enable/disable (AM, FM, PM, IQ)
      - Reference clock management
      - Error queue reading
      - Context-manager (with statement) for safe resource release
    """

    def __init__(
        self,
        resource_address: str,
        timeout_ms: int = DEFAULT_TIMEOUT,
        reset_on_connect: bool = False,
        visa_backend: str = "",
        mock: bool = False,
    ):
        """
        Parameters
        ----------
        resource_address : str
            VISA resource string. Examples:
              "GPIB0::28::INSTR"                      (local GPIB)
              "TCPIP0::100.64.0.3::gpib0,28::INSTR"   (VXI-11 over Tailscale)
              "TCPIP0::192.168.1.10::5025::SOCKET"     (raw socket / LAN)
        timeout_ms : int
            VISA I/O timeout in milliseconds.
        reset_on_connect : bool
            If True, send *RST at startup (instrument returns to defaults).
        visa_backend : str
            Override pyvisa backend, e.g. "@sim" for simulation.
        """
        self._address = resource_address
        self._timeout_ms = timeout_ms
        self._reset_on_connect = reset_on_connect
        self._visa_backend = visa_backend
        self._mock = mock
        self._mock_freq = 1e9
        self._mock_pwr = -10.0
        self._mock_rf = "0"

        self._rm: Optional[pyvisa.ResourceManager] = None
        self._inst: Optional[pyvisa.resources.Resource] = None

        self.connect()

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Open VISA connection unless in mock mode."""
        if self._mock:
            logger.info("SMW200A initialized in MOCK mode (no VISA connection).")
            return

        try:
            self._rm = (
                pyvisa.ResourceManager(self._visa_backend)
                if self._visa_backend
                else pyvisa.ResourceManager()
            )
            self._inst = self._rm.open_resource(self._address)
            self._inst.timeout = self._timeout_ms
            self._inst.read_termination  = "\n"
            self._inst.write_termination = "\n"

            idn = self.identify()
            if "SMW200" not in idn:
                logger.warning(
                    "IDN does not confirm SMW200A. Got: %s", idn
                )
            else:
                logger.info("Connected to: %s", idn.strip())

            if self._reset_on_connect:
                self.reset()

        except pyvisa.VisaIOError as exc:
            raise SMW200AConnectionError(
                f"Cannot connect to SMW200A at '{self._address}': {exc}"
            ) from exc

    def disconnect(self) -> None:
        """Close the VISA session cleanly."""
        if self._inst:
            try:
                self._inst.close()
            except Exception:  # noqa: BLE001
                pass
            self._inst = None
        if self._rm:
            try:
                self._rm.close()
            except Exception:  # noqa: BLE001
                pass
            self._rm = None
        logger.info("SMW200A disconnected.")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.disconnect()

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    def _write(self, cmd: str) -> None:
        """Send a command and check for SCPI errors (skipped if mock)."""
        logger.debug("WRITE >> %s", cmd)
        if self._mock:
            parts = cmd.split()
            if len(parts) >= 2:
                val_str = parts[-2] if parts[-1].isalpha() else parts[-1]
                try:
                    val = float(val_str)
                    if "FREQ:CW" in cmd: self._mock_freq = val
                    if "POW:POW" in cmd: self._mock_pwr = val
                except: pass
            if "OUTP:STAT ON" in cmd: self._mock_rf = "1"
            if "OUTP:STAT OFF" in cmd: self._mock_rf = "0"
            return
        self._inst.write(cmd)
        self._check_errors(context=cmd)

    def _query(self, cmd: str) -> str:
        """Send a query and return stripped response (returns dummy if mock)."""
        logger.debug("QUERY >> %s", cmd)
        if self._mock:
            if "*IDN?" in cmd: return "Rohde&Schwarz,SMW200A,MOCK,v4.0"
            if "OUTP:STAT?" in cmd: return self._mock_rf
            if "FREQ:CW?" in cmd: return str(self._mock_freq)
            if "POW:POW?" in cmd: return str(self._mock_pwr)
            return "0"
        response = self._inst.query(cmd).strip()
        logger.debug("RESP  << %s", response)
        return response

    def _check_errors(self, context: str = "") -> None:
        """
        Read the instrument error queue until empty.
        Raises SMW200ACommandError if any error is found.
        """
        errors = []
        for _ in range(20):                        # safety limit
            err = self._inst.query("SYST:ERR?").strip()
            if err.startswith("0"):                # "0, No Error"
                break
            errors.append(err)
        if errors:
            raise SMW200ACommandError(
                f"Instrument error after '{context}': {'; '.join(errors)}"
            )

    # ------------------------------------------------------------------
    # Identification & housekeeping
    # ------------------------------------------------------------------

    def identify(self) -> str:
        """Return the *IDN? string."""
        return self._query("*IDN?")

    def reset(self) -> None:
        """Send *RST and wait for operation complete."""
        self._inst.write("*RST")
        self._inst.write("*WAI")
        time.sleep(2.0)
        logger.info("SMW200A reset complete.")

    def clear_status(self) -> None:
        """Send *CLS to clear status registers and error queue."""
        self._inst.write("*CLS")

    def wait_for_completion(self, timeout_s: float = 30.0) -> None:
        """
        Block until all pending operations finish (*OPC? polling).
        """
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self._query("*OPC?") == "1":
                return
            time.sleep(0.1)
        raise SMW200AError("Timeout waiting for operation complete.")

    # ------------------------------------------------------------------
    # Frequency control
    # ------------------------------------------------------------------

    def set_frequency(self, freq_hz: float, channel: int = 1) -> None:
        """
        Set the CW output frequency.

        Parameters
        ----------
        freq_hz : float
            Frequency in Hz (100 kHz – 20 GHz).
        channel : int
            RF channel: 1 or 2.
        """
        if not (FREQ_MIN_HZ <= freq_hz <= FREQ_MAX_HZ):
            raise SMW200AValueError(
                f"Frequency {freq_hz/1e6:.6f} MHz out of range "
                f"[{FREQ_MIN_HZ/1e6:.3f} – {FREQ_MAX_HZ/1e9:.0f} GHz]"
            )
        self._write(f"SOUR{channel}:FREQ:CW {freq_hz:.6f} HZ")
        logger.info("CH%d frequency set to %.6f MHz", channel, freq_hz / 1e6)

    def get_frequency(self, channel: int = 1) -> float:
        """Return the current CW frequency in Hz."""
        return float(self._query(f"SOUR{channel}:FREQ:CW?"))

    def set_frequency_offset(self, offset_hz: float, channel: int = 1) -> None:
        """Set a frequency offset (useful for up/down-converter compensation)."""
        self._write(f"SOUR{channel}:FREQ:OFFS {offset_hz:.3f} HZ")

    # ------------------------------------------------------------------
    # Power / amplitude control
    # ------------------------------------------------------------------

    def set_power(self, power_dbm: float, channel: int = 1) -> None:
        """
        Set the output power level.

        Parameters
        ----------
        power_dbm : float
            Power in dBm.
        channel : int
            RF channel: 1 or 2.
        """
        if not (POWER_MIN_DBM <= power_dbm <= POWER_MAX_DBM):
            raise SMW200AValueError(
                f"Power {power_dbm:.2f} dBm out of range "
                f"[{POWER_MIN_DBM} – {POWER_MAX_DBM}]"
            )
        self._write(f"SOUR{channel}:POW:POW {power_dbm:.3f} dBm")
        logger.info("CH%d power set to %.3f dBm", channel, power_dbm)

    def get_power(self, channel: int = 1) -> float:
        """Return the current output power in dBm."""
        return float(self._query(f"SOUR{channel}:POW:POW?"))

    def set_power_offset(self, offset_db: float, channel: int = 1) -> None:
        """Set a power offset (cable loss / attenuator compensation)."""
        self._write(f"SOUR{channel}:POW:OFFS {offset_db:.3f}")

    # ------------------------------------------------------------------
    # RF output enable / disable
    # ------------------------------------------------------------------

    def rf_on(self, channel: int = 1) -> None:
        """Enable RF output on the given channel."""
        self._write(f"OUTP{channel}:STAT ON")
        logger.info("CH%d RF output ON", channel)

    def rf_off(self, channel: int = 1) -> None:
        """Disable RF output on the given channel."""
        self._write(f"OUTP{channel}:STAT OFF")
        logger.info("CH%d RF output OFF", channel)

    def is_rf_on(self, channel: int = 1) -> bool:
        """Return True if RF output is currently enabled."""
        return self._query(f"OUTP{channel}:STAT?") in ("1", "ON")

    # ------------------------------------------------------------------
    # Reference clock
    # ------------------------------------------------------------------

    def set_reference_internal(self) -> None:
        """Use the internal 10 MHz reference oscillator."""
        self._write("ROSC:SOUR INT")

    def set_reference_external(self, freq_hz: float = 10e6) -> None:
        """
        Lock to an external reference.

        Parameters
        ----------
        freq_hz : float
            External reference frequency (e.g. 10e6 for 10 MHz).
        """
        self._write("ROSC:SOUR EXT")
        self._write(f"ROSC:EXT:FREQ {freq_hz:.0f} HZ")

    def get_reference_source(self) -> str:
        """Return 'INT' or 'EXT'."""
        return self._query("ROSC:SOUR?")

    # ------------------------------------------------------------------
    # Modulation
    # ------------------------------------------------------------------

    def enable_modulation(self, mod_type: str = "AM", channel: int = 1) -> None:
        """
        Enable a modulation type.

        Parameters
        ----------
        mod_type : str
            One of: 'AM', 'FM', 'PM', 'IQ'.
        """
        mod_type = mod_type.upper()
        if mod_type not in ("AM", "FM", "PM", "IQ"):
            raise SMW200AValueError(f"Unsupported modulation type: {mod_type}")
        self._write(f"SOUR{channel}:{mod_type}:STAT ON")
        logger.info("CH%d %s modulation enabled", channel, mod_type)

    def disable_modulation(self, mod_type: str = "AM", channel: int = 1) -> None:
        """Disable a modulation type."""
        mod_type = mod_type.upper()
        self._write(f"SOUR{channel}:{mod_type}:STAT OFF")

    def disable_all_modulation(self, channel: int = 1) -> None:
        """Disable all modulation types at once."""
        for mod in ("AM", "FM", "PM", "IQ"):
            try:
                self._write(f"SOUR{channel}:{mod}:STAT OFF")
            except SMW200ACommandError:
                pass

    # ------------------------------------------------------------------
    # Level sweep (frequency / power sweep)
    # ------------------------------------------------------------------

    def configure_freq_sweep(
        self,
        start_hz: float,
        stop_hz: float,
        step_hz: float,
        dwell_s: float = 0.01,
        channel: int = 1,
    ) -> None:
        """
        Configure a stepped frequency sweep (not triggered, manual step).
        """
        self._write(f"SOUR{channel}:FREQ:STAR {start_hz:.3f} HZ")
        self._write(f"SOUR{channel}:FREQ:STOP {stop_hz:.3f} HZ")
        self._write(f"SOUR{channel}:SWE:FREQ:STEP:LIN {step_hz:.3f} HZ")
        self._write(f"SOUR{channel}:SWE:FREQ:DWEL {dwell_s:.6f} S")
        self._write(f"SOUR{channel}:FREQ:MODE SWE")
        self._write(f"SOUR{channel}:SWE:FREQ:MODE STEP")
        logger.info(
            "CH%d freq sweep configured: %.3f MHz → %.3f MHz, step %.3f kHz",
            channel, start_hz/1e6, stop_hz/1e6, step_hz/1e3,
        )

    def sweep_step(self, channel: int = 1) -> None:
        """Advance the sweep by one step (manual trigger)."""
        self._write(f"SOUR{channel}:SWE:FREQ:EXEC")

    def abort_sweep(self, channel: int = 1) -> None:
        """Abort the sweep and return to CW mode."""
        self._write(f"SOUR{channel}:FREQ:MODE CW")

    # ------------------------------------------------------------------
    # Status / diagnostics
    # ------------------------------------------------------------------

    def get_all_errors(self) -> list[str]:
        """Drain and return the full error queue."""
        errors = []
        for _ in range(50):
            err = self._query("SYST:ERR?").strip()
            if err.startswith("0"):
                break
            errors.append(err)
        return errors

    def get_status(self, channel: int = 1) -> dict:
        """
        Return a snapshot of the current instrument state.

        Returns
        -------
        dict with keys: idn, frequency_hz, power_dbm, rf_on, ref_source
        """
        return {
            "idn":          self.identify(),
            "frequency_hz": self.get_frequency(channel),
            "power_dbm":    self.get_power(channel),
            "rf_on":        self.is_rf_on(channel),
            "ref_source":   self.get_reference_source(),
        }

    def __repr__(self) -> str:
        return f"SMW200A(address='{self._address}')"