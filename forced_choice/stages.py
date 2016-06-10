# -*- coding: utf-8 -*-
'''Stages
===========

The stages of the experiment.
'''

from functools import partial
import traceback
from time import clock, strftime
from re import match, compile
from os.path import join, isfile
from math import ceil
import csv
from random import choice, randint, random, shuffle, uniform
from collections import defaultdict
import numpy as np

from moa.stage import MoaStage
from moa.base import MoaBase
from moa.threads import ScheduledEventLoop
from moa.utils import to_bool
from moa.compat import unicode_type
from moa.device.analog import NumericPropertyChannel
from moa.device.digital import ButtonChannel
from moa.utils import ObjectStateTracker

from kivy.properties import (
    ObjectProperty, ListProperty, ConfigParserProperty, NumericProperty,
    BooleanProperty, StringProperty, OptionProperty, DictProperty)
from kivy.clock import Clock
from kivy.factory import Factory
from kivy.uix.behaviors.knspace import knspace, KNSpaceBehavior
from kivy import resources

from forced_choice.devices import (
    FTDIOdors, FTDIOdorsSim, DAQInDevice, DAQInDeviceSim, DAQOutDevice,
    DAQOutDeviceSim)

from cplcom.moa.device.barst_server import Server
from cplcom.moa.device.ftdi import FTDIDevChannel
from cplcom.moa.device.mfc import MFC
from cplcom.moa.device.ffplayer import FFPyPlayerAudioDevice
from cplcom.moa.app import app_error
from cplcom.moa.stages import ConfigStageBase

__all__ = ('RootStage', 'ExperimentConfig', 'AnimalStage', 'extract_odor',
           'select_odor')

odor_method_pat = compile('random([0-9]*)')
odor_name_pat = compile('p[0-9]+')
odor_select_pat = compile('(?:p([0-9]+))(?:\(([0-9\.]+)\))?\
(?:/p([0-9]+)(?:\(([0-9\.]+)\))?)?(?:@\[(.+)\])?')


def extract_odor(odors, block, N):
    '''Takes the list of odors for a block, provided in
    :attr:`ExperimentConfig.odor_selection`, and parses it and returns
    the possible odors to choose from for that block.

    :Parameters:

        `odors`: list
            The odors list for a specific block, provided in
            :attr:`ExperimentConfig.odor_selection`.
        `block`: int
            The block associated with the odors.
        `N`: int
            The total of number of odor valves available (typically 8 or 16).

    :returns:

        A list of the parsed odors.

        Each element of the list is a 1 or 2-tuple. The elements in this tuple
        is each a 3-tuple with the valve number controlling this odor, the
        probability p of this odor being rewarded, even if correctly chosen by
        the subject when provided, and the MFC
        rate at which this odor airflow will bubble through (in order to mix
        them), if :attr:`RootStage.use_mfc`.
    '''
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


def select_odor(odors):
    '''Given a element of the list returned by :func:`extract_odor`, if the
    element is a 1-tuple it returns the first item, otherwise, it returns
    the odor with the higher flow rate of the two.

    It is the odor (with the
    higher flow rate) that is rewarded when the animal picks that side when
    a odor mixture is presented.
    '''
    if len(odors) == 1:
        return odors[0]
    else:
        return odors[0] if odors[0][2] >= odors[1][2] else odors[1]


