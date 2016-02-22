# -*- coding: utf-8 -*-
'''The stages of the experiment.
'''


from functools import partial
import traceback
from time import clock, strftime
from re import match, compile
from os.path import join, isfile
from math import ceil
import csv
from random import choice, randint, random, shuffle
from collections import defaultdict

from moa.stage import MoaStage
from moa.threads import ScheduledEventLoop
from moa.utils import ConfigPropertyList, to_bool, ConfigPropertyDict
from moa.compat import unicode_type
from moa.base import named_moas as moas
from moa.device.analog import NumericPropertyChannel
from moa.device.digital import ButtonChannel

from kivy.app import App
from kivy.properties import (
    ObjectProperty, ListProperty, ConfigParserProperty, NumericProperty,
    BooleanProperty, StringProperty, OptionProperty)
from kivy.clock import Clock
from kivy.factory import Factory
from kivy import resources

from forced_choice.devices import (
    FTDIOdors, FTDIOdorsSim, DAQInDevice, DAQInDeviceSim, DAQOutDevice,
    DAQOutDeviceSim, FFpyPlayer)

from cplcom import exp_config_name, device_config_name
from cplcom.device.barst_server import Server
from cplcom.device.ftdi import FTDIDevChannel
from cplcom.device.mfc import MFC


odor_method_pat = compile('random([0-9]*)')
odor_name_pat = compile('p[0-9]+')
odor_select_pat = compile('(?:p([0-9]+))(?:\(([0-9\.]+)\))?\
(?:/p([0-9]+)(?:\(([0-9\.]+)\))?)?(?:@\[(.+)\])?')


def extract_odor(odors, block, N):
    # do all the odors in the list match the pattern?
    matched = [match(odor_select_pat, o) for o in odors]
    if not all(matched):
        raise Exception('not all odors in "{}" matched the pattern'
                        ' for block {}'.format(odors, block))

    odor_list = []
    for m in matched:
        oa, pa, ob, pb, rates = m.groups()
        rates = rates or '100'
        oa = int(oa)
        if oa >= N:
            raise Exception('Odor {} is larger than the number of valves, {}'.
                            format(oa, N))
        pa = float(pa) / 100. if pa is not None else 1.
        if ob is not None:
            ob = int(ob)
            if ob >= N:
                raise Exception('Odor {} is larger than the number of valves, '
                                '{}'.format(ob, N))
            pb = float(pb) / 100. if pb is not None else 1.

        rates = [float(v.strip()) / 100. for v in rates.split(';')]
        if not all([0. <= rate <= 1. for rate in rates]):
            raise Exception('Rates, {}, are out of the (0, 100) range'.
                            format(rates))

        rate_group = []
        for rate in rates:
            if ob is not None:
                rate_group.append(((oa, pa, rate), (ob, pb, 1. - rate)))
            else:
                rate_group.append(((oa, pa, rate), ))
        odor_list.append(rate_group)
    return odor_list


