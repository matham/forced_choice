# -*- coding: utf-8 -*-
'''Graphics
=====================

GUI elements.
'''

from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.properties import StringProperty, NumericProperty, BooleanProperty
from kivy.lang import Builder
from kivy.garden.graph import Graph

import cplcom.graphics

from os import path

__all__ = ('TrialOutcome', 'TrialPrediction')

Builder.load_file(path.join(path.dirname(__file__), 'display.kv'))


class TrialOutcome(GridLayout):
    '''Visualizes the outcome of a trial. Typically a few instances are created
    and then reused in a rotating fashion.
    '''

    animal = StringProperty('')
    '''The animal ID for the trial.
    '''

    block = NumericProperty(0)
    '''The zero-based block number.
    '''

    trial = NumericProperty(0)
    '''The zero-based trial number.
    '''

    ttnp = NumericProperty(None, allownone=True)
    '''How long from trial start until it visited the nose port.
    '''

    tinp = NumericProperty(None, allownone=True)
    '''How long it spent in the nose port.
    '''

    ttrp = NumericProperty(None, allownone=True)
    '''How long it spent after the nose poke until it visited a feeder.
    '''

    iti = NumericProperty(None, allownone=True)
    '''The ITI of the trial.
    '''

    side = StringProperty('-')
    '''The side that will be rewarded.
    '''

    side_went = StringProperty('-')
    '''The feeder side the animal visited.
    '''

    rewarded = StringProperty('-')
    '''Which feeder side was rewarded.
    '''

    passed = BooleanProperty(None, allownone=True)
    '''Whether the trial was passes or failed.
    '''

    incomplete = BooleanProperty(None, allownone=True)
    '''Whether the trial ended with an incomplete if the animal didn't sample
    the odor stream long enough.
    '''

    def init_outcome(self, animal, block, trial):
        '''Called at the start of a trial with the trial information in
        order to reset the widget and prepare for this trial.
        '''
        self.animal = animal
        self.block = block
        self.trial = trial

        self.ttnp = self.tinp = self.ttrp = self.iti = None
        self.passed = self.incomplete = None
        self.side = self.side_went = self.rewarded = '-'


class TrialPrediction(Label):
    '''A Label generated for each trial ahead of time, indicating the
    pre-computed params for that trial.
    '''

    odor = StringProperty('')
    '''The odor scehduled for that trial.
    '''

    trial = NumericProperty(0)
    '''The trial number.
    '''

    outcome = BooleanProperty(None)
    '''Whether it passed or failed the trial.
    '''

    outcome_text = StringProperty('')
    '''A textual version of :attr:`outcome`.
    '''

    side = StringProperty(u'Ø')
    '''The feeder side the animal has to go to for this trial in order to get
    rewarded.
    '''

    side_went = StringProperty(u'Ø')
    '''Which feeder side the animal actually went to for the trial.
    '''

    side_rewarded = StringProperty(u'Ø')
    '''Which feeder side was rewarded for this trial.
    '''