class RootStage(ConfigStageBase):
    '''The stage that creates and initializes all the Barst devices (or
    simulation devices if :attr:`ExperimentApp.simulate`).
    '''

    __settings_attrs__ = ('n_valve_boards', 'use_mfc', 'use_mfc_air',
                          'sound_file_r', 'sound_file_l', 'log_filename',
                          'filter_len')

    server = ObjectProperty(None, allownone=True)
    '''The Barst server instance,
    :class:`~cplcom.moa.device.barst_server.Server`, or None when
    :attr:`simulate`.
    '''

    ftdi_chan = ObjectProperty(None, allownone=True)
    '''The FTDI controller device,
    :class:`~cplcom.moa.device.ftdi.FTDIDevChannel`
    when using actual hardware, or None when :attr:`simulate`.
    '''

    mfc_air = ObjectProperty(None, allownone=True)
    '''The MFC controlling the air, :class:`~cplcom.moa.device.mfc.MFC`
    when using actual hardware, or a
    :class:`~moa.device.analog.NumericPropertyChannel` when :attr:`simulate`
    the hardware.
    '''

    mfc_a = ObjectProperty(None, allownone=True)
    '''The MFC controlling one odor stream, :class:`~cplcom.moa.device.mfc.MFC`
    when using actual hardware, or a
    :class:`~moa.device.analog.NumericPropertyChannel` when :attr:`simulate`
    the hardware.
    '''

    mfc_b = ObjectProperty(None, allownone=True)
    '''The MFC controlling the other odor stream,
    :class:`~cplcom.moa.device.mfc.MFC` when using actual hardware, or a
    :class:`~moa.device.analog.NumericPropertyChannel` when :attr:`simulate`
    the hardware.
    '''

    odor_dev = ObjectProperty(None, allownone=True)
    '''The FTDI valve board, :class:`~forced_choice.devices.FTDIOdors`
    when using actual hardware, or a
    :class:`~forced_choice.devices.FTDIOdorsSim` when :attr:`simulate` the
    hardware.
    '''

    n_valve_boards = NumericProperty(2)
    '''The number of valve boards connected. Each board typically controls
    8 valves.
    '''

    daq_in_dev = ObjectProperty(None, allownone=True)
    '''The Switch and Sense device, :class:`~forced_choice.devices.DAQInDevice`
    when using actual hardware, or a
    :class:`~forced_choice.devices.DAQInDeviceSim` when :attr:`simulate` the
    hardware.
    '''

    daq_out_dev = ObjectProperty(None, allownone=True)
    '''The Switch and Sense device,
    :class:`~forced_choice.devices.DAQOutDevice`
    when using actual hardware, or a
    :class:`~forced_choice.devices.DAQOutDeviceSim` when :attr:`simulate` the
    hardware.
    '''

    use_mfc = BooleanProperty(False)
    '''Whether a MFC is used for mixing the odor streams (i.e. two odors
    are presented in a mixed form for each trial).
    '''

    use_mfc_air = BooleanProperty(False)
    '''When :attr:`use_mfc` is False, if this is True, a MFC will be used for
    driving air as a single odor stream. No mixing is performed.
    '''

    sound_file_r = StringProperty('Tone.wav')
    '''The sound file used in training as a cue when the right side is
    rewarded.
    '''

    sound_file_l = StringProperty('Tone.wav')
    '''The sound file used in training as a cue when the left side is
    rewarded.
    '''

    sound_r = ObjectProperty(None, allownone=True, rebind=True)
    '''The :class:`cplcom.moa.device.ffplayer.FFPyPlayerAudioDevice`
    that plays the file provided in :attr:`sound_file_r`.
    '''

    sound_l = ObjectProperty(None, allownone=True, rebind=True)
    '''The :class:`cplcom.moa.device.ffplayer.FFPyPlayerAudioDevice`
    that plays the file provided in :attr:`sound_file_l`.
    '''

    configs = DictProperty({})
    '''A dict whose keys are names of experiment types and whose values are
    :class:`ExperimentConfig` instances configuring the corresponding
    experiment.
    '''

    simulate = BooleanProperty(False)
    '''Whether the user has chosen to simulate the experiment. When ``True``,
    no actual hardware is required and all the hardware will be emulated
    by software and virtual devices.
    '''

    tracker = None
    '''The :class:`~moa.utils.ObjectStateTracker` instance used to
    process the device activation and deactivation during startup and
    shutdown.
    '''

    log_filename = StringProperty('{animal}_%m-%d-%Y_%I-%M-%S_%p.csv')
    '''The pattern that will be used to generate the log filenames for each
    trial. It is generated as follows::

        strftime(log_name_pat.format(**{'animal': animal_id, 'trial': trial,
        'block': block}))

    Which basically means that all instances of ``{animal}``, ``{trial}``, and
    ``{block}`` in the filename will be replaced by the
    animal name given in the GUI, the current trial, and block numbers. Then,
    it's is passed to `strftime` that formats any time parameters to get the
    log name used for that animal.

    If the filename matches an existing file, the new data will be appended to
    that file.
    '''

    filter_len = NumericProperty(1)
    '''The number of previous trials to average when displaying the trial
    result in the graphs.
    '''

    _shutting_down_devs = False

    @classmethod
    def get_config_classes(cls):
        d = {
            'barst_server': Server, 'ftdi_chan': FTDIDevChannel,
            'devices': RootStage, 'odors': FTDIOdors,
            'daqout': DAQOutDevice, 'daqin': DAQInDevice, 'mfc_air': MFC,
            'mfc_a': MFC, 'mfc_b': MFC,
            '_experiment': {'default': ExperimentConfig}}
        d.update(ConfigStageBase.get_config_classes())
        return d

    def clear(self, *largs, **kwargs):
        super(RootStage, self).clear(*largs, **kwargs)
        self._shutting_down_devs = False

    @app_error
    def init_devices(self):
        '''Called to start the devices during the init stage.
        '''
        settings = knspace.app.app_settings
        for k, v in settings['devices'].items():
            setattr(self, k, v)

        configs = self.configs = {
            k: ExperimentConfig(**opts)
            for k, opts in settings['_experiment'].items()}
        for config in configs.values():
            config.compute_odors()
        if not configs:
            raise Exception('No experiment configuration provided')

        sim = self.simulate = knspace.gui_simulate.state == 'down'
        tracker = self.tracker = ObjectStateTracker()

        self.create_odor_devs(sim, settings)
        self.create_daqout_devs(sim, settings)
        self.create_daqin_devs(sim, settings)
        self.create_mfc_devs(sim, settings)
        self.create_sound_devs(sim, settings)

        devs = [self.odor_dev, self.daq_out_dev, self.daq_in_dev, self.mfc_air,
                self.mfc_a, self.mfc_b, self.sound_l, self.sound_r]
        devs = [d for d in devs if d]

        if not sim:
            server = self.server = Server(
                knsname='barst_server', **settings.get('barst_server', {}))
            ftdi = self.ftdi_chan = FTDIDevChannel(
                server=server, devs=[self.odor_dev], knsname='ftdi_chan',
                **settings.get('ftdi_chan', {}))

            for d in devs:
                d.server = server
            devs = [server, ftdi] + devs

        callbacks = [partial(d.activate, self) for d in devs[1:]]
        callbacks.append(knspace.exp_dev_init.ask_step_stage)
        tracker.add_func_links(devs, callbacks, 'activation', 'active')
        devs[0].activate(self)

    @app_error
    def step_stage(self, source=None, **kwargs):
        if not self.started or (source is not None and source != self) or \
                self._shutting_down_devs:
            return super(RootStage, self).step_stage(source=source, **kwargs)
        self._shutting_down_devs = True

        devs = [self.odor_dev, self.daq_out_dev, self.daq_in_dev, self.mfc_air,
                self.mfc_a, self.mfc_b, self.sound_l, self.sound_r,
                self.ftdi_chan, self.server]
        devs = [d for d in devs if d]

        if not devs:
            return super(RootStage, self).step_stage(source=source, **kwargs)

        tracker = self.tracker = ObjectStateTracker()
        callbacks = [partial(d.deactivate, self, clear=True) for d in devs[1:]]
        callbacks.append(partial(self.ask_step_stage, source=source, **kwargs))
        tracker.add_func_links(devs, callbacks, 'activation', 'inactive',
                               timeout=5.)
        devs[0].deactivate(self, clear=True)

    def create_odor_devs(self, sim, settings):
        '''Creates the odor device, :attr:`odor_dev`.
        '''
        n_valve_boards = self.n_valve_boards
        dev_cls = [Factory.get('SwitchIcon'), Factory.get('DarkSwitchIcon')]
        gui_odors = knspace.gui_odors
        gui_odors.clear_widgets()

        odor_map = {}
        for i in range(n_valve_boards * 8):
            name = 'p{}'.format(i)
            widget = dev_cls[i % 2](text=name, knsname='gui_' + name)
            gui_odors.add_widget(widget)
            odor_map[name] = widget

        odorcls = FTDIOdorsSim if sim else FTDIOdors
        s = settings.get('odors', {}) if not sim else {}
        self.odor_dev = odorcls(
            knsname='odors', attr_map=odor_map, n_valve_boards=n_valve_boards,
            **s)

    def create_daqout_devs(self, sim, settings):
        '''Creates the daq output device, :attr:`daq_out_dev`.
        '''
        daqout_map = {}
        for name in ('ir_leds', 'fans', 'house_light', 'feeder_l', 'feeder_r'):
            daqout_map[name] = getattr(knspace, 'gui_{}'.format(name))

        daqoutcls = DAQOutDeviceSim if sim else DAQOutDevice
        s = settings.get('daqout', {}) if not sim else {}
        self.daq_out_dev = daqoutcls(
            knsname='daqout', attr_map=daqout_map, **s)

    def create_daqin_devs(self, sim, settings):
        '''Creates the daq input device, :attr:`daq_in_dev`.
        '''
        daqin_map = {}
        for name in ('nose_beam', 'reward_beam_l', 'reward_beam_r'):
            daqin_map[name] = getattr(knspace, 'gui_{}'.format(name))

        daqincls = DAQInDeviceSim if sim else DAQInDevice
        s = settings.get('daqin', {}) if not sim else {}
        self.daq_in_dev = daqincls(knsname='daqin', attr_map=daqin_map, **s)

    def create_mfc_devs(self, sim, settings):
        '''Creates the MFC devices: :attr:`mfc_air`, :attr:`mfc_a`, and
        :attr:`mfc_b`.
        '''
        if sim:
            s_air = s_a = a_b = {}
            cls = NumericPropertyChannel
        else:
            s_air = settings.get('mfc_air', {})
            s_a = settings.get('mfc_a', {})
            s_b = settings.get('mfc_b', {})
            cls = MFC

        gui_air = knspace.gui_mfc_air
        gui_a = knspace.gui_mfc_a
        gui_b = knspace.gui_mfc_b

        mfc = self.use_mfc
        if mfc or self.use_mfc_air:
            self.mfc_air = cls(
                knsname='mfc_air', channel_widget=gui_air, prop_name='value',
                **s_air)
            if mfc:
                self.mfc_a = cls(
                    knsname='mfc_a', channel_widget=gui_a,
                    prop_name='value', **s_a)
                self.mfc_b = cls(
                    knsname='mfc_b', channel_widget=gui_b,
                    prop_name='value', **s_b)

    def create_sound_devs(self, sim, settings):
        '''Creates the sound devices: :attr:`sound_l` and :attr:`sound_r`.
        '''
        self.sound_l = FFPyPlayerAudioDevice(
            button=knspace.gui_sound_l, knsname='sound_l',
            filename=self.sound_file_l)
        self.sound_r = FFPyPlayerAudioDevice(
            button=knspace.gui_sound_r, knsname='sound_r',
            filename=self.sound_file_r)


