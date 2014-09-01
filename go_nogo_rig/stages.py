'''The stages of the experiment.
'''


from functools import partial
import traceback
from time import clock, strftime
from re import match, compile
from os.path import join, isfile
import csv
from random import choice

from moa.stage import MoaStage
from moa.threads import ScheduledEventLoop
from moa.tools import ConfigPropertyList, to_bool
from moa.compat import unicode_type

from kivy.app import App
from kivy.properties import (ObjectProperty, ListProperty,
    ConfigParserProperty, NumericProperty, BooleanProperty,
    StringProperty)
from kivy.clock import Clock
from kivy.factory import Factory

from go_nogo_rig.devices import Server, FTDIDevChannel, FTDIOdors,\
    FTDIOdorsSim, FTDIPin, FTDIPinSim, DAQInDevice, DAQInDeviceSim,\
    DAQOutDevice, DAQOutDeviceSim
from go_nogo_rig import exp_config_name


odor_method_pat = compile('random([0-9]*)')
odor_pat = compile('p[0-9]+')


class RootStage(MoaStage):
    '''The root stage of the experiment. This stage contains all the other
    experiment stages.
    '''

    def on_finished(self, *largs, **kwargs):
        '''Executed after the root stage and all sub-stages finished. It stops
        all the devices.
        '''
        if self.finished:
            def clear_app(*l):
                app = App.get_running_app()
                app.app_state = 'clear'
                app.exp_status = 0
            barst = self.barst
            barst.clear_events()
            barst.start_thread()
            barst.request_callback('stop_devices', clear_app)
            fd = self.animal_stage._fd
            if fd is not None:
                fd.close()


