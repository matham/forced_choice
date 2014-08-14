# TODO: fix restart, check pause

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
from moa.logger import Logger
#Logger.setLevel(logging.TRACE)


class GoNoGoApp(MoaApp):

    app_state = OptionProperty('clear', options=('clear', 'exception',
                                                 'paused', 'running'))
    ''' The current app state. Can be one of `'clear'`, `'exception'`,
    `'paused'`, or `'running'`.
    '''

    exp_status = NumericProperty(0)
    '''Numerical representation of the current experiment stage.

    Defaults to zero.
    '''

    exception_value = StringProperty('')
    '''The text of the current/last exception.
    '''

    recovery_path = ConfigParserProperty('', 'App', 'recovery_path',
        device_config_name, val_type=unicode_type)
    '''The directory path to where the recovery files are saved.
    '''

    go_nogo_configparser = ObjectProperty(None)
    '''The :class:`ConfigParser` instance used for configuring the devices /
    system. The config file used with this instance is called `'config.ini'`.
    '''

    experiment_configparser = ObjectProperty(None)
    '''The :class:`ConfigParser` instance used for configuring the experimental
    parameters.
    '''

    exp_config_path = ConfigParserProperty('experiment.ini', 'Experiment',
        'exp_config_path', device_config_name, val_type=unicode_type)
    '''The path to the config file used with :attr:`experiment_configparser`.
    Defaults to `'experiment.ini'`.
    '''

    simulate = BooleanProperty(False)
    '''If True, virtual devices should be used for the experiment. Otherwise
    actual Barst devices will be used.
    '''

    err_popup = ObjectProperty(None)
    '''Contains the error popup object.
    '''

    popup_anim = None
    '''Contains the animation used to display that an error exists.
    '''

    base_stage = ObjectProperty(None, allownone=True, rebind=True)
    '''The instance of the :class:`RootStage`.
    '''

    next_animal_btn = ObjectProperty(None, rebind=True)

    simulation_devices = ObjectProperty(None)

    def __init__(self, **kw):
        super(GoNoGoApp, self).__init__(**kw)
        app_path = dirname(dirname(__file__))
        self.data_directory = join(app_path, 'data')
        resources.resource_add_path(self.data_directory)
        resources.resource_add_path(join(app_path, 'media'))

    def build(self):
        #self.load_kv('display.kv')
        main_view = MainView()
        self.err_popup = Factory.get('ErrorPopup')()
        self.popup_anim = Sequence(Animation(t='in_bounce', warn_alpha=1.),
                                   Animation(t='out_bounce', warn_alpha=0))
        self.popup_anim.repeat = True
        # inspector.create_inspector(Window, main_view)
        return main_view

    def start_stage(self, restart=False):
        self.exception_value = ''
        try:
            self.barst_stage = None
            self.app_state = 'running'
            root = self.base_stage
            self.base_stage = None
            if root is not None:
                def clear_name(stage):
                    stage.name = ''
                    for child in stage.stages:
                        clear_name(child)
                clear_name(root)

            parser = self.go_nogo_configparser
            config_path = resources.resource_find('config.ini')
            if parser is None:
                parser = self.go_nogo_configparser = \
                    ConfigParser(name=device_config_name)
            if not config_path:
                config_path = join(self.data_directory, 'config.ini')
                with open(config_path, 'w'):
                    pass
            parser.read(config_path)
            parser.write()

            parser = self.experiment_configparser
            config_path = resources.resource_find(self.exp_config_path)
            if parser is None:
                parser = self.experiment_configparser = \
                    ConfigParser(name=exp_config_name)
            if not config_path:
                self.exp_config_path = config_path = join(self.data_directory,
                                                          'experiment.ini')
                with open(config_path, 'w'):
                    pass
            parser.read(config_path)
            parser.write()

            root = self.base_stage = RootStage()
        except Exception as e:
            self.exception_value = '{}\n\n\n{}'.format(e,
                                                       traceback.format_exc())
            logging.exception(self.exception_value)
            self.app_state = 'clear'
            return

        if restart and isfile(self.recovery_path):
            self.recover_state(self.recovery_path, stage=root)
        root.step_stage()

    def device_exception(self, exception, *largs):
        if self.app_state == 'exception':
            return
        self.app_state = 'exception'
        self.exception_value = '{}\n\n\n{}'.format(*exception)
        logging.exception(self.exception_value)

        root = self.base_stage
        if root is not None and root.block.started and not root.block.finished:
            self.recovery_path = self.save_state(prefix='go_nogo_', stage=root)
        if root:
            root.stop()

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
        app.device_exception((e, traceback.format_exc()))

    root = app.base_stage
    if root:
        root.stop()


if __name__ == '__main__':
    run_app()
