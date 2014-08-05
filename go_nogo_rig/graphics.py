from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.properties import (ObjectProperty, StringProperty, NumericProperty,
                             BooleanProperty)


class MainView(BoxLayout):
    pass


class TrialOutcome(GridLayout):

    outcome = ObjectProperty(None)

    animal = StringProperty('')

    block = NumericProperty(0)

    def __init__(self, outcome=None, animal='', block=0, **kw):
        from go_nogo_rig.stages import TrialOutcomeStats
        self.outcome = outcome if outcome is not None else TrialOutcomeStats()
        self.animal = animal
        self.block = block
        super(TrialOutcome, self).__init__(**kw)


class TrialPrediction(Label):

    odor = StringProperty('')
    trial = NumericProperty(0)
    outcome = BooleanProperty(None)
    go = BooleanProperty(False)