class InitBarstStage(MoaStage, ScheduledEventLoop):
    '''The stage that creates and initializes all the Barst devices (or
    simulation devices if :attr:`ExperimentApp.simulate`).
    '''

    # if a device is currently being initialized by the secondary thread.
    _finished_init = False
    # if while a device is initialized, stage should stop when finished.
    _should_stop = None

    server = ObjectProperty(None, allownone=True)
    '''The :class:`Server` instance. When :attr:`simulate`, this is None. '''

    ftdi_chan = ObjectProperty(None, allownone=True)
    '''The :class:`FTDIDevChannel` instance. When :attr:`simulate`, this is
    None.
    '''

    mfc_air = ObjectProperty(None, allownone=True)

    mfc_a = ObjectProperty(None, allownone=True)

    mfc_b = ObjectProperty(None, allownone=True)

    mfc_names = ConfigPropertyDict(
        {'mfc_air': 0, 'mfc_a': 0, 'mfc_b': 0}, 'MFC', 'mfc_names',
        device_config_name, val_type=int, key_type=str)

    odor_dev = ObjectProperty(None, allownone=True)
    '''The :class:`FTDIOdors` instance, or :class:`FTDIOdorsSim` instance when
    :attr:`simulate`.
    '''

    num_boards = ConfigPropertyList(
        1, 'FTDI_odor', 'num_boards', device_config_name, val_type=int)

    daq_in_dev = ObjectProperty(None, allownone=True)
    '''The :class:`DAQInDevice` instance, or :class:`DAQInDeviceSim` instance
    when :attr:`simulate`.
    '''

    daq_out_dev = ObjectProperty(None, allownone=True)
    '''The :class:`DAQOutDevice` instance, or :class:`DAQOutDeviceSim`
    instance when :attr:`simulate`.
    '''

    use_mfc = ConfigParserProperty(
        False, 'MFC', 'use_mfc', device_config_name, val_type=to_bool)

    use_mfc_air = ConfigParserProperty(
        False, 'MFC', 'use_mfc_air', device_config_name, val_type=to_bool)

    sound_file_r = ConfigParserProperty(
        '', 'Sound', 'sound_file_r', device_config_name, val_type=unicode_type)

    sound_file_l = ConfigParserProperty(
        '', 'Sound', 'sound_file_l', device_config_name, val_type=unicode_type)

    sound_r = ObjectProperty(None, allownone=True, rebind=True)

    sound_l = ObjectProperty(None, allownone=True, rebind=True)

    next_animal_dev = ObjectProperty(None, allownone=True)

    exception_callback = None
    '''The partial function that has been scheduled to be called by the kivy
    thread when an exception occurs. This function must be unscheduled when
    stopping, in case there are waiting to be called after it already has been
    stopped.
    '''

    def __init__(self, **kw):
        super(InitBarstStage, self).__init__(**kw)
        self.exclude_attrs = ['finished']

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

        # if we simulate, create them and step immediately
        try:
            if App.get_running_app().simulate:
                self.create_devices()
                self.step_stage()
            else:
                self.create_devices(sim=False)
                self.request_callback(
                    'start_devices', callback=self.finish_start_devices)
        except Exception as e:
            App.get_running_app().device_exception(e)

        return True

    def create_devices(self, sim=True):
        '''Creates simulated versions of the barst devices.
        '''
        daqout = ['ir_leds', 'fans', 'house_light', 'feeder_l', 'feeder_r']
        daqin = ['nose_beam', 'reward_beam_l', 'reward_beam_r']
        ids = App.get_running_app().simulation_devices.ids
        for o in ([ids[x] for x in daqout + daqin + ['sound_l', 'sound_r']]):
            o.state = 'normal'

        if sim:
            odorcls = FTDIOdorsSim
            daqincls = DAQInDeviceSim
            daqoutcls = DAQOutDeviceSim
        else:
            odorcls = FTDIOdors
            daqincls = DAQInDevice
            daqoutcls = DAQOutDevice
        app = App.get_running_app()
        ids = app.simulation_devices.ids

        self.next_animal_dev = ButtonChannel(
            button=app.next_animal_btn.__self__, name='next_animal')
        self.next_animal_dev.activate(self)

        dev_cls = [Factory.get('ToggleDevice'), Factory.get('DarkDevice')]
        odor_btns = ids.odors
        odor_btns.clear_widgets()
        for i in range(self.num_boards[0] * 8):
            odor_btns.add_widget(dev_cls[i % 2](text='p{}'.format(i)))
        odors = self.odor_dev = odorcls(
            name='odors', odor_btns=odor_btns.children,
            N=self.num_boards[0] * 8)

        self.daq_in_dev = daqincls(
            attr_map={k: ids[k].__self__ for k in daqin})
        self.daq_out_dev = daqoutcls(
            attr_map={k: ids[k].__self__ for k in daqout})

        mfc = self.use_mfc
        if mfc or self.use_mfc_air:
            air = self.mfc_names['mfc_air']
            if mfc:
                a = self.mfc_names['mfc_a']
                b = self.mfc_names['mfc_b']
            if sim:
                self.mfc_air = NumericPropertyChannel(
                    channel_widget=ids.mfc_air, prop_name='value')
                if mfc:
                    self.mfc_a = NumericPropertyChannel(
                        channel_widget=ids.mfc_a, prop_name='value')
                    self.mfc_b = NumericPropertyChannel(
                        channel_widget=ids.mfc_b, prop_name='value')
            else:
                self.mfc_air = MFC(
                    channel_widget=ids.mfc_air, prop_name='value', idx=air)
                if mfc:
                    self.mfc_a = MFC(
                        channel_widget=ids.mfc_a, prop_name='value', idx=a)
                    self.mfc_b = MFC(
                        channel_widget=ids.mfc_b, prop_name='value', idx=b)

        f = self.sound_file_r or self.sound_file_l
        if f:
            self.sound_l = FFpyPlayer(button=ids.sound_l)
            self.sound_r = FFpyPlayer(button=ids.sound_r)

        if not sim:
            server = self.server = Server()
            server.create_device()
            ftdi = self.ftdi_chan = FTDIDevChannel()
            ftdi.create_device([odors], server)
            for dev in [
                self.odor_dev, self.daq_in_dev,
                self.daq_out_dev, self.mfc_air, self.mfc_a, self.mfc_b]:
                if dev is not None:
                    dev.create_device(server)
            if self.sound_l is not None:
                self.sound_l.create_device(f)
                self.sound_r.create_device(f, player=self.sound_l.player)
        else:
            for dev in [
                self.odor_dev, self.daq_in_dev, self.daq_out_dev, self.mfc_air,
                self.mfc_a, self.mfc_b, self.sound_l, self.sound_r]:
                if dev is not None:
                    dev.activate(self)

    def start_devices(self):
        for dev in [
            self.server, self.ftdi_chan, self.odor_dev, self.daq_in_dev,
            self.daq_out_dev, self.mfc_air, self.mfc_a, self.mfc_b,
            self.sound_l, self.sound_r]:
            if dev is not None:
                dev.start_channel()

    def finish_start_devices(self, *largs):
        self._finished_init = True
        should_stop = self._should_stop
        if should_stop is not None:
            super(InitBarstStage, self).stop(*should_stop[0], **should_stop[1])
            return
        if self.paused:
            return

        for dev in [
            self.odor_dev, self.daq_in_dev, self.daq_out_dev, self.mfc_air,
            self.mfc_a, self.mfc_b, self.sound_l, self.sound_r]:
            if dev is not None:
                dev.activate(self)
        self.step_stage()

    def handle_exception(self, exception, event):
        '''The overwritten method called by the devices when they encounter
        an exception.
        '''
        callback = self.exception_callback = partial(
            App.get_running_app().device_exception, exception, event)
        Clock.schedule_once(callback)

    def stop_devices(self):
        for dev in [
            self.odor_dev, self.daq_in_dev, self.daq_out_dev, self.mfc_air,
            self.mfc_a, self.mfc_b, self.sound_l, self.sound_r]:
            if dev is not None:
                dev.deactivate(self)

        fd = moas.animal_stage._fd
        if fd is not None:
            fd.close()

        Clock.unschedule(self.exception_callback)
        self.clear_events()
        self.stop_thread(join=True)
        if App.get_running_app().simulate:
            App.get_running_app().app_state = 'clear'
            return

        for dev in [
            self.odor_dev, self.daq_in_dev, self.daq_out_dev, self.mfc_air,
            self.mfc_a, self.mfc_b, self.sound_l, self.sound_r, self.ftdi_chan,
            self.server]:
            if dev is not None:
                dev.stop_device()

        def clear_app(*l):
            App.get_running_app().app_state = 'clear'
        self.start_thread()
        self.request_callback(
            'stop_devices_internal', callback=clear_app, cls_method=True)

    def stop_devices_internal(self):
        '''Called from :class:`InitBarstStage` internal thread. It stops
        and clears the states of all the devices.
        '''
        for dev in [
            self.odor_dev, self.daq_in_dev, self.daq_out_dev, self.mfc_air,
            self.mfc_a, self.mfc_b, self.sound_l, self.sound_r, self.ftdi_chan,
            self.server]:
            try:
                if dev is not None:
                    dev.stop_channel()
            except:
                pass
        self.stop_thread()


