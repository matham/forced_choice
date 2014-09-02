from setuptools import setup, find_packages
import go_nogo


setup(
    name='Go-NoGo',
    version=go_nogo.__version__,
    packages=find_packages(),
    install_requires=['moa', 'pybarst', 'moadevs'],
    author='Matthew Einhorn',
    author_email='moiein2000@gmail.com',
    url='https://cpl.cornell.edu/',
    license='MIT',
    description='Go/NoGo experiment.',
    entry_points={'console_scripts': ['go_nogo=go_nogo.main:run_app']},
    )
