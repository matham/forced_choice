

from functools import partial
import traceback
from time import clock
from re import match, compile
from os.path import join, isfile
import csv
from random import choice

from moa.stage import MoaStage
from moa.threads import ScheduledEventLoop
from moa.tools import ConfigPropertyList
from moa.compat import unicode_type

from kivy.app import App
from kivy.event import EventDispatcher
from kivy.properties import (ObjectProperty, ListProperty,
    ConfigParserProperty, NumericProperty, BooleanProperty,
    StringProperty)
from kivy.clock import Clock
from kivy.factory import Factory
from kivy.lang import Builder

from go_nogo_rig.devices import (Server, FTDIDevChannel, FTDIOdors,
    FTDIOdorsSim, FTDIPin, FTDIPinSim, DAQInDevice, DAQInDeviceSim,
    DAQOutDevice, DAQOutDeviceSim)
from go_nogo_rig import exp_config_name
from go_nogo_rig.graphics import TrialOutcome

import pstats
import cProfile

odor_method_pat = compile('random([0-9]*)')
odor_pat = compile('p[0-9]+')


class RootStage(MoaStage):

    def on_finished(self, *largs, **kwargs):
        if self.finished:
            app = App.get_running_app()
            app.pin_dev.deactivate(self)
            app.odor_dev.deactivate(self)
            app.daq_in_dev.deactivate(self)
            app.daq_out_dev.deactivate(self)

    def activate_devices(self):
        app = App.get_running_app()
        app.pin_dev.activate(self)
        app.odor_dev.activate(self)
        app.daq_in_dev.activate(self)
        app.daq_out_dev.activate(self)


class InitBarstStage(MoaStage, ScheduledEventLoop):

    _current_step = ''
    _is_running = False
    _should_stop = None

    def recover_state(self, state):
        ''' When recovering this stage, even if finished before, always redo it
        because we need to init the Barst devices, so skip `finished`.
        '''
        state.pop('finished', None)
        return super(InitBarstStage, self).recover_state(state)

    def clear(self, *largs, **kwargs):
        self._is_running = False
        self._current_step = ''
        self._should_stop = None
        return super(InitBarstStage, self).clear(*largs, **kwargs)

    def unpause(self, *largs, **kwargs):
        if super(InitBarstStage, self).unpause(*largs, **kwargs):
            if not self._is_running and self._current_step is not 'daq_out':
                self.start_devices(self._current_step)
            return True
        return False

    def stop(self, *largs, **kwargs):
        if self._is_running and self._current_step is not 'daq_out':
            self._should_stop = (largs, kwargs)
            return False
        return super(InitBarstStage, self).stop(*largs, **kwargs)

    def step_stage(self, *largs, **kwargs):
        if not super(InitBarstStage, self).step_stage(*largs, **kwargs):
            return False

        app = App.get_running_app()
        if app.simulate:
            ids = app.simulation_devices.ids
            odors = ids['odors2'].children + ids['odors1'].children
            N = len(odors)
            app.odor_dev = FTDIOdorsSim(mapping={'p{}'.format(i):
                odors[N - i - 1].__self__ for i in range(N)})
            app.pin_dev = FTDIPinSim(mapping={'pump': ids['pump'].__self__})
            app.daq_in_dev = DAQInDeviceSim(mapping={
                'nose_beam': ids['nose_beam'].__self__,
                'reward_beam_r': ids['reward_beam_r'].__self__})
            app.daq_out_dev = DAQOutDeviceSim(mapping={
                'house_light': ids['house_light'].__self__,
                'stress_light': ids['stress_light'].__self__})

            app.root_stage.activate_devices()
            self.step_stage()
            return

        server = app.server = Server()
        self._current_step = ''
        self._is_running = True
        server.start_device(partial(self.start_devices, 'server'))
        return True

    def start_devices(self, state, *largs):
        self._current_step = state
        if self._should_stop:
            largs, kwargs = self._should_stop
            self._is_running = False
            super(InitBarstStage, self).stop(*largs, **kwargs)
            return
        if self.paused:
            self._is_running = False
            return

        app = App.get_running_app()
        try:
            if state == 'server':
                chan = app.ftdi_chan = FTDIDevChannel(
                    exception_callback=partial)
                ftdi_pin = app.pin_dev = FTDIPin()
                odors = app.odor_dev = FTDIOdors()
                chan.start_device(partial(self.start_devices, 'ftdi'),
                    [odors.get_settings(), ftdi_pin.get_settings()],
                    app.server.target)
            elif state == 'ftdi':
                app.odor_dev.target, app.pin_dev.target = largs[0]
                app.odor_dev.start_device(partial(self.start_devices, 'odors'))
            elif state == 'odors':
                app.pin_dev.start_device(partial(self.start_devices,
                                                 'ftdi_pin'))
            elif state == 'ftdi_pin':
                daq = app.daq_in_dev = DAQInDevice()
                daq.start_device(partial(self.start_devices, 'daq_in'),
                                 app.server.target)
            elif state == 'daq_in':
                daq = app.daq_out_dev = DAQOutDevice()
                daq.start_device(partial(self.start_devices, 'daq_out'),
                                 app.server.target)
            elif state == 'daq_out':
                app.root_stage.activate_devices()
                self.step_stage()
            else:
                assert False
        except Exception as e:
            App.get_running_app().device_exception((e, traceback.format_exc()))

    def stop_devices(self, join=False):
        app = App.get_running_app()
        if app.simulate:
            self.stop_thread(join)
            return

        for dev in (app.server, app.ftdi_chan, app.pin_dev, app.odor_dev,
                    app.daq_in_dev, app.daq_out_dev):
            if dev is not None:
                dev.stop_thread(True)
                dev.clear_events()

        mapping = app.daq_out_dev.mapping
        mask = 0
        for val in mapping.values():
            mask |= 1 << val

        f = (partial(app.daq_out_dev.target.write, mask=mask, value=0),
             partial(app.odor_dev.target.write,
                     set_low=range(8 * self.num_boards)),
             app.ftdi_chan.target.close_channel_server,
             app.daq_in_dev.target.close_channel_server)
        for fun in f:
            try:
                fun()
            except:
                pass
        self.stop_thread(join)

    def cancel_exceptions(self):
        app = App.get_running_app()
        if app.simulate:
            return

        for dev in (app.server, app.ftdi_chan, app.pin_dev, app.odor_dev,
                    app.daq_in_dev, app.daq_out_dev):
            if dev is not None:
                Clock.unschedule(dev.exception_callback)


