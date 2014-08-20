from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.properties import (ObjectProperty, StringProperty, NumericProperty,
                             BooleanProperty)
from kivy.factory import Factory
from kivy.lang import Builder

from os import path
Builder.load_file(path.join(path.dirname(__file__), 'display.kv'))


class MainView(BoxLayout):
    pass


class OdorSwitch(Factory.get('SwitchIcon')):

    odor_dev = ObjectProperty(None, allownone=True)


class SimulatedDevices(GridLayout):

    pin_dev = ObjectProperty(None, allownone=True)
    odor_dev = ObjectProperty(None, allownone=True)
    daq_in_dev = ObjectProperty(None, allownone=True)
    daq_out_dev = ObjectProperty(None, allownone=True)


class TrialOutcome(GridLayout):

    animal = StringProperty('')

    block = NumericProperty(0)

    trial = NumericProperty(0)

    ttnp = NumericProperty(None, allownone=True)

    tinp = NumericProperty(None, allownone=True)

    ttrp = NumericProperty(None, allownone=True)

    iti = NumericProperty(None, allownone=True)

    is_go = BooleanProperty(None, allownone=True)

    went = BooleanProperty(None, allownone=True)

    passed = BooleanProperty(None, allownone=True)

    incomplete = BooleanProperty(None, allownone=True)

    rewarded = BooleanProperty(None, allownone=True)

    def init_outcome(self, animal, block, trial):
        self.animal = animal
        self.block = block
        self.trial = trial

        self.ttnp = self.tinp = self.ttrp = self.iti = self.is_go = None
        self.went = self.passed = self.incomplete = self.rewarded = None


class TrialPrediction(Label):

    odor = StringProperty('')

    trial = NumericProperty(0)

    outcome = BooleanProperty(None)

    outcome_text = StringProperty('')

    go = BooleanProperty(False)
