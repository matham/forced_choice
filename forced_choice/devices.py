'''Devices
===========

Defines some of the devices that are used in the experiment.
'''


__all__ = (
    'FTDIOdorsBase', 'FTDIOdorsSim', 'FTDIOdors', 'DAQInDeviceBase',
    'DAQInDeviceSim', 'DAQInDevice', 'DAQOutDeviceBase', 'DAQOutDeviceSim',
    'DAQOutDevice')

from weakref import ref

from moa.device.digital import ButtonChannel, ButtonPort
from moa.device.analog import NumericPropertyChannel

from ffpyplayer.player import MediaPlayer

from kivy.properties import (
    ConfigParserProperty, BooleanProperty, ListProperty, ObjectProperty,
    NumericProperty)
from kivy.app import App
from kivy import resources

from cplcom.moa.device.ftdi import FTDISerializerDevice
from cplcom.moa.device.mcdaq import MCDAQDevice



class FTDIOdorsBase(object):
    '''Base class for the FTDI odor device.
    '''

    def __init__(self, **kwargs):
        n_valve_boards = kwargs.get('n_valve_boards', self.n_valve_boards)
        # we don't know ahead of time how many valves, so we need to create
        # the bool prop for each valve dynamically
        for i in range(8 * n_valve_boards):
            self.create_property('p{}'.format(i), value=False, allownone=True)

        super(FTDIOdorsBase, self).__init__(direction='o', **kwargs)

    n_valve_boards = NumericProperty(2)
    '''The number of valve boards that are connected to the FTDI controller.
    Each board can typically control 8 valves.

    Defaults to 2.
    '''


class FTDIOdorsSim(FTDIOdorsBase, ButtonPort):
    '''Device used when simulating the odor device.
    '''
    pass


class FTDIOdors(FTDIOdorsBase, FTDISerializerDevice):
    '''Device used when using the barst ftdi odor device.
    '''

    def __init__(self, **kwargs):
        super(FTDIOdors, self).__init__(**kwargs)
        self.dev_map = {'p{}'.format(i): i
                        for i in range(self.n_valve_boards * 8)}


class DAQInDeviceBase(object):
    '''Base class for the Switch & Sense 8/8 input ports.
    '''

    nose_beam = BooleanProperty(False, allownone=True)
    '''Reads / controls the nose port photobeam.
    '''

    reward_beam_r = BooleanProperty(False, allownone=True)
    '''Reads / controls the right reward port photobeam.
    '''

    reward_beam_l = BooleanProperty(False, allownone=True)
    '''Reads / controls the left reward port photobeam.
    '''


class DAQInDeviceSim(DAQInDeviceBase, ButtonPort):
    '''Device used when simulating the Switch & Sense 8/8 input device.
    '''
    pass


class DAQInDevice(DAQInDeviceBase, MCDAQDevice):
    '''Device used when using the barst Switch & Sense 8/8 input device.
    '''

    __settings_attrs__ = (
        'nose_beam_pin', 'reward_beam_r_pin', 'reward_beam_l_pin')

    def __init__(self, **kwargs):
        super(DAQInDevice, self).__init__(direction='i', **kwargs)
        self.dev_map = {
        'nose_beam': self.nose_beam_pin,
        'reward_beam_r': self.reward_beam_r_pin,
        'reward_beam_l': self.reward_beam_l_pin}

    nose_beam_pin = NumericProperty(1)
    '''The port in the Switch & Sense to which the nose port photobeam is
    connected to.

    Defaults to 1.
    '''

    reward_beam_r_pin = NumericProperty(3)
    '''The port in the Switch & Sense to which the right reward port photobeam
    is connected to.

    Defaults to 3.
    '''

    reward_beam_l_pin = NumericProperty(2)
    '''The port in the Switch & Sense to which the left reward port photobeam
    is connected to.

    Defaults to 2.
    '''


class DAQOutDeviceBase(object):
    '''Base class for the Switch & Sense 8/8 output ports.
    '''

    house_light = BooleanProperty(False, allownone=True)
    '''Controls the house light.
    '''

    ir_leds = BooleanProperty(False, allownone=True)
    '''Controls the IR light.
    '''

    fans = BooleanProperty(False, allownone=True)
    '''Controls the fans.
    '''

    feeder_r = BooleanProperty(False, allownone=True)
    '''Controls the right feeder.
    '''

    feeder_l = BooleanProperty(False, allownone=True)
    '''Controls the left feeder.
    '''


class DAQOutDeviceSim(DAQOutDeviceBase, ButtonPort):
    '''Device used when simulating the Switch & Sense 8/8 output device.
    '''
    pass


class DAQOutDevice(DAQOutDeviceBase, MCDAQDevice):
    '''Device used when using the barst Switch & Sense 8/8 output device.
    '''

    __settings_attrs__ = (
        'house_light_pin', 'ir_leds_pin', 'fans_pin', 'feeder_r_pin',
        'feeder_l_pin')

    def __init__(self, **kwargs):
        super(DAQOutDevice, self).__init__(direction='o', **kwargs)
        self.dev_map = {'house_light': self.house_light_pin,
                   'ir_leds': self.ir_leds_pin,
                   'fans': self.fans_pin,
                   'feeder_r': self.feeder_r_pin,
                   'feeder_l': self.feeder_l_pin}

    house_light_pin = NumericProperty(4)
    '''The port in the Switch & Sense that controls the house light.

    Defaults to 4.
    '''

    ir_leds_pin = NumericProperty(6)
    '''The port in the Switch & Sense that controls the IR lights.

    Defaults to 6.
    '''

    fans_pin = NumericProperty(5)
    '''The port in the Switch & Sense that controls the fans.

    Defaults to 5.
    '''

    feeder_r_pin = NumericProperty(2)
    '''The port in the Switch & Sense that controls the right feeder.

    Defaults to 2.
    '''

    feeder_l_pin = NumericProperty(0)
    '''The port in the Switch & Sense that controls the left feeder.

    Defaults to 0.
    '''