def verify_odor_method(val):
    if val in ('constant', 'list') or match(odor_method_pat, val):
        return val
    else:
        raise Exception('"{}" does not match an odor method'.format(val))


class VerifyConfigStage(MoaStage):

    def recover_state(self, state):
        state.pop('finished', None)
        return super(InitBarstStage, self).recover_state(state)

    def step_stage(self, *largs, **kwargs):
        if not super(VerifyConfigStage, self).step_stage(*largs, **kwargs):
            return False

        self.verify_stage()
        return True

    def verify_stage(self):
        odor_NO = self.odor_NO
        odor_method = self.odor_method
        odor_selection = self.odor_selection
        num_trials = self.num_trials
        num_blocks = self.num_blocks
        app = App.get_running_app()
        odor_go = {}

        try:
            # now read the odor list
            odor_path = self.odor_path
            if not isfile(odor_path):
                odor_path = join(app.data_directory, odor_path)
            with open(odor_path, 'rb') as fh:
                odors = [('p{}'.format(i), '')
                              for i in range(8 * app.odor_dev.num_boards)]
                for row in csv.reader(fh):
                    row = [elem.strip() for elem in row]
                    go = bool(row[2] and int(row[2]))
                    odor_idx = int(row[0])
                    odor_go[odors[odor_idx][0]] = go
                    odors[odor_idx] = row[1], 'GO' if go else 'NOGO'
                self.odors = odors

            # make sure the number of blocks match
            for item in (self.false_no_go_iti, self.false_go_iti,
                self.no_go_iti, self.go_iti, self.base_iti, odor_NO,
                odor_method, odor_selection, self.decision_duration,
                self.max_nose_poke, num_trials):
                if len(item) != num_blocks:
                    raise Exception('The size of {} is not equal to the number '
                                    'of blocks, {}'.format(item, num_blocks))

            # now prepare the actual trial odors
            odors = list(odor_selection)
            # for each block
            for i, odor in enumerate(odors):
                odor = [o for o in odor if odor]
                if not len(odor):
                    raise Exception('no odors specified for block {}'
                                    .format(i))

                method = odor_method[i]
                # if there's only a filename there, read it for this block
                if method == 'list':
                    if len(odor) > 1:
                        raise Exception('More than one odor "{}" specified'
                            'for list odor method'.format(odor))

                    if not isfile(odor[0]):
                        odor[0] = join(app.data_directory, odor[0])
                    with open(odor_path, 'rb') as fh:
                        read_odors = list(csv.reader(fh))
                    idx = None
                    for row in read_odors:
                        if int(row[0]) == i:
                            idx = i
                            break

                    if idx is None:
                        raise Exception('odors not found for block "{}" '
                                        'in the list'.format(i))
                    odors[i] = read_odors[idx][1:]

                # then it's a list of odors to use in the block
                else:

                    # do all the odors in the list match the pattern?
                    matched = [match(odor_pat, o) for o in odor]
                    if not all(matched):
                        raise Exception('not all odors in "{}" '
                        'matched the "p[0-9]+" pattern for block {}'
                        .format(odor, i))

                    # now use the method to generate the odors
                    if method == 'constant':
                        if len(odor) > 1:
                            raise Exception('More than one odor "{}" specified'
                                'for constant odor method'.format(odor))
                        odors[i] = odor * num_trials[i]

                    # random
                    else:
                        if len(odor) == 1:
                            raise Exception('Only one odor "{}" was specified '
                                'with with random method'.format(odor))
                        m = match(odor_method_pat, method)
                        if m is None:
                            raise Exception('method "{}" does not match a '
                                            'a method'.format(method))

                        # the condition for this random method
                        condition = int(m.group(1)) if m.group(1) else 0
                        if condition <= 0:  # random without condition
                            odors[i] = [choice(odor) for _
                                        in range(num_trials[i])]
                        else:
                            rand_odors = []
                            for _ in range(num_trials[i]):
                                o = choice(odor)
                                while (len(rand_odors) >= condition and all([t == o for t in rand_odors[-condition:]])):
                                    o = choice(odor)
                                rand_odors.append(o)
                            odors[i] = rand_odors

            for i, odor in enumerate(odors):
                if len(odor) != num_trials[i]:
                    raise Exception('The number of odors "{}" for block "{}" '
                        'doesn\'t match the number of trials "{}"'.format(
                        odor, i, num_trials[i]))

            self.trial_odors = odors
            self.trial_go = [[odor_go[o] for o in odor] for odor in odors]
            self.reward = [[False for o in odor] for odor in odors]
            self.iti = [[0 for o in odor] for odor in odors]
        except Exception as e:
            App.get_running_app().device_exception((e, traceback.format_exc()))
            return
        self.step_stage()

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
        reward_list = list(self.reward[block])
        reward_list[trial] = reward
        self.reward[block] = reward_list
        iti_list = list(self.iti[block])
        iti_list[trial] = iti + self.base_iti[block]
        self.iti[block] = iti_list

    trial_odors = ListProperty(None, allownone=True)

    trial_go = ListProperty(None, allownone=True)

    reward = ListProperty(None, allownone=True)

    iti = ListProperty(None, allownone=True)

    num_blocks = ConfigParserProperty(1, 'Experiment', 'num_blocks',
                                      exp_config_name, val_type=int)

    num_trials = ConfigPropertyList(1, 'Experiment', 'num_trials',
                                      exp_config_name, val_type=int)

    max_nose_poke = ConfigPropertyList(1, 'Experiment', 'max_nose_poke_dur',
                                       exp_config_name, val_type=float)

    decision_duration = ConfigPropertyList(1, 'Experiment',
        'decision_duration', exp_config_name, val_type=float)

    odor_method = ConfigPropertyList('constant', 'Experiment',
        'odor_method', exp_config_name, val_type=verify_odor_method)

    odor_selection = ConfigPropertyList('p1', 'Experiment',
        'odor_selection', exp_config_name, val_type=unicode_type,
        inner_list=True)

    odor_NO = ConfigPropertyList('p0', 'Experiment', 'odor_NO',
                                 exp_config_name, val_type=unicode_type)

    odor_path = ConfigParserProperty(u'odor_list.txt', 'Experiment',
        'Odor_list_path', exp_config_name, val_type=unicode_type)

    odors = ListProperty(None)

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


