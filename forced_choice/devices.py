''' Devices used in the experiment.
'''


__all__ = ('DeviceStageInterface', 'Server', 'FTDIDevChannel', 'FTDIPinBase',
           'FTDIPinSim', 'FTDIPin', 'FTDIOdorsBase', 'FTDIOdorsSim',
           'FTDIOdors', 'DAQInDeviceBase', 'DAQInDeviceSim', 'DAQInDevice',
           'DAQOutDeviceBase', 'DAQOutDeviceSim', 'DAQOutDevice')

from functools import partial

from moa.compat import bytes_type, unicode_type
from moa.threads import ScheduledEventLoop
from moa.device import Device
from moa.device.digital import ButtonPort
from moa.device.analog import NumericPropertyChannel

from pybarst.core.server import BarstServer
from pybarst.ftdi import FTDIChannel
from pybarst.ftdi.switch import PinSettings, SerializerSettings
from pybarst.mcdaq import MCDAQChannel
from moadevs.ftdi import FTDISerializerDevice
from moadevs.mfc import MFC
from moadevs.mcdaq import MCDAQDevice

from kivy.properties import (ConfigParserProperty, BooleanProperty,
    ListProperty, ObjectProperty)
from kivy.app import App
from kivy.clock import Clock
from kivy.event import EventDispatcher

from forced_choice import device_config_name


class DeviceStageInterface(object):
    ''' Base class for devices used in this project. It provides the callback
    on exception functionality which calls :meth:`ExperimentApp.device_exception`
    when an exception occurs.
    '''

    exception_callback = None
    '''The partial function that has been scheduled to be called by the kivy
    thread when an exception occurs. This function must be unscheduled when
    stopping, in case there are waiting to be called after it already has been
    stopped.
    '''

    def handle_exception(self, exception, event):
        '''The overwritten method called by the devices when they encounter
        an exception.
        '''
        callback = self.exception_callback = partial(
            App.get_running_app().device_exception, exception, event)
        Clock.schedule_once(callback)

    def cancel_exception(self):
        '''Called to cancel the potentially scheduled exception, scheduled with
        :meth:`handle_exception`.
        '''
        Clock.unshcedule(self.exception_callback)
        self.exception_callback = None

    def create_device(self):
        '''Called from the kivy thread to create the internal target of this
        device.
        '''
        pass

    def start_channel(self):
        '''Called from secondary thread to initialize the target device. This
        is typically called after :meth:`create_device` is called.
        This method typically opens e.g. the Barst channels on the server and
        sets them to their initial values.
        '''
        pass


class Server(DeviceStageInterface, ScheduledEventLoop, Device):
    '''Server device which creates and opens the Barst server.
    '''

    def create_device(self):
        # create actual server
        self.target = BarstServer(
            barst_path=(self.server_path if self.server_path else None),
            pipe_name=self.server_pipe)

    def start_channel(self):
        server = self.target
        server.open_server()

    server_path = ConfigParserProperty('', 'Server', 'barst_path',
        device_config_name, val_type=unicode_type)
    '''The full path to the Barst executable. Could be empty if the server
    is already started, on remote computer, or if it's in the typical
    `Program Files` path. If the server is not running, this path is needed
    to launch the server.

    Defaults to `''`.
    '''

    server_pipe = ConfigParserProperty(b'', 'Server', 'pipe',
                                       device_config_name, val_type=bytes_type)
    '''The full path to the pipe name (to be) used by the server. Examples are
    ``\\\\remote_name\pipe\pipe_name``, where ``remote_name`` is the name of
    the remote computer, or a period (`.`) if the server is local, and
    ``pipe_name`` is the name of the pipe used to create the server.

    Defaults to `''`.
    '''


class FTDIDevChannel(DeviceStageInterface, ScheduledEventLoop, Device):
    '''FTDI channel device. This controls internally both the odor
    and ftdi pin devices.
    '''

    def create_device(self, dev_settings, server):
        '''See :meth:`DeviceStageInterface.create_device`.

        `dev_settings` is the list of device setting to be passed to the
        Barst ftdi channel. `server` is the Barst server.
        '''
        self.target = FTDIChannel(
            channels=dev_settings, server=server, desc=self.ftdi_desc,
            serial=self.ftdi_serial)

    def start_channel(self):
        self.target.open_channel(alloc=True)
        self.target.close_channel_server()
        return self.target.open_channel(alloc=True)

    ftdi_serial = ConfigParserProperty(b'', 'FTDI_chan', 'serial_number',
                                       device_config_name, val_type=bytes_type)
    '''The serial number if the FTDI hardware board. Can be empty.
    '''

    ftdi_desc = ConfigParserProperty(b'', 'FTDI_chan', 'description_id',
                                     device_config_name, val_type=bytes_type)
    '''The description of the FTDI hardware board.

    :attr:`ftdi_serial` or :attr:`ftdi_desc` are used to locate the correct
    board to open. An example is `'Alder Board'` for the Alder board.
    '''


