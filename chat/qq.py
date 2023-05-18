import requests
import re
import time
import threading
from typing import Set, Any
from flask import Flask, request
from urllib import parse

from tool.util import log_dbg, log_err, log_info, read_yaml
from tool.config import config

class GoCQHttp:
    name: str = 'go-cqhttp'
    post_host: str = '127.0.0.1'
    post_port: int = 5700
    notofy_host: str = '127.0.0.1'
    notify_port: int = 5701
    account_uin: int = 0

    def __init__(self):
        self.__load_go_cqhttp_config()
    
    def __load_go_cqhttp_config(self):
        go_cqhttp_config = './run/config.yml'
        try:
            go_cqhttp_config = config.setting['config']
        except:
            go_cqhttp_config = './run/config.yml'
        
        obj = read_yaml(go_cqhttp_config)
        try:
            self.account_uin = obj['account']['uin']
            
            http_config = obj['servers'][0]['http']
            
            go_host = http_config['host']
            go_port = http_config['port']
            self.post_host = str(go_host)
            self.post_port = int(go_port)

            url = http_config['post'][0]['url']

            host, port = url.replace('http://', '').split(':')
            self.notify_host = str(host)
            self.notify_port = int(port)

        except Exception as e:
            log_err('fail to get go-cqhttp config: ' + str(e))

    def is_message(self, msg) -> bool:
        try:
            return msg['post_type'] == 'message'
        except:
            log_err('fail to check msg type')
            return False
    
    def is_private(self, msg) -> bool:    
        if not self.is_message(msg):
            return False
        
        try:
            return msg['message_type'] == 'private'
        except:
            log_err('fail to check private type')
            return False

    def is_group(self, msg) -> bool:
        if not self.is_message(msg):
            return False
        try:
            return msg['message_type'] == 'group'
        except:
            log_err('failt to check is_group')
            return False

    def make_at(self, id: int) -> str:
        return '[CQ:at,qq={}]'.format(id)

    def is_at_self(self, message) -> bool:
        at_self = self.make_at(self.account_uin)
        if at_self in message:
            return True
        return False

    def get_name(self, msg) -> str:
        try:
            return msg['sender']['nickname']
        except:
            return ''

    def need_filter_question(self, question) -> bool:
        if self.is_at_self(question):
            return True
        
        del_msg = '请使用最新版手机QQ体验新功能'
        if del_msg in question:
            return True

        return False

    def filter_question(self, question) -> str:
        if self.is_at_self(question):
            log_dbg('question: ' + str(question))
            question = re.sub('\[CQ:.*?\]', '', question)
            log_dbg('del at self done: ' + str(question))

        del_msg = '请使用最新版手机QQ体验新功能'
        if del_msg in question:
            question = question.replace(del_msg, ' ')
            log_dbg('del: ' + str(del_msg))

        return question

    def get_message(self, msg) -> str:
        try:
            return msg['message']
        except:
            return ''

    def get_question(self, msg) -> str:
        question = self.get_message(msg)

        # del qq function content.
        if self.need_filter_question(question):
            log_info('question need filter.')
            question = self.filter_question(question)
            log_dbg('question filter done: ' + str(question))

        return question

    def get_user_id(self, msg) -> int:
        try:
            return msg['user_id']
        except:
            return 0
    
    def get_group_id(self, msg) -> int:
        try:
            return msg['group_id']
        except:
            return 0
    
    def get_image_cq(self, file) -> str:
        return '[CQ:image,file=file://{}]'.format(file)
    
    def get_reply_private(self, user_id: int, reply: str) -> str:
        reply_quote = parse.quote(reply)
        
        api_private_reply = "http://{}:{}/send_private_msg?user_id={}&message={}".format(
            self.post_host, self.post_port, user_id, reply_quote)

        return api_private_reply

    def get_reply_group(self, group_id: int, user_id: int, reply) -> str:
        at_user = ''
        if user_id:
            at_user = self.make_at(user_id) + '\n'
        at_reply = at_user + reply
        at_reply_quote = parse.quote(at_reply)
        
        api_group_reply = "http://{}:{}/send_group_msg?group_id={}&message={}".format(
                self.post_host, self.post_port, group_id, at_reply_quote)

        return api_group_reply