class TrialOutcomeStats(EventDispatcher):

    def __init__(self, **kwargs):
        super(TrialOutcomeStats, self).__init__(**kwargs)

        def update_outcome(*largs):
            nps, ts, = self.nose_poke_ts, self.trial_start_ts
            rps, npe = self.reward_entery_ts, self.nose_poke_exit_ts
            if nps is not None and ts is not None:
                self.ttnp = max(0, nps - ts)
            if npe is not None and nps is not None:
                self.tinp = max(0, npe - nps)
            if npe is not None and rps is not None:
                self.ttrp = max(0, rps - npe)

        self.bind(trial_start_ts=update_outcome, nose_poke_ts=update_outcome,
                  nose_poke_exit_ts=update_outcome,
                  reward_entery_ts=update_outcome)

    trial = NumericProperty(0)

    trial_start_ts = NumericProperty(None)

    nose_poke_ts = NumericProperty(None)

    nose_poke_exit_ts = NumericProperty(None)

    reward_entery_ts = NumericProperty(None)

    ttnp = NumericProperty(None)

    tinp = NumericProperty(None)

    ttrp = NumericProperty(None)

    iti = NumericProperty(None)

    is_go = BooleanProperty(None)

    went = BooleanProperty(None)

    passed = BooleanProperty(None)

    rewarded = BooleanProperty(None)


