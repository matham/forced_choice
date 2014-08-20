from setuptools import setup, find_packages
import go_nogo_rig


setup(
    name='Go-NoGo',
    version=go_nogo_rig.__version__,
    packages=find_packages(),
    install_requires=['moa', 'pybarst', 'moadevs'],
    author='Matthew Einhorn',
    author_email='moiein2000@gmail.com',
    url='https://cpl.cornell.edu/',
    license='MIT',
    description='Go/NoGo experiment.',
    entry_points={'console_scripts': ['go_nogo=go_nogo_rig.main:run_app']},
    )