class BotManage:
    reply_time: Dict[int, int]
    protect_bot_ids: List[int]

    def __init__(self):
        self.__load_setting()
        
        for bot_id in self.protect_bot_ids:
            self.reply_time[bot_id] = 0

    def __load_setting(self):
        try:
            setting = config.load_setting('qq')
        except Exception as e:
            log_err(f'fail to get qq cfg: {e}')
            return

        try:
            self.protect_bot_ids = setting['protect_bot_ids']
        except Exception as e:
            log_err(f'fail to load protect_bot_ids: {e}')
            self.protect_bot_ids = []

    def update_reply_time(self, bot_id: int):
        current_time_seconds = int(time.time())
        self.reply_time[bot_id] = current_time_seconds

    def over_reply_time_limit(self, bot_id: int) -> bool:

        if not self.reply_time[bot_id]:
            return True
    
        current_time_seconds = int(time.time())
        
        if (self.reply_time[bot_id] + 60*60) < current_time_seconds:
            return True
        return False

    def need_manage(self, user_id: int) -> bool:

        if not (user_id in self.protect_bot_ids):
            return False

        if self.over_reply_time_limit(user_id):
            return True
        
        return False

    def is_at_message(self, message: str) -> bool:
        return '[CQ:' in bot_message

    def manage_event(self, bot_id: int, bot_message: str):
        if not self.is_at_message(bot_message):
            log_dbg('no have at, no need manage')
            return ''

        if self.over_reply_time_limit(bot_id):
            current_time_seconds = int(time.time())
            if not self.reply_time[bot_id]:
                self.reply_time[bot_id] = current_time_seconds
                log_info(f'update bot:{bot_id} first time.')
                return ''
            self.reply_time[bot_id] = current_time_seconds
            return self.manage_action(' 😱 ~ ')

        return ''