class AnimalStage(MoaStage):

    animal_id = StringProperty('')

    outcomes = ListProperty([])

    outcome = ObjectProperty(TrialOutcomeStats(), rebind=True)

    total_pass = NumericProperty(0)

    total_fail = NumericProperty(0)

    _has_dummy_outcome = False

    outcome_wids = None

    def recover_state(self, state):
        state.pop('finished', None)
        return super(AnimalStage, self).recover_state(state)

    def pre_animal(self):
        pass

    def post_verify(self):
        verify = self.verify
        self.outcomes = [[] for _ in range(verify.num_blocks)]
        n = verify.num_trials
        anim, block = self.animal_id, self.block.count
        self.outcome_wids = [[TrialOutcome(TrialOutcomeStats(), anim, block)
            for _ in range(n[i])] for i in range(verify.num_blocks)]
        outcome_wid = self.outcome_wids[0][0]
        self.outcome = outcome_wid.outcome

        app = App.get_running_app()
        outcome_container = app.outcome_container
        predict = app.prediction_container
        predict_add = predict.add_widget
        odors = self.verify.trial_odors
        go = self.verify.trial_go
        PredictionGrid = Factory.get('PredictionGrid')
        TrialPrediction = Factory.get('TrialPrediction')

        predict.clear_widgets()
        for block in range(len(odors)):
            block_grid = PredictionGrid()
            predict_add(block_grid)
            block_add = block_grid.add_widget
            for trial in range(len(odors[block])):
                trial_wid = TrialPrediction(odor=odors[block][trial],
                    go=go[block][trial], trial=trial)
                block_add(trial_wid)

        rem = outcome_container.remove_widget
        children = outcome_container.children[:]
        outcome_container.add_widget(outcome_wid)
        for wid in children:
            rem(wid)
        self._has_dummy_outcome = True

    def pre_block(self):
        self.total_fail = self.total_pass = 0

    def post_block(self):
        verify = self.verify
        verify.trial_odors = []
        verify.trial_go = []
        verify.reward = []
        verify.iti = []

    def pre_trial(self):
        block, trial = self.block.count, self.trial.count
        outcome_wid = self.outcome_wids[block][trial]
        outcome = self.outcome = outcome_wid.outcome

        outcome.block = block
        outcome.trial = trial
        outcome.trial_start_ts = clock()
        outcome.is_go = self.verify.trial_go[block][trial]
        if self._has_dummy_outcome:
            self._has_dummy_outcome = False
            return

        outcome_container = App.get_running_app().outcome_container
        outcome_container.add_widget(outcome_wid,
                                     len(outcome_container.children))
        if len(outcome_container.children) > 5:
            outcome_container.remove_widget(outcome_container.children[0])

    def do_decision(self, timed_out):
        verify, block, trial = self.verify, self.block, self.trial
        outcome = self.outcome
        app = App.get_running_app()

        verify.compute_reward(block.count, trial.count, not timed_out)
        if not timed_out:
            outcome.reward_entery_ts = clock()
        outcome.went = not timed_out
        outcome.rewarded = verify.reward[block.count][trial.count]
        outcome.iti = verify.iti[block.count][trial.count]
        outcome.passed = (not timed_out and outcome.is_go or
                          not outcome.is_go and timed_out)

        if outcome.passed:
            self.total_pass += 1
        else:
            self.total_fail += 1
        blocks = app.prediction_container.children
        trials = blocks[len(blocks) - self.block.count - 1].children
        trials[len(trials) - self.trial.count - 1].outcome = outcome.passed

    def post_trial(self):
        self.outcomes[self.block.count].append(self.outcome)
