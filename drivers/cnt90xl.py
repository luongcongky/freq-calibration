"""
Driver for Pendulum CNT-90XL Frequency Counter / Timer / Analyzer
Controlled via GPIB over VISA (local or remote via Tailscale/VPN)

Usage:
    from drivers.cnt90xl import CNT90XL

    with CNT90XL("GPIB0::7::INSTR") as counter:
        counter.configure_frequency(channel=1, gate_time=1.0)
        result = counter.measure_frequency()
        print(f"Frequency: {result.value:.6f} Hz  ±{result.uncertainty:.2e}")

        stats = counter.measure_statistics(n_samples=100)
        print(stats)
"""

import time
import logging
import statistics
from dataclasses import dataclass, field
from typing import Optional

import pyvisa

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class CNT90XLError(Exception):
    """Base exception for CNT-90XL driver."""


class CNT90XLConnectionError(CNT90XLError):
    """Raised when connection to instrument fails."""


class CNT90XLCommandError(CNT90XLError):
    """Raised when an instrument command returns an error."""


class CNT90XLValueError(CNT90XLError):
    """Raised when a parameter is out of the allowed range."""


class CNT90XLMeasurementError(CNT90XLError):
    """Raised when a measurement fails or times out."""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class MeasurementResult:
    """Single measurement result with metadata."""
    value: float                        # measured value in base unit (Hz, s, …)
    unit: str                           # 'Hz', 's', 'V', etc.
    timestamp: float = field(default_factory=time.time)
    gate_time_s: float = 0.0
    channel: int = 1

    def __str__(self) -> str:
        return (
            f"MeasurementResult(value={self.value:.9g} {self.unit}, "
            f"gate={self.gate_time_s:.3f}s, ch={self.channel}, "
            f"t={self.timestamp:.3f})"
        )


@dataclass
class StatisticsResult:
    """Statistical summary over N repeated measurements."""
    n_samples: int
    mean: float
    std_dev: float
    minimum: float
    maximum: float
    unit: str
    samples: list[float] = field(default_factory=list)

    @property
    def uncertainty(self) -> float:
        """Type-A standard uncertainty (standard error of the mean)."""
        if self.n_samples < 2:
            return 0.0
        return self.std_dev / (self.n_samples ** 0.5)

    @property
    def relative_std_dev(self) -> float:
        """Relative standard deviation (Allan deviation proxy)."""
        if self.mean == 0:
            return float("inf")
        return self.std_dev / abs(self.mean)

    def __str__(self) -> str:
        return (
            f"StatisticsResult(\n"
            f"  n         = {self.n_samples}\n"
            f"  mean      = {self.mean:.9g} {self.unit}\n"
            f"  std_dev   = {self.std_dev:.4e} {self.unit}\n"
            f"  rel_std   = {self.relative_std_dev:.4e}\n"
            f"  min       = {self.minimum:.9g} {self.unit}\n"
            f"  max       = {self.maximum:.9g} {self.unit}\n"
            f"  u(type-A) = {self.uncertainty:.4e} {self.unit}\n"
            f")"
        )


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Measurement functions supported by the CNT-90XL
MEAS_FUNC = {
    "FREQ":     "MEAS:FREQ?",        # Frequency
    "PERIOD":   "MEAS:PER?",         # Period
    "PWIDTH":   "MEAS:PWID?",        # Positive pulse width
    "NWIDTH":   "MEAS:NWID?",        # Negative pulse width
    "DUTY":     "MEAS:DCYC?",        # Duty cycle
    "RISE":     "MEAS:RTIM?",        # Rise time
    "FALL":     "MEAS:FTIM?",        # Fall time
    "PHASE":    "MEAS:PHAS?",        # Phase (between 2 channels)
    "TINTERVAL":"MEAS:TINT?",        # Time interval A→B
    "RATIO":    "MEAS:RAT?",         # Frequency ratio A/B
    "TOTALIZE": "MEAS:TOT?",         # Totalize / count
}

GATE_MIN_S = 1e-4      # 100 µs minimum gate time
GATE_MAX_S = 1000.0    # 1000 s maximum gate time

TRIG_MODES = ("AUTO", "LEVEL", "EXT")
CHANNELS   = (1, 2, 3)             # A, B, C (optional)

DEFAULT_TIMEOUT_MS  = 15_000
DEFAULT_GATE_TIME_S = 1.0


# ---------------------------------------------------------------------------
# Driver class
# ---------------------------------------------------------------------------