class VerifyConfigStage(MoaStage):
    '''Stage that is run before the first block of each animal.

    The stage verifies that all the experimental parameters are correct and
    computes all the values, e.g. odors needed for the trials.

    If the values are incorrect, it calls
    :meth:`ExperimentApp.device_exception` with the exception.
    '''

    def __init__(self, **kw):
        super(VerifyConfigStage, self).__init__(**kw)
        self.exclude_attrs = ['finished']

    def step_stage(self, *largs, **kwargs):
        if not super(VerifyConfigStage, self).step_stage(*largs, **kwargs):
            return False

        try:
            self.read_odors()
            self.ensure_full_blocks()
            self.parse_odors()
            if any(self.sound_dur):
                if not moas.barst.sound_r or not moas.barst.sound_l:
                    raise Exception('Sound selected, but sound files not '
                                    'provided')
            ch = App.get_running_app().simulation_devices.ids.odors.children
            no = int(self.NO_valve[0][1:])
            mix = int(self.mix_valve[0][1:])
            ch[15 - no].background_down = 'dark-blue-led-on-th.png'
            ch[15 - no].background_normal = 'dark-blue-led-off-th.png'
            ch[15 - mix].background_down = 'brown-led-on-th.png'
            ch[15 - mix].background_normal = 'brown-led-off-th.png'
            timer = App.get_running_app().timer
            timer.clear_slices()
            elems = (
                (0, 'Init'), (0, 'Wait NP'),
                (max(self.max_nose_poke), 'NP'),
                (max(self.max_decision_duration), 'Wait HP'),
                (max([max(self.good_iti), max(self.bad_iti),
                      max(self.incomplete_iti)]), 'ITI'))
            for t, name in elems:
                timer.add_slice(name=name, duration=t)
            timer.smear_slices()
        except Exception as e:
            App.get_running_app().device_exception(e)
            return
        self.step_stage()
        return True

    def read_odors(self):
        '''Reads odors from a csv file. Each line is 3, or 4 cols with
        valve index, odor name, and the side of the odor (r, l, rl, lr, or -).
        If using an mfc, the 4th column is either a, or b indicating the mfc
        to use of that valve.
        '''
        N = 8 * moas.barst.num_boards[0]
        use_mfc = moas.barst.use_mfc
        odor_side = ['rl', ] * N
        valve_mfc = [None, ] * N
        odor_name = ['p{}'.format(i) for i in range(N)]

        # now read the odor list
        odor_path = resources.resource_find(self.odor_path)
        with open(odor_path, 'rb') as fh:
            for row in csv.reader(fh):
                row = [elem.strip() for elem in row]
                if use_mfc:
                    i, name, side, mfc = row[:4]
                else:
                    i, name, side = row[:3]
                i = int(i)
                if i >= N:
                    raise Exception('Odor {} is out of bounds: {}'.
                                    format(i, row))

                sides = ('rl', 'lr', 'l', 'r', '-', '')
                if side not in sides:
                    raise Exception('Side {} not recognized. Acceptable '
                                    'values are {}'.format(side, sides))
                if side == 'lr':
                    side = 'rl'
                if side == '':
                    side = '-'
                odor_name[i] = name
                odor_side[i] = side
                if use_mfc:
                    if mfc not in ('a', 'b'):
                        raise Exception('MFC {} not recognized. Acceptable '
                                        'values are a or b'.format(mfc))
                    valve_mfc[i] = 'mfc_a' if mfc == 'a' else 'mfc_b'
        self.odor_side = odor_side
        self.odor_names = odor_name
        self.valve_mfc = valve_mfc

    def ensure_full_blocks(self):
        num_blocks = self.num_blocks
        if num_blocks <= 0:
            raise Exception('Number of blocks is not positive')
        # make sure the number of blocks match, otherwise, fill it up
        for item in (
                self.num_trials, self.wait_for_nose_poke, self.odor_delay,
                self.odor_method, self.odor_selection, self.NO_valve,
                self.min_nose_poke, self.sound_cue_delay,
                self.max_nose_poke, self.sound_dur, self.odor_equalizer,
                self.max_decision_duration, self.bad_iti,
                self.good_iti, self.incomplete_iti, self.num_pellets,
                self.mix_valve):
            if len(item) > num_blocks:
                raise Exception('The size of {} is larger than the number '
                                'of blocks, {}'.format(item, num_blocks))
        if any([x <= 0 for x in self.num_trials]):
            raise Exception('Number of trials is not positive for every block')
        for v in self.NO_valve:
            m = match(odor_name_pat, v)
            if m is None or int(v[1:]) >= 16:
                raise Exception('NO valve {} is not recognized')
        for v in self.mix_valve:
            m = match(odor_name_pat, v)
            if m is None or int(v[1:]) >= 16:
                raise Exception('Mixing valve {} is not recognized')

    def do_equal_random(self, n, m, cond, last_val=None):
        vals = []
        k = n // m
        if n % m:
            raise ValueError("{} odors don't equally divide {}".format(m, n))

        if cond == 1 and m == 2:
            newvals = [0, 1] if last_val is None or last_val else [1, 0]
            for i in range(k):
                vals.extend(newvals)
            return vals

        for i in range(m):
            vals.extend([i, ] * k)
        shuffle(vals)
        if not cond:
            return vals

        if last_val is not None and vals[0] == last_val:
            i = 1
            while vals[i] == last_val:
                i += 1
            vals[0] = vals[i]
            vals[i] = last_val

        # cond is now > 1
        while True:
            dups = [(vals[0], 1)]
            for i, val in enumerate(vals[1:], 1):
                if val == dups[-1][0]:
                    dups.append((val, dups[-1][1] + 1))
                else:
                    dups.append((val, 1))

            first, second = None, None  # first two that violate the cond
            for i, (val, count) in enumerate(dups[::-1]):  # <-- backwards
                i = len(dups) - 1 - i
                if count > cond:
                    if first is None:
                        first = val, i
                    elif first[0] != val:
                        second = val, i
                        break

            if first is None:  # no violators
                return vals

            if first is not None and second is not None:
                # exchange the first with second violator
                val1, i1 = first
                val2, i2 = second
                vals[i1] = val2
                vals[i2] = val1
                continue

            # only one violator, put it in the first place it won't violate
            while True:
                val1, i1 = first
                i = randint(0, len(vals))  # add AFTER i
                if i1 - i >= -1 and i1 - i <= cond:
                    continue

                if i == len(vals):  # it's at the end
                    if vals[-1] != val1 or dups[-1][1] + 1 <= cond:
                        del vals[i1 - 1]
                        vals.append(val1)
                        break
                    continue

                # it's at 0, or last val is different, or we're still under cond
                if not i or vals[i - 1] != val1 or dups[i - 1][1] + 1 <= cond:
                    # how many are will be total
                    count = 1
                    s = i
                    if vals[i - 1] == val1:
                        count += dups[i - 1][1]
                    while s < len(vals) and vals[s] == val1:
                        count += 1
                        s += 1

                    if count <= cond:
                        vals.insert(i, val1)
                    del vals[i1 if i1 < i else i1 + 1]

    def parse_odors(self):
        odor_method = self.odor_method
        odor_equalizer = self.odor_equalizer
        odor_selection = self.odor_selection
        num_trials = self.num_trials
        app = App.get_running_app()
        trial_odors = [None, ] * len(odor_selection)
        wfnp = self.wait_for_nose_poke

        for block, block_odors in enumerate(odor_selection):
            n = num_trials[block]
            if not wfnp[block]:
                trial_odors[block] = [None, ] * n
                continue

            block_odors = [o.strip() for o in block_odors if o.strip()]
            if not len(block_odors):
                raise Exception('no odors specified for block {}'
                                .format(block))

            method = odor_method[block]
            equalizer = odor_equalizer[block]
            # if there's only a filename there, read it for this block
            if method == 'list':
                if len(block_odors) > 1:
                    raise Exception('More than one odor "{}" specified'
                                    'for list odor method'.format(block_odors))

                if not isfile(block_odors[0]):
                    block_odors[0] = join(app.data_directory, block_odors[0])
                with open(block_odors[0], 'rb') as fh:
                    read_odors = list(csv.reader(fh))
                idx = None
                for line_num, row in enumerate(read_odors):
                    if int(row[0]) == block:
                        idx = line_num
                        break

                if idx is None:
                    raise Exception('odors not found for block "{}" '
                                    'in the list'.format(block))
                odors = extract_odor(read_odors[line_num][1:], block, 16)
                if any([len(o) != 1 for o in odors]):
                    raise Exception('Number of flow rates specified for block'
                                    ' {} is not 1: {}'.format(block, odors))
                trial_odors[block] = [o for elems in odors for o in elems]
            # then it's a list of odors to use in the block
            else:

                odors = extract_odor(block_odors, block, 16)
                odors = [o for elems in odors for o in elems]

                # now use the method to generate the odors
                if method == 'constant':
                    if len(odors) > 1:
                        raise Exception(
                            'More than one odor "{}" specified for constant '
                            'odor method'.format(odors))
                    trial_odors[block] = odors * n

                # random
                else:
                    if len(odors) <= 1:
                        raise Exception(
                            'Only one odor "{}" was specified with with random'
                            ' method'.format(odors))
                    m = match(odor_method_pat, method)
                    if m is None:
                        raise Exception('method "{}" does not match a '
                                        'a method'.format(method))

                    # the condition for this random method
                    condition = int(m.group(1)) if m.group(1) else 0
                    if not equalizer:
                        if condition <= 0:  # random without condition
                            trial_odors[block] = [choice(odors) for _ in range(n)]
                        else:
                            rand_odors = []
                            for _ in range(n):
                                o = randint(0, len(odors) - 1)
                                while (len(rand_odors) >= condition and
                                       all([t == o for t in
                                            rand_odors[-condition:]])):
                                    o = randint(0, len(odors) - 1)
                                rand_odors.append(o)
                            trial_odors[block] = [odors[i] for i in rand_odors]
                    else:
                        rand_odors = []
                        for _ in range(int(ceil(n / float(equalizer)))):
                            rand_odors.extend(self.do_equal_random(
                                equalizer, len(odors), condition,
                                last_val=rand_odors[-1] if rand_odors else None))
                        del rand_odors[n:]
                        trial_odors[block] = [odors[i] for i in rand_odors]

        for block, odors in enumerate(trial_odors):
            if len(odors) != num_trials[block]:
                raise Exception(
                    'The number of odors "{}" for block "{}" '
                    'doesn\'t match the number of trials "{}"'.format(
                        odors, block, num_trials[block]))
        self.trial_odors = trial_odors

    num_blocks = ConfigParserProperty(1, 'Experiment', 'num_blocks',
                                      exp_config_name, val_type=int)
    '''The number of blocks to run. Each block runs :attr:`num_trials` trials.
    '''

    num_trials = ConfigPropertyList(1, 'Experiment', 'num_trials',
                                    exp_config_name, val_type=int)
    '''A list of the number of trials to run for each block in
    :attr:`num_blocks`.
    '''

    wait_for_nose_poke = ConfigPropertyList(
        True, 'Experiment', 'wait_for_nose_poke', exp_config_name,
        val_type=to_bool)
    '''A list of, for each block in :attr:`num_blocks`, whether to wait for a
    nose poke, or if to immediately go to the reward stage. When False,
    entering the reward port will dispense reward and end the trial. The ITI
    will then be :attr:`base_iti` for that block.
    '''

    odor_delay = ConfigPropertyList(0, 'Odor', 'odor_delay',
                                    exp_config_name, val_type=float)

    mix_dur = ConfigParserProperty(1.5, 'Odor', 'mix_dur',
                                   exp_config_name, val_type=float)

    air_rate = ConfigParserProperty(0, 'Odor', 'air_rate', exp_config_name,
                                    val_type=float)

    mfc_a_rate = ConfigParserProperty(.1, 'Odor', 'mfc_a_rate',
                                      exp_config_name, val_type=float)

    mfc_b_rate = ConfigParserProperty(.1, 'Odor', 'mfc_b_rate',
                                      exp_config_name, val_type=float)

    def verify_odor_method(val):
        if val in ('constant', 'list') or match(odor_method_pat, val):
            return val
        else:
            raise Exception('"{}" does not match an odor method'.format(val))

    odor_equalizer = ConfigPropertyList(
        0, 'Odor', 'odor_equalizer', exp_config_name, val_type=int)

    odor_method = ConfigPropertyList(
        'constant', 'Odor', 'odor_method', exp_config_name,
        val_type=verify_odor_method)
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

    odor_selection = ConfigPropertyList(
        'p1', 'Odor', 'odor_selection', exp_config_name, val_type=unicode_type,
        inner_list=True)
    '''A list of, for each block in :attr:`num_blocks`, a list of odors to
    select from for each block. See :attr:`odor_method`.
    '''

    def verify_valve_name(val):
        if not match(odor_name_pat, val):
            raise Exception('{} does not match the valve name pattern'.
                            format(val))
        return val

    NO_valve = ConfigPropertyList('p0', 'Odor', 'NO_valve',
                                  exp_config_name, val_type=verify_valve_name)
    '''A list of, for each block in :attr:`num_blocks`, the normally open
    (mineral oil) odor valve. I.e. the valve which is normally open and closes
    during the trial when the odor is released.

    Defaults to ``p0``.
    '''

    mix_valve = ConfigPropertyList('p7', 'Odor', 'mix_valve',
                                   exp_config_name, val_type=verify_valve_name)

    odor_path = ConfigParserProperty(
        u'odor_list.txt', 'Odor', 'Odor_list_path', exp_config_name,
        val_type=unicode_type)
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

    valve_mfc = None

    odor_side = ListProperty([])

    odor_names = ListProperty([])

    def on_odor_names(self, *largs):
        odors = App.get_running_app().simulation_devices.ids.odors
        sides, names = self.odor_side, self.odor_names
        for i, o in enumerate(odors.children[::-1]):
            s = u''
            side = sides[i]
            if 'l' in side:
                s += u'[color=0080FF]L[/color]'
            if 'r' in side:
                s += u'[color=9933FF]R[/color]'
            if '-' == side:
                s = u'[color=FF0000]Ø[/color]'
            o.text = u'{}\n{}'.format(s, names[i])

    trial_odors = None
    '''A 2d list of the odors for each trial in each block. '''

    min_nose_poke = ConfigPropertyList(0, 'Odor', 'min_nose_poke',
                                       exp_config_name, val_type=float)
    '''A list of, for each block in :attr:`num_blocks`, the minimum duration
    in the nose port AFTER the odor is released. A nose port exit less than
    this duration will result
    in an incomplete trial. The ITI will then be :attr:`incomplete_iti`.

    If zero, there is no minimum.
    '''

    sound_cue_delay = ConfigPropertyList(
        0, 'Odor', 'sound_cue_delay', exp_config_name, val_type=float)

    max_nose_poke = ConfigPropertyList(10, 'Odor', 'max_nose_poke',
                                       exp_config_name, val_type=float)
    '''A list of, for each block in :attr:`num_blocks`, the maximum duration
    of the nose port stage. After this duration, the stage will terminate and
    proceed to the decision stage even if the animal is still in the nose port.

    If zero, there is no maximum.
    '''

    sound_dur = ConfigPropertyList(0, 'Sound', 'sound_dur',
                                   exp_config_name, val_type=float)

    max_decision_duration = ConfigPropertyList(
        20, 'Experiment', 'max_decision_duration', exp_config_name,
        val_type=float)
    '''A list of, for each block in :attr:`num_blocks`, the maximum duration
    of the decision stage. After this duration, the stage will terminate and
    proceed to the ITI stage even if the animal didn't visit the reward port.

    The decision determines whether a reward is dispensed and the duration of
    the ITI.

    If zero, there is no maximum.
    '''

    num_pellets = ConfigPropertyList(2, 'Experiment', 'num_pellets',
                                     exp_config_name, val_type=int)

    good_iti = ConfigPropertyList(3, 'ITI', 'good_iti', exp_config_name,
                                  val_type=float)

    bad_iti = ConfigPropertyList(4, 'ITI', 'bad_iti', exp_config_name,
                                 val_type=float)

    incomplete_iti = ConfigPropertyList(4, 'ITI', 'incomplete_iti',
                                        exp_config_name, val_type=float)