class MassFlowControllerBase(EventDispatcher):

    air = ObjectProperty(None)

    odor_a = ObjectProperty(None)

    odor_b = ObjectProperty(None)


class MassFlowControllerSim(MassFlowControllerBase):

    def __init__(self, air, odor_a, odor_b):
        self.air = NumericPropertyChannel(channel_widget=air[0],
                                          prop_name=air[1])
        self.odor_a = NumericPropertyChannel(channel_widget=odor_a[0],
                                             prop_name=odor_a[1])
        self.odor_b = NumericPropertyChannel(channel_widget=odor_b[0],
                                             prop_name=odor_b[1])


class MFCSafe(DeviceStageInterface, MFC):
    pass


class MassFlowController(MassFlowControllerBase):

    def start_device(self, started_callback, server):
        self.air = MFCSafe(server=server, mfc_port_name=self.air_port,
                           mfc_id=self.air_id)
        self.odor_a = MFCSafe(server=server, mfc_port_name=self.air_port,
                              mfc_id=self.air_id)
        self.odor_b = MFCSafe(server=server, mfc_port_name=self.air_port,
                              mfc_id=self.air_id)

    def start_channel(self):
        pass

    air_id = ConfigParserProperty(0, 'MFC', 'air_id', device_config_name,
                                  val_type=int)

    air_port = ConfigParserProperty('', 'MFC', 'air_port', device_config_name,
                                    val_type=unicode_type)

    odor_a_id = ConfigParserProperty(0, 'MFC', 'odor_a_id', device_config_name,
                                     val_type=int)

    odor_a_port = ConfigParserProperty('', 'MFC', 'odor_a_port',
        device_config_name, val_type=unicode_type)

    odor_b_id = ConfigParserProperty(0, 'MFC', 'odor_b_id', device_config_name,
                                     val_type=int)

    odor_b_port = ConfigParserProperty('', 'MFC', 'odor_b_port',
        device_config_name, val_type=unicode_type)


class FTDIOdorsBase(object):
    '''Base class for the FTDI odor devices.
    '''

    p0 = BooleanProperty(False, allownone=True)
    '''Controls valve 0. '''

    p1 = BooleanProperty(False, allownone=True)
    '''Controls valve 1. '''

    p2 = BooleanProperty(False, allownone=True)
    '''Controls valve 2. '''

    p3 = BooleanProperty(False, allownone=True)
    '''Controls valve 3. '''

    p4 = BooleanProperty(False, allownone=True)
    '''Controls valve 4. '''

    p5 = BooleanProperty(False, allownone=True)
    '''Controls valve 5. '''

    p6 = BooleanProperty(False, allownone=True)
    '''Controls valve 6. '''

    p7 = BooleanProperty(False, allownone=True)
    '''Controls valve 7. '''

    p8 = BooleanProperty(False, allownone=True)
    '''Controls valve 8. '''

    p9 = BooleanProperty(False, allownone=True)
    '''Controls valve 9. '''

    p10 = BooleanProperty(False, allownone=True)
    '''Controls valve 10. '''

    p11 = BooleanProperty(False, allownone=True)
    '''Controls valve 11. '''

    p12 = BooleanProperty(False, allownone=True)
    '''Controls valve 12. '''

    p13 = BooleanProperty(False, allownone=True)
    '''Controls valve 13. '''

    p14 = BooleanProperty(False, allownone=True)
    '''Controls valve 14. '''

    p15 = BooleanProperty(False, allownone=True)
    '''Controls valve 15. '''

    num_boards = ConfigParserProperty(2, 'FTDI_odor', 'num_boards',
                                      device_config_name, val_type=int)
    '''The number of valve boards connected to the FTDI device.

    Each board controls 8 valves. Defaults to 2.
    '''


class FTDIOdorsSim(FTDIOdorsBase, ButtonPort):
    '''Device used when simulating the odor devices.
    '''
    pass


