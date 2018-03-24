# Import python modules
import logging, time, json, threading

# Import all possible states & errors
from states import States
from errors import Errors

# Import shared memory objects
from system import System
from environment import Environment


class StateMachine(object):
    """ A state machine that spawns threads to run recipes, read sensors, set 
    actuators, manage control loops, sync data, and manage external events. """

    # Initialize logger
    logger = logging.getLogger(__name__)

    # Initialize state and error lists
    states = States()
    errors = Errors()

    # Initialize thread objects
    peripheral = {}
    controller = {}


    def __init__(self):
        """ Initializes state machine. """
        self.sys = System()

    
    def run(self):
        """ Runs state machine. """
        self.logger.info("Starting state machine")
        while True:
            if self.sys.state == self.states.CONFIG:
                self.config_state()
            elif self.sys.state == self.states.SETUP:
                self.setup_state()
            elif self.sys.state == self.states.INIT:
                self.init_state()
            elif self.sys.state == self.states.NOS:
                self.nos_state()


    def config_state(self):
        """ Runs configuration state. Loads config then transitions to 
            setup state. """
        self.logger.debug("Entered CONFIG state")
        self.load_config()
        self.set_state(self.states.SETUP)


    def setup_state(self):
        """ Runs setup state. Creates `environment` shared memory object, 
            creates peripheral object threads, spawns peripheral threads, 
            then transitions to initialization state. """
        self.logger.debug("Entered SETUP state")
        self.env = Environment()
        self.create_peripherals()
        self.spawn_peripherals()
        self.sys.state = self.states.INIT


    def init_state(self):
        """ Runs initialization state. Waits for all peripherals to enter NOS, 
            WARMING, or ERROR, then transitions to normal operating state. """
        self.logger.debug("Entered INIT state")
        while not self.all_peripherals_ready():
            time.sleep(2)
        self.sys.state = self.states.NOS


    def nos_state(self):
        """ Runs normal operation state. Transitions to reset if commanded. 
            Transitions to error state on error."""
        self.logger.debug("Entered NOS state")

        while True:
            self.logger.info(self.env.sensor)
            time.sleep(3) # seconds


    def reset_state(self):
        """ Runs reset state. """
        time.sleep(0.1) # 100ms


    def error_state(self):
        """ Runs error state. """
        time.sleep(0.1) # 100ms


    def set_state(self, state):
        """ Safely sets state on `system` shared memory object. """
        with threading.Lock():
            self.sys.state = state


    def load_config(self):
        """ Loads configuration. """
        self.config = json.load(open('config.json'))
        # TODO: validate config


    def create_peripherals(self):
        """ Creates peripheral thread objects defined in config. """
        
        for peripheral_name in self.config["peripherals"]:
            # Extract module parameters from config
            peripheral = self.config["peripherals"][peripheral_name]
            module_name = "peripherals." + peripheral["class_file"]
            class_name = peripheral["class_name"]

            # Import peripheral library
            module_instance= __import__(module_name, fromlist=[class_name])
            class_instance = getattr(module_instance, class_name)

            # Create peripheral object instances
            self.peripheral[peripheral_name] = class_instance(peripheral_name, self.config["peripherals"][peripheral_name], self.env, self.sys)


    def spawn_peripherals(self):
        """ Runs peripheral threads. """
        for peripheral_name in self.peripheral:
            self.peripheral[peripheral_name].run()


    def all_peripherals_ready(self):
        for peripheral in self.sys.peripheral_state:
            state = self.sys.peripheral_state[peripheral]
            self.logger.warning(state)
