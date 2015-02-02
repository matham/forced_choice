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

import cplcom.graphics

from os import path
Builder.load_file(path.join(path.dirname(__file__), 'display.kv'))


class MainView(BoxLayout):
    pass


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