class AnimalStage(MoaStage):
    '''In this stage, each loop runs another animal and its blocks and trials.
    '''

    _filename = ''
    _fd = None

    animal_id = StringProperty('')
    '''The animal id of the current animal. '''

    num_trials = NumericProperty(0)

    trial_start_ts = None
    '''The start time of the trial. '''

    trial_start_time = None

    nose_poke_ts = None
    '''The time of the nose port entry. '''

    odor_start_ts = None

    nose_poke_exit_ts = None
    '''The time of the nose port exit. '''

    nose_poke_exit_timed_out = False

    reward_entry_ts = None
    '''The time of the reward port exit. '''

    reward_entry_timed_out = False

    sound = ObjectProperty(None, allownone=True)

    odor = None
    ''' The odor to reward for this trial.
    '''

    side = None
    '''The side of :attr:`odor` to reward.
    '''

    side_went = None
    '''The side the animal visited. '''

    reward_side = OptionProperty(None, options=['feeder_r', 'feeder_l', False,
                                                None], allownone=True)
    '''The side on which to reward this trial. '''

    iti = NumericProperty(0)
    '''The ITI of this trial. '''

    outcome = None
    '''Whether this trial was an incomplete. '''

    outcome_wid = None
    '''The widget describing the current trial in the list. '''

    total_pass = NumericProperty(0)
    '''Total number of passed trials for this block. '''

    total_fail = NumericProperty(0)
    '''Total number of failed trials for this block. '''

    total_incomplete = NumericProperty(0)
    '''Total number of incomplete trials for this block. '''

    outcomes = []

    log_filename = ConfigParserProperty('', 'Experiment', 'log_filename',
                                        exp_config_name, val_type=unicode_type)

    filter_len = ConfigParserProperty(1, 'Experiment', 'filter_len',
                                      exp_config_name, val_type=int)

    def load_attributes(self, state):
        state.pop('finished', None)
        return super(AnimalStage, self).load_attributes(state)

    def post_verify(self):
        '''Executed after the :class:`VerifyConfigStage` stage finishes. '''
        verify = moas.verify
        wfnp = verify.wait_for_nose_poke
        predict = App.get_running_app().root.ids.prediction_container
        predict_add = predict.add_widget
        odors = verify.trial_odors
        names = verify.odor_names
        sides = verify.odor_side
        PredictionGrid = Factory.get('PredictionGrid')
        TrialPrediction = Factory.get('TrialPrediction')

        predict.clear_widgets()
        for block in range(len(odors)):
            block_grid = PredictionGrid()
            predict_add(block_grid)
            block_add = block_grid.add_widget
            w = wfnp[block]
            for trial in range(len(odors[block])):
                if w:
                    odor = odors[block][trial]
                    if len(odor) == 1:
                        odor = odor[0]
                    else:
                        odor = odor[0] if odor[0][2] >= odor[1][2] else odor[1]
                    side = sides[odor[0]]
                    if side == '-':
                        side = u'Ø'
                    trial_wid = TrialPrediction(
                        odor=names[odor[0]], side=side, trial=trial)
                else:
                    trial_wid = TrialPrediction(side='rl', trial=trial)
                block_add(trial_wid)

    def initialize_box(self):
        ''' Turns on fans, lights etc. '''
        moas.barst.daq_out_dev.set_state(high=['ir_leds', 'fans'])

    def pre_block(self):
        '''Executed before each block. '''
        self.total_fail = self.total_pass = self.total_incomplete = 0
        self.num_trials = moas.verify.num_trials[moas.block.count]
        ids = App.get_running_app().root.ids
        for graph in (ids.ttnp, ids.tinp, ids.ttrp, ids.outcome):
            graph.plots[0].points = []
        self.outcomes = []

    def start_mixing(self):
        verify, block, trial = moas.verify, moas.block.count, moas.trial.count
        barst = moas.barst
        if barst.use_mfc:
            pass
        else:
            odors = verify.trial_odors[block][trial]
            barst.odor_dev.set_state(high=['p{}'.format(o[0]) for o in odors] +
                                     [verify.NO_valve[block]])

    def pre_trial(self):
        '''Executed before each trial. '''
        self.trial_start_ts = clock()
        self.trial_start_time = strftime('%H:%M:%S')

        container = App.get_running_app().root.ids.results_container
        self.outcome_wid = widget = container.children[0]
        container.remove_widget(widget)
        container.add_widget(widget, len(container.children))

        block, trial = moas.block.count, moas.trial.count
        verify = moas.verify
        widget.init_outcome(self.animal_id, block, trial)

        self.nose_poke_ts = self.odor_start_ts = self.nose_poke_exit_ts = None
        self.reward_entry_ts = self.sound = self.side_went = None
        self.reward_side = self.outcome = None
        self.reward_entry_timed_out = self.nose_poke_exit_timed_out = False
        self.iti = 0

        if not verify.wait_for_nose_poke[block]:
            self.odor = ''
            self.side = 'rl'
            return

        odor = verify.trial_odors[block][trial]
        if len(odor) == 1:
            self.odor = odor = odor[0]
        else:
            self.odor = odor = odor[0] if odor[0][2] >= odor[1][2] else odor[1]
        widget.side = side = self.side = verify.odor_side[odor[0]]
        if verify.sound_dur[block] and side != '-':
            self.sound = (moas.barst.sound_r if 'r' in side else
                          moas.barst.sound_l)

    def do_nose_poke(self):
        '''Executed after the first nose port entry of the trial. '''
        self.nose_poke_ts = clock()
        ttnp = self.outcome_wid.ttnp = self.nose_poke_ts - self.trial_start_ts
        App.get_running_app().root.ids.ttnp.plots[0].points.append((moas.trial.count, ttnp))

    def do_odor_release(self):
        moas.barst.odor_dev.set_state(
            high=[moas.verify.mix_valve[moas.block.count]])
        self.odor_start_ts = clock()

    def do_nose_poke_exit(self, timed_out):
        '''Executed after the first nose port exit of the trial. '''
        te = self.nose_poke_exit_ts = clock()

        # turn off odor
        verify, block, trial = moas.verify, moas.block.count, moas.trial.count
        barst = moas.barst
        if barst.use_mfc:
            pass
        else:
            odors = verify.trial_odors[block][trial]
            barst.odor_dev.set_state(
                low=['p{}'.format(o[0]) for o in odors] +
                [verify.NO_valve[block], verify.mix_valve[block]])

        self.nose_poke_exit_timed_out = timed_out
        wid = self.outcome_wid
        tinp = wid.tinp = te - self.nose_poke_ts
        App.get_running_app().root.ids.tinp.plots[0].points.append((moas.trial.count, tinp))

        if not timed_out:
            min_poke = moas.verify.min_nose_poke[block]
            if min_poke > 0 and tinp < min_poke:
                self.outcome = 'inc'
                self.reward_side = False
                self.total_incomplete += 1
                wid.passed = False
                wid.incomplete = True
                self.iti = wid.iti = verify.incomplete_iti[block]

                blocks = App.get_running_app().root.ids.prediction_container.children
                trials = blocks[len(blocks) - block - 1].children
                predict = trials[len(trials) - trial - 1]
                predict.outcome = False
                predict.outcome_text = 'INC'
                self.outcomes.append(0)

    def do_decision(self, r, l, timed_out):
        '''Executed after the reward port entry or after waiting for the
        reward port entry timed out. '''
        ts = self.reward_entry_ts = clock()
        verify, block, trial = moas.verify, moas.block.count, moas.trial.count
        wid = self.outcome_wid
        blocks = App.get_running_app().root.ids.prediction_container.children
        trials = blocks[len(blocks) - block - 1].children
        predict = trials[len(trials) - trial - 1]

        side = self.side
        wfnp = verify.wait_for_nose_poke[block]

        self.reward_entry_timed_out = timed_out
        if not timed_out:
            predict.side_went = wid.side_went = side_went = self.side_went = \
                'r' if r else 'l'
            wid.ttrp = ts - (self.nose_poke_exit_ts if self.nose_poke_exit_ts
                             is not None else self.trial_start_ts)
            App.get_running_app().root.ids.ttrp.plots[0].points.append((moas.trial.count,
                                                          wid.ttrp))


        reward = not timed_out and (not wfnp or (
            side == 'rl' or side == side_went) and random() <= self.odor[1])
        predict.outcome = wid.passed = passed = not timed_out and (
            not wfnp or (side == 'rl' or side == side_went))
        self.outcomes.append(int(predict.outcome))

        wid.iti = self.iti = (
            verify.good_iti[block] if passed else verify.bad_iti[block])
        self.reward_side = reward and ('feeder_' + side_went)
        if reward:
            predict.side_rewarded = wid.rewarded = side_went
        self.outcome = 'pass' if passed else 'fail'

        if passed:
            self.total_pass += 1
            predict.outcome_text = 'PASS'
        else:
            self.total_fail += 1
            predict.outcome_text = 'FAIL'

    def post_trial(self):
        '''Executed after each trial. '''
        fname = strftime(self.log_filename.format(**{'trial': moas.trial.count,
            'block': moas.block.count, 'animal': self.animal_id}))
        filename = self._filename
        o = self.outcomes[-self.filter_len:]
        App.get_running_app().root.ids.outcome.plots[0].points.append((
            moas.trial.count, sum(o) / max(1., float(len(o))) * 100))

        if filename != fname:
            if not fname:
                return
            fd = self._fd
            if fd is not None:
                fd.close()
            fd = self._fd = open(fname, 'a')
            fd.write('Date,Time,RatID,Block,Trial,OdorName, OdorIndex,'
                     'TrialSide,SideWent,Outcome,Rewarded?,TTNP,TINP,TTRP,'
                     'ITI\n')
            self._filename = fname
        elif not filename:
            return
        else:
            fd = self._fd

        ts = self.trial_start_ts
        np = self.nose_poke_ts
        ne = self.nose_poke_exit_ts
        rp = self.reward_entry_ts

        odor_idx = self.odor[0]
        outcome = {'fail': 0, 'pass': 1, 'inc': 2, None: None}
        vals = [strftime('%m-%d-%Y'), self.trial_start_time, self.animal_id,
                moas.block.count, moas.trial.count,
                moas.verify.odor_names[odor_idx], 'p{}'.format(odor_idx),
                self.side, self.side_went, outcome[self.outcome],
                bool(self.reward_side), (np - ts) if np else None,
                (ne - np) if ne and np else None,
                (rp - (ne if ne else ts)) if rp else None, self.iti]
        for i, val in enumerate(vals):
            if val is None:
                vals[i] = ''
            elif isinstance(val, bool):
                vals[i] = str(int(val))
        fd.write(','.join(map(str, vals)))
        fd.write('\n')
