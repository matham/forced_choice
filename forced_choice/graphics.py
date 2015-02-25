# -*- coding: utf-8 -*-
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.properties import StringProperty, NumericProperty, BooleanProperty
from kivy.lang import Builder
from kivy.garden.graph import Graph

import cplcom.graphics

from os import path
Builder.load_file(path.join(path.dirname(__file__), 'display.kv'))


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
