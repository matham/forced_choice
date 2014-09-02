from setuptools import setup, find_packages
import forced_choice


setup(
    name='Go-NoGo',
    version=forced_choice.__version__,
    packages=find_packages(),
    install_requires=['moa', 'pybarst', 'moadevs'],
    author='Matthew Einhorn',
    author_email='moiein2000@gmail.com',
    url='https://cpl.cornell.edu/',
    license='MIT',
    description='Go/NoGo experiment.',
    entry_points={'console_scripts': ['forced_choice=forced_choice.main:run_app']},
    )
