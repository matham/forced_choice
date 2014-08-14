

from functools import partial
import traceback
from time import clock
from re import match, compile
from os.path import join, isfile
import csv
from random import choice

from moa.stage import MoaStage
from moa.threads import ScheduledEventLoop
from moa.tools import ConfigPropertyList, to_bool
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


odor_method_pat = compile('random([0-9]*)')
odor_pat = compile('p[0-9]+')


class RootStage(MoaStage):

    def on_finished(self, *largs, **kwargs):
        if self.finished:
            def clear_app(*l):
                app = App.get_running_app()
                app.app_state = 'clear'
                app.exp_status = 0
            self.barst.request_callback('stop_devices', clear_app)


class InitBarstStage(MoaStage, ScheduledEventLoop):

    _current_step = ''
    _is_running = False
    _should_stop = False

    simulate = BooleanProperty(False)
    '''If True, virtual devices should be used for the experiment. Otherwise
    actual Barst devices will be used.
    '''

    server = ObjectProperty(None, allownone=True)

    ftdi_chan = ObjectProperty(None, allownone=True)

    pin_dev = ObjectProperty(None, allownone=True, rebind=True)

    odor_dev = ObjectProperty(None, allownone=True, rebind=True)

    daq_in_dev = ObjectProperty(None, allownone=True, rebind=True)

    daq_out_dev = ObjectProperty(None, allownone=True, rebind=True)

    def __init__(self, **kw):
        super(InitBarstStage, self).__init__(**kw)
        self.simulate = App.get_running_app().simulate

    def recover_state(self, state):
        ''' When recovering this stage, even if finished before, always redo it
        because we need to init the Barst devices, so skip `finished`.
        '''
        state.pop('finished', None)
        return super(InitBarstStage, self).recover_state(state)

    def clear(self, *largs, **kwargs):
        self._is_running = False
        self._current_step = ''
        self._should_stop = False
        return super(InitBarstStage, self).clear(*largs, **kwargs)

    def unpause(self, *largs, **kwargs):
        # if simulating, we cannot be in pause state
        if super(InitBarstStage, self).unpause(*largs, **kwargs):
            if not self._is_running and self._current_step:
                # when unpausing, just continue where we were
                self.create_barst_devices(self._current_step)
            return True
        return False

    def stop(self, *largs, **kwargs):
        # if the stage is done pass it on, otherwise stop it later on callback
        if self._current_step:
            self._should_stop = True
        return super(InitBarstStage, self).stop(*largs, **kwargs)

    def step_stage(self, *largs, **kwargs):
        if not super(InitBarstStage, self).step_stage(*largs, **kwargs):
            return False

        # if we simulate, create the sim devices, otherwise the barst devices
        if self.simulate:
            self.create_sim_devices()
            self.step_stage()
            return

        server = self.server = Server()
        self._is_running = True
        server.start_device(partial(self.create_barst_devices, 'server'))
        return True

    def create_sim_devices(self):
        app = App.get_running_app()
        ids = app.simulation_devices.ids
        odors = ids['odors2'].children + ids['odors1'].children
        N = len(odors)
        self.odor_dev = FTDIOdorsSim(mapping={'p{}'.format(i):
            odors[N - i - 1].__self__ for i in range(N)})
        self.pin_dev = FTDIPinSim(mapping={'pump': ids['pump'].__self__})
        self.daq_in_dev = DAQInDeviceSim(mapping={
            'nose_beam': ids['nose_beam'].__self__,
            'reward_beam_r': ids['reward_beam_r'].__self__})
        self.daq_out_dev = DAQOutDeviceSim(mapping={
            'house_light': ids['house_light'].__self__,
            'stress_light': ids['stress_light'].__self__})

        self.pin_dev.activate(self)
        self.odor_dev.activate(self)
        self.daq_in_dev.activate(self)
        self.daq_out_dev.activate(self)

    def create_barst_devices(self, state, *largs):
        self._current_step = state
        if self._should_stop:
            return
        if self.paused:
            self._is_running = False
            return

        try:
            if state == 'server':
                chan = self.ftdi_chan = FTDIDevChannel()
                ftdi_pin = self.pin_dev = FTDIPin()
                odors = self.odor_dev = FTDIOdors()
                chan.start_device(partial(self.create_barst_devices, 'ftdi'),
                    [odors.get_settings(), ftdi_pin.get_settings()],
                    self.server.target)
            elif state == 'ftdi':
                self.odor_dev.target, self.pin_dev.target = largs[0]
                self.odor_dev.start_device(partial(self.create_barst_devices,
                                                   'odors'))
            elif state == 'odors':
                self.pin_dev.start_device(partial(self.create_barst_devices,
                                                 'ftdi_pin'))
            elif state == 'ftdi_pin':
                daq = self.daq_in_dev = DAQInDevice()
                daq.start_device(partial(self.create_barst_devices, 'daq_in'),
                                 self.server.target)
            elif state == 'daq_in':
                daq = self.daq_out_dev = DAQOutDevice()
                daq.start_device(partial(self.create_barst_devices, 'daq_out'),
                                 self.server.target)
            elif state == 'daq_out':
                self.pin_dev.activate(self)
                self.odor_dev.activate(self)
                self.daq_in_dev.activate(self)
                self.daq_out_dev.activate(self)
                self._current_step = ''
                self.step_stage()
            else:
                assert False
        except Exception as e:
            App.get_running_app().device_exception((e, traceback.format_exc()))

    def stop_devices(self):
        '''Called from barst internal thread.
        If join, thread will wait for other threads to finish.
        '''
        pin_dev = self.pin_dev
        odor_dev = self.odor_dev
        daq_in_dev = self.daq_in_dev
        daq_out_dev = self.daq_out_dev
        ftdi_chan = self.ftdi_chan
        for dev in (pin_dev, odor_dev, daq_in_dev, daq_out_dev):
            if dev is not None:
                dev.deactivate(self)

        if self.simulate:
            self.stop_thread()
            return
        unschedule = Clock.unschedule

        for dev in (self.server, self.ftdi_chan, pin_dev, odor_dev, daq_in_dev,
                    daq_out_dev):
            if dev is not None:
                unschedule(dev.exception_callback)
                dev.stop_thread(True)
                dev.clear_events()

        f = []
        if daq_out_dev is not None:
            mapping = daq_out_dev.mapping
            mask = 0
            for val in mapping.values():
                mask |= 1 << val
            f.append(partial(daq_out_dev.target.write, mask=mask, value=0))

        if odor_dev is not None and odor_dev.target is not None:
            f.append(partial(odor_dev.target.write,
                             set_low=range(8 * self.num_boards)))
        if ftdi_chan is not None and ftdi_chan.target is not None:
            f.append(ftdi_chan.target.close_channel_server)
        if daq_in_dev is not None and daq_in_dev.target is not None:
            f.append(daq_in_dev.target.close_channel_server)

        for fun in f:
            try:
                fun()
            except:
                pass
        self.stop_thread()


