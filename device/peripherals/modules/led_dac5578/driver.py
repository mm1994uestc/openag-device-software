# Import standard python modules
import time, threading

# Import python types
from typing import NamedTuple, Optional, Tuple, Dict, Any, List

# Import device utilities
from device.utilities.logger import Logger
from device.utilities import maths

# Import mux simulator
from device.comms.i2c2.mux_simulator import MuxSimulator

# Import peripheral utilities
from device.peripherals.utilities import light

# Import dac driver elements
from device.peripherals.common.dac5578.driver import DAC5578Driver

# Import exceptions
from device.peripherals.classes.peripheral.exceptions import (
    DriverError,
    InitError,
    SetupError,
)
from device.peripherals.modules.led_dac5578.exceptions import (
    NoActivePanelsError,
    TurnOnError,
    TurnOffError,
    SetSPDError,
    SetOutputError,
    SetOutputsError,
    InvalidChannelNameError,
)


class LEDDAC5578Panel(object):
    """An led panel controlled by a dac5578."""

    # Initialize var defaults
    is_shutdown: bool = True
    driver: Optional[DAC5578Driver] = None

    def __init__(
        self,
        driver_name: str,
        config: Dict[str, Any],
        i2c_lock: threading.Lock,
        simulate: bool,
        mux_simulator: Optional[MuxSimulator],
        logger: Logger,
    ) -> None:
        """Initializes panel."""

        # Initialize panel parameters
        self.driver_name = driver_name
        self.name = str(config.get("name"))
        self.full_name = driver_name + "-" + self.name
        self.bus = config.get("bus")
        self.address = int(config.get("address"), 16)  # type: ignore
        self.active_low = config.get("active_low")
        self.i2c_lock = i2c_lock
        self.simulate = simulate
        self.mux_simulator = mux_simulator
        self.logger = logger

        # Initialize i2c mux address
        self.mux = config.get("mux")
        if self.mux != None:
            self.mux = int(self.mux, 16)  # type: ignore

        # Initialize i2c channel value
        self.channel = config.get("channel")
        if self.channel != None:
            self.channel = int(self.channel)  # type: ignore

    def initialize(self) -> None:
        """Initializes panel."""
        self.logger.debug("Initializing {}".format(self.name))
        try:
            self.driver = DAC5578Driver(
                name=self.full_name,
                i2c_lock=self.i2c_lock,
                bus=self.bus,
                address=self.address,
                mux=self.mux,
                channel=self.channel,
                simulate=self.simulate,
                mux_simulator=self.mux_simulator,
            )
            self.is_shutdown = False
        except Exception as e:
            self.logger.exception("Unable to initialize `{}`".format(self.name))
            self.is_shutdown = True


