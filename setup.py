from setuptools import setup, find_packages
import forced_choice


setup(
    name='Forced Choice',
    version=forced_choice.__version__,
    packages=find_packages(),
    install_requires=['moa', 'pybarst', 'moadevs', 'ffpyplayer', 'cplcom'],
    author='Matthew Einhorn',
    author_email='moiein2000@gmail.com',
    url='https://cpl.cornell.edu/',
    license='MIT',
    description='Forced choice experiment.',
    entry_points={'console_scripts':
                  ['forced_choice=forced_choice.main:run_app']},
    )
