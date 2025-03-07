import html
import json

from gevent import monkey
monkey.patch_all()

from flask import Flask, render_template, request
from werkzeug.debug import DebuggedApplication

from geventwebsocket import WebSocketServer, WebSocketApplication, Resource
import geventwebsocket

flask_app = Flask(__name__, static_folder="static", template_folder="templates")
flask_app.debug = True

empty, black, white = 0, -1, 1
directions = [(1, 1), (-1, 1), (0, 1), (1, -1), (-1, -1), (0, -1), (1, 0), (-1, 0)]

online = 0
last_chat = []


def init_board():
    global board, score, turn, last_move
    board = [[empty for x in range(8)] for y in range(8)]
    board[3][3] = board[4][4] = white
    board[3][4] = board[4][3] = black
    turn = black
    score = '2-2'
    last_move = None

init_board()

client_name = {}
color_client = {}


def possible_move(board, x, y, color):
    if board[x][y] != empty:
        return False
    for direction in directions:
        if flip_in_direction(board, x, y, direction, color):
            return True
    return False


def possible_moves(board, color):
    return [(x,y) for x in range(8) for y in range(8) if possible_move(board, x, y, color)]


def flip_in_direction(board, x, y, direction, color):
    other_color = False
    while True:
        x, y = x+direction[0], y+direction[1]
        if x not in range(8) or y not in range(8):
            return False
        square = board[x][y]
        if square == empty:
            return False
        if square != color:
            other_color = True
        else:
            return other_color


def flip_stones(board, move, color):
    for direction in directions:
        if flip_in_direction(board, move[0], move[1], direction, color):
            x, y = move[0]+direction[0], move[1]+direction[1]
            while board[x][y] != color:
                board[x][y] = color
                x, y = x+direction[0], y+direction[1]
    board[move[0]][move[1]] = color


def panel_data(client=None):
    result = {
        'score': score,
        'online': online,
    }
    for color in ('black', 'white'):
        player = '(empty)'
        disabled = ''
        text = 'zit'
        if color in color_client:
            player = client_name.get(color_client[color], '(empty)')
            if client == color_client[color]:
                text = 'sta'
                disabled = ''
            else:
                disabled = 'disabled'
        result[f'{color}_player'] = player
        result[f'{color}_disabled'] = disabled
        result[f'{color}_text'] = text
    return result


class Application(WebSocketApplication):
    def on_open(self):
        global online
        online += 1
        current_client = self.ws.handler.active_client
        self.broadcast('''
<div hx-swap-oob="beforeend:#audiohere">
<audio controls autoplay>
  <source src="/static/ding.wav" type="audio/wav">
</audio>
</div>''')

    def on_close(self, x):
        global online
        online -= 1
        current_client = self.ws.handler.active_client
        for color in ('black', 'white'):
            if color in color_client and color_client[color] == current_client:
                del color_client[color]
                self.update_panel()
                self.check_nobody()

    def update_panel(self):
        for client in list(self.ws.handler.server.clients.values()):
            with flask_app.app_context():
                html = render_template('panel.html', **panel_data(client))
            msg = f'<div hx-swap-oob="innerHTML:#panel">{html}</div>'
            self.send(client, msg)

    def update_board(self):
        board2 = [[x for x in y] for y in board]
        if last_move:
            board2[last_move[0]][last_move[1]] *= 2
        with flask_app.app_context():
            html = render_template('board.html', board=board2)
        message = f'<div hx-swap-oob="innerHTML:#board">{html}</div>'
        self.broadcast(message)

    def on_message(self, message):
        global turn, board, score, last_move, last_chat
        if message is None:
            return
        message = json.loads(message)
        current_client = self.ws.handler.active_client
        if 'pos' in message:
            if turn == black and color_client.get('black') != current_client:
                return
            elif turn == white and color_client.get('white') != current_client:
                return
            move = [int(i) for i in message['pos'].split('_')][::-1]
            if possible_move(board, move[0], move[1], turn):
                flip_stones(board, move, turn)
                last_move = move
                if possible_moves(board, -turn):
                    turn = -turn
                self.update_board()
                blk = sum([b.count(-1) for b in board])
                wht = sum([b.count(1) for b in board])
                score = f'{blk}-{wht}'
                self.update_panel()

        elif 'reset' in message:
            self.reset_board()

        elif 'chat_message' in message:
            user = client_name.get(current_client) or '(anon)'
            msg = html.escape(f'{user}: ' + message['chat_message'])
            message = f'<div hx-swap-oob="beforeend:#nouzeg">{msg}<br/></div>'
            self.broadcast(message)
            message = f'<div hx-swap-oob="outerHTML:#inpoet"><input id="inpoet" name="chat_message" placeholder="(enter message)" autocomplete="off" autofocus></div>'
            self.send(current_client, message)
            last_chat = last_chat[-20:] + [msg]

        elif 'username' in message:
            client_name[current_client] = message['username'] or '(anon)'
            self.update_panel()

        elif 'zit' in message:
            if message['zit'] not in color_client:
                color_client[message['zit']] = current_client
                self.update_panel()

        elif 'sta' in message:
            if message['sta'] in color_client:
                del color_client[message['sta']]
                self.update_panel()
                self.check_nobody()

    def reset_board(self):
        init_board()
        self.update_board()
        self.update_panel()

    def check_nobody(self):
        if not color_client:
            self.reset_board()

    def send(self, client, message):
        try:
            client.ws.send(message)
        except Exception as e: # skip dead sockets
            pass

    def broadcast(self, message, all_=True):
        for client in list(self.ws.handler.server.clients.values()):
            if all_ or client != self.ws.handler.active_client:
                self.send(client, message)


@flask_app.route('/')
def index():
    return render_template('index.html', board=board, **panel_data(), chat=last_chat+['(entering chat)'])


@flask_app.route('/username', methods=['POST'])
def username():
    print('USERNAME!', request.form['username'])
    return '', 204


WebSocketServer(
    ('0.0.0.0', 8000),

    Resource([
        ('^/chat', Application),
        ('^/.*', DebuggedApplication(flask_app))
    ]),

    debug=False
).serve_forever()