class FTDIOdors(FTDIOdorsBase, DeviceStageInterface, FTDISerializerDevice):
    '''Device used when using the barst ftdi odor devices.
    '''

    def __init__(self, **kwargs):
        mapping = {'p{}'.format(i): i for i in range(8 * self.num_boards)}
        super(FTDIOdors, self).__init__(mapping=mapping, **kwargs)

    def get_settings(self):
        '''Returns the :class:`SerializerSettings` instance used to create the
        Barst FTDI odor device.
        '''
        return SerializerSettings(clock_bit=self.clock_bit,
            data_bit=self.data_bit, latch_bit=self.latch_bit,
            num_boards=self.num_boards, output=True)

    def start_channel(self):
        odors = self.target
        odors.open_channel()
        odors.set_state(True)
        odors.write(set_low=range(8 * self.num_boards))

    clock_bit = ConfigParserProperty(0, 'FTDI_odor', 'clock_bit',
                                     device_config_name, val_type=int)
    '''The pin on the FTDI board to which the valve's clock bit is connected.

    Defaults to zero.
    '''

    data_bit = ConfigParserProperty(0, 'FTDI_odor', 'data_bit',
                                    device_config_name, val_type=int)
    '''The pin on the FTDI board to which the valve's data bit is connected.

    Defaults to zero.
    '''

    latch_bit = ConfigParserProperty(0, 'FTDI_odor', 'latch_bit',
                                     device_config_name, val_type=int)
    '''The pin on the FTDI board to which the valve's latch bit is connected.

    Defaults to zero.
    '''


class DAQInDeviceBase(object):
    '''Base class for the Switch & Sense 8/8 input ports.
    '''

    nose_beam = BooleanProperty(False, allownone=True)
    '''Reads / controls the nose port photobeam.
    '''

    reward_beam_r = BooleanProperty(False, allownone=True)
    '''Reads / controls the reward port photobeam.
    '''


class DAQInDeviceSim(DAQInDeviceBase, ButtonPort):
    '''Device used when simulating the Switch & Sense 8/8 input device.
    '''
    pass


class DAQInDevice(DAQInDeviceBase, DeviceStageInterface, MCDAQDevice):
    '''Device used when using the barst Switch & Sense 8/8 output devices.
    '''

    def __init__(self, **kwargs):
        mapping = {'nose_beam': self.nose_beam_pin,
                   'reward_beam_r': self.reward_beam_r_pin}
        super(DAQInDevice, self).__init__(mapping=mapping, input=True,
                                          **kwargs)

    def create_device(self, server):
        '''See :meth:`DeviceStageInterface.create_device`.

        `server` is the Barst server.
        '''

        self.target = MCDAQChannel(chan=self.SAS_chan, server=server)

    def start_channel(self):
        target = self.target
        target.open_channel()
        target.close_channel_server()
        target.open_channel()

    SAS_chan = ConfigParserProperty(0, 'Switch_and_Sense_8_8',
        'channel_number', device_config_name, val_type=int)
    '''`channel_number`, the channel number of the Switch & Sense 8/8 as
    configured in InstaCal.

    Defaults to zero.
    '''

    nose_beam_pin = ConfigParserProperty(0, 'Switch_and_Sense_8_8',
        'nose_beam_pin', device_config_name, val_type=int)
    '''The port in the Switch & Sense to which the nose port photobeam is
    connected to.

    Defaults to zero.
    '''

    reward_beam_r_pin = ConfigParserProperty(0, 'Switch_and_Sense_8_8',
        'reward_beam_r_pin', device_config_name, val_type=int)
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

    stress_light = BooleanProperty(False, allownone=True)
    '''Controls the stress light.
    '''


class DAQOutDeviceSim(DAQOutDeviceBase, ButtonPort):
    '''Device used when simulating the Switch & Sense 8/8 output device.
    '''
    pass


class DAQOutDevice(DAQOutDeviceBase, DeviceStageInterface, MCDAQDevice):
    '''Device used when using the barst Switch & Sense 8/8 output devices.
    '''

    def __init__(self, **kwargs):
        mapping = {'house_light': self.house_light_pin,
                   'stress_light': self.stress_light_pin}
        super(DAQOutDevice, self).__init__(mapping=mapping, **kwargs)

    def create_device(self, server):
        '''See :meth:`DeviceStageInterface.create_device`.

        `server` is the Barst server.
        '''

        self.target = MCDAQChannel(chan=self.SAS_chan, server=server)

    def start_channel(self):
        self.target.open_channel()
        self.target.write(mask=0xFF, value=0)

    SAS_chan = ConfigParserProperty(0, 'Switch_and_Sense_8_8',
        'channel_number', device_config_name, val_type=int)
    '''`channel_number`, the channel number of the Switch & Sense 8/8 as
    configured in InstaCal.
    '''

    house_light_pin = ConfigParserProperty(0, 'Switch_and_Sense_8_8',
        'house_light_pin', device_config_name, val_type=int)
    '''The port in the Switch & Sense to which the house light is
    connected to.

    Defaults to zero.
    '''

    stress_light_pin = ConfigParserProperty(0, 'Switch_and_Sense_8_8',
        'stress_light_pin', device_config_name, val_type=int)
    '''The port in the Switch & Sense to which the stress light is connected
    to.

    Defaults to zero.
    '''
