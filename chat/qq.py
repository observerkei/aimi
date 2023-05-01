import abc
import requests
from typing import List, Tuple, Union, Set, Any, Generator
from quart import Quart, request
from urllib import parse

from tool.util import log_dbg, log_err, log_info, read_yaml, write_yaml
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
            if msg['post_type'] == 'message':
                return True
        except:
            log_err('fail to check msg type')
            return False
        return False
    
    def is_private(self, msg) -> bool:    
        if not self.is_message(msg):
            return False
        
        try:
            if msg['message_type'] == 'private':
                return True
        except:
            log_err('fail to check private type')
            return False
        return False

    def is_group(self, msg) -> bool:
        if not self.is_message(msg):
            return False
        try:
            if msg['message_type'] == 'group':
                return True
        except:
            log_err('fail to check group type')
            return False
        return False

    def make_at(self, id: int) -> str:
        return '[CQ:at,qq={}]'.format(id)

    def is_at_self(self, msg) -> bool:
        if not self.is_message:
            return False
        
        message = self.get_message(msg)            
        at_self = self.make_at(self.account_uin)
        if at_self in message:
            return True
        return False

    def get_name(self, msg) -> str:
        try:
            return msg['sender']['nickname']
        except:
            return ''

    def get_message(self, msg) -> str:
        try:
            return msg['message']
        except:
            return ''

    def get_user_id(self, msg) -> int:
        try:
            return msg['user_id']
        except:
            return ''
    
    def get_group_id(self, msg) -> int:
        try:
            return msg['group_id']
        except:
            return ''
    
    def reply_private(self, user_id: int, reply: str):
        reply_quote = parse.quote(reply)
        
        api_private_reply = "http://{}:{}/send_private_msg?user_id={}&message={}".format(
            self.post_host, self.post_port, user_id, reply_quote)
        log_info('send get: ' + str(api_private_reply))
        response = requests.get(api_private_reply)
        log_info('res code: {} data: {}'.format(str(response), str(response.text)))

    def reply_group(self, group_id: int, user_id: int, reply):
        at_user = ''
        if user_id:
            at_user = self.make_at(user_id) + '\n'
        at_reply = at_user + reply
        at_reply_quote = parse.quote(at_reply)
        
        api_group_reply = "http://{}:{}/send_group_msg?group_id={}&message={}".format(
                self.post_host, self.post_port, group_id, at_reply_quote)
        log_info('send get: ' + str(api_group_reply))
        response = requests.get(api_group_reply)            
        log_info('res code: {} data: {}'.format(str(response), str(response.text)))
    
class ChatQQ:
    response_user_ids: Set[int] = {}
    response_group_ids: Set[int] = {}
    master_id: int = 0
    port: int = 5701
    host: str = '127.0.0.1'
    type: str = 'go-cqhttp'
    go_cqhttp: GoCQHttp
    app: Any
    message: Set[dict] = []
    message_size: int = 1024
    
    
    def append_message(self, msg):
        if len(self.message) >= self.message_size:
            log_err('msg full({}). bypass: {}'.format(str(len(self.message), str(msg))))
            return
        self.message.append(msg)

    def __iter__(self):
        return self

    def __next__(self):
        if not self.message:
            raise StopIteration
        else:
            return self.message.pop()
    
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
        
    def get_message(self, msg):
        if self.type == GoCQHttp.name:
            return self.go_cqhttp.get_message(msg)
        return ''

    def get_user_id(self, msg):
        if self.type == GoCQHttp.name:
            return self.go_cqhttp.get_user_id(msg)
        return ''
    
    def get_group_id(self, msg):
        if self.type == GoCQHttp.name:
            return self.go_cqhttp.get_group_id(msg)
        return ''

    def reply_private(self, user_id: int, reply: str):
        if self.type == GoCQHttp.name:
            return self.go_cqhttp.reply_private(user_id, reply)
        return ''

    def reply_group(self, group_id: int, user_id: int, reply):
        if self.type == GoCQHttp.name:
            return self.go_cqhttp.reply_group(group_id, user_id, reply)
        return ''

    def has_message(self):
        return len(self.message)
    
    def need_reply(self, msg) -> bool:
        if self.is_private(msg):
            uid = self.get_user_id(msg)
            if uid == self.master_id:
                return True
            if uid in self.response_user_ids:
                return True
        elif self.is_group(msg):

            # only use at on group.
            if not self.go_cqhttp.is_at_self(msg):
                return False
            
            uid = self.get_user_id(msg)
            gid = self.get_group_id(msg)

            if uid in self.response_user_ids and gid in self.response_group_ids:
                return True            
        else:
            return False
        
        return False

    def __init__(self):
        self.__load_setting()
        
        if self.type == GoCQHttp.name:
            self.go_cqhttp = GoCQHttp()
            self.host = self.go_cqhttp.notify_host
            self.port = self.go_cqhttp.notify_port

        self.__listen_init()

    def __listen_init(self):

        self.app = Quart(__name__)
        
        @self.app.route('/', methods = ['POST'])
        async def listen():
            msg = await request.get_json()
            log_info('recv msg: ' + str(msg))
            if self.need_reply(msg):
                log_info('need reply append msg.')
                self.append_message(msg)
            else:
                log_info('no need reply')
            
            return 'ok'
        
    async def listen(self):
        await self.app.run_task(self.host, self.port)
 
    def __load_setting(self):
        try:
            self.master_id = config.setting['qq']['master_id']
        except:
            self.master_id = 0

        try:
            self.response_user_ids = set(config.setting['qq']['response_user_ids'])
        except:
            self.response_user_ids = set()        
        try:
            self.response_group_ids = set(config.setting['qq']['response_group_ids'])
        except:
            self.response_group_ids = set()

        try:
            self.type = config.setting['qq']['type']
        except:
            self.type = GoCQHttp.name
        
chat_qq = ChatQQ()
