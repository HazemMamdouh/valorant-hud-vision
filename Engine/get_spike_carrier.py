import numpy as np
import time
import glob
import cv2


class GetSpike:
    def __init__(self):
        self.screen_config = self.parse_config()

    def parse_config(self):
        config_txt = open('./Engine/screen_config.txt').readlines()
        config = dict()
        for each_line in config_txt:
            key = each_line.strip().split('=')[0]
            value = int(each_line.strip().split('=')[-1])
            config[key] = value
        return config

    def get_spike_status(self, frame):
        frame = cv2.resize(frame, (self.screen_config['resize_width'], self.screen_config['resize_height']))
        spike = frame[self.screen_config['spike_min_y']:self.screen_config['spike_max_y'],
                      self.screen_config['spike_min_x']:self.screen_config['spike_max_x'], :]
        spike = cv2.cvtColor(spike, cv2.COLOR_BGR2HSV)
        lower1 = np.array([0, 100, 20]);   upper1 = np.array([10, 255, 255])
        lower2 = np.array([160, 100, 20]); upper2 = np.array([179, 255, 255])
        lower_mask = cv2.inRange(spike, lower1, upper1)
        upper_mask = cv2.inRange(spike, lower2, upper2)
        full_mask = lower_mask + upper_mask
        red_pix = np.sum(full_mask / 255)
        total_pix = spike.shape[0] * spike.shape[1]
        if red_pix > total_pix / 2:
            return True

    def get_spike_carrier(self, frame):
        frame = cv2.resize(frame, (self.screen_config['resize_width'], self.screen_config['resize_height']))
        frame_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        left_carrier = frame_gray[self.screen_config['carrier_min_y']:self.screen_config['carrier_max_y'],
                                  self.screen_config['carrier_min_x']:self.screen_config['carrier_max_x']]
        carrier_mask = np.array(left_carrier > 240, dtype=np.float32)
        h, w = carrier_mask.shape
        step = int(w / 5)
        carrier_idx = None
        prev_x = 0
        counter = 1
        for end_x in range(step, w, step):
            area = np.sum(carrier_mask[:, prev_x:end_x])
            if area > h * w / 100:
                carrier_idx = counter
            counter += 1
            prev_x = end_x
        if carrier_idx is not None:
            return carrier_idx
        rev_frame = cv2.flip(frame_gray, 1)
        right_carrier = rev_frame[self.screen_config['carrier_min_y']:self.screen_config['carrier_max_y'],
                                  self.screen_config['carrier_min_x']:self.screen_config['carrier_max_x']]
        carrier_mask = np.array(right_carrier > 240, dtype=np.float32)
        h, w = carrier_mask.shape
        step = int(w / 5)
        carrier_idx = None
        prev_x = 0
        counter = 10
        for end_x in range(step, w, step):
            area = np.sum(carrier_mask[:, prev_x:end_x])
            if area > h * w / 100:
                carrier_idx = counter
            counter -= 1
            prev_x = end_x
        if carrier_idx is not None:
            return carrier_idx
