''' Devices used in the experiment.
'''


__all__ = ('DeviceStageInterface', 'Server', 'FTDIDevChannel', 'FTDIOdorsBase',
           'FTDIOdorsSim', 'FTDIOdors', 'DAQInDeviceBase', 'DAQInDeviceSim',
           'DAQInDevice', 'DAQOutDeviceBase', 'DAQOutDeviceSim',
           'DAQOutDevice', 'MassFlowControllerBase', 'MassFlowControllerSim',
           'MFCSafe', 'MassFlowController', 'FFpyPlayer')

from weakref import ref

from moa.device.digital import ButtonChannel, ButtonPort
from moa.device.analog import NumericPropertyChannel

from ffpyplayer.player import MediaPlayer

from kivy.properties import (ConfigParserProperty, BooleanProperty,
                             ListProperty, ObjectProperty)
from kivy.app import App
from kivy import resources

from cplcom import device_config_name
from cplcom.device.ftdi import FTDISerializerDevice
from cplcom.device.mcdaq import MCDAQDevice
from cplcom.device import DeviceStageInterface



class FTDIOdorsBase(object):
    '''Base class for the FTDI odor devices.
    '''

    def __init__(self, odor_btns=None, N=8, **kwargs):
        Nb = len(odor_btns)
        for i in range(N):
            self.create_property('p{}'.format(i), value=False, allownone=True)
        attr_map = {
            'p{}'.format(i): odor_btns[Nb - i - 1].__self__ for i in range(Nb)}
        super(FTDIOdorsBase, self).__init__(
            attr_map=attr_map, direction='o', **kwargs)


class FTDIOdorsSim(FTDIOdorsBase, ButtonPort):
    '''Device used when simulating the odor devices.
    '''
    pass


class FTDIOdors(FTDIOdorsBase, FTDISerializerDevice):
    '''Device used when using the barst ftdi odor devices.
    '''

    def __init__(self, N=8, **kwargs):
        dev_map = {'p{}'.format(i): i for i in range(N)}
        super(FTDIOdors, self).__init__(dev_map=dev_map, N=N, **kwargs)


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
    '''Device used when using the barst Switch & Sense 8/8 output devices.
    '''

    def __init__(self, **kwargs):
        dev_map = {'nose_beam': self.nose_beam_pin,
                   'reward_beam_r': self.reward_beam_r_pin,
                   'reward_beam_l': self.reward_beam_l_pin}
        super(DAQInDevice, self).__init__(
            dev_map=dev_map, direction='i', **kwargs)

    nose_beam_pin = ConfigParserProperty(
        1, 'Switch_and_Sense_8_8', 'nose_beam_pin', device_config_name,
        val_type=int)
    '''The port in the Switch & Sense to which the nose port photobeam is
    connected to.

    Defaults to zero.
    '''

    reward_beam_r_pin = ConfigParserProperty(
        3, 'Switch_and_Sense_8_8', 'reward_beam_r_pin', device_config_name,
        val_type=int)
    '''The port in the Switch & Sense to which the reward port photobeam is
    connected to.

    Defaults to zero.
    '''

    reward_beam_l_pin = ConfigParserProperty(
        2, 'Switch_and_Sense_8_8', 'reward_beam_l_pin', device_config_name,
        val_type=int)
    '''The port in the Switch & Sense to which the reward port photobeam is
    connected to.

    Defaults to zero.
    '''


class DAQOutDeviceBase(object):
    '''Base class for the Switch & Sense 8/8 output ports.
    '''

    house_light = BooleanProperty(False, allownone=True)
    '''Controls the house light.
    '''

    ir_leds = BooleanProperty(False, allownone=True)
    '''Controls the stress light.
    '''

    fans = BooleanProperty(False, allownone=True)
    '''Controls the stress light.
    '''

    feeder_r = BooleanProperty(False, allownone=True)
    '''Controls the stress light.
    '''

    feeder_l = BooleanProperty(False, allownone=True)
    '''Controls the stress light.
    '''


class DAQOutDeviceSim(DAQOutDeviceBase, ButtonPort):
    '''Device used when simulating the Switch & Sense 8/8 output device.
    '''
    pass


class DAQOutDevice(DAQOutDeviceBase, MCDAQDevice):
    '''Device used when using the barst Switch & Sense 8/8 output devices.
    '''

    def __init__(self, **kwargs):
        dev_map = {'house_light': self.house_light_pin,
                   'ir_leds': self.ir_leds_pin,
                   'fans': self.fans_pin,
                   'feeder_r': self.feeder_r_pin,
                   'feeder_l': self.feeder_l_pin}
        super(DAQOutDevice, self).__init__(
            dev_map=dev_map, direction='o', **kwargs)

    house_light_pin = ConfigParserProperty(
        4, 'Switch_and_Sense_8_8', 'house_light_pin', device_config_name,
        val_type=int)

    ir_leds_pin = ConfigParserProperty(
        6, 'Switch_and_Sense_8_8', 'ir_leds_pin', device_config_name,
        val_type=int)

    fans_pin = ConfigParserProperty(
        5, 'Switch_and_Sense_8_8', 'fans_pin', device_config_name,
        val_type=int)

    feeder_r_pin = ConfigParserProperty(
        2, 'Switch_and_Sense_8_8', 'feeder_r_pin', device_config_name,
        val_type=int)

    feeder_l_pin = ConfigParserProperty(
        0, 'Switch_and_Sense_8_8', 'feeder_l_pin', device_config_name,
        val_type=int)


def ffplayer_callback(*l):
    pass


class FFpyPlayer(DeviceStageInterface, ButtonChannel):

    player = None

    playing = False

    def create_device(self, filename, *largs, **kwargs):
        self.player = MediaPlayer(
            filename=resources.resource_find(filename),
            callback=ref(ffplayer_callback), ff_opts={
                'loop': 0, 'vn': True, 'sn': True, 'paused': True})

    def on_state(self, *l):
        if self.playing == self.state:
            return
        try:
            self.player.toggle_pause()
        except Exception as e:
            App.get_running_app().device_exception(e)
        else:
            self.playing = not self.playing