def _verify_odor_method(val):
    '''Callback used to verify that the odor selection method for the block is
    valid.
    '''
    if val in ('constant', 'list') or match(odor_method_pat, val):
        return val
    raise Exception('"{}" does not match an odor method'.format(val))


def _verify_valve_name(val):
    '''Callback used to verify that the valve name is valid.
    '''
    if not match(odor_name_pat, val):
        raise Exception('{} does not match the valve name pattern'.
                        format(val))
    return val


def _verify_list(prop, func, val):
    '''Callback used to verify and convert each element in ``val`` using
    ``func``. Also verifies that ``val`` is not empty.
    '''
    if not val:
        raise Exception('No value provided for "{}"'.format(prop))

    try:
        return [func(v) for v in val]
    except Exception as e:
        e.args = ('Error validating "{}" for "{}"'.format(val, prop),
                  ) + e.args
        raise


class ExperimentConfig(MoaBase):
    '''Stores the configuration parameters for a experiment.
    '''

    __settings_attrs__ = (
        'num_blocks', 'num_trials', 'wait_for_nose_poke', 'odor_delay',
        'mix_dur', 'air_rate', 'mfc_a_rate', 'mfc_b_rate', 'odor_beta',
        'beta_trials_min', 'beta_trials_max', 'odor_equalizer', 'odor_method',
        'NO_valve', 'mix_valve', 'min_nose_poke', 'sound_cue_delay',
        'max_nose_poke', 'sound_dur', 'max_decision_duration', 'num_pellets',
        'odor_path', 'good_iti', 'bad_iti', 'incomplete_iti', 'odor_selection')

    _list_props = [
        ('num_trials', int), ('wait_for_nose_poke', to_bool),
        ('odor_delay', float), ('air_rate', float),
        ('mfc_a_rate', float), ('mfc_b_rate', float), ('odor_beta', int),
        ('odor_equalizer', int),
        ('odor_method', _verify_odor_method),
        ('min_nose_poke', float),
        ('sound_cue_delay', float), ('max_nose_poke', float),
        ('sound_dur', float), ('max_decision_duration', float),
        ('num_pellets', int), ('good_iti', float), ('bad_iti', float),
        ('incomplete_iti', float),
        ('odor_selection', partial(_verify_list, 'odor_selection', str))]
    '''Lists the properties that are lists and the method used to convert their
    user given value into a valid format with :meth:`_validate_config_list`.
    '''

    def __init__(self, load=True, **kwargs):
        fbind = self.fbind
        for name, f in self._list_props:
            fbind(name, self._validate_config_list, name, f)

        super(ExperimentConfig, self).__init__(**kwargs)
        if load:
            self.read_odors()
            self.verify_config()

    @app_error
    def _validate_config_list(self, prop, func, *largs):
        setattr(self, prop, _verify_list(prop, func, getattr(self, prop)))

    @app_error
    def read_odors(self):
        '''Reads odors from a csv file as provided by :attr:`odor_path`.
        '''
        N = 8 * knspace.exp_root.n_valve_boards
        use_mfc = knspace.exp_root.use_mfc
        odor_side = ['rl', ] * N
        valve_mfc = [None, ] * N
        odor_name = ['p{}'.format(i) for i in range(N)]
        sides = ('rl', 'lr', 'l', 'r', '-', '')

        # now read the odor list
        odor_path = resources.resource_find(self.odor_path)
        with open(odor_path, 'rb') as fh:
            for row in csv.reader(fh):
                row = [elem.strip() for elem in row]
                if not row:
                    continue

                try:
                    if use_mfc:
                        i, name, side, mfc = row[:4]
                    else:
                        i, name, side = row[:3]
                except ValueError:
                    raise ValueError(
                        '"{}" does not match the "(index, name, side, [mfc])" '
                        'pattern'.format(row))
                i = int(i)

                if i >= N:
                    raise Exception('Odor {} is out of bounds: {}'.
                                    format(i, row))

                if side not in sides:
                    raise Exception('Side "{}" not recognized. Acceptable '
                                    'values are {}'.format(side, sides))
                if side == 'lr':
                    side = 'rl'
                elif not side:
                    side = '-'

                odor_name[i] = name
                odor_side[i] = side
                if use_mfc:
                    if mfc not in ('a', 'b'):
                        raise Exception('MFC "{}" not recognized. Acceptable '
                                        'values are a or b'.format(mfc))
                    valve_mfc[i] = 'mfc_a' if mfc == 'a' else 'mfc_b'

        self.odor_side = odor_side
        self.odor_names = odor_name
        self.valve_mfc = valve_mfc

    @app_error
    def verify_config(self):
        '''Verifies that everything is OK with the provided configuration
        parameters
        '''
        n = self.num_blocks
        if n <= 0:
            raise Exception('Number of blocks is not positive')

        # make sure the number of blocks match, otherwise, fill it up
        for name, _ in self._list_props:
            vals = getattr(self, name)[:n]
            vals += [vals[-1], ] * (n - len(vals))
            setattr(self, name, vals)

        if any([x <= 0 for x in self.num_trials]):
            raise Exception('Number of trials is not positive for every block')

        _verify_valve_name(self.NO_valve)
        _verify_valve_name(self.mix_valve)

    def apply_config_ui(self):
        '''Updates the odor and experiment values of the UI using the provided
        configuration parameters.
        '''
        no = getattr(knspace, 'gui_' + self.NO_valve)
        mix = getattr(knspace, 'gui_' + self.mix_valve)
        no.background_down = 'dark-blue-led-on-th.png'
        no.background_normal = 'dark-blue-led-off-th.png'
        mix.background_down = 'brown-led-on-th.png'
        mix.background_normal = 'brown-led-off-th.png'

        for i, (side, odor_name) in enumerate(
                zip(self.odor_side, self.odor_names)):
            name = 'gui_p{}'.format(i)
            obj = getattr(knspace, name)

            s = u''
            if 'l' in side:
                s += u'[color=0080FF]L[/color]'
            if 'r' in side:
                s += u'[color=9933FF]R[/color]'
            if '-' == side:
                s = u'[color=FF0000]Ø[/color]'

            obj.text = u'{}\n{}'.format(s, odor_name)

        time_line = knspace.time_line
        time_line.clear_slices()
        elems = (
            (0, 'Init'), (0, 'Ready'), (0, 'Wait NP'),
            (max(self.max_nose_poke), 'NP'),
            (max(self.max_decision_duration), 'Wait HP'),
            (0, 'Reward'),
            (max([max(self.good_iti), max(self.bad_iti),
                  max(self.incomplete_iti)]), 'ITI'),
            (0, 'Done'))
        for t, name in elems:
            time_line.add_slice(name=name, duration=t)
        time_line.smear_slices()

    def do_odor_list(self, block, block_odors, odor_opts):
        '''Reads the odor selection for each trial from a list when
        :attr:`odor_method` `'`list'``.
        '''
        if len(block_odors) > 1:
            raise Exception('More than one odor "{}" specified'
                            'for list odor method'.format(block_odors))

        fname = resources.resource_find(block_odors[0])
        with open(fname, 'rb') as fh:
            read_odors = list(csv.reader(fh))

        idx = None
        for line_num, row in enumerate(read_odors):
            if int(row[0]) == block:
                idx = line_num
                break

        if idx is None:
            raise Exception('odors not found for block "{}" '
                            'in the list'.format(block))

        odors = extract_odor(read_odors[line_num][1:], block,
                             knspace.exp_root.n_valve_boards * 8)
        odor_opts.append([])
        if any([len(o) != 1 for o in odors]):
            raise Exception('Number of flow rates specified for block'
                            ' {} is not 1: {}'.format(block, odors))
        return [o for elems in odors for o in elems]

    def do_odor_random(self, block, block_odors, odor_opts, method, n):
        '''When :attr:`odor_method` is not ``'list'``, but is `random` or
        `constant`, this generates the odors list for each trial.
        '''
        equalizer = self.odor_equalizer[block]

        odors = extract_odor(block_odors, block,
                             knspace.exp_root.n_valve_boards * 8)
        odors = [o for elems in odors for o in elems]
        odor_opts.append(odors)

        # now use the method to generate the odors
        if method == 'constant':
            if len(odors) > 1:
                raise Exception(
                    'More than one odor "{}" specified for constant '
                    'odor method'.format(odors))
            return odors * n

        # now it's random selection
        if len(odors) <= 1:
            raise Exception(
                'Only one odor "{}" was specified with with random'
                ' method'.format(odors))

        m = match(odor_method_pat, method)
        if m is None:
            raise Exception('method "{}" does not match a odor'
                            ' method'.format(method))

        # the condition for this random method
        condition = int(m.group(1)) if m.group(1) else 0
        if not equalizer:
            if condition <= 0:  # random without condition
                return [choice(odors) for _ in range(n)]

            # random with condition
            rand_odors = []
            for _ in range(n):
                o = randint(0, len(odors) - 1)
                while (len(rand_odors) >= condition and
                       all([t == o for t in
                            rand_odors[-condition:]])):
                    o = randint(0, len(odors) - 1)
                rand_odors.append(o)

            return [odors[i] for i in rand_odors]

        # equalize
        rand_odors = []
        for _ in range(int(ceil(n / float(equalizer)))):
            rand_odors.extend(self.do_equal_random(
                equalizer, len(odors), condition,
                last_val=rand_odors[-1] if rand_odors else None))
        del rand_odors[n:]

        return [odors[i] for i in rand_odors]

    def do_equal_random(self, n, m, cond, last_val=None):
        '''Implements :attr:`odor_equalizer` when selected.
        '''
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

        failed = True
        while failed:
            count = 0 if last_val is None else 1
            last = last_val
            failed = False

            for val in vals:
                if val == last:
                    count += 1
                else:
                    last = val
                    count = 1

                if count > cond:
                    failed = True
                    shuffle(vals)
                    break

        return vals

    @app_error
    def compute_odors(self):
        '''Computes the odors for all the trials and blocks.
        '''
        odor_method = self.odor_method
        odor_selection = self.odor_selection
        num_trials = self.num_trials
        trial_odors = [None, ] * len(odor_selection)
        wfnp = self.wait_for_nose_poke
        odor_opts = self.odor_opts = []

        for block, block_odors in enumerate(odor_selection):
            n = num_trials[block]
            if not wfnp[block]:
                odor_opts.append([])
                trial_odors[block] = [None, ] * n
                continue

            block_odors = [o.strip() for o in block_odors if o.strip()]
            if not len(block_odors):
                raise Exception('no odors specified for block {}'
                                .format(block))

            method = odor_method[block]
            # if there's only a filename there, read it for this block
            if method == 'list':
                trial_odors[block] = self.do_odor_list(
                    block, block_odors, odor_opts)
            else:
                # then it's a list of odors to use in the block
                trial_odors[block] = self.do_odor_random(
                    block, block_odors, odor_opts, method, n)

        for block, odors in enumerate(trial_odors):
            if len(odors) != num_trials[block]:
                raise Exception(
                    'The number of odors "{}" for block "{}" '
                    'doesn\'t match the number of trials "{}"'.format(
                        odors, block, num_trials[block]))
        self.trial_odors = trial_odors

    valve_mfc = None
    '''A :attr:`RootStage.n_valve_boards` * 8 long list for each valve,
    indicating whether MFC a or b is used for that valve.
    '''

    odor_side = ListProperty([])
    '''A :attr:`RootStage.n_valve_boards` * 8 long list for each valve,
    indicating which side is rewarded for that valve.
    '''

    odor_names = ListProperty([])
    '''A :attr:`RootStage.n_valve_boards` * 8 long list for each valve,
    indicating the name of the odor for that valve.
    '''

    trial_odors = None
    '''A 2d list of the odors for each trial in each block.

    Each element is a tuple of 1 or two odors with the same structure as
    the elements returned by :func:`extract_odor`.
    '''

    odor_opts = None
    '''A list containing, for each block, a list of all the possible odors for
    this block from which we select a odor for every trial.

    Each element is a tuple of 1 or two odors with the same structure as
    the elements returned by :func:`extract_odor`.
    '''

    num_blocks = NumericProperty(3)
    '''The number of blocks to run. Each block runs :attr:`num_trials` trials.

    All the configuration parameters that are lists, e.g. :attr:`num_trials`
    can specify a different value for each block.

    If the number of elements in these lists are less than the number of
    blocks, the last value of the list is used for the remaining blocks. E.g.
    for 10 blocks, if :attr:`num_trials` is ``[5, 6, 2]``, then blocks 2 - 9
    will have 2 trials.
    '''

    num_trials = ListProperty([10])
    '''A list of the number of trials to run for each block of
    :attr:`num_blocks`.
    '''

    wait_for_nose_poke = ListProperty([False, True])
    '''A list of, for each block in :attr:`num_blocks`, whether to wait for a
    nose poke or to immediately go to the reward stage.

    When False, entering the reward port will dispense reward and end the
    trial. The ITI will then be :attr:`good_iti` for that block.
    '''

    odor_delay = ListProperty([0])
    '''A list of, for each block in :attr:`num_blocks`, how long to delay the
    odor delivery onset from when the animal enters the nose port.

    If zero, there's no delay.
    '''

    mix_dur = NumericProperty(1.5)
    '''A list of, for each block in :attr:`num_blocks`, how long to pass the
    air stream through the odor vials before the trial starts (during
    the last ITI).

    This ensures that when the animal enters the nose port, the odor is stream
    is already saturated. During this time the odor is directed to teh vaccum.
    '''

    air_rate = ListProperty([0])
    '''A list of, for each block in :attr:`num_blocks`, the flow rate for the
    air stream using the air MFC when :attr:`RootStage.use_mfc` or
    :attr:`RootStage.use_mfc_air`.
    '''

    mfc_a_rate = ListProperty([.1])
    '''A list of, for each block in :attr:`num_blocks`, the flow rate for the
    odor stream a using the odor a MFC when :attr:`RootStage.use_mfc`.
    '''

    mfc_b_rate = ListProperty([.1])
    '''A list of, for each block in :attr:`num_blocks`, the flow rate for the
    odor stream b using the odor b MFC when :attr:`RootStage.use_mfc`.
    '''

    odor_beta = ListProperty([0])
    '''A list of, for each block in :attr:`num_blocks`, the beta value to use
    when compensating for unequal side performance. This compensation is
    applied dynamically during the trials on top of any previous odor
    computations.

    We keep track of the accuracy rate of every odor (i.e. how often the animal
    chooses the incorrectly for that odor). Then, odors where the animal
    performed poorly will get presented with a higher probability.

    A :attr:`odor_beta` value of zero disables this bias compensation. A value
    of e.g. 10, will bias very strongly towards changing the next trial odor
    to be a odor in which the animal performed poorly. The closer to zero, the
    lower such bias compensation. A value of 2-3 is reasonable.

    The trials are accumulated across blocks so a new block does not clear the
    odor bias history.
    '''

    beta_trials_min = NumericProperty(10)
    '''The minimum number of trials for each odor that must have occured before
    :attr:`odor_beta` bias compensation is activated. If the number of trial
    that occurred for any odor is less than :attr:`beta_trials_min`, bias
    compensation is disabled.
    '''

    beta_trials_max = NumericProperty(15)
    '''For each odor, it is the last :attr:`beta_trials_max` trials (of that
    odor) to take into account when computing the accuracy rate for that odor.

    Trials for this odor further back in history than :attr:`beta_trials_max`
    specific to this odor are dropped.
    '''

    odor_equalizer = ListProperty([6, 8])
    '''A list of, for each block in :attr:`num_blocks`, the number of trials
    during which all the odors for that block will be presented an equal
    number of times.

    That is, during these exclusively grouped :attr:`odor_equalizer` trials,
    no odor will be presented more times than any other odor.

    The number of odors for each block listed in :attr:`odor_selection` must
    divide without remainder the :attr:`odor_equalizer` value for that block.
    '''

    odor_method = ListProperty(['constant', 'random2'])
    '''A list of, for each block in :attr:`num_blocks`, the method used to
    determine which odor to use in the trials for the odors listed in
    :attr:`odor_selection`.

    Possible methods are `constant`, `randomx`, or `list`.
    :attr:`odor_selection` is used to select the odor to be used with this
    method.

        `constant`:
            :attr:`odor_selection` is a 2d list of odors of length
            :attr:`num_blocks`. Each element in the outer list is a single
            element list containing the odor that is used for all the trials of
            that block.
        `randomx`: x is a number or empty
            :attr:`odor_selection` is a 2d list of odors of length
            :attr:`num_blocks`. Each inner list is a list of odors from which
            the trial odor would be randomly selected for each trial in the
            block.

            If the method is ``random``, the odor is randomly selected
            from that list. If random is followed by an integer, e.g.
            ``random2``, then it's random with the condition that no odor can
            be repeated more then x (2 in this) times successively.
        `list`:
            :attr:`odor_selection` is a 2d list of filenames. The files are
            read for each block and the odors listed in the file is used for
            the trials.

            The structure of the text file is a line for each block. Each line
            is a comma separated list, with the first column being the block
            number and the other column the odors to use for that block.

            Each inner list in the 2d list (line) can only have a
            single filename for that block.
    '''

    odor_selection = ListProperty([['p1'], ['p1', 'p2']])
    '''A list of, for each block in :attr:`num_blocks`, a inner list of odors
    used to select from trial odors for each block. See :attr:`odor_method`.
    '''

    NO_valve = StringProperty('p0')
    '''A list of, for each block in :attr:`num_blocks`, the normally open
    (mineral oil) odor valve. I.e. the valve which is normally open and closes
    during the trial when the odor is released.
    '''

    mix_valve = StringProperty('p7')
    '''A list of, for each block in :attr:`num_blocks`, the valve that directs
    the odor to go to vacuum or to the animal. Before the odor goes to the
    animal, the odor is mixed and evacuated to vacuum in order to saturate the
    air stream into a steady state condition.
    '''

    odor_path = StringProperty('odor_list.txt')
    '''The filename of a file containing the names of odors and which side to
    reward that odor.

    The structure of the file is as follows: each line
    describes an odor and is a 3 or 4 column comma separated list of
    ``(idx, name, side, mfc)``, where idx is the zero-based valve index.
    Name is the odor name. And side is the side of the odor to reward
    (r, l, rl, lr, or -).
    If using an mfc, the 4th column is either ``a``, or ``b`` indicating the
    mfc to use of that valve.

    An example file is::

        1, mineral oil, r
        4, citric acid, rl
        5, limonene, l
        ...
    '''

    min_nose_poke = ListProperty([0])
    '''A list of, for each block in :attr:`num_blocks`, the minimum duration
    in the nose port AFTER the odor is released (i.e. :attr:`odor_delay`).
    A nose port exit less than this duration will result in an incomplete
    trial. The ITI will then be :attr:`incomplete_iti`.

    If zero, there is no minimum.
    '''

    sound_cue_delay = ListProperty([0])
    '''A list of, for each block in :attr:`num_blocks`, the random amount
    of time to delay the sound cue AFTER :attr:`min_nose_poke` elapsed. It's
    a value between zero and :attr:`sound_cue_delay`.

    If zero or if :attr:`sound_dur` is zero, there is no delay.
    '''

    max_nose_poke = ListProperty([10.])
    '''A list of, for each block in :attr:`num_blocks`, the maximum duration
    of the nose port stage. After this duration, the stage will terminate and
    proceed to the decision stage even if the animal is still in the nose port.

    If zero, there is no maximum.
    '''

    sound_dur = ListProperty([0])
    '''A list of, for each block in :attr:`num_blocks`, the duration to play
    the sound cue after :attr:`sound_cue_delay`. It plays either
    :attr:`RootStage.sound_file_r` or :attr:`RootStage.sound_file_l` depending
    on the trial odor.

    If zero, no sound is played.
    '''

    max_decision_duration = ListProperty([20.])
    '''A list of, for each block in :attr:`num_blocks`, the maximum duration
    of the decision stage. After this duration, the stage will terminate and
    proceed to the ITI stage even if the animal didn't visit the reward port.

    The decision determines whether a reward is dispensed and the duration of
    the ITI.

    If zero, there is no maximum.
    '''

    num_pellets = ListProperty([2])
    '''The number of sugar pellets to deliver upon a successful trial.
    '''

    good_iti = ListProperty([3])
    '''The ITI duration of a passed trial.
    '''

    bad_iti = ListProperty([4])
    '''The ITI duration of a failed trial.
    '''

    incomplete_iti = ListProperty([4])
    '''The ITI duration of a trial where the animal did not hold its nose long
    enough in the nose port and :attr:`min_nose_poke` was not satisfied.
    '''


