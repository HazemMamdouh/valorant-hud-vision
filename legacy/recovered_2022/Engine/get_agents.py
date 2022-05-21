# Recovered from server.exe (PyInstaller 4.10, CPython 3.9) — May 2022 build.
# Reconstructed from bytecode with pycdc/pycdas. Logic is kept 1:1 with the
# original, including its known issues (see docs/ORIGINAL_ANALYSIS.md).
# Only decompiler artefacts were fixed; the unused `from turtle import left`
# import from the original is commented out because it pulls in Tk.
import glob
import os
import time

# from turtle import left   # original: unused import
import cv2
import numpy as np


class GetLiveAgents:
    def __init__(self):
        self.agent_templates = self.generate_agent_templates()
        self.screen_config = self.parse_config()

    def parse_config(self):
        config_txt = open('./Engine/screen_config.txt').readlines()
        config = dict()
        for each_line in config_txt:
            key = each_line.strip().split('=')[0]
            value = int(each_line.strip().split('=')[-1])
            config[key] = value
        return config

    def generate_agent_templates(self):
        generated_agent_templates = []
        for template in glob.glob('./Engine/templates/agents/*'):
            agent = template.split('/')[-1].split('_icon')[0]
            original = cv2.resize(cv2.imread(template, cv2.IMREAD_UNCHANGED), (55, 55))
            gray = cv2.resize(cv2.imread(template, 0), (55, 55))
            o_ret, original_mask = cv2.threshold(original[:, :, 3], 0, 255, cv2.THRESH_BINARY)
            generated_agent_templates.append({
                'agent': agent,
                'original': original,
                'gray': gray,
                'original_mask': original_mask})
        return generated_agent_templates

    def identify_agent(self, resized_frame):
        identified_agent = None
        for template in self.agent_templates:
            result = cv2.matchTemplate(resized_frame, template['gray'], cv2.TM_CCOEFF_NORMED,
                                       None, template['original_mask'])
            max_location = cv2.minMaxLoc(result)[1]          # NB: this is max *value*
            if max_location > 0.5:                           # NB: last match > 0.5 wins
                identified_agent = template['agent']
        return identified_agent

    def process_frame(self, screen_frame):
        all_agents = []
        for agent_place in range(1, 6):
            start_x = self.screen_config['agent' + str(agent_place) + '_x']
            start_y = self.screen_config['agent' + str(agent_place) + '_y']
            end_x = start_x + self.screen_config['agent_w']
            end_y = start_y + self.screen_config['agent_h']
            cropped_agent_image = cv2.cvtColor(
                cv2.resize(screen_frame[start_y:end_y, start_x:end_x], (55, 55)), cv2.COLOR_BGR2GRAY)
            identified_agent = self.identify_agent(cropped_agent_image)
            all_agents.append(identified_agent)
        return all_agents

    def get_curr_agent(self, frame, res):
        agent_fig = frame[self.screen_config['agent_start_y']:self.screen_config['agent_end_y'],
                          self.screen_config['agent_start_x']:self.screen_config['agent_end_x'], :]
        h, w, _ = agent_fig.shape
        mask = cv2.inRange(agent_fig, (100, 131, 34), (239, 253, 199))
        gr_pix = np.sum(mask > 0)
        if gr_pix > h * w / 4:
            res['AGENT_TEAM'] = 'Green'
        else:
            res['AGENT_TEAM'] = 'Red'
        agent_res = cv2.cvtColor(cv2.resize(agent_fig, (55, 55)), cv2.COLOR_BGR2GRAY)
        res['curr_agent'] = self.identify_agent(agent_res)
        return res

    def get_alive_agents(self, frame):
        agent_area = cv2.cvtColor(
            frame[self.screen_config['agent_area_min_y']:self.screen_config['agent_area_max_y'],
                  self.screen_config['agent_area_min_x']:self.screen_config['agent_area_max_x'], :],
            cv2.COLOR_BGR2GRAY)
        agent_area = cv2.Sobel(agent_area, cv2.CV_8U, 1, 0, ksize=3)
        h, w = agent_area.shape
        step = int(w / 5)
        alive_agents = []
        prev_x = 0
        counter = 1
        for end_x in range(step, w, step):
            area = np.sum(agent_area[:, prev_x:end_x] / 255)
            if area > 100:
                alive_agents.append(counter)
            counter += 1
            prev_x = end_x
        return alive_agents

    def get_agents(self, main_frame):
        main_frame_res = cv2.resize(main_frame, (self.screen_config['resize_width'],
                                                 self.screen_config['resize_height']))
        left_alive_agents = self.get_alive_agents(main_frame_res)
        right_alive_agents = self.get_alive_agents(cv2.flip(main_frame_res, 1))
        alive_agents = {}
        for idx in range(1, 11):
            if idx < 6:
                alive_agents['agent' + str(idx)] = idx in left_alive_agents
            else:
                agent_idx = idx + (8 - idx) * 2
                alive_agents['agent' + str(agent_idx)] = idx - 5 in right_alive_agents
        return alive_agents
