from moa.clock import MoaClockBase
from kivy.context import register_context
import kivy
kivy.clock.Clock = register_context('Clock', MoaClockBase)

from kivy.config import Config
Config.set('kivy', 'exit_on_escape', 0)
Config.set('kivy', 'multitouch_on_demand', 1)
from kivy.properties import (ObjectProperty, OptionProperty,
    ConfigParserProperty, StringProperty, BooleanProperty, NumericProperty)
from kivy import resources
from kivy.modules import inspector
from kivy.core.window import Window
from kivy.factory import Factory
from kivy.animation import Sequence, Animation

from moa.app import MoaApp
from moa.compat import unicode_type
from moa.config import ConfigParser
from go_nogo_rig.graphics import MainView
from go_nogo_rig.stages import RootStage
from go_nogo_rig import device_config_name, exp_config_name

from os.path import dirname, join, isfile
import traceback
import logging


class GoNoGoApp(MoaApp):

    app_state = OptionProperty('clear', options=('clear', 'exception',
                                                 'paused', 'running'))
    ''' While in exception, you cannot start/stop/pause.
    '''

    recovery_path = ConfigParserProperty('', 'App', 'recovery_path',
        device_config_name, val_type=unicode_type)

    config_path = StringProperty('')

    barst_stage = ObjectProperty(None, allownone=True, rebind=True)

    exception_value = StringProperty('')

    go_nogo_configparser = ObjectProperty(None)

    experiment_configparser = ObjectProperty(None)

    exp_config_path = ConfigParserProperty('experiment.ini', 'Experiment',
        'exp_config_path', device_config_name, val_type=unicode_type)

    simulate = BooleanProperty(False)

    animal_pause_btn = ObjectProperty(None, rebind=True)

    simulation_devices = ObjectProperty(None)

    server = ObjectProperty(None, allownone=True)

    ftdi_chan = ObjectProperty(None, allownone=True)

    pin_dev = ObjectProperty(None, allownone=True, rebind=True)

    odor_dev = ObjectProperty(None, allownone=True, rebind=True)

    daq_in_dev = ObjectProperty(None, allownone=True, rebind=True)

    daq_out_dev = ObjectProperty(None, allownone=True, rebind=True)

    animal_stage = ObjectProperty(None, rebind=True)

    verify_stage = ObjectProperty(None, rebind=True)

    outcome_container = ObjectProperty(None)

    prediction_container = ObjectProperty(None)

    exp_status = NumericProperty(0)

    err_popup = ObjectProperty(None)

    popup_anim = None

    def __init__(self, **kw):
        super(GoNoGoApp, self).__init__(**kw)
        self.data_directory = join(dirname(dirname(__file__)), 'data')
        resources.resource_add_path(self.data_directory)
        resources.resource_add_path(join(dirname(dirname(__file__)), 'media'))

    def build(self):
        self.load_kv('display.kv')
        main_view = MainView()
        self.err_popup = Factory.get('ErrorPopup')()
        self.popup_anim = Sequence(Animation(t='in_cubic', warn_alpha=1.),
                                   Animation(t='out_cubic', warn_alpha=0))
        self.popup_anim.repeat = True
        inspector.create_inspector(Window, main_view)
        return main_view

    def start_stage(self, restart=False):
        self.exception_value = ''
        try:
            self.barst_stage = None
            self.app_state = 'running'
            root = self.root_stage
            if root is not None:
                def clear_name(stage):
                    stage.name = ''
                    for child in stage.stages:
                        clear_name(child)
                clear_name(root)
            root = self.root_stage = RootStage()
        except Exception as e:
            self.exception_value = '{}\n\n\n{}'.format(e, traceback.format_exc())
            logging.exception(self.exception_value)
            self.app_state = 'clear'
            return

        p = self.go_nogo_configparser
        if p is not None:
            p.name = ''
        self.go_nogo_configparser = ConfigParser(name=device_config_name)
        config_path = self.config_path
        if not config_path:
            self.config_path = config_path = 'config.ini'
        if isfile(join(self.data_directory, config_path)):
            self.go_nogo_configparser.read(join(self.data_directory,
                                                config_path))
        elif isfile(config_path):
            self.go_nogo_configparser.read(config_path)
        else:
            with open(join(self.data_directory, config_path), 'w'):
                pass
            self.go_nogo_configparser.read(config_path)
        self.go_nogo_configparser.write()

        p = self.experiment_configparser
        if p is not None:
            p.name = ''
        self.experiment_configparser = ConfigParser(name=exp_config_name)
        config_path = self.exp_config_path
        if not config_path:
            self.exp_config_path = config_path = 'experiment.ini'
        if isfile(join(self.data_directory, config_path)):
            self.experiment_configparser.read(join(self.data_directory,
                                                config_path))
        elif isfile(config_path):
            self.experiment_configparser.read(config_path)
        else:
            with open(join(self.data_directory, config_path), 'w'):
                pass
            self.experiment_configparser.read(config_path)
        self.experiment_configparser.write()

        self.barst_stage = root.stages[0]
        if restart and isfile(self.recovery_path):
            self.recover_state(self.recovery_path)
        root.step_stage()

    def clean_up(self):
        barst = self.barst_stage
        if barst is not None:
            barst.stop_devices(True)

    def device_exception(self, exception, *largs):
        if self.app_state == 'exception':
            return
        self.app_state = 'exception'
        self.exception_value = '{}\n\n\n{}'.format(*exception)
        logging.exception(self.exception_value)

        root = self.root_stage
        verify = self.verify_stage
        if root is not None and verify is not None:
            if verify.finished:
                self.recovery_path = self.save_state(prefix='go_nogo_')
            root.pause()
        barst = self.barst_stage
        if barst is not None:
            barst.request_callback('stop_devices',
                lambda *l: setattr(self, 'app_state', 'clear'))

    def compute_simulated_state(self, sim_state, dev_state):
        if dev_state is None:
            return sim_state
        if (sim_state == 'down') == dev_state:
            return sim_state
        return 'down' if dev_state else 'normal'

    def set_dev_state(self, sim_state, dev, attr):
        if dev is not None:
            high = []
            low = []
            if sim_state == 'down':
                high = [attr]
            else:
                low = [attr]
            dev.set_state(high=high, low=low)


def run_app():
    app = GoNoGoApp()
    try:
        app.run()
    except Exception as e:
        logging.exception('{}\n{}'.format(e, traceback.format_exc()))
        if app.root_stage is not None:
            app.recovery_path = app.save_state(prefix='go_nogo_')
    app.clean_up()


if __name__ == '__main__':
    run_app()