class InitBarstStage(MoaStage, ScheduledEventLoop):
    '''The stage that creates and initializes all the Barst devices (or
    simulation devices if :attr:`ExperimentApp.simulate`).
    '''

    # if a device is currently being initialized by the secondary thread.
    _finished_init = False
    # if while a device is initialized, stage should stop when finished.
    _should_stop = None

    simulate = BooleanProperty(False)
    '''If True, virtual devices should be used for the experiment. Otherwise
    actual Barst devices will be used. This is set to the same value as
    :attr:`ExperimentApp.simulate`.
    '''

    server = ObjectProperty(None, allownone=True)
    '''The :class:`Server` instance. When :attr:`simulate`, this is None. '''

    ftdi_chan = ObjectProperty(None, allownone=True)
    '''The :class:`FTDIDevChannel` instance. When :attr:`simulate`, this is
    None.
    '''

    pin_dev = ObjectProperty(None, allownone=True, rebind=True)
    '''The :class:`FTDIPin` instance, or :class:`FTDIPinSim` instance when
    :attr:`simulate`.
    '''

    odor_dev = ObjectProperty(None, allownone=True, rebind=True)
    '''The :class:`FTDIOdors` instance, or :class:`FTDIOdorsSim` instance when
    :attr:`simulate`.
    '''

    daq_in_dev = ObjectProperty(None, allownone=True, rebind=True)
    '''The :class:`DAQInDevice` instance, or :class:`DAQInDeviceSim` instance
    when :attr:`simulate`.
    '''

    daq_out_dev = ObjectProperty(None, allownone=True, rebind=True)
    '''The :class:`DAQOutDevice` instance, or :class:`DAQOutDeviceSim`
    instance when :attr:`simulate`.
    '''

    exception_callback = None
    '''The partial function that has been scheduled to be called by the kivy
    thread when an exception occurs. This function must be unscheduled when
    stopping, in case there are waiting to be called after it already has been
    stopped.
    '''

    def __init__(self, **kw):
        super(InitBarstStage, self).__init__(**kw)
        self.simulate = App.get_running_app().simulate

    def recover_state(self, state):
        # When recovering stage, even if finished before, always redo it
        # because we need to init the Barst devices, so skip `finished`.
        state.pop('finished', None)
        return super(InitBarstStage, self).recover_state(state)

    def clear(self, *largs, **kwargs):
        self._finished_init = False
        self._should_stop = None
        return super(InitBarstStage, self).clear(*largs, **kwargs)

    def unpause(self, *largs, **kwargs):
        # if simulating, we cannot be in pause state
        if super(InitBarstStage, self).unpause(*largs, **kwargs):
            if self._finished_init:
                # when unpausing, just continue where we were
                self.finish_start_devices()
            return True
        return False

    def stop(self, *largs, **kwargs):
        if self.started and not self._finished_init and not self.finished:
            self._should_stop = largs, kwargs
            return False
        return super(InitBarstStage, self).stop(*largs, **kwargs)

    def step_stage(self, *largs, **kwargs):
        if not super(InitBarstStage, self).step_stage(*largs, **kwargs):
            return False

        # if we simulate, create the sim devices, otherwise the barst devices
        if self.simulate:
            self.create_sim_devices()
            self.step_stage()
            return True

        try:
            self.create_devices()
            self.request_callback('start_devices',
                                  callback=self.finish_start_devices)
        except Exception as e:
            App.get_running_app().device_exception((e, traceback.format_exc()))

        return True

    def create_sim_devices(self):
        '''Creates simulated versions of the barst devices.
        '''
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

    def create_devices(self):
        server = self.server = Server()
        server.create_device()
        barst_server = server.target
        ftdi = self.ftdi_chan = FTDIDevChannel()
        pin = self.pin_dev = FTDIPin()
        odors = self.odor_dev = FTDIOdors()
        ftdi.create_device([odors.get_settings(), pin.get_settings()],
                           barst_server)
        daqin = self.daq_in_dev = DAQInDevice()
        daqout = self.daq_out_dev = DAQOutDevice()
        daqin.create_device(barst_server)
        daqout.create_device(barst_server)

    def start_devices(self):
        self.server.start_channel()
        x = self.ftdi_chan.start_channel()
        print x
        self.odor_dev.target, self.pin_dev.target = x
        print self.odor_dev.target, self.pin_dev.target
        self.odor_dev.start_channel()
        self.pin_dev.start_channel()
        self.daq_in_dev.start_channel()
        self.daq_out_dev.start_channel()

    def finish_start_devices(self, *largs):
        self._finished_init = True
        should_stop = self._should_stop
        if should_stop is not None:
            super(InitBarstStage, self).stop(*should_stop[0], **should_stop[1])
            return
        if self.paused:
            return

        self.pin_dev.activate(self)
        self.odor_dev.activate(self)
        self.daq_in_dev.activate(self)
        self.daq_out_dev.activate(self)
        self.step_stage()

    def handle_exception(self, exception, event):
        '''The overwritten method called by the devices when they encounter
        an exception.
        '''
        callback = self.exception_callback = partial(
            App.get_running_app().device_exception, exception, event)
        Clock.schedule_once(callback)

    def stop_devices(self):
        '''Called from :class:`InitBarstStage` internal thread. It stops
        and clears the states of all the devices, except the ftdi pin devices
        to leave the pump high so it doesn't discharge.
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

        unschedule(self.exception_callback)
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
    '''If the odor method (``val``) matches a odor method it returns ``val``,
    otherwise it raises an exception.

    Possible methods are `constant`, `list`, or `randomx`.
    '''
    if val in ('constant', 'list') or match(odor_method_pat, val):
        return val
    else:
        raise Exception('"{}" does not match an odor method'.format(val))


class VerifyConfigStage(MoaStage):
    '''Stage that is run before the first block of each animal.

    The stage verifies that all the experimental parameters are correct and
    computes all the values, e.g. odors needed for the trials.

    If the values are incorrect, it calls :meth:`ExperimentApp.device_exception`
    with the exception.
    '''

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
        '''Verifies that all the paramters are correct and computes the odors
        and go/nogo for each trial in each block.
        '''
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
        '''Takes the current ``block``, ``trial``, and whether the animal
        ``went`` or didn't go to the reward port and returns a 2-tuple of
        whether the animal should be rewarded, and the ITI for this trial.
        '''
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

        return reward, iti

    trial_odors = ListProperty(None, allownone=True)
    '''A 2d list of the odors for each trial in each block. '''

    trial_go = ListProperty(None, allownone=True)
    '''A 2d list of whether it's a go or nogo for each trial in each block. '''

    num_blocks = ConfigParserProperty(1, 'Experiment', 'num_blocks',
                                      exp_config_name, val_type=int)
    '''The number of blocks to run. Each block runs :attr:`num_trials` trials.
    '''

    num_trials = ConfigPropertyList(1, 'Experiment', 'num_trials',
                                      exp_config_name, val_type=int)
    '''A list of the number of trials to run for each block in
    :attr:`num_blocks`.
    '''

    wait_for_nose_poke = ConfigPropertyList(True, 'Experiment',
        'wait_for_nose_poke', exp_config_name, val_type=to_bool)
    '''A list of, for each block in :attr:`num_blocks`, whether to wait for a
    nose poke, or if to immediately go to the reward stage. When False,
    entering the reward port will dispense reward and end the trial. The ITI
    will then be :attr:`base_iti` for that block.
    '''

    min_nose_poke = ConfigPropertyList(0, 'Experiment', 'min_nose_poke',
                                       exp_config_name, val_type=float)
    '''A list of, for each block in :attr:`num_blocks`, the minimum duration
    in the nose port. A nose port exit less than this duration will result
    in an incomplete trial. The ITI will then be :attr:`incomplete_iti`.

    If zero, there is no minimum.
    '''

    max_nose_poke = ConfigPropertyList(1, 'Experiment', 'max_nose_poke',
                                       exp_config_name, val_type=float)
    '''A list of, for each block in :attr:`num_blocks`, the maximum duration
    of the nose port stage. After this duration, the stage will terminate and
    proceed to the decision stage even if the animal is still in the nose port.

    If zero, there is no maximum.
    '''

    decision_duration = ConfigPropertyList(1, 'Experiment',
        'decision_duration', exp_config_name, val_type=float)
    '''A list of, for each block in :attr:`num_blocks`, the maximum duration
    of the decision stage. After this duration, the stage will terminate and
    proceed to the ITI stage even if the animal didn't visit the reward port.

    The decision determines whether a reward is dispensed and the duration of
    the ITI.

    If zero, there is no maximum.
    '''

    odor_method = ConfigPropertyList('constant', 'Experiment',
        'odor_method', exp_config_name, val_type=verify_odor_method)
    '''A list of, for each block in :attr:`num_blocks`, the method used to
    determine which odor to use in the trials. Possible methods are `constant`,
    `randomx`, or `list`. :attr:`odor_selection` is used to select the odor
    to be used with this method.

        `constant`:
            ``odor_selection`` is a 2d list of odors, each odor in the list
            is applied to all the trials of that block. Each inner list in the
            2d list (line) can only have a single odor listed.
        `randomx`: x is a number or empty
            ``odor_selection`` is a 2d list of odors. Each inner list is a
            list of odors from which the trial odor would be randomly selected
            from. If the method is ``random``, the odor is randomly selected
            from that list. If random is followed by an integer, e.g.
            ``random2``, then it's random with the condition that no odor can
            be repeated more then x (2 in this) times successively.
        `list`:
            ``odor_selection`` is a 2d list of filenames. The files are
            read for each block and the odors listed in the file is used for
            the trials.

            The structure of the text file is a line for each block. Each line
            is a comma separated list, with the first column being the block
            number and the other column the odors to use for that block.

            Each inner list in the 2d list (line) can only have a
            single filename for that block.

    Defaults to `constant`.
    '''

    odor_selection = ConfigPropertyList('p1', 'Experiment',
        'odor_selection', exp_config_name, val_type=unicode_type,
        inner_list=True)
    '''A list of, for each block in :attr:`num_blocks`, a list of odors to
    select from for each block. See :attr:`odor_method`.
    '''

    odor_NO = ConfigPropertyList('p0', 'Experiment', 'odor_NO',
                                 exp_config_name, val_type=unicode_type)
    '''A list of, for each block in :attr:`num_blocks`, the normally open
    (mineral oil) odor valve. I.e. the valve which is normally open and closes
    during the trial when the odor is released.

    Defaults to ``p0``.
    '''

    odor_path = ConfigParserProperty(u'odor_list.txt', 'Experiment',
        'Odor_list_path', exp_config_name, val_type=unicode_type)
    '''The filename of a file containing the names of odors and whether each
    odor is a go or nogo. The structure of the file is as follows: each line
    describes an odor and is a 3-column comma separated list of
    ``(idx, name, go)``, where idx is the zero-based valve index. name is the
    odor name. And go is a bool and is True, if that odor is a go, and False
    otherwise.

    An example file is::

        1, mineral oil, 0
        4, citric acid, 1
        5, limonene, 1
        ...
    '''

    odors = ListProperty(None)
    '''List of 2-tuples for all the odors, 1st element is odor name, second
    element is either empty string, 'NOGO', or 'GO' string.
    '''

    base_iti = ConfigPropertyList(1, 'Experiment', 'base_iti', exp_config_name,
                                  val_type=float)
    '''A list of, for each block in :attr:`num_blocks`, the ITI duration when
    the nose poke stage is skipped and the animal is always rewarded.
    '''

    go_iti = ConfigPropertyList(1, 'Experiment', 'go_iti', exp_config_name,
                                val_type=float)
    '''A list of, for each block in :attr:`num_blocks`, the ITI duration when
    the the animal goes to the reward port in a go trial.
    '''

    no_go_iti = ConfigPropertyList(1, 'Experiment', 'no_go_iti',
                                   exp_config_name, val_type=float)
    '''A list of, for each block in :attr:`num_blocks`, the ITI duration when
    the the animal does not to the reward port in a nogo trial.
    '''

    false_go_iti = ConfigPropertyList(1, 'Experiment', 'false_go_iti',
                                      exp_config_name, val_type=float)
    '''A list of, for each block in :attr:`num_blocks`, the ITI duration when
    the the animal goes to the reward port in a nogo trial.
    '''

    false_no_go_iti = ConfigPropertyList(1, 'Experiment', 'false_no_go_iti',
                                         exp_config_name, val_type=float)
    '''A list of, for each block in :attr:`num_blocks`, the ITI duration when
    the the animal does not go to the reward port in a go trial.
    '''

    incomplete_iti = ConfigPropertyList(1, 'Experiment', 'incomplete_iti',
                                        exp_config_name, val_type=float)
    '''A list of, for each block in :attr:`num_blocks`, the ITI duration when
    the animal stays in the nose port less than the :attr:`min_nose_poke` if
    non-zero.
    '''