class AnimalStage(MoaStage):
    '''In this stage, each loop iteration runs another animal.
    '''

    _filename = ''
    _fd = None

    config = ObjectProperty(ExperimentConfig(load=False), rebind=True)
    '''The :class:`ExperimentConfig` instance used to configure the current
    animal.
    '''

    animal_id = StringProperty('')
    '''The animal id of the current animal. '''

    block = NumericProperty(0)
    '''The current block number.
    '''

    trial = NumericProperty(0)
    '''The current trial number.
    '''

    trial_start_ts = None
    '''The start time of the trial in seconds. '''

    trial_start_time = None
    '''The start time of the trial in human readable clock format. '''

    nose_poke_ts = None
    '''The time of the nose port entry. '''

    odor_start_ts = None
    '''The time when the odor was released to the animal. '''

    nose_poke_exit_ts = None
    '''The time of the nose port exit. '''

    nose_poke_exit_timed_out = False
    '''Whether the animal was in the nose port longer than
    :attr:`ExperimentConfig.max_nose_poke` and it timed out.
    '''

    reward_entry_ts = None
    '''The time of the reward port entry. '''

    reward_entry_timed_out = False
    '''Whether the animal waited longer than
    :attr:`ExperimentConfig.max_decision_duration` before making a decision by
    going to either feeder side and it timed out.
    '''

    sound = ObjectProperty(None, allownone=True)
    '''The sound file, from :attr:`RootStage.sound_r` and
    :attr:`RootStage.sound_l`, to use for this trial.
    '''

    odor = None
    '''The odor to reward for this trial.
    '''

    side = None
    '''The side (``rl``) of :attr:`odor` to reward.
    '''

    side_went = None
    '''The feeder side the animal visited. '''

    reward_side = OptionProperty(None, options=['feeder_r', 'feeder_l', False,
                                                None], allownone=True)
    '''The feeder device name of the side on which to reward this trial. '''

    iti = NumericProperty(0)
    '''The ITI used for this trial. '''

    outcome = None
    '''Whether this trial was an incomplete. '''

    outcome_wid = None
    '''The :class:`forced_choice.graphics.TrialOutcome` widget describing the
    current trial. '''

    total_pass = NumericProperty(0)
    '''Total number of passed trials for this block. '''

    total_fail = NumericProperty(0)
    '''Total number of failed trials for this block. '''

    total_incomplete = NumericProperty(0)
    '''Total number of incomplete trials for this block. '''

    outcomes = []
    '''1 or 0 for each trial indicating the trial reward outcome. Reset at each
    block.
    '''

    odor_outcome = {}
    '''keys are the odor indices, values are a list with 0 or 1 indicating the
    trial reward outcome for that odor. This combines all the blocks for
    the animal.
    '''

    odor_widgets = []
    '''List of :class:`forced_choice.graphics.TrialPrediction` instances
    for all the blocks, containing all the trials.
    '''

    predict_widget = None
    ''':class:`forced_choice.graphics.TrialPrediction` instance for the current
    trial.
    '''

    def initialize_box(self):
        ''' Turns on fans, lights etc at the beginning of the experiment. '''
        knspace.daqout.set_state(high=['ir_leds', 'fans'])

    def initialize_animal(self):
        '''Executed before the start of a new animal. '''
        # get the config instance for this animal
        c = self.config = knspace.exp_root.configs[knspace.gui_trial_type.text]
        c.knsname = 'exp_config'
        config = knspace.exp_config
        config.apply_config_ui()
        config.compute_odors()
        names = config.odor_names
        self.animal_id = knspace.gui_animal_id.text

        sides = config.odor_side
        odor_widgets = self.odor_widgets = []
        PredictionGrid = Factory.PredictionGrid
        TrialPrediction = Factory.TrialPrediction

        predict_add = knspace.gui_prediction_container.add_widget
        knspace.gui_prediction_container.clear_widgets()

        # create the prediction displays for all trials
        for block, block_odors in enumerate(config.trial_odors):
            block_grid = PredictionGrid()
            predict_add(block_grid)
            block_add = block_grid.add_widget

            block_widgets = []
            odor_widgets.append(block_widgets)

            for trial, odor in enumerate(block_odors):
                if odor is not None:
                    odor = select_odor(odor)[0]
                    side = sides[odor]
                    if side == '-':
                        side = u'Ø'

                    trial_wid = TrialPrediction(
                        odor=names[odor], side=side, trial=trial)
                else:
                    trial_wid = TrialPrediction(side='rl', trial=trial)

                block_widgets.append(trial_wid)
                block_add(trial_wid)

    def pre_block(self):
        '''Executed before each block. '''
        self.block = knspace.exp_block.count
        self.total_fail = self.total_pass = self.total_incomplete = 0
        for graph in (knspace.gui_ttnp, knspace.gui_tinp, knspace.gui_ttrp,
                      knspace.gui_outcome):
            graph.plots[0].points = []
        self.outcomes = []
        self.odor_outcome = defaultdict(list)

    def init_trial(self, block, trial):
        '''Starts the trial.
        '''
        trial = self.trial = knspace.exp_trial.count
        block = self.block
        config = self.config
        blocks = knspace.gui_prediction_container.children
        trials = blocks[-block - 1].children
        self.predict_widget = trials[-trial - 1]

        knspace.time_line.update_slice_attrs(
            'NP', text='NP ({}.{})'.format(block, trial),
            duration=config.max_nose_poke[block])
        knspace.time_line.update_slice_attrs(
            'Wait HP', duration=config.max_decision_duration[block])

        container = knspace.gui_results_container
        self.outcome_wid = widget = container.children[0]
        container.remove_widget(widget)
        container.add_widget(widget, len(container.children))
        widget.init_outcome(self.animal_id, block, trial)

        self.nose_poke_ts = self.odor_start_ts = self.nose_poke_exit_ts = None
        self.reward_entry_ts = self.sound = self.side_went = None
        self.reward_side = self.outcome = None
        self.reward_entry_timed_out = self.nose_poke_exit_timed_out = False
        self.iti = 0

        self.update_trial_odor()
        if config.trial_odors[block][trial] is None:
            self.odor = None
            self.side = 'rl'
        else:
            self.odor = odor = config.trial_odors[block][trial]
            widget.side = side = self.side = \
                config.odor_side[select_odor(odor)[0]]
            if config.sound_dur[block] and side != '-':
                self.sound = (knspace.sound_r if 'r' in side else
                              knspace.sound_l)
        self.start_mixing()

    def update_trial_odor(self):
        '''Updates the trial odor using :attr:`ExperimentConfig.beta` when
        non-zero.
        '''
        config = self.config
        block, trial = self.block, self.trial
        if config.trial_odors[block][trial] is None:
            return

        beta = config.odor_beta[block]
        beta_trials_min = max(config.beta_trials_min, 1)
        beta_trials_max = max(config.beta_trials_max, 1)
        outcomes = self.odor_outcome
        widget = self.odor_widgets[block][trial]

        odor_opts = config.odor_opts[block]
        N = len(odor_opts)
        odor_idxs = [select_odor(o)[0] for o in odor_opts]

        if not beta or not odor_idxs or not outcomes:
            return

        outcome_frac = np.zeros(N)
        for i, o in enumerate(odor_idxs):
            odor_outcome = outcomes[o][-beta_trials_max:]
            if len(odor_outcome) < beta_trials_min:
                return
            outcome_frac[i] = sum(odor_outcome) / float(len(odor_outcome))

        p = np.exp(-beta * np.array(outcome_frac))
        p *= 1 / float(N)
        p /= np.sum(p)
        k = uniform(0, 1.)

        cum_sum = np.cumsum(p)
        cum_sum[-1] = 1.
        for i, f in enumerate(cum_sum):
            if k < f:
                break

        odor = odor_idxs[i]
        if config.trial_odors[block][trial] == odor:
            return

        widget.odor = config.odor_names[odor]
        side = config.odor_side[odor]
        if side == '-':
            side = u'Ø'
        widget.side = side
        config.trial_odors[block][trial] = odor_opts[i]

    def start_mixing(self):
        '''Opens the odor valves to start mixing with the air stream, but
        directs it to the vacuum.
        '''
        config = self.config
        block = self.block
        odor = self.odor
        if odor is None:
            return

        if knspace.exp_root.use_mfc:  # laterz
            raise NotImplementedError()
        else:
            knspace.odors.set_state(
                high=['p{}'.format(select_odor(odor)[0]), config.NO_valve])

    def pre_trial(self):
        '''Executed before each trial. '''
        self.trial_start_ts = clock()
        self.trial_start_time = strftime('%H:%M:%S')

    def do_nose_poke(self):
        '''Executed after the first nose port entry of the trial. '''
        self.nose_poke_ts = clock()
        ttnp = self.outcome_wid.ttnp = self.nose_poke_ts - self.trial_start_ts
        knspace.gui_ttnp.plots[0].points.append((self.trial, ttnp))

    def do_odor_release(self):
        '''After :meth:`start_mixing`, it redirects the already mixing odor
        to the animal.
        '''
        knspace.odors.set_state(high=[self.config.mix_valve])
        self.odor_start_ts = clock()

    def do_nose_poke_exit(self, timed_out):
        '''Executed after the first nose port exit of the trial. '''
        te = self.nose_poke_exit_ts = clock()

        # turn off odor
        config, block, trial = self.config, self.block, self.trial
        if knspace.exp_root.use_mfc:
            raise NotImplementedError()
        else:
            knspace.odors.set_state(
                low=['p{}'.format(select_odor(self.odor)[0]),
                     config.NO_valve, config.mix_valve])

        self.nose_poke_exit_timed_out = timed_out
        wid = self.outcome_wid
        tinp = wid.tinp = te - self.nose_poke_ts
        knspace.gui_tinp.plots[0].points.append((trial, tinp))

        if not timed_out:
            min_poke = config.min_nose_poke[block]
            if min_poke > 0 and tinp < min_poke:
                self.outcome = 'inc'
                self.reward_side = False
                self.total_incomplete += 1
                wid.passed = False
                wid.incomplete = True
                self.iti = wid.iti = config.incomplete_iti[block]

                predict = self.predict_widget
                predict.outcome = False
                predict.outcome_text = 'INC'
                self.outcomes.append(0)

    def do_decision(self, r, l, timed_out):
        '''Executed after the reward port entry or after waiting for the
        reward port entry timed out. It decides whether the animal is
        rewarded.
        '''
        ts = self.reward_entry_ts = clock()
        config, block, trial = self.config, self.block, self.trial
        odor = self.odor and select_odor(self.odor)
        wid = self.outcome_wid
        predict = self.predict_widget
        side = self.side
        wfnp = config.wait_for_nose_poke[block]

        self.reward_entry_timed_out = timed_out
        if not timed_out:
            predict.side_went = wid.side_went = side_went = self.side_went = \
                'r' if r else 'l'
            wid.ttrp = ts - (self.nose_poke_exit_ts if self.nose_poke_exit_ts
                             is not None else self.trial_start_ts)
            knspace.gui_ttrp.plots[0].points.append((trial, wid.ttrp))


        reward = not timed_out and (odor is None or (
            side == 'rl' or side == side_went) and random() <= odor[1])
        predict.outcome = wid.passed = passed = not timed_out and (
            not wfnp or (side == 'rl' or side == side_went))
        self.outcomes.append(int(predict.outcome))
        if odor is not None:
            self.odor_outcome[odor[0]].append(passed)

        wid.iti = self.iti = (
            config.good_iti[block] if passed else config.bad_iti[block])
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
        fname = strftime(
            knspace.exp_root.log_filename.format(**{'trial': self.trial,
            'block': self.block, 'animal': self.animal_id}))
        filename = self._filename
        o = self.outcomes[-knspace.exp_root.filter_len:]
        knspace.gui_outcome.plots[0].points.append((
            self.trial, sum(o) / max(1., float(len(o))) * 100))

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

        if self.odor is not None:
            odor_idx = select_odor(self.odor)[0]
            odor_name = self.config.odor_names[odor_idx]
            odor_i = 'p{}'.format(odor_idx)
        else:
            odor_i = odor_name = ''

        outcome = {'fail': 0, 'pass': 1, 'inc': 2, None: None}
        vals = [strftime('%m-%d-%Y'), self.trial_start_time, self.animal_id,
                self.block, self.trial,
                odor_name, odor_i,
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