class ChatQQ:
    response_user_ids: Set[int] = {}
    response_group_ids: Set[int] = {}
    master_id: int = 0
    port: int = 5700
    host: str = '127.0.0.1'
    type: str = 'go-cqhttp'
    go_cqhttp: GoCQHttp
    app: Any
    http_server: Any
    message: Set[dict] = []
    message_size: int = 1024    
    reply_message: Set[str] = []
    reply_message_size: int = 1024
    running: bool = True
    manage: BotManage = BotManage()

    def __message_append(self, msg):
        if len(self.message) >= self.message_size:
            log_err('msg full: {}. bypass: {}'.format(str(len(self.message)), str(msg)))
            return False

        self.message.append(msg)

        return True

    def __iter__(self):
        return self

    def __next__(self):
        if not self.message:
            raise StopIteration
        else:
            return self.message.pop()

    def __reply_append(self, reply: str):
        if len(self.reply_message) >= self.reply_message_size:
            log_err('reply full: {}. bypass: {}'
                    .format(str(len(self.reply_message)), str(reply)))
            return False

        self.reply_message.append(reply)

        log_dbg('append new reply.')

        return True

    def reply_url(self, reply_url: str) -> bool:
        try:
            log_dbg('send get: ' + str(reply_url))
            response = requests.get(reply_url, proxies={})            
            log_dbg('res code: {} data: {}'.format(str(response), str(response.text)))
            if response.status_code != 200:
                log_err('code: {}. fail to reply, sleep.'.format(response.status_code))
                return False
            return True
        except Exception as e:
            log_err('fail to reply, sleep: ' + str(e))
            return False

    def reply(self):
        while self.running:
            if not len(self.reply_message):
                time.sleep(1)
                continue

            log_info('recv reply. try send qq server')

            for reply_url in self.reply_message:

                res = self.reply_url(reply_url)
                if not res:
                    log_err('fail to send reply. sleep...')
                    time.sleep(5)
                    continue

                self.reply_message.remove(reply_url)

    def is_message(self, msg) -> bool:
        if self.type == GoCQHttp.name:
            return self.go_cqhttp.is_message(msg)
        return False

    def is_private(self, msg) -> bool:
        if self.type == GoCQHttp.name:
            return self.go_cqhttp.is_private(msg)
        return False

    def is_group(self, msg) -> bool:
        if self.type == GoCQHttp.name:
            return self.go_cqhttp.is_group(msg)
        return False
    
    def get_name(self, msg):
        if self.type == GoCQHttp.name:
            return self.go_cqhttp.get_name(msg)
        return ''
        
    def get_question(self, msg):
        if self.type == GoCQHttp.name:
            return self.go_cqhttp.get_question(msg)
        return ''

    def get_user_id(self, msg):
        if self.type == GoCQHttp.name:
            return self.go_cqhttp.get_user_id(msg)
        return ''
    
    def get_group_id(self, msg):
        if self.type == GoCQHttp.name:
            return self.go_cqhttp.get_group_id(msg)
        return ''

    def get_message(self, msg):
        if self.type == GoCQHttp.name:
            return self.go_cqhttp.get_message(msg)
        return ''

    def reply_private(self, user_id: int, reply: str):
        if self.type == GoCQHttp.name:
            reply_url = self.go_cqhttp.get_reply_private(user_id, reply)
            return self.__reply_append(reply_url)

        return None

    def reply_group(self, group_id: int, user_id: int, reply):
        if self.type == GoCQHttp.name:
            reply_url = self.go_cqhttp.get_reply_group(group_id, user_id, reply)
            return self.__reply_append(reply_url)

        return None

    def get_image_message(self, file) -> str:
        if self.type == GoCQHttp.name:
            return self.go_cqhttp.get_image_cq(file)
        return ''            

    def reply_question(self, msg, reply):
        if not len(reply):
            log_info('reply is empty.')
            return None
        
        user_id = self.get_user_id(msg)
        
        if self.is_private(msg):
            return self.reply_private(user_id, reply)
        elif self.is_group(msg):
            group_id = self.get_group_id(msg)
            return self.reply_group(group_id, user_id, reply) 

        return None

    def has_message(self):
        return len(self.message)

    def reply_permission_denied(self, msg):
        if not self.is_permission_denied(msg):
            return
        
        meme_com = config.meme.common
        img_meme_com = self.get_image_message(meme_com)
        
        chat_qq.reply_question(msg, '非服务对象 :(')
        chat_qq.reply_question(msg, img_meme_com)

    def reply_online(self):
        if self.type == GoCQHttp.name:
            return self.reply_private(self.master_id, 'server init complate :)')

        return None

    def reply_offline(self):
        if self.type == GoCQHttp.name:
            reply_api = self.go_cqhttp.get_reply_private(self.master_id, 'Server unknown error :(')
            return self.reply_url(reply_api)

        return None
            
    # notify permission denied
    def is_permission_denied(self, msg) -> bool:
        if self.is_private(msg):
            uid = self.get_user_id(msg)
            if uid == self.master_id:
                return False
            if uid in self.response_user_ids:
                return False
            
            return True
        
        elif self.is_group(msg):

            # only use at on group.
            message = self.get_message(msg)
            if not self.go_cqhttp.is_at_self(message):
                return False
            
            uid = self.get_user_id(msg)
            gid = self.get_group_id(msg)

            if uid in self.response_user_ids and gid in self.response_group_ids:
                return False

            return True

        else:
            return False
        
        return False
    
    def need_reply(self, msg) -> bool:
        if self.is_private(msg):
            uid = self.get_user_id(msg)
            if uid == self.master_id:
                return True
            if uid in self.response_user_ids:
                return True
        elif self.is_group(msg):

            # only use at on group.
            message = self.get_message(msg)
            if not self.go_cqhttp.is_at_self(message):
                return False
            
            gid = self.get_group_id(msg)

            if not (gid in self.response_group_ids):
                return False

            uid = self.get_user_id(msg)

            if uid == self.master_id:
                return True

            if uid in self.response_user_ids:
                return True
        else:
            return False
        
        return False

    def need_check_manage_msg(self, msg) -> bool:
        if not self.is_group(msg):
            return False
        
        user_id = self.get_user_id(msg)
        group_id = self.get_group_id(msg)
        protect_bot_ids = self.manage.protect_bot_ids
        
        if not (group_id in self.response_group_ids):
            return False

        if user_id in protect_bot_ids: 
            return True

        return False

    def manage_msg(self, msg):
        group_id = self.get_group_id(msg)
        if not (group_id in self.response_group_ids)
            return
        
        user_id = self.get_user_id(msg)
        if not self.manage.need_manage(user_id):
            return

        message = self.get_message(msg)
        notify_msg = self.manage.manage_event(user_id, message)
        if not len(notify_msg):
            return
        
        at_master = self.go_cqhttp.make_at(self.master_id)
        self.reply_group(group_id, f'{at_master} {notify_msg}')
        self.reply_group(group_id, self.master_id, f'{at_master} {notify_msg}')

    def __init__(self):
        self.__load_setting()
        
        if self.type == GoCQHttp.name:
            self.go_cqhttp = GoCQHttp()
            self.host = self.go_cqhttp.notify_host
            self.port = self.go_cqhttp.notify_port

        self.__listen_init()

    def __listen_init(self):

        self.app = Flask(__name__)
        
        @self.app.route('/', methods = ['POST'])
        def listen():
            msg = request.get_json()
            if not self.is_message(msg):
                log_dbg('skip not msg.')
                return 'skip'
            log_info('recv msg: ' + str(msg))
            if self.need_reply(msg):
                log_info('need reply append msg.')
                self.__message_append(msg)
            elif self.is_permission_denied(msg):
                log_info('user permission_denied')
                self.reply_permission_denied(msg)
            elif self.need_check_manage_msg(msg):
                log_info('need check manage msg')
                self.manage.manage_msg(msg)
            else:
                log_info('no need reply')
            
            return 'ok'
        
    def server(self):
        # 开启回复线程
        threading.Thread(target = chat_qq.reply).start()

        from gevent import pywsgi
        self.http_server = pywsgi.WSGIServer(
            listener = (self.host, self.port),
            application = self.app,
            log = None 
        )
        self.http_server.serve_forever()

    def stop(self):
        self.running = False
        self.http_server.stop()
 
    def __load_setting(self):
        try:
            setting = config.load_setting('qq')
        except Exception as e:
            log_err(f'fail to load {self.type}: {e}')
            setting = {}
            return
        
        try:
            self.master_id = setting['master_id']
        except Exception as e:
            log_err(f'fail to load qq: {e}')
            self.master_id = 0

        try:
            self.response_user_ids = set(setting['response_user_ids'])
        except Exception as e:
            log_err(f'fail to load qq: {e}')
            self.response_user_ids = set()        
        try:
            self.response_group_ids = set(setting['response_group_ids'])
        except Exception as e:
            log_err(f'fail to load qq: {e}')
            self.response_group_ids = set()

        try:
            self.type = setting['type']
        except Exception as e:
            log_err(f'fail to load qq: {e}')
            self.type = GoCQHttp.name
        
chat_qq = ChatQQ()