def verify_odor_method(val):
    '''If the odor method matches a odor method it returns the odor,
    otherwise it raises and exception.

    Possible methods are `constant`, `list`, or `randomx`
    '''
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

        try:
            self.verify_stage()
        except Exception as e:
            App.get_running_app().device_exception((e, traceback.format_exc()))
            return
        self.step_stage()
        return True

    def verify_stage(self):
        odor_NO = self.odor_NO
        odor_method = self.odor_method
        odor_selection = self.odor_selection
        num_trials = self.num_trials
        num_blocks = self.num_blocks
        app = App.get_running_app()
        odor_go = {}

        # now read the odor list
        odor_path = self.odor_path
        if not isfile(odor_path):
            odor_path = join(app.data_directory, odor_path)
        with open(odor_path, 'rb') as fh:
            odors = [('p{}'.format(i), '') for i in
                     range(8 * app.base_stage.barst.odor_dev.num_boards)]
            for row in csv.reader(fh):
                row = [elem.strip() for elem in row]
                go = bool(row[2] and int(row[2]))
                odor_idx = int(row[0])
                odor_go[odors[odor_idx][0]] = go
                odors[odor_idx] = row[1], 'GO' if go else 'NOGO'
            self.odors = odors

        # make sure the number of blocks match, otherwise, fill it up
        for item in (self.false_no_go_iti, self.false_go_iti,
                     self.no_go_iti, self.go_iti, self.base_iti, odor_NO,
                     odor_method, odor_selection, self.decision_duration,
                     self.max_nose_poke, num_trials, self.min_nose_poke,
                     self.wait_for_nose_poke, self.incomplete_iti):
            if len(item) > num_blocks:
                raise Exception('The size of {} is not equal to the number '
                                'of blocks, {}'.format(item, num_blocks))
            elif len(item) < num_blocks:
                item += [item[-1]] * (num_blocks - len(item))

        # now generate the actual trial odors
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
                matched = [match(odor_pat, o) for o in odors[i]]
                if not all(matched):
                    raise Exception('not all odors in "{}" '
                    'matched the "p[0-9]+" pattern for block {}'
                    .format(odors[i], i))

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
                            while (len(rand_odors) >= condition and
                                   all([t == o for t in
                                        rand_odors[-condition:]])):
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

        return reward, iti + self.base_iti[block]

    trial_odors = ListProperty(None, allownone=True)

    trial_go = ListProperty(None, allownone=True)

    num_blocks = ConfigParserProperty(1, 'Experiment', 'num_blocks',
                                      exp_config_name, val_type=int)

    num_trials = ConfigPropertyList(1, 'Experiment', 'num_trials',
                                      exp_config_name, val_type=int)

    wait_for_nose_poke = ConfigPropertyList(True, 'Experiment',
        'wait_for_nose_poke', exp_config_name, val_type=to_bool)

    min_nose_poke = ConfigPropertyList(0, 'Experiment', 'min_nose_poke_dur',
                                       exp_config_name, val_type=float)

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
    '''List of 2-tuples for all the odors, 1st element is odor name, second
    element is either empty string, 'NOGO', or 'GO' string.
    '''

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

    incomplete_iti = ConfigPropertyList(1, 'Experiment', 'incomplete_iti',
                                        exp_config_name, val_type=float)


