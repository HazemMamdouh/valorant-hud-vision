# Recovered from server.exe (PyInstaller 4.10, CPython 3.9) — May 2022 build.
# Orchestrates all detectors. `threading_call` spawns 14 threads *per frame*
# that write into one shared dict (works under the GIL, but is racy by design).
import json
import threading
import time

import cv2
import numpy as np

from . import get_agents, get_loadouts, get_agent_abilities_health, get_spike_carrier

get_live_agents = get_agents.GetLiveAgents()
get_curr_loadout = get_loadouts.GetLoadouts()
get_agent_info = get_agent_abilities_health.GetCurrAgentInfo()
get_spike_info = get_spike_carrier.GetSpike()
screen_config = {'resize_width': 1280, 'resize_height': 720}


class NpEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super(NpEncoder, self).default(obj)


class NewThread(threading.Thread):
    def __init__(self, frame, key, res_json):
        threading.Thread.__init__(self)
        self.key = key
        self.res = res_json
        self.frame = frame

    def run(self):
        if self.key == 'CURR_AGENT':
            self.res['CURR_AGENT'] = get_agent_info.get_curr_agent(self.frame, self.res)
        elif self.key == 'HP':
            self.res['HP'] = get_agent_info.get_agent_health(self.frame, self.res, 'hp')
        elif self.key == 'SHIELD':
            self.res['SHIELD'] = get_agent_info.get_agent_health(self.frame, self.res, 'sh')
        elif self.key == 'AB_Q':
            self.res['AB_Q'] = get_agent_info.get_abilities(self.res['CURR_AGENT'], self.frame, self.res, 'q')
        elif self.key == 'AB_E':
            self.res['AB_E'] = get_agent_info.get_abilities(self.res['CURR_AGENT'], self.frame, self.res, 'e')
        elif self.key == 'AB_C':
            self.res['AB_C'] = get_agent_info.get_abilities(None, self.frame, self.res, 'c')
        elif self.key == 'AB_X':
            self.res['AB_X'] = get_agent_info.get_abilities(None, self.frame, self.res, 'x')
        elif self.key == 'ULT_READY':
            self.res['ULT_READY'] = get_agent_info.get_abilities(None, self.frame, self.res, 'Ult')
        elif self.key == 'CURR_WEAPON':
            self.res['CURR_WEAPON'] = get_curr_loadout.get_loadouts(self.frame)
        elif self.key == 'SPIKE_PLANTED':
            self.res['SPIKE_PLANTED'] = get_spike_info.get_spike_status(self.frame)
        elif self.key == 'SPIKE_CARRIER_IDX':
            self.res['SPIKE_CARRIER_IDX'] = get_spike_info.get_spike_carrier(self.frame)
        elif self.key == 'LEFT_ALIVE_AGENTS':
            self.res['ALIVE_AGENTS']['LEFT'] = get_live_agents.get_alive_agents(self.frame)
        elif self.key == 'RIGHT_ALIVE_AGENTS':
            self.res['ALIVE_AGENTS']['RIGHT'] = get_live_agents.get_alive_agents(cv2.flip(self.frame, 1))
        elif self.key == 'MERGE_ALIVE':
            alive_agents = {}
            for idx in range(1, 11):
                if idx < 6:
                    alive_agents['agent' + str(idx)] = idx in self.res['ALIVE_AGENTS']['LEFT']
                else:
                    agent_idx = idx + (8 - idx) * 2
                    alive_agents['agent' + str(agent_idx)] = idx - 5 in self.res['ALIVE_AGENTS']['RIGHT']
            self.res['ALIVE_AGENTS'] = alive_agents


def sequential_call(frame):
    result_Json = dict()
    result_Json['ALIVE_AGENTS'] = {}
    frame = cv2.resize(frame, (screen_config['resize_width'], screen_config['resize_height']))
    result_Json['CURR_AGENT'] = get_agent_info.get_curr_agent(frame, result_Json)
    result_Json['HP'] = get_agent_info.get_agent_health(frame, result_Json, 'hp')
    result_Json['SHIELD'] = get_agent_info.get_agent_health(frame, result_Json, 'sh')
    result_Json['AB_Q'] = get_agent_info.get_abilities(result_Json['CURR_AGENT'], frame, result_Json, 'q')
    result_Json['AB_E'] = get_agent_info.get_abilities(result_Json['CURR_AGENT'], frame, result_Json, 'e')
    result_Json['AB_C'] = get_agent_info.get_abilities(result_Json['CURR_AGENT'], frame, result_Json, 'c')
    result_Json['AB_X'] = get_agent_info.get_abilities(result_Json['CURR_AGENT'], frame, result_Json, 'x')
    result_Json['ULT_READY'] = get_agent_info.get_abilities(result_Json['CURR_AGENT'], frame, result_Json, 'Ult')
    result_Json['CURR_WEAPON'] = get_curr_loadout.get_loadouts(frame)
    result_Json['SPIKE_PLANTED'] = get_spike_info.get_spike_status(frame)
    result_Json['SPIKE_CARRIER_IDX'] = get_spike_info.get_spike_carrier(frame)
    left_alive = get_live_agents.get_alive_agents(frame)
    right_alive = get_live_agents.get_alive_agents(cv2.flip(frame, 1))
    alive_agents = {}
    for idx in range(1, 11):
        if idx < 6:
            alive_agents['agent' + str(idx)] = idx in left_alive
        else:
            agent_idx = idx + (8 - idx) * 2
            alive_agents['agent' + str(agent_idx)] = idx - 5 in right_alive
    result_Json['ALIVE_AGENTS'] = alive_agents
    return json.dumps(result_Json, cls=NpEncoder)


def threading_call(frame):
    result_Json = dict()
    result_Json['ALIVE_AGENTS'] = {}
    frame = cv2.resize(frame, (screen_config['resize_width'], screen_config['resize_height']))
    first_wave = ['CURR_AGENT', 'HP', 'SHIELD', 'AB_X', 'ULT_READY', 'CURR_WEAPON', 'SPIKE_PLANTED',
                  'SPIKE_CARRIER_IDX', 'LEFT_ALIVE_AGENTS', 'RIGHT_ALIVE_AGENTS', 'AB_C']
    threads = [NewThread(frame, k, result_Json) for k in first_wave]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    threads = [NewThread(frame, k, result_Json) for k in ['AB_Q', 'AB_E', 'MERGE_ALIVE']]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    if result_Json['SPIKE_PLANTED']:
        result_Json['SPIKE_CARRIER_IDX'] = None
    return json.dumps(result_Json, cls=NpEncoder)
