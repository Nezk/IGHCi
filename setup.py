from setuptools import setup, find_packages
import os

with open('requirements.txt') as f:
    requirements = f.read().splitlines()

setup(
    name             = "IGHCi",
    version          = "0.0.1",
    description      = "Minimalistic kernel for Haskell",
    long_description = open('README.md').read(),
    license          = "GPLv3",
    classifiers      = [
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Programming Language :: Python :: 3",
    ],
    packages             = find_packages(),
    install_requires     = requirements,
    include_package_data = True,
    entry_points         = {
        'console_scripts': [
            'IGHCi-install = IGHCi.install:main',
        ],
    }
)