class TrialOutcomeStats(object):

    block = 0

    trial = 0

    trial_start_ts = None

    nose_poke_ts = None

    nose_poke_exit_ts = None

    reward_entery_ts = None

    iti = None

    is_go = None

    went = None

    passed = None

    rewarded = None

    incomplete = None


class AnimalStage(MoaStage):

    animal_id = StringProperty('')

    outcomes = ListProperty([])

    outcome = None

    outcome_wid = None

    total_pass = NumericProperty(0)

    total_fail = NumericProperty(0)

    total_incomplete = NumericProperty(0)

    trial_odor = StringProperty('')

    trial_reward = BooleanProperty(False)

    trial_iti = NumericProperty(0)

    wait_for_nose_poke = BooleanProperty(False)

    incomplete = BooleanProperty(False)

    def recover_state(self, state):
        state.pop('finished', None)
        return super(AnimalStage, self).recover_state(state)

    def pre_animal(self):
        pass

    def post_verify(self):
        verify = self.verify
        self.outcomes = [[] for _ in range(verify.num_blocks)]
        block = self.block.count

        predict = App.get_running_app().prediction_container
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

    def pre_block(self):
        self.total_fail = self.total_pass = self.total_incomplete = 0
        self.wait_for_nose_poke = \
            self.verify.wait_for_nose_poke[self.block.count]

    def post_block(self):
        pass

    def pre_trial(self):
        container = App.get_running_app().outcome_container
        self.outcome_wid = widget = container.children[0]
        container.remove_widget(widget)
        container.add_widget(widget, len(container.children))
        outcome = self.outcome = TrialOutcomeStats()

        block, trial = self.block.count, self.trial.count
        widget.init_outcome(self.animal_id, block, trial)
        outcome.block, outcome.trial = block, trial
        outcome.trial_start_ts = clock()
        widget.is_go = outcome.is_go = self.verify.trial_go[block][trial]
        self.trial_odor = self.verify.trial_odors[block][trial]
        self.trial_went = self.trial_reward = self.incomplete = False
        self.trial_iti = 0

    def do_nose_poke(self):
        outcome = self.outcome
        outcome.nose_poke_ts = clock()
        self.outcome_wid.ttnp = outcome.nose_poke_ts - outcome.trial_start_ts

    def do_nose_poke_exit(self, timed_out):
        outcome = self.outcome
        wid = self.outcome_wid
        te = outcome.nose_poke_exit_ts = clock()
        wid.tinp = te - outcome.nose_poke_ts
        if not timed_out:
            block = self.block.count
            self.incomplete = outcome.incomplete = wid.incomplete = \
                wid.tinp < self.verify.min_nose_poke[block]
            if self.incomplete:
                self.total_incomplete += 1
                outcome.passed = wid.passed = False
                self.trial_reward = outcome.rewarded = wid.rewarded = False
                verify = self.verify
                self.trial_iti = outcome.iti = wid.iti = \
                    verify.base_iti[block] + verify.incomplete_iti[block]

                blocks = App.get_running_app().prediction_container.children
                trials = blocks[len(blocks) - block - 1].children
                predict = trials[len(trials) - self.trial.count - 1]
                predict.outcome = False
                predict.outcome_text = 'INC'

    def do_decision(self, timed_out):
        verify, block, trial = self.verify, self.block, self.trial
        outcome = self.outcome
        wid = self.outcome_wid

        if not self.wait_for_nose_poke:
            ts = outcome.reward_entery_ts = clock()
            wid.ttrp = ts - outcome.trial_start_ts
            wid.went = outcome.went = True
            self.trial_reward = outcome.rewarded = wid.rewarded = True
            self.trial_iti = outcome.iti = wid.iti = \
                verify.base_iti[block.count]
            wid.passed = outcome.passed = True
            self.total_pass += 1
            blocks = App.get_running_app().prediction_container.children
            trials = blocks[len(blocks) - block.count - 1].children
            predict = trials[len(trials) - trial.count - 1]
            predict.outcome = True
            predict.outcome_text = 'PASS'
            return

        reward, iti = verify.compute_reward(block.count, trial.count,
                                            not timed_out)

        if not timed_out:
            ts = outcome.reward_entery_ts = clock()
            wid.ttrp = ts - outcome.nose_poke_exit_ts
        wid.went = outcome.went = not timed_out
        self.trial_reward = outcome.rewarded = wid.rewarded = reward
        self.trial_iti = outcome.iti = wid.iti = iti
        passed = wid.passed = outcome.passed = \
            not timed_out and outcome.is_go or not outcome.is_go and timed_out

        if outcome.passed:
            self.total_pass += 1
        else:
            self.total_fail += 1
        blocks = App.get_running_app().prediction_container.children
        trials = blocks[len(blocks) - block.count - 1].children
        predict = trials[len(trials) - trial.count - 1]
        predict.outcome = passed
        predict.outcome_text = 'PASS' if passed else 'FAIL'

    def post_trial(self):
        self.outcomes[self.block.count].append(self.outcome)
