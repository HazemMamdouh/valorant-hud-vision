# Recovered from server.exe (PyInstaller 4.10, CPython 3.9) — May 2022 build.
# HP / shield were read with Tesseract OCR (an LSTM neural network in v4+).
# The refactored engine replaces this with pure template matching.
import glob
import os
import re
import time

import cv2
import numpy as np
import pytesseract

# original: hard-coded Windows path
if os.name == 'nt':
    pytesseract.pytesseract.tesseract_cmd = 'C:\\Program Files\\Tesseract-OCR\\tesseract.exe'


class GetCurrAgentInfo:
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
                'agent': agent, 'original': original, 'gray': gray,
                'original_mask': original_mask})
        return generated_agent_templates

    def identify_agent(self, resized_frame):
        identified_agent = None
        for template in self.agent_templates:
            result = cv2.matchTemplate(resized_frame, template['gray'], cv2.TM_CCOEFF_NORMED,
                                       None, template['original_mask'])
            max_location = cv2.minMaxLoc(result)[1]
            if max_location > 0.5:
                identified_agent = template['agent']
        return identified_agent

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
        return self.identify_agent(agent_res)

    def get_agent_health(self, frame, res, points):
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if points == 'hp':
            health_points = frame[self.screen_config['hp_start_y']:self.screen_config['hp_end_y'],
                                  self.screen_config['hp_start_x']:self.screen_config['hp_end_x']]
            health_points = cv2.threshold(health_points, 160, 255, cv2.THRESH_BINARY_INV)[1]
            hp = re.sub('[^z0-9]+', '', pytesseract.image_to_string(health_points, config='--psm 6').strip())
            if hp == '':
                hp = 0
            return hp
        if points == 'sh':
            shield_points = frame[self.screen_config['sh_start_y']:self.screen_config['sh_end_y'],
                                  self.screen_config['sh_start_x']:self.screen_config['sh_end_x']]
            shield_points = cv2.threshold(shield_points, 160, 255, cv2.THRESH_BINARY_INV)[1]
            sh = re.sub('[^z0-9]+', '', pytesseract.image_to_string(shield_points, config='--psm 6').strip())
            if sh == '':
                sh = 0
            return sh
        return None

    def get_abilities(self, agent, frame, res, each_ab):
        if each_ab in ('q', 'e') and agent in ('Reyna',):
            each_ab = 'qe'
        if each_ab != 'x' and each_ab != 'Ult':
            ab_box = frame[self.screen_config['ab_' + each_ab + '_start_y']:self.screen_config['ab_' + each_ab + '_end_y'],
                           self.screen_config['ab_' + each_ab + '_start_x']:self.screen_config['ab_' + each_ab + '_end_x'], :]
            ab_bin = cv2.threshold(ab_box[:, :, 1], 220, 255, cv2.THRESH_BINARY)[1]
            out = cv2.connectedComponentsWithStats(ab_bin, 8, cv2.CV_32S)
            ab_count = 0
            max_comp = 0
            area_comp = []
            for idx in range(0, out[0]):
                area = np.sum(out[1] == idx + 1)
                area_comp.append(area)
                if area > 50:
                    max_comp = max(area, max_comp)
            if max_comp == 0:
                ab_count = 0
            else:
                ab_count = np.sum(np.array(area_comp) / max_comp > 0.8)
            return ab_count
        if each_ab == 'x':
            ab_box = frame[self.screen_config['ab_' + each_ab + '_start_y']:self.screen_config['ab_' + each_ab + '_end_y'],
                           self.screen_config['ab_' + each_ab + '_start_x']:self.screen_config['ab_' + each_ab + '_end_x'], :]
            ab_bin = cv2.threshold(ab_box[:, :, 1], 200, 255, cv2.THRESH_BINARY)[1]
            kernel = np.zeros((3, 3), dtype=np.uint8)
            kernel[1, :] = 1
            closing = cv2.morphologyEx(ab_bin, cv2.MORPH_CLOSE, kernel)
            diff_close = closing - ab_bin
            out = cv2.connectedComponentsWithStats(diff_close, 8, cv2.CV_32S)
            ab_x_count = 0
            for idx in range(0, out[0]):
                area = np.sum(out[1] == idx + 1)
                if area > 0:
                    ab_x_count += 1
            if ab_x_count == 0:
                h, _ = ab_bin.shape
                out = cv2.connectedComponents(ab_bin[:int(h / 2), :])
                if out[0] == 2:
                    ab_x_count = 1
            elif ab_x_count > 1:
                ab_x_count += 1
            return ab_x_count
        if each_ab == 'Ult':
            ab_box = frame[self.screen_config['ab_x_start_y']:self.screen_config['ab_x_end_y'],
                           self.screen_config['ab_x_start_x']:self.screen_config['ab_x_end_x'], :]
            ab_bin = cv2.threshold(ab_box[:, :, 1], 200, 255, cv2.THRESH_BINARY)[1]
            out = cv2.connectedComponentsWithStats(ab_bin, 8, cv2.CV_32S)
            ab_count = 0
            max_comp = 0
            area_comp = []
            for idx in range(0, out[0]):
                area = np.sum(out[1] == idx + 1)
                area_comp.append(area)
                if area > 250:
                    max_comp = max(area, max_comp)
            if max_comp != 0:
                return True
            return False
