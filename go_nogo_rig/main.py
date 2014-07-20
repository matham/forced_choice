from moa.clock import MoaClockBase
from kivy.context import register_context
import kivy
kivy.clock.Clock = register_context('Clock', MoaClockBase)

from kivy.config import Config
Config.set('kivy', 'exit_on_escape', 0)
Config.set('kivy', 'multitouch_on_demand', 1)
from kivy.properties import (ObjectProperty, OptionProperty,
                             ConfigParserProperty, StringProperty)
from kivy.config import ConfigParser

from moa.app import MoaApp
from moa.compat import unicode_type
from go_nogo_rig.graphics import MainView
from go_nogo_rig.stages import RootStage
from go_nogo_rig import device_config_name, exp_config_name

from functools import partial
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

    animal_pause_btn = ObjectProperty(None)

    def __init__(self, **kw):
        super(GoNoGoApp, self).__init__(**kw)
        self.data_directory = join(dirname(dirname(__file__)), 'data')

    def build(self):
        return MainView()

    def start_stage(self, restart=False):
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
            self.exception_value = '{}\n{}'.format(e, traceback.format_exc())
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
        self.exception_value = '{}\n{}'.format(*exception)
        logging.exception(self.exception_value)

        root = self.root_stage
        if root is not None:
            if root.stages[1].finished:
                self.recovery_path = self.save_state(prefix='go_nogo_')
            root.pause()
        barst = self.barst_stage
        if barst is not None:
            barst.request_callback('stop_devices',
                lambda *l: setattr(self, 'app_state', 'clear'))


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
