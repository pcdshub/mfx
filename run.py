import sys
import os
import matplotlib.pyplot as plt

# plt.ion()

# sys.path.append(os.getcwd())
# from mfx.optimize.beam import Beam
# b = Beam()
# b.focus(0.0)

import numpy as np
desc = {'data_keys':
    {'temperature':
        {'dtype': 'number',
         'source': '<descriptive string>',
         'shape': [],
         'units': 'K',
         'precision': 3},
     'x_setpoint':
        {'dtype': 'number',
         'source': '<descriptive string>',
         'shape': [],
         'units': 'mm',
         'precision': 2},
     'x_readback':
        {'dtype': 'number',
         'source': '<descriptive string>',
         'shape': [],
         'units': 'mm',
         'precision': 2}}}

event_data = {
    "data": {
        "det": np.float64(0.6065306597126334),
        "motor": np.float64(1.0),
        "motor_setpoint": np.float64(1.0),
    },
    "descriptor": desc,
    "filled": {},
    "seq_num": 1,
    "time": 1745516544.202272,
    "timestamps": {
        "det": 1745516544.200438,
        "motor": 1745516544.2000709,
        "motor_setpoint": 1745516544.199954,
    },
   "uid": "0fbde9d6-f012-426f-926b-b96d2425289a",
}
event_data = [event_data]

from collections import OrderedDict

descriptor = {
    "configuration": {
        "det": {
            "data": {
                "det_Imax": 1,
                "det_center": 0,
                "det_noise": "none",
                "det_noise_multiplier": 1,
                "det_sigma": 1,
            },
            "data_keys": OrderedDict(
                [
                    (
                        "det_Imax",
                        {"dtype": "integer", "shape": [], "source": "SIM:det_Imax"},
                    ),
                    (
                        "det_center",
                        {"dtype": "integer", "shape": [], "source": "SIM:det_center"},
                    ),
                    (
                        "det_sigma",
                        {"dtype": "integer", "shape": [], "source": "SIM:det_sigma"},
                    ),
                    (
                        "det_noise",
                        {
                            "dtype": "integer",
                            "enum_strs": ("none", "poisson", "uniform"),
                            "shape": [],
                            "source": "SIM:det_noise",
                        },
                    ),
                    (
                        "det_noise_multiplier",
                        {
                            "dtype": "integer",
                            "shape": [],
                            "source": "SIM:det_noise_multiplier",
                        },
                    ),
                ]
            ),
            "timestamps": {
                "det_Imax": 1745516543.9561658,
                "det_center": 1745516543.9561641,
                "det_noise": 1745516543.956157,
                "det_noise_multiplier": 1745516543.956162,
                "det_sigma": 1745516543.956168,
            },
        },
        "motor": {
            "data": {"motor_acceleration": 1, "motor_velocity": 1},
            "data_keys": OrderedDict(
                [
                    (
                        "motor_velocity",
                        {
                            "dtype": "integer",
                            "shape": [],
                            "source": "SIM:motor_velocity",
                        },
                    ),
                    (
                        "motor_acceleration",
                        {
                            "dtype": "integer",
                            "shape": [],
                            "source": "SIM:motor_acceleration",
                        },
                    ),
                ]
            ),
            "timestamps": {
                "motor_acceleration": 1745516543.95071,
                "motor_velocity": 1745516543.950704,
            },
        },
    },
    "data_keys": {
        "det": {
            "dtype": "number",
            "object_name": "det",
            "precision": 3,
            "shape": [],
            "source": "SIM:det",
        },
        "motor": {
            "dtype": "number",
            "object_name": "motor",
            "precision": 3,
            "shape": [],
            "source": "SIM:motor",
        },
        "motor_setpoint": {
            "dtype": "number",
            "object_name": "motor",
            "precision": 3,
            "shape": [],
            "source": "SIM:motor_setpoint",
        },
    },
    "hints": {"det": {"fields": ["det"]}, "motor": {"fields": ["motor"]}},
    "name": "primary",
    "object_keys": {"det": ["det"], "motor": ["motor", "motor_setpoint"]},
    "run_start": "38fc4999-b11a-4a4b-8be3-622323b32759",
    "time": 1745516544.201453,
    "uid": "b2c9a782-533e-42f2-8ace-568244a6c7cc",
}

from event_model import compose_event_page

descriptor_uid = descriptor["uid"]
print({descriptor_uid:[1]})
new_doc = compose_event_page(
    descriptor=descriptor,
    event_counters={descriptor_uid:[1]},
    data={descriptor_uid:event_data},
    timestamps={descriptor_uid: [event_data[0]["time"]]},
    seq_num=[1],
    filled={descriptor_uid: [False]},
)
