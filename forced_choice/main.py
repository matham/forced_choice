'''The main module that starts the experiment.
'''

__all__ = ('ForcedChoiceApp', 'run_app')


from functools import partial
from os.path import join, dirname

from cplcom.app import ExperimentApp, run_app as run_cpl_app

from kivy.resources import resource_add_path
from kivy.lang import Builder
from kivy.garden.graph import Graph
from kivy.properties import ObjectProperty

import forced_choice.graphics
import forced_choice.stages


class ForcedChoiceApp(ExperimentApp):

    timer = ObjectProperty(None)

    def __init__(self, **kwargs):
        super(ForcedChoiceApp, self).__init__(**kwargs)
        resource_add_path(join(dirname(dirname(__file__)), 'data'))
        Builder.load_file(join(dirname(__file__), 'Experiment.kv'))

run_app = partial(run_cpl_app, ForcedChoiceApp)

if __name__ == '__main__':
    run_app()
