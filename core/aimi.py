import atexit
import signal
import threading
import time
from typing import Generator, List, Tuple, Union, Set, Any

from tool.config import config
from tool.openai_api import openai_api
from tool.bing_api import bing_api
from tool.util import log_dbg, log_err, log_info
from chat.qq import chat_qq

from core.md2img import md
from core.memory import memory

class Aimi:
    timeout: int = 360
    master_name: str = ''
    aimi_name: str = 'Aimi'
    preset_facts: str = ''
    max_link_think: int = 1024
    running: bool = True
    api: str = ''

    def __init__(self):
        self.__load_setting()

        # 注册意外退出保护记忆
        atexit.register(self.__when_exit)
        signal.signal(signal.SIGTERM, self.__signal_exit)
        signal.signal(signal.SIGINT, self.__signal_exit)

    def make_link_think(
        self,
        question: str,
        nickname: str = None
    ) -> str:

        nickname = nickname if nickname and len(nickname) else self.master_name
        
        # append setting
        link_think = '设定: {{\n“{}”\n}}.\n\n'.format(self.preset_facts)
        link_think += '请只关注最新消息,历史如下: {\n'

        # cul question
        question_item = '}}.\n\n请根据设定和最新对话历史和你的历史回答,不用“{}:”开头,回答如下问题: {{\n{}说: “{}”\n}}.'.format(
            self.aimi_name, nickname, question)

        # append history
        link_think += memory.search(question, self.max_link_think)
        # append question
        link_think += question_item

        return link_think

    def run(self):

        self.notify_online()

        threading.Thread(target = self.read).start()
        threading.Thread(target = chat_qq.server).start()

        cnt = 0
        while self.running:
            cnt = cnt + 1
            if cnt < 60:
                time.sleep(1)
                continue
            else:
                cnt = 0;
            
            try:
                memory.save_memory()
                log_info('save memory done')
            except Exception as e:
                log_err('fail to save memory: ' + str(e))
                

    def read(self):
        while self.running:
            if not chat_qq.has_message():
                time.sleep(1)
                continue
            
            for msg in chat_qq:
                log_info('recv msg, try analyse')
                nickname = chat_qq.get_name(msg)
                question = chat_qq.get_question(msg)
                log_info('{}: {}'.format(nickname, question))

                reply = ''
                code = 0
                for answer in self.ask(question, nickname):
                    reply = answer['message']
                    code = answer['code']
                    log_dbg('msg: ' + str(reply))

                log_dbg('answer: ' + str(type(answer)) + ' ' + str(answer))
                
                log_info('{}: {}'.format(nickname, question))
                log_info('{}: {}'.format(self.aimi_name, str(reply)))


                if code == 0:
                    chat_qq.reply_question(msg, reply)

                # server failed
                if code == -1:
                    meme_err = config.meme.error
                    img_meme_err = chat_qq.get_image_message(meme_err)
                    chat_qq.reply_question(msg, 'server unknow error :(')
                    chat_qq.reply_question(msg, img_meme_err)
                    
                
                # trans text to img  
                if md.need_set_img(reply):
                    log_info('msg need set img')
                    img_file = md.message_to_img(reply)
                    cq_img = chat_qq.get_image_message(img_file)
                    
                    chat_qq.reply_question(msg, cq_img)
        
    def ask(
        self,
        question: str,
        nickname: str = None
    ) -> Generator[dict, None, None]:

        if self.api == bing_api.type:
            link_think = question
        else:
            link_think = self.make_link_think(question, nickname)

        answer = self.__post_question(link_think)

        for message in answer:
            if (not message):
                continue
            log_dbg('message: {} {} answer: {} {}'.format(
            str(type(message)), str(message), str(type(answer)), str(answer)))

            yield message 
            
            if (message['code'] != 0):
                continue
            
            memory.append(q = question, a = message['message'])
    
    def __post_question(
        self, 
        link_think: str
    )-> Generator[dict, None, None]:
        if self.api == openai_api.type:
            yield from self.__post_openai(link_think, memory.openai_conversation_id)
        elif self.api == bing_api.type:
            yield from self.__post_chatbing(link_think, memory.openai_conversation_id)
     
    def __post_chatbing(
        self, 
        question: str,
        openai_conversation_id: str = None
    )-> Generator[dict, None, None]:
        yield from bing_api.ask(question)
    
    def __post_openai(
        self, 
        question: str,
        openai_conversation_id: str = None
    )-> Generator[dict, None, None]:
        
        answer = openai_api.ask(question, openai_conversation_id)
        # get yield last val
        for message in answer:
            log_dbg('now msg: ' + str(message))
            yield from answer

            if (not message) or (message['code'] != 0):
                continue
            
            if message['conversation_id'] and message['conversation_id'] != memory.openai_conversation_id:
                memory.openai_conversation_id = message['conversation_id']
                log_info('set new con_id: ' + str(memory.openai_conversation_id))
        
    def __load_setting(self):
        try:
            self.aimi_name = config.setting['aimi']['name']
        except:
            self.aimi_name = 'Aimi'
        try:
            self.master_name = config.setting['aimi']['master_name']
        except:
            self.master_name = ''

        try:
            self.api = api = config.setting['aimi']['api']
        except:
            self.api = openai_api.type
            
        if api == openai_api.type:
            self.max_link_think = openai_api.max_requestion
        elif api == bing_api.type:
            self.max_link_think = bing_api.max_requestion
        else:
            self.max_link_think = 1024

        try:
            self.preset_facts = ''
            preset_facts: List[str] = config.setting['aimi']['preset_facts']
            count = 0
            for fact in preset_facts:
                fact = fact.replace('<name>', self.aimi_name)
                fact = fact.replace('<master>', self.master_name)
                count += 1
                if count != len(preset_facts):
                    fact += '\n'
                self.preset_facts += fact
        except:
            self.preset_facts = ''

    def need_reply(self, user: dict) -> bool:
        if user['chat'] == 'qq' and chat_qq.need_reply(user):
            return True
        return False

    def notify_online(self):
        chat_qq.reply_online()

    def notify_offline(self):
        chat_qq.reply_offline()
    
    def __signal_exit(self, sig, e):
        log_info('recv exit sig.')
        self.running = False
        chat_qq.stop()

    def __when_exit(self):
        self.running = False
        
        log_info('now exit aimi.')
        self.notify_offline()
        
        bye_string = 'server unknow error. sweven-box ready to go offline\n'
        if memory.save_memory():
            log_info('exit: save memory done.')
        else:
            log_err('exit: fail to save memory.')



aimi = Aimi()
