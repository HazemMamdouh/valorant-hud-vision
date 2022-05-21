# Recovered from server.exe (PyInstaller 4.10, CPython 3.9) — May 2022 build.
import glob
import os
import time

import cv2
import numpy as np


class GetLoadouts:
    def __init__(self):
        self.mainarms_templates = self.generate_weapon_templates('./Engine/templates/mainarms')
        self.sidearms_templates = self.generate_weapon_templates('./Engine/templates/sidearms')
        self.screen_config = self.parse_config()

    def parse_config(self):
        config_txt = open('./Engine/screen_config.txt').readlines()
        config = dict()
        for each_line in config_txt:
            key = each_line.strip().split('=')[0]
            value = int(each_line.strip().split('=')[-1])
            config[key] = value
        return config

    def generate_weapon_templates(self, filepath):
        generated_weapon_templates = []
        for template in glob.glob(filepath + '/*'):
            weapon = template.split('/')[-1].split('_killfeed')[0]
            generated_weapon_templates.append({
                'weapon': weapon,
                'gray': cv2.imread(template, 0),
                # NB: alpha is dropped by imread(...,0); transparent pixels that
                # carry non-zero RGB leak into the binary template.
                'binary': cv2.threshold(cv2.imread(template, 0), 120, 255, cv2.THRESH_BINARY)[1]})
        return generated_weapon_templates

    def resize_and_pad(self, img, target_h, target_w):
        h, w = img.shape
        resized_w = int(w * target_h / h)
        diff_w = int(target_w - resized_w)
        if diff_w < 0:
            padded_img = cv2.resize(img, (target_w, target_h))
        else:
            img_resize = cv2.resize(img, (resized_w, target_h))
            padded_img = cv2.copyMakeBorder(img_resize, 0, 0, diff_w, 0, cv2.BORDER_CONSTANT, (0, 0, 0))
        return padded_img

    def identify_weapons(self, frame, type):
        identified_weapon = None
        if type == 'side':
            template = self.sidearms_templates
        else:
            template = self.mainarms_templates
        h, w = frame.shape
        max_loc = -999
        for each_template in template:
            curr_template = each_template['binary']
            new_template = self.resize_and_pad(curr_template, h, w)   # re-done every frame
            result = cv2.matchTemplate(frame, new_template, cv2.TM_CCOEFF_NORMED)
            max_location = cv2.minMaxLoc(result)[1]
            if max_loc < max_location:
                identified_weapon = each_template['weapon']
                max_loc = max_location
        return identified_weapon

    def get_loadouts(self, frame):
        """Version wired into the server: returns the slot-1 (sidearm) weapon only."""
        main_frame_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        weap1_xs = self.screen_config['weap1_x_start']
        weap1_xe = self.screen_config['weap1_x_end']
        weap1_ys = self.screen_config['weap1_y_start']
        weap1_ye = self.screen_config['weap1_y_end']
        weapon1 = main_frame_gray[weap1_ys:weap1_ye, weap1_xs:weap1_xe]
        o_ret, weapon1_mask = cv2.threshold(weapon1, 160, 255, cv2.THRESH_BINARY)
        h, w = weapon1.shape
        if np.sum(weapon1_mask) / 255 > h * w / 3 or np.sum(weapon1_mask) / 255 == 0:
            loadout1 = None
        else:
            loadout1 = self.identify_weapons(weapon1_mask, 'side')
        return loadout1

    def get_loadouts2(self, frame):
        """Unused in the 2022 server: reads the primary slot (weap2)."""
        main_frame_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        weap2_xs = self.screen_config['weap2_x_start']
        weap2_xe = self.screen_config['weap2_x_end']
        weap2_ys = self.screen_config['weap2_y_start']
        weap2_ye = self.screen_config['weap2_y_end']
        weapon2 = main_frame_gray[weap2_ys:weap2_ye, weap2_xs:weap2_xe]
        o_ret, weapon2_mask = cv2.threshold(weapon2, 120, 255, cv2.THRESH_BINARY)
        if np.sum(weapon2_mask) / 255 == 0:
            loadout2 = None
        else:
            loadout2 = self.identify_weapons(weapon2_mask, 'main')
        return loadout2