class LEDDAC5578Driver:
    """Driver for array of led panels controlled by a dac5578."""

    # Initialize var defaults
    num_active_panels = 0
    num_expected_panels = 1

    def __init__(
        self,
        name: str,
        panel_configs: List[Dict[str, Any]],
        panel_properties: Dict[str, Any],
        i2c_lock: threading.Lock,
        simulate: bool = False,
        mux_simulator: Optional[MuxSimulator] = None,
    ) -> None:
        """Initializes driver."""

        # Initialize driver parameters
        self.panel_properties = panel_properties
        self.i2c_lock = i2c_lock
        self.simulate = simulate

        # Initialize logger
        self.logger = Logger(name="Driver({})".format(name), dunder_name=__name__)

        # Parse panel properties
        self.channels = self.panel_properties.get("channels")
        self.dac_map = self.panel_properties.get("dac_map")

        # Initialze num expected panels
        self.num_expected_panels = len(panel_configs)

        # Initialize panels
        self.panels: List[LEDDAC5578Panel] = []
        for config in panel_configs:
            panel = LEDDAC5578Panel(
                name, config, i2c_lock, simulate, mux_simulator, self.logger
            )
            panel.initialize()
            self.panels.append(panel)

        # Check at least one panel is still active
        active_panels = [panel for panel in self.panels if not panel.is_shutdown]
        self.num_active_panels = len(active_panels)
        if self.num_active_panels < 1:
            raise NoActivePanelsError(logger=self.logger)

        # Successfully initialized
        message = "Successfully initialized with {} ".format(self.num_active_panels)
        message2 = "active panels, expected {}".format(self.num_expected_panels)
        self.logger.debug(message + message2)

    def turn_on(self) -> Dict[str, float]:
        """Turns on leds."""
        self.logger.debug("Turning on")
        channel_outputs = self.build_channel_outputs(100)
        self.set_outputs(channel_outputs)

        return channel_outputs

    def turn_off(self) -> Dict[str, float]:
        """Turns off leds."""
        self.logger.debug("Turning off")
        channel_outputs = self.build_channel_outputs(0)
        self.set_outputs(channel_outputs)
        return channel_outputs

    def set_spd(
        self, desired_distance: float, desired_intensity: float, desired_spectrum: Dict
    ) -> Tuple[Optional[Dict], Optional[Dict], Optional[Dict]]:
        """Sets spectral power distribution."""
        message = "Setting spd, distance={}cm, ppfd={}umol/m2/s, spectrum={}".format(
            desired_distance, desired_intensity, desired_spectrum
        )
        self.logger.debug(message)

        # Approximate spectral power distribution
        try:
            channel_outputs, output_spectrum, output_intensity = light.approximate_spd(
                self.panel_properties,
                desired_distance,
                desired_intensity,
                desired_spectrum,
            )
        except Exception as e:
            message = "approximate spd failed"
            raise SetSPDError(message=message, logger=self.logger) from e

        # Set outputs
        self.set_outputs(channel_outputs)

        # Successfully set channel outputs
        message = "Successfully set spd, output: channels={}, spectrum={}, intensity={}umol/m2/s".format(
            channel_outputs, output_spectrum, output_intensity
        )
        self.logger.debug(message)
        return (channel_outputs, output_spectrum, output_intensity)

    def set_outputs(self, par_setpoints: dict) -> None:
        """Sets outputs on light panels. Converts channel names to channel numbers, 
        translates par setpoints to dac setpoints, then sets dac."""
        self.logger.debug("Setting outputs: {}".format(par_setpoints))

        # Check at least one panel is active
        active_panels = [panel for panel in self.panels if not panel.is_shutdown]
        self.num_active_panels = len(active_panels)
        if self.num_active_panels < 1:
            raise NoActivePanelsError(logger=self.logger)
        message = "Setting outputs on {} active panels".format(self.num_active_panels)
        self.logger.debug(message)

        # Convert channel names to channel numbers
        converted_outputs = {}
        for name, percent in par_setpoints.items():

            # Convert channel name to channel number
            try:
                number = self.get_channel_number(name)
            except Exception as e:
                raise SetOutputsError(logger=self.logger) from e

            # Append to converted outputs
            converted_outputs[number] = percent

        # Try to set outputs on all panels
        for panel in self.panels:

            # Scale setpoints
            dac_setpoints = self.translate_setpoints(converted_outputs)

            # Set outputs on panel
            try:
                panel.driver.write_outputs(dac_setpoints)  # type: ignore
            except AttributeError:
                message = "Unable to set outputs on `{}`".format(panel.name)
                self.logger.error(message + ", panel not initialized")
            except Exception as e:
                message = "Unable to set outputs on `{}`".format(panel.name)
                self.logger.exception(message)
                panel.is_shutdown = True

        # Check at least one panel is still active
        active_panels = [panel for panel in self.panels if not panel.is_shutdown]
        self.num_active_panels = len(active_panels)
        if self.num_active_panels < 1:
            message = "failed when setting outputs"
            raise NoActivePanelsError(message=message, logger=self.logger)

    def set_output(self, channel_name: str, par_setpoint: float) -> None:
        """Sets output on light panels. Converts channel name to channel number, 
        translates par setpoint to dac setpoint, then sets dac."""
        self.logger.debug("Setting ch {}: {}".format(channel_name, par_setpoint))

        # Check at least one panel is active
        active_panels = [panel for panel in self.panels if not panel.is_shutdown]
        if len(active_panels) < 1:
            raise NoActivePanelsError(logger=self.logger)
        message = "Setting output on {} active panels".format(self.num_active_panels)
        self.logger.debug(message)

        # Convert channel name to channel number
        try:
            channel_number = self.get_channel_number(channel_name)
        except Exception as e:
            raise SetOutputError(logger=self.logger) from e

        # Set output on all panels
        for panel in self.panels:

            # Scale setpoint
            dac_setpoint = self.translate_setpoint(par_setpoint)

            # Set output on panel
            try:
                panel.driver.write_output(channel_number, dac_setpoint)  # type: ignore
            except AttributeError:
                message = "Unable to set output on `{}`".format(panel.name)
                self.logger.error(message + ", panel not initialized")
            except Exception as e:
                message = "Unable to set output on `{}`".format(panel.name)
                self.logger.exception(message)
                panel.is_shutdown = True

        # Check at least one panel is still active
        active_panels = [panel for panel in self.panels if not panel.is_shutdown]
        self.num_active_panels = len(active_panels)
        if self.num_active_panels < 1:
            message = "failed when setting output"
            raise NoActivePanelsError(message=message, logger=self.logger)

    def get_channel_number(self, channel_name: str) -> int:
        """Gets channel number from channel name."""
        try:
            channel_dict = self.channels[channel_name]
            channel_number = channel_dict.get("port", -1)
            return int(channel_number)
        except KeyError:
            raise InvalidChannelNameError(message=channel_name, logger=self.logger)

    def build_channel_outputs(self, value: float) -> Dict[str, float]:
        """Build channel outputs. Sets each channel to provided value."""
        self.logger.debug("Building channel outputs")
        channel_outputs = {}
        for key in self.channels.keys():
            channel_outputs[key] = value
        self.logger.debug("channel outputs = {}".format(channel_outputs))
        return channel_outputs

    def translate_setpoints(self, par_setpoints: Dict) -> Dict:
        """Translates par setpoints to dac setpoints."""

        # Build interpolation lists
        dac_list = []
        par_list = []
        for dac_percent, par_percent in self.dac_map.items():
            dac_list.append(float(dac_percent))
            par_list.append(float(par_percent))

        # Get dac setpoints
        dac_setpoints = {}
        for key, par_setpoint in par_setpoints.items():
            dac_setpoint = maths.interpolate(par_list, dac_list, par_setpoint)
            dac_setpoints[key] = dac_setpoint

        # Successfully translated dac setpoints
        return dac_setpoints

    def translate_setpoint(self, par_setpoint: float) -> float:
        """Translates par setpoint to dac setpoint."""

        # Build interpolation lists
        dac_list = []
        par_list = []
        for dac_percent, par_percent in self.dac_map.items():
            dac_list.append(float(dac_percent))
            par_list.append(float(par_percent))

        # Get dac setpint
        dac_setpoint = maths.interpolate(par_list, dac_list, par_setpoint)

        # Successfully translated dac setpoint
        return dac_setpoint
