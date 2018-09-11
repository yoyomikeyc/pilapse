"""Module to load configuration yaml"""
import sys
import os
import pprint
import yaml

def load_config():
    print("Reading config file ...")
    config = yaml.safe_load(open(os.path.join(sys.path[0], "config.yml")))
    pprint.pprint(config)
    return config
