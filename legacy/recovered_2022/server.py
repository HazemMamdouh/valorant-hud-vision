# Recovered from server.exe (PyInstaller 4.10, CPython 3.9) — May 2022 build.
# Flask-SocketIO server. The engine ran only when a client sent a chat
# `message` / `inf_screen` event (request-driven, no capture loop). The overlay
# was the Angular "chat-example" app that printed the JSON string as a message.
from datetime import datetime

import cv2
import numpy as np
import pyautogui
from flask import Flask, render_template, session, request
from flask_cors import CORS, cross_origin
from flask_socketio import SocketIO

from Engine import inference_videos as inf

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins='*', async_mode='eventlet')
CORS(app)
users = {}


@socketio.on('connect')
def on_connect():
    print('Client connected')
    socketio.emit('my response', {'data': 'Connected'})


@socketio.on('disconnect')
def on_disconnect():
    users.pop(request.sid, 'No user found')
    socketio.emit('current_users', users)
    print('User disconnected!\nThe users are: ', users)


@socketio.on('sign_in')
def user_sign_in(user_name, methods=['GET', 'POST']):
    users[request.sid] = user_name['name']
    socketio.emit('current_users', users)
    print('New user sign in!\nThe users are: ', users)


@socketio.on('message')
def messaging(message, methods=['GET', 'POST']):
    screen = pyautogui.screenshot()
    img = np.array(screen)[:, :, ::-1].copy()
    res = inf.threading_call(img)
    print('received message: ', message)
    message['from'] = request.sid
    message['message'] = str(res)
    socketio.emit('message', message, room=request.sid)
    socketio.emit('message', message, room=message['to'])


@socketio.on('inf_screen')
def inf_screen(message, methods=['GET', 'POST']):
    screen = pyautogui.screenshot()
    img = np.array(screen)[:, :, ::-1].copy()
    res = inf.threading_call(img)
    print(res)
    socketio.emit('inf_screen', str(res), room=message['to'])


if __name__ == '__main__':
    socketio.run(app, debug=True)
