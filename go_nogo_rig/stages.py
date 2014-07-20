

from functools import partial
import traceback

from moa.stage import MoaStage
from moa.threads import ScheduledEventLoop
from moa.tools import ConfigPropertyList

from kivy.app import App
from kivy.properties import ObjectProperty, ListProperty, ConfigParserProperty
from kivy.clock import Clock

from go_nogo_rig.devices import (Server, FTDIDevChannel, FTDIOdors,
                                 FTDIPin, DAQInDevice, DAQOutDevice)
from go_nogo_rig import exp_config_name


class RootStage(MoaStage):
    pass


class InitBarstStage(MoaStage, ScheduledEventLoop):
    '''
    TODO: fix pasuing
    '''

    _current_step = ''
    _is_running = False

    def recover_state(self, state):
        ''' When recovering this stage, even if finished before, always redo it
        because we need to init the Barst devices, so skip `finished`.
        '''
        state.pop('finished', None)
        return super(InitBarstStage, self).recover_state(state)

    def unpause(self, *largs, **kwargs):
        if super(InitBarstStage, self).unpause(*largs, **kwargs):
            if not self._is_running and self._current_step is not 'daq_out':
                self.start_devices(self._current_step)
            return True
        return False

    def step_stage(self, *largs, **kwargs):
        if not super(InitBarstStage, self).step_stage(*largs, **kwargs):
            return False

        server = self.server = Server()
        self._current_step = ''
        self._is_running = True
        server.start_device(partial(self.start_devices, 'server'))
        return True

    def start_devices(self, state, *largs):
        self._current_step = state
        if self.paused:
            self._is_running = False
            return
        try:
            if state == 'server':
                chan = self.ftdi_chan = FTDIDevChannel(exception_callback=
                                                       partial)
                ftdi_pin = self.pin_dev = FTDIPin()
                odors = self.odor_dev = FTDIOdors()
                chan.start_device(partial(self.start_devices, 'ftdi'),
                    [odors.get_settings(), ftdi_pin.get_settings()],
                    self.server.target)
            elif state == 'ftdi':
                self.odor_dev.target, self.pin_dev.target = largs[0]
                self.odor_dev.start_device(partial(self.start_devices,
                                                   'odors'))
            elif state == 'odors':
                self.pin_dev.start_device(partial(self.start_devices,
                                                  'ftdi_pin'))
            elif state == 'ftdi_pin':
                daq = self.daq_in_dev = DAQInDevice()
                daq.start_device(partial(self.start_devices, 'daq_in'),
                                 self.server.target)
            elif state == 'daq_in':
                daq = self.daq_out_dev = DAQOutDevice()
                daq.start_device(partial(self.start_devices, 'daq_out'),
                                 self.server.target)
            elif state == 'daq_out':
                self.step_stage()
            else:
                assert False
        except Exception as e:
            App.get_running_app().device_exception((e, traceback.format_exc()))

    def stop_devices(self, join=False):
        for dev in (self.server, self.ftdi_chan, self.pin_dev, self.odor_dev,
                    self.daq_in_dev, self.daq_out_dev):
            if dev is not None:
                dev.stop_thread(True)
                dev.clear_events()
        try:
            self.ftdi_chan.target.close_channel_server()
        except:
            pass
        try:
            self.daq_in_dev.target.close_channel_server()
        except:
            pass
        self.stop_thread(join)

    def cancel_exceptions(self):
        for dev in (self.server, self.ftdi_chan, self.pin_dev, self.odor_dev,
                    self.daq_in_dev, self.daq_out_dev):
            if dev is not None:
                Clock.unschedule(dev.exception_callback)

    def compute_reward(self, block, trial, went):
        if self.trial_go[block][trial]:  # supposed to go
            if went:  # positive
                reward, iti = True, self.go_iti[block]
            else:  # false negative
                reward, iti = False, self.false_no_go_iti[block]
        else:  # not supposed to go
            if went:  # false positive
                reward, iti = False, self.false_go_iti[block]
            else:  # negative
                reward, iti = False, self.no_go_iti[block]
        self.reward[block][trial] = reward
        self.iti[block][trial] = iti + self.base_iti[block]

    server = ObjectProperty(None, allownone=True)

    ftdi_chan = ObjectProperty(None, allownone=True)

    pin_dev = ObjectProperty(None, allownone=True)

    odor_dev = ObjectProperty(None, allownone=True)

    daq_in_dev = ObjectProperty(None, allownone=True)

    daq_out_dev = ObjectProperty(None, allownone=True)

    trial_odors = ListProperty([['p1'] * 10] * 2)

    trial_go = ListProperty([[True, False] * 5] * 2)

    reward = ListProperty([[True] * 10] * 2)

    iti = ListProperty([[4] * 10] * 2)

    num_blocks = ConfigParserProperty(1, 'Experiment', 'num_blocks',
                                      exp_config_name, val_type=int)

    num_trials = ConfigPropertyList(1, 'Experiment', 'num_trials',
                                      exp_config_name, val_type=int)

    max_nose_poke = ConfigPropertyList(1, 'Experiment', 'max_nose_poke_dur',
                                       exp_config_name, val_type=float)

    decision_duration = ConfigPropertyList(1, 'Experiment',
        'decision_duration', exp_config_name, val_type=float)

    base_iti = ConfigPropertyList(1, 'Experiment', 'base_iti', exp_config_name,
                                  val_type=float)

    go_iti = ConfigPropertyList(1, 'Experiment', 'go_iti', exp_config_name,
                                val_type=float)

    no_go_iti = ConfigPropertyList(1, 'Experiment', 'no_go_iti',
                                   exp_config_name, val_type=float)

    false_go_iti = ConfigPropertyList(1, 'Experiment', 'false_go_iti',
                                      exp_config_name, val_type=float)

    false_no_go_iti = ConfigPropertyList(1, 'Experiment', 'false_no_go_iti',
                                         exp_config_name, val_type=float)