class CNT90XL:
    """
    Driver for Pendulum CNT-90XL Frequency Counter / Timer / Analyzer.

    Supports:
      - Frequency, period, pulse width, duty cycle, time interval, phase
      - Configurable gate time and trigger levels
      - Single and multi-sample measurements
      - Statistical analysis (mean, std, min, max, type-A uncertainty)
      - Auto-level trigger
      - Reference clock management
      - Error queue reading
      - Context-manager for safe resource release
    """

    def __init__(
        self,
        resource_address: str,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
        reset_on_connect: bool = False,
        visa_backend: str = "",
        mock: bool = False,
    ):
        """
        Parameters
        ----------
        resource_address : str
            VISA resource string. Examples:
              "GPIB0::7::INSTR"                      (local GPIB)
              "TCPIP0::100.64.0.3::gpib0,7::INSTR"   (VXI-11 over Tailscale)
        timeout_ms : int
            VISA I/O timeout in milliseconds. Increase for long gate times.
        reset_on_connect : bool
            If True, send *RST at startup.
        visa_backend : str
            Override pyvisa backend, e.g. "@sim" for simulation/testing.
        """
        self._address = resource_address
        self._timeout_ms = timeout_ms
        self._reset_on_connect = reset_on_connect
        self._visa_backend = visa_backend
        self._mock = mock
        self._mock_freq = 1e9  # Default fake measurement
        self._mock_gate = 1.0

        self._rm:   Optional[pyvisa.ResourceManager]  = None
        self._inst: Optional[pyvisa.resources.Resource] = None

        # Current configuration cache
        self._gate_time_s: float = DEFAULT_GATE_TIME_S
        self._channel: int = 1

        self.connect()

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Open VISA session unless in mock mode."""
        if self._mock:
            logger.info("CNT90XL initialized in MOCK mode (no VISA connection).")
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
            if "CNT-90" not in idn and "CNT90" not in idn:
                logger.warning("IDN does not confirm CNT-90XL. Got: %s", idn)
            else:
                logger.info("Connected to: %s", idn.strip())

            if self._reset_on_connect:
                self.reset()

        except pyvisa.VisaIOError as exc:
            raise CNT90XLConnectionError(
                f"Cannot connect to CNT-90XL at '{self._address}': {exc}"
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
        logger.info("CNT-90XL disconnected.")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.disconnect()

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------
    def _write(self, cmd: str) -> None:
        """Send a command (skipped if mock)."""
        logger.debug("WRITE >> %s", cmd)
        if self._mock:
            parts = cmd.split()
            if len(parts) >= 2:
                # Handle cases like "CMD 123.4" or "CMD 123.4 S"
                val_str = parts[-2] if parts[-1].isalpha() else parts[-1]
                try:
                    val = float(val_str)
                    if "GATE:TIME" in cmd: self._mock_gate = val
                    if "FAKE:FREQ" in cmd: self._mock_freq = val
                except ValueError: pass
            return
        self._inst.write(cmd)

    def _query(self, cmd: str, timeout_override_ms: Optional[int] = None) -> str:
        """Send a query and return the stripped response (returns dummy if mock)."""
        logger.debug("QUERY >> %s", cmd)
        if self._mock:
            if "*IDN?" in cmd: return "Pendulum,CNT-90XL,MOCK,v1.0"
            if "MEAS:FREQ?" in cmd or "READ:FREQ?" in cmd: 
                import random
                return str(self._mock_freq + random.gauss(0, 0.5))
            if "GATE:TIME?" in cmd: return str(self._mock_gate)
            return "0"
        
        if timeout_override_ms is not None:
            old = self._inst.timeout
            self._inst.timeout = timeout_override_ms
        try:
            response = self._inst.query(cmd).strip()
        finally:
            if timeout_override_ms is not None:
                self._inst.timeout = old
        logger.debug("RESP  << %s", response)
        return response

    def _check_errors(self) -> None:
        """Read the error queue (skipped if mock)."""
        if self._mock: return
        errors = []
        for _ in range(20):
            err = self._inst.query("SYST:ERR?").strip()
            if err.startswith("0"):
                break
            errors.append(err)
        if errors:
            raise CNT90XLCommandError(
                "Instrument error queue: " + "; ".join(errors)
            )

    def _gate_timeout_ms(self) -> int:
        """Calculate safe query timeout based on current gate time."""
        return int(self._gate_time_s * 1000) + 5_000   # gate + 5 s margin

    # ------------------------------------------------------------------
    # Identification & housekeeping
    # ------------------------------------------------------------------

    def identify(self) -> str:
        """Return the *IDN? string."""
        return self._query("*IDN?")

    def reset(self) -> None:
        """Send *RST and wait for operation complete."""
        self._write("*RST")
        self._write("*WAI")
        time.sleep(2.0)
        logger.info("CNT-90XL reset complete.")

    def clear_status(self) -> None:
        """Send *CLS to clear status registers."""
        self._inst.write("*CLS")

    def wait_for_completion(self, timeout_s: float = 60.0) -> None:
        """Block until all pending operations complete."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                if self._query("*OPC?", timeout_override_ms=2000) == "1":
                    return
            except pyvisa.VisaIOError:
                pass
            time.sleep(0.2)
        raise CNT90XLError("Timeout waiting for operation complete.")

    # ------------------------------------------------------------------
    # Input channel configuration
    # ------------------------------------------------------------------

    def configure_channel(
        self,
        channel: int = 1,
        impedance: str = "1M",
        coupling: str = "AC",
        attenuation: int = 1,
    ) -> None:
        """
        Configure input channel hardware settings.

        Parameters
        ----------
        channel : int
            Channel number (1 = A, 2 = B).
        impedance : str
            '50' for 50 Ω, '1M' for 1 MΩ.
        coupling : str
            'AC' or 'DC'.
        attenuation : int
            1 (×1) or 10 (×10 / ÷10).
        """
        if channel not in CHANNELS:
            raise CNT90XLValueError(f"Invalid channel: {channel}")
        if impedance not in ("50", "1M"):
            raise CNT90XLValueError(f"Invalid impedance: {impedance}")
        if coupling not in ("AC", "DC"):
            raise CNT90XLValueError(f"Invalid coupling: {coupling}")
        if attenuation not in (1, 10):
            raise CNT90XLValueError("Attenuation must be 1 or 10.")

        ch = channel
        self._write(f"INP{ch}:IMP {impedance}")
        self._write(f"INP{ch}:COUP {coupling}")
        self._write(f"INP{ch}:ATT {attenuation}")
        logger.info(
            "CH%d configured: %s Ω, %s coupling, ÷%d",
            channel, impedance, coupling, attenuation,
        )

    def set_trigger_level(self, level_v: float, channel: int = 1) -> None:
        """
        Set the trigger threshold voltage manually.

        Parameters
        ----------
        level_v : float
            Trigger level in Volts.
        channel : int
            Channel number.
        """
        self._write(f"INP{channel}:LEV {level_v:.4f} V")
        logger.info("CH%d trigger level set to %.4f V", channel, level_v)

    def set_trigger_auto(self, channel: int = 1) -> None:
        """Enable automatic trigger level (50% of input signal)."""
        self._write(f"INP{channel}:LEV:AUTO ON")
        logger.info("CH%d trigger level AUTO", channel)

    def set_hysteresis(self, hysteresis: str = "MED", channel: int = 1) -> None:
        """
        Set trigger hysteresis level.

        Parameters
        ----------
        hysteresis : str
            'LOW', 'MED', or 'HIGH'.
        """
        hysteresis = hysteresis.upper()
        if hysteresis not in ("LOW", "MED", "HIGH"):
            raise CNT90XLValueError(f"Invalid hysteresis: {hysteresis}")
        self._write(f"INP{channel}:HYST {hysteresis}")

    # ------------------------------------------------------------------
    # Gate time & measurement mode
    # ------------------------------------------------------------------

    def set_gate_time(self, gate_s: float) -> None:
        """
        Set the measurement gate time.

        Parameters
        ----------
        gate_s : float
            Gate time in seconds (100 µs – 1000 s).
            Longer gate = higher resolution, lower throughput.
        """
        if not (GATE_MIN_S <= gate_s <= GATE_MAX_S):
            raise CNT90XLValueError(
                f"Gate time {gate_s} s out of range "
                f"[{GATE_MIN_S*1e3:.3f} ms – {GATE_MAX_S:.0f} s]"
            )
        self._write(f"SENS:GATE:TIME {gate_s:.6f} S")
        self._gate_time_s = gate_s
        # Automatically extend VISA timeout for long gates
        if not self._mock:
            self._inst.timeout = self._gate_timeout_ms()
        logger.info("Gate time set to %.6f s (timeout %d ms if not mock)",
                    gate_s, self._gate_timeout_ms())

    def get_gate_time(self) -> float:
        """Return the currently configured gate time in seconds."""
        return float(self._query("SENS:GATE:TIME?"))

    def configure_frequency(
        self,
        channel: int = 1,
        gate_time: float = DEFAULT_GATE_TIME_S,
        auto_trigger: bool = True,
    ) -> None:
        """
        Convenience method: configure for standard frequency measurement.

        Parameters
        ----------
        channel : int
            Input channel (1 or 2).
        gate_time : float
            Gate time in seconds.
        auto_trigger : bool
            If True, set trigger level automatically.
        """
        self._channel = channel
        self._write(f"FUNC 'FREQ {channel}'")
        self.set_gate_time(gate_time)
        if auto_trigger:
            self.set_trigger_auto(channel)
        logger.info(
            "Configured for FREQ measurement on CH%d, gate=%.3f s",
            channel, gate_time,
        )

    def configure_period(self, channel: int = 1, gate_time: float = 1.0) -> None:
        """Configure for period measurement."""
        self._channel = channel
        self._write(f"FUNC 'PER {channel}'")
        self.set_gate_time(gate_time)

    def configure_time_interval(
        self, start_channel: int = 1, stop_channel: int = 2
    ) -> None:
        """Configure for time interval measurement (A → B)."""
        self._write(f"FUNC 'TINT {start_channel},{stop_channel}'")

    def configure_phase(
        self, ref_channel: int = 1, meas_channel: int = 2
    ) -> None:
        """Configure for phase measurement (degrees)."""
        self._write(f"FUNC 'PHAS {ref_channel},{meas_channel}'")

    def configure_totalize(self, channel: int = 1, duration_s: float = 1.0) -> None:
        """Configure for event counting / totalize mode."""
        self._write(f"FUNC 'TOT {channel}'")
        self.set_gate_time(duration_s)

    # ------------------------------------------------------------------
    # Single measurement
    # ------------------------------------------------------------------

    def measure_frequency(self, channel: Optional[int] = None) -> MeasurementResult:
        """
        Trigger a single frequency measurement and return the result.

        Returns
        -------
        MeasurementResult
            .value  → frequency in Hz
            .unit   → 'Hz'
        """
        ch = channel or self._channel
        timeout_ms = self._gate_timeout_ms()
        raw = self._query(f"MEAS:FREQ? (@{ch})", timeout_override_ms=timeout_ms)

        try:
            value = float(raw)
        except ValueError as exc:
            raise CNT90XLMeasurementError(
                f"Cannot parse frequency response: '{raw}'"
            ) from exc

        return MeasurementResult(
            value=value,
            unit="Hz",
            gate_time_s=self._gate_time_s,
            channel=ch,
        )

    def measure_period(self, channel: Optional[int] = None) -> MeasurementResult:
        """Trigger a single period measurement. Returns result in seconds."""
        ch = channel or self._channel
        raw = self._query(f"MEAS:PER? (@{ch})",
                          timeout_override_ms=self._gate_timeout_ms())
        return MeasurementResult(
            value=float(raw), unit="s",
            gate_time_s=self._gate_time_s, channel=ch,
        )

    def measure_pulse_width(
        self, polarity: str = "POS", channel: Optional[int] = None
    ) -> MeasurementResult:
        """
        Measure pulse width.

        Parameters
        ----------
        polarity : str
            'POS' for positive pulse, 'NEG' for negative pulse.
        """
        ch = channel or self._channel
        cmd = "MEAS:PWID?" if polarity.upper() == "POS" else "MEAS:NWID?"
        raw = self._query(f"{cmd} (@{ch})",
                          timeout_override_ms=self._gate_timeout_ms())
        return MeasurementResult(
            value=float(raw), unit="s",
            gate_time_s=self._gate_time_s, channel=ch,
        )

    def measure_duty_cycle(self, channel: Optional[int] = None) -> MeasurementResult:
        """Measure duty cycle (0–100 %)."""
        ch = channel or self._channel
        raw = self._query(f"MEAS:DCYC? (@{ch})",
                          timeout_override_ms=self._gate_timeout_ms())
        return MeasurementResult(
            value=float(raw), unit="%",
            gate_time_s=self._gate_time_s, channel=ch,
        )

    def measure_phase(
        self, ref_channel: int = 1, meas_channel: int = 2
    ) -> MeasurementResult:
        """Measure phase difference between two channels (degrees)."""
        raw = self._query(
            f"MEAS:PHAS? (@{ref_channel},{meas_channel})",
            timeout_override_ms=self._gate_timeout_ms(),
        )
        return MeasurementResult(
            value=float(raw), unit="deg",
            gate_time_s=self._gate_time_s, channel=meas_channel,
        )

    def measure_time_interval(
        self, start_channel: int = 1, stop_channel: int = 2
    ) -> MeasurementResult:
        """Measure time interval from start_channel edge to stop_channel edge."""
        raw = self._query(
            f"MEAS:TINT? (@{start_channel},{stop_channel})",
            timeout_override_ms=self._gate_timeout_ms(),
        )
        return MeasurementResult(
            value=float(raw), unit="s",
            gate_time_s=self._gate_time_s, channel=stop_channel,
        )

    # ------------------------------------------------------------------
    # Multi-sample & statistics
    # ------------------------------------------------------------------

    def measure_statistics(
        self,
        n_samples: int = 10,
        channel: Optional[int] = None,
        func: str = "FREQ",
        delay_s: float = 0.0,
    ) -> StatisticsResult:
        """
        Perform N repeated measurements and compute statistics.

        Parameters
        ----------
        n_samples : int
            Number of measurements (≥ 2 for meaningful statistics).
        channel : int, optional
            Channel override.
        func : str
            Measurement function: 'FREQ', 'PERIOD', 'PWIDTH', etc.
        delay_s : float
            Optional inter-measurement delay in seconds.

        Returns
        -------
        StatisticsResult
            Contains mean, std_dev, min, max, type-A uncertainty.
        """
        if n_samples < 1:
            raise CNT90XLValueError("n_samples must be ≥ 1.")

        ch = channel or self._channel
        samples = []
        unit = "Hz" if func == "FREQ" else "s"

        logger.info(
            "Starting %d-sample statistics: func=%s ch=%d gate=%.3f s",
            n_samples, func, ch, self._gate_time_s,
        )

        for i in range(n_samples):
            if func == "FREQ":
                result = self.measure_frequency(channel=ch)
            elif func == "PERIOD":
                result = self.measure_period(channel=ch)
            elif func in ("PWIDTH", "NWIDTH"):
                polarity = "POS" if func == "PWIDTH" else "NEG"
                result = self.measure_pulse_width(polarity=polarity, channel=ch)
            elif func == "DUTY":
                result = self.measure_duty_cycle(channel=ch)
            else:
                raise CNT90XLValueError(f"Unsupported function: {func}")

            samples.append(result.value)
            unit = result.unit
            logger.debug("  Sample %d/%d: %.9g %s", i + 1, n_samples, result.value, unit)

            if delay_s > 0:
                time.sleep(delay_s)

        mean    = statistics.mean(samples)
        std_dev = statistics.stdev(samples) if len(samples) > 1 else 0.0

        return StatisticsResult(
            n_samples=n_samples,
            mean=mean,
            std_dev=std_dev,
            minimum=min(samples),
            maximum=max(samples),
            unit=unit,
            samples=samples,
        )

    # ------------------------------------------------------------------
    # Reference clock
    # ------------------------------------------------------------------

    def set_reference_internal(self) -> None:
        """Use the internal time base (OCXO / TCXO)."""
        self._write("ROSC:SOUR INT")
        logger.info("CNT-90XL reference: INTERNAL")

    def set_reference_external(self, freq_hz: float = 10e6) -> None:
        """
        Lock to an external 10 MHz reference.

        Parameters
        ----------
        freq_hz : float
            External reference frequency in Hz (default 10 MHz).
        """
        self._write("ROSC:SOUR EXT")
        self._write(f"ROSC:EXT:FREQ {freq_hz:.0f} HZ")
        logger.info("CNT-90XL reference: EXTERNAL %.0f Hz", freq_hz)

    def get_reference_source(self) -> str:
        """Return 'INT' or 'EXT'."""
        return self._query("ROSC:SOUR?")

    def is_locked(self) -> bool:
        """
        Check if the timebase is locked to the external reference.
        Returns True when locked (only meaningful in EXT mode).
        """
        try:
            resp = self._query("ROSC:LOCK?")
            return resp in ("1", "LOCK", "LOCKED")
        except CNT90XLCommandError:
            return False

    # ------------------------------------------------------------------
    # Status / diagnostics
    # ------------------------------------------------------------------

    def get_all_errors(self) -> list[str]:
        """Drain and return the full error queue."""
        errors = []
        for _ in range(50):
            err = self._query("SYST:ERR?")
            if err.startswith("0"):
                break
            errors.append(err)
        return errors

    def get_status(self) -> dict:
        """
        Return a snapshot of current instrument configuration.

        Returns
        -------
        dict with keys: idn, gate_time_s, channel, ref_source, locked
        """
        return {
            "idn":         self.identify(),
            "gate_time_s": self.get_gate_time(),
            "channel":     self._channel,
            "ref_source":  self.get_reference_source(),
            "locked":      self.is_locked(),
        }

    def __repr__(self) -> str:
        return f"CNT90XL(address='{self._address}')"