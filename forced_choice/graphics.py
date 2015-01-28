# -*- coding: utf-8 -*-
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.properties import (ObjectProperty, StringProperty, NumericProperty,
                             BooleanProperty)
from kivy.factory import Factory
from kivy.lang import Builder
from kivy.app import App
from kivy.utils import get_color_from_hex as rgb
from kivy.garden.graph import Graph, MeshLinePlot
from kivy.clock import Clock

from os import path
Builder.load_file(path.join(path.dirname(__file__), 'display.kv'))


class MainView(BoxLayout):
    pass


class DeviceSwitch(Factory.get('SwitchIcon')):

    def __init__(self, **kw):
        super(DeviceSwitch, self).__init__(**kw)
        Clock.schedule_once(self._bind_button)

    def _bind_button(self, *largs):
        if (not self.input and not App.get_running_app().simulate
            and not self.virtual):
            self.bind(state=self.update_from_button)

    dev = ObjectProperty(None, allownone=True)

    _dev = None

    channel = StringProperty(None)

    input = BooleanProperty(False)

    virtual = BooleanProperty(False)
    '''If it's backed up by a button. Similar to app.simulate, but even if
    that's false it could be kivy button backed.
    '''

    multichannel = BooleanProperty(True)

    _last_chan_value = None

    def on_dev(self, *largs):
        if self._dev:
            self._dev.unbind(**{self.channel: self.update_from_channel})
        self._dev = self.dev
        if (self.dev and not App.get_running_app().simulate and
                not self.virtual):
            self.dev.bind(**{self.channel: self.update_from_channel})

    def update_from_channel(self, *largs):
        '''A convenience method which takes the state of the simulated device
        (buttons) and the state of the actual device and returns if the
        simulated device should be `'down'` or `'normal'`.

        It is used to set the button state to match the actual device state,
        if not simulating.
        '''

        self._last_chan_value = state = getattr(self.dev, self.channel)
        self.state = 'down' if state else 'normal'
        self._last_chan_value = None

    def update_from_button(self, *largs):
        '''A convenience method which takes the state of the simulated device
        (buttons) and sets the state of the actual device to match it when not
        simulating.
        '''
        dev = self.dev
        if dev is not None:
            if self.state == 'down':
                if self._last_chan_value is not True:
                    self._last_chan_value = None
                    if self.multichannel:
                        dev.set_state(high=[self.channel])
                    else:
                        dev.set_state(True)
            else:
                if self._last_chan_value is not False:
                    self._last_chan_value = None
                    if self.multichannel:
                        dev.set_state(low=[self.channel])
                    else:
                        dev.set_state(False)


class OdorContainer(GridLayout):

    def __init__(self, **kw):
        super(OdorContainer, self).__init__(**kw)
        switch = [Factory.get('OdorSwitch'), Factory.get('OdorDarkSwitch')]
        for i in range(16):
            self.add_widget(switch[i % 2](channel='p{}'.format(i)))


class SimulatedDevices(GridLayout):

    odor_dev = ObjectProperty(None, allownone=True)
    daq_in_dev = ObjectProperty(None, allownone=True)
    daq_out_dev = ObjectProperty(None, allownone=True)
    sound_l_dev = ObjectProperty(None, allownone=True)
    sound_r_dev = ObjectProperty(None, allownone=True)


class TrialOutcome(GridLayout):

    animal = StringProperty('')

    block = NumericProperty(0)

    trial = NumericProperty(0)

    ttnp = NumericProperty(None, allownone=True)

    tinp = NumericProperty(None, allownone=True)

    ttrp = NumericProperty(None, allownone=True)

    iti = NumericProperty(None, allownone=True)

    side = StringProperty('-')

    side_went = StringProperty('-')

    rewarded = StringProperty('-')

    passed = BooleanProperty(None, allownone=True)

    incomplete = BooleanProperty(None, allownone=True)

    def init_outcome(self, animal, block, trial):
        self.animal = animal
        self.block = block
        self.trial = trial

        self.ttnp = self.tinp = self.ttrp = self.iti = None
        self.passed = self.incomplete = None
        self.side = self.side_went = self.rewarded = '-'


class TrialPrediction(Label):

    odor = StringProperty('')

    trial = NumericProperty(0)

    outcome = BooleanProperty(None)

    outcome_text = StringProperty('')

    side = StringProperty(u'Ø')

    side_went = StringProperty(u'Ø')

    side_rewarded = StringProperty(u'Ø')