class AnimalStage(MoaStage):
    '''In this stage, each loop runs another animal and its blocks and trials.
    '''

    _filename = ''
    _fd = None

    animal_id = StringProperty('')
    '''The animal id of the current animal. '''

    trial_start_ts = None
    '''The start time of the trial. '''

    nose_poke_ts = None
    '''The time of the nose port entry. '''

    nose_poke_exit_ts = None
    '''The time of the nose port exit. '''

    reward_entery_ts = None
    '''The time of the reward port exit. '''

    odor = ''
    '''The odor name of the current trial. '''

    is_go = None
    '''Whether the current trial is a go (True) or nogo (False). '''

    went = None
    '''Whether the animal went to the reward port in time for this trial. '''

    passed = None
    '''If the animal passed this trial. '''

    reward = BooleanProperty(False)
    '''If this trial will be rewarded. '''

    iti = NumericProperty(0)
    '''The ITI of this trial. '''

    wait_for_nose_poke = BooleanProperty(False)
    '''Whether to wait for nose port entry or skip to the reward entery stage
    for the trial.
    '''

    incomplete = BooleanProperty(False)
    '''Whether this trial was an incomplete. '''

    outcome_wid = None
    '''The widget describing the current trial in the list. '''

    total_pass = NumericProperty(0)
    '''Total number of passed trials for this block. '''

    total_fail = NumericProperty(0)
    '''Total number of failed trials for this block. '''

    total_incomplete = NumericProperty(0)
    '''Total number of incomplete trials for this block. '''

    log_filename = ConfigParserProperty('', 'Experiment', 'log_filename',
                                        exp_config_name, val_type=unicode_type)

    def recover_state(self, state):
        state.pop('finished', None)
        return super(AnimalStage, self).recover_state(state)

    def post_verify(self):
        '''Executed after the :class:`VerifyConfigStage` stage finishes. '''
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
        '''Executed before each block. '''
        self.total_fail = self.total_pass = self.total_incomplete = 0
        self.wait_for_nose_poke = \
            self.verify.wait_for_nose_poke[self.block.count]

    def pre_trial(self):
        '''Executed before each trial. '''
        container = App.get_running_app().outcome_container
        self.outcome_wid = widget = container.children[0]
        container.remove_widget(widget)
        container.add_widget(widget, len(container.children))

        block, trial = self.block.count, self.trial.count
        widget.init_outcome(self.animal_id, block, trial)
        self.trial_start_ts = clock()
        widget.is_go = self.is_go = self.verify.trial_go[block][trial]
        self.odor = self.verify.trial_odors[block][trial]
        self.trial_went = self.reward = self.incomplete = False
        self.iti = 0

    def do_nose_poke(self):
        '''Executed after the first nose port entry of the trial. '''
        self.nose_poke_ts = clock()
        self.outcome_wid.ttnp = self.nose_poke_ts - self.trial_start_ts

    def do_nose_poke_exit(self, timed_out):
        '''Executed after the first nose port exit of the trial. '''
        wid = self.outcome_wid
        te = self.nose_poke_exit_ts = clock()
        wid.tinp = te - self.nose_poke_ts
        if not timed_out:
            block = self.block.count
            min_poke = self.verify.min_nose_poke[block]
            self.incomplete = wid.incomplete = \
                min_poke > 0 and wid.tinp < min_poke
            if self.incomplete:
                self.total_incomplete += 1
                self.passed = wid.passed = False
                self.reward = wid.rewarded = False
                verify = self.verify
                self.iti = wid.iti = verify.incomplete_iti[block]

                blocks = App.get_running_app().prediction_container.children
                trials = blocks[len(blocks) - block - 1].children
                predict = trials[len(trials) - self.trial.count - 1]
                predict.outcome = False
                predict.outcome_text = 'INC'

    def do_decision(self, timed_out):
        '''Executed after the reward port entry or after waiting for the
        reward port entry timed out. '''
        verify, block, trial = self.verify, self.block, self.trial
        wid = self.outcome_wid

        if not self.wait_for_nose_poke:
            ts = self.reward_entery_ts = clock()
            wid.ttrp = ts - self.trial_start_ts
            wid.went = self.went = True
            self.reward = wid.rewarded = True
            self.iti = wid.iti = verify.base_iti[block.count]
            wid.passed = self.passed = True
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
            ts = self.reward_entery_ts = clock()
            wid.ttrp = ts - self.nose_poke_exit_ts
        wid.went = self.went = not timed_out
        self.reward = wid.rewarded = reward
        self.iti = wid.iti = iti
        passed = wid.passed = self.passed = \
            not timed_out and self.is_go or not self.is_go and timed_out

        if self.passed:
            self.total_pass += 1
        else:
            self.total_fail += 1
        blocks = App.get_running_app().prediction_container.children
        trials = blocks[len(blocks) - block.count - 1].children
        predict = trials[len(trials) - trial.count - 1]
        predict.outcome = passed
        predict.outcome_text = 'PASS' if passed else 'FAIL'

    def post_trial(self):
        '''Executed after each trial. '''
        fname = strftime(self.log_filename.format(**{'trial': self.trial.count,
            'block': self.block.count, 'animal': self.animal_id}))
        filename = self._filename

        if filename != fname:
            if not fname:
                return
            fd = self._fd
            if fd is not None:
                fd.close()
            fd = self._fd = open(fname, 'a')
            fd.write('time,ID,block,trial,ttnp,tinp,ttrp,odor,is_go,went,'
                     'incomplete,passed,rewarded,iti\n')
            self._filename = fname
        elif not filename:
            return
        else:
            fd = self._fd

        wid = self.outcome_wid
        vals = [strftime('log_{animal}_%m-%d-%y'),
                "'{}'".format(self.animal_id), self.block.count,
                self.trial.count, wid.ttnp, wid.tinp, wid.ttrp, self.odor,
                self.is_go, self.went, self.incomplete, self.passed,
                self.reward, self.iti]
        for i, val in enumerate(vals):
            if val is None:
                vals[i] = ''
            elif isinstance(val, bool):
                vals[i] = str(int(val))
        fd.write(','.join(map(str, vals)))
        fd.write('\n')
