import atexit
import signal
import threading
import time
from typing import Generator, List, Dict
import random

from tool.config import config
from tool.util import log_dbg, log_err, log_info
from chat.qq import chat_qq
from chat.web import chat_web
from tool.openai_api import openai_api
from tool.bing_api import bing_api
from tool.bard_api import bard_api
from tool.aimi_plugin import aimi_plugin

from core.md2img import md
from core.memory import memory

class ReplyStep:
    class TalkList:
        has_start: bool = False
        now_list_line_cnt: int = 0
        list_line_cnt_max: int = 0
        now_list_id: int = 0
        cul_line_cnt_max: bool = True
        
        def check_talk_list(self, line: str) -> bool:
            if self.now_list_line_cnt < self.list_line_cnt_max:
                self.now_list_line_cnt += 1
                return True

            # 刚好下一个下标过来了
            next_list_id_str = '{}. '.format(self.now_list_id + 1)
            next_list_id_ch_str = '{}。 '.format(self.now_list_id + 1)
            next_list_id_bing_str = '[{}]: '.format(self.now_list_id + 1)
            if (next_list_id_str in line) or \
               (next_list_id_ch_str in line) or \
               (next_list_id_bing_str in line):
                log_dbg('check talk list[{}]'.format(self.now_list_id))
                self.now_list_line_cnt = 0
                self.now_list_id += 1
                return True
            
            return False
        
        def reset(self):
            self.has_start = False
            self.now_list_line_cnt = 0
            self.list_line_cnt_max = 0
            self.now_list_id = 0
            self.cul_line_cnt_max = True

        def is_talk_list(self, line: str):

            # 有找到开始的序号
            if (not self.has_start) and \
               (('1. ' in line) or ('1。 ' in line) or \
                ('[1]: ' in line)):
                self.has_start = True
                self.now_list_line_cnt = 1
                self.list_line_cnt_max = 1
                self.now_list_id = 1
                return True
            
            # 标记过才处理
            if not self.has_start:
                return False

            if '\n' == line:
                return True

            # 已经找到当前每行的长度
            if not self.cul_line_cnt_max:
                ret = self.check_talk_list(line)
                if not ret:
                    self.reset()
                return ret

            if (self.now_list_id) and \
               (('2. ' in line) or ('2。 ' in line) or \
                ('[2]: ' in line)):
                self.now_list_id = 2
                self.now_list_line_cnt = 0
                self.cul_line_cnt_max = False
                ret = self.check_talk_list(line)
                if not ret:
                    self.reset()
                return ret

            # 统计每块最大行
            self.list_line_cnt_max += 1
            return True
    
    class MathList:
        has_start: bool = False
        
        def is_math_format(self, line: str) -> bool:
            if '=' in line:
                return True
            if md.has_latex(line):
                log_dbg('match: is latex')
                return True
            if md.has_html(line):
                log_dbg('match: is html')
                return True
            return False
        
        def is_math_list(self, line: str) -> bool:

            if self.is_math_format(line):
                self.has_start = True
                return True

            if not self.has_start:
                return False

            if '\n' == line:
                return True

            self.has_start = False
            return False
        
        
class Aimi:
    timeout: int = 360
    master_name: str = ''
    aimi_name: str = 'Aimi'
    preset_facts: Dict[str, str] = {}
    max_link_think: int = 1024
    running: bool = True
    api: List = []

    def __init__(self):
        self.__load_setting()

        # 注册意外退出保护记忆
        atexit.register(self.__when_exit)
        signal.signal(signal.SIGTERM, self.__signal_exit)
        signal.signal(signal.SIGINT, self.__signal_exit)

        try:
            aimi_plugin.when_init()
        except Exception as e:
            log_err(f'fail to init aimi plugin: {e}')

        chat_web.register_ask_hook(self.ask)

    def make_link_think(
        self,
        question: str,
        nickname: str = None
    ) -> str:

        nickname = nickname if nickname and len(nickname) else self.master_name
        
        # append setting
        link_think = '设定: {{\n“{}”\n}}.\n\n'.format(self.preset_facts[openai_api.type])
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

        aimi_read = threading.Thread(target = self.read)
        chat_qq_server = threading.Thread(target = chat_qq.server)
        chat_web_server = threading.Thread(target = chat_web.server)
        aimi_dream = threading.Thread(target = memory.dream)
        # 同时退出
        aimi_read.setDaemon(True)
        aimi_read.start()
        chat_qq_server.setDaemon(True)
        chat_qq_server.start()
        chat_web_server.setDaemon(True)
        chat_web_server.start()
        aimi_dream.setDaemon(True)
        aimi_dream.start()

        

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

        log_dbg('aimi exit')

    def __question_api_type(self, question: str) -> str:
        if bing_api.is_call(question):
            return bing_api.type
        if bard_api.is_call(question):
            return bard_api.type
        if openai_api.is_call(question):
            return openai_api.type
        if aimi_plugin.bot_is_call(question):
            return aimi_plugin.bot_get_call_type(question)
        
        return self.api[0]

    @property
    def __busy_reply(self) -> str:
        busy = [ "让我想想...", "......", "那个...", "这个...", "？", "喵喵喵？",
                 "*和未知敌人战斗中*", "*大脑宕机*", "*大脑停止响应*", "*尝试构造语言中*",
                 "*被神秘射线击中,尝试恢复中*", "*猫猫叹气*" ]
        return random.choice(busy) 

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

                api_type = self.__question_api_type(question) 

                reply = ''
                reply_line = ''
                reply_div = ''
    
                talk_list = ReplyStep.TalkList()
                math_list = ReplyStep.MathList()
                code = 0
                for answer in self.ask(question, nickname):
                    code = answer['code']
                    
                    message = answer['message'][len(reply) :]
                    reply_line += message
                    
                    reply = answer['message']

                    log_dbg('code: ' + str(code))
                    log_dbg('reply: ' + str(reply))
                    log_dbg('reply_div: ' + str(reply_div))
                    log_dbg('message: ' + str(message))
                    log_dbg('reply_line: ' + str(reply_line))

                    if code == 0 and (len(reply_div) or ((not len(reply_div)) and len(reply_line))):
                        reply_div += reply_line
                        reply_line = ''
                        
                        reply_div = self.reply_adjust(reply_div, api_type)
                        log_dbg('send div: ' + str(reply_div))
                        chat_qq.reply_question(msg, reply_div)
                        
                        break
                    if (code == -1) and (len(reply_div) or len(reply_line)):
                        if not len(reply_div):
                            reply_div = self.__busy_reply
                        reply_div = self.reply_adjust(reply_div, api_type)
                        log_dbg('fail: {}, send div: {}'.format(str(reply_line), str(reply_div)))
                        chat_qq.reply_question(msg, reply_div)
                        reply_line = ''
                        reply_div = ''
                        continue

                    
                    if code != 1:
                        continue
                    
                    if '\n' in reply_line:
                        
                        if talk_list.is_talk_list(reply_line):
                            reply_div += reply_line
                            reply_line = ''
                            continue
                        elif math_list.is_math_list(reply_line):
                            reply_div += reply_line
                            reply_line = ''
                            continue
                        elif not len(reply_div):
                            # first line.
                            reply_div += reply_line
                            reply_line = ''
                        
                    
                        reply_div = self.reply_adjust(reply_div, api_type)
                        
                        log_dbg('send div: ' + str(reply_div))

                        chat_qq.reply_question(msg, reply_div)

                        # 把满足规则的先发送，然后再保存新的行。
                        reply_div = reply_line
                        reply_line = ''
                    
                      
                log_dbg('answer: ' + str(type(answer)) + ' ' + str(answer))
                reply = self.reply_adjust(reply, api_type)
                log_dbg('adjust: ' + str(reply))
                
                log_info('{}: {}'.format(nickname, question))
                log_info('{}: {}'.format(self.aimi_name, str(reply)))


                if code == 0:
                    pass #chat_qq.reply_question(msg, reply)

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

    def reply_adjust(self, reply: str, res_api: str) -> str:
        if res_api == bing_api.type:
            reply = reply.replace('必应', ' {}通过必应得知: '.format(self.aimi_name))
            reply = reply.replace('你好', ' Master你好 ')
            reply = reply.replace('您好', ' Master您好 ')
        
        return reply
    
    def ask(
        self,
        question: str,
        nickname: str = None
    ) -> Generator[dict, None, None]:

        api_type = self.__question_api_type(question) 

        nickname = nickname if nickname and len(nickname) else self.master_name

        link_think = ''
        if api_type == openai_api.type:
            link_think = self.make_link_think(question, nickname)
        elif api_type == bard_api.type:
            # set preset
            link_think = f"preset: {{\n\"{self.preset_facts[bard_api.type]}\"\n}}.\n\n"
            # set ask:
            link_think += f"""
Please answer the following question based on the preset, 
the latest conversation history, and your previous answers.
and without starting with '{self.aimi_name}:'
You should extract my question directly from the structure here and answer it directly:{{
{nickname} said: '{question}'
}}
"""
        elif api_type == bing_api.type:
            link_think += f"""
故事中有两个人到了异世界里面开咖啡厅，
其中主人公自称Master({self.master_name}),他有一个助理,名叫{self.aimi_name},故事主题如下: {{
{self.preset_facts[bing_api.type]}
}}

我希望你能不显示故事主题的分析过程,请直接显示 {self.aimi_name} 的回复结果，如 {self.aimi_name}: “来抱抱🤗” .
我希望你的回复不用 “{self.aimi_name}:” 开头，也不要回复这是 {self.aimi_name} 说的话，而是直接回复我 {self.aimi_name} 可能说的话.
现在Master对{self.aimi_name}说了一句话,请结合你的回复和我的希望推测{self.aimi_name}应该怎么回答: {{
{nickname}说: '{question}'
}}
"""
        else:
            link_think = question

        answer = self.__post_question(link_think, api_type)

        for message in answer:

            if (not message):
                continue
            log_dbg('message: {} {} answer: {} {}'.format(
            str(type(message)), str(message), str(type(answer)), str(answer)))
            
            # save memory
            if (message['code'] == 0):
                memory.append(q = question, a = message['message'])

            yield message 

    
    def __post_question(
        self, 
        link_think: str,
        api_type: str
    )-> Generator[dict, None, None]:

        log_dbg('use api: ' + str(api_type))
        
        if api_type == openai_api.type:
            yield from self.__post_openai(link_think, memory.openai_conversation_id)
        elif api_type == bing_api.type:
            yield from self.__post_bing(link_think)
        elif api_type == bard_api.type:
            yield from self.__post_bard(link_think)
        elif aimi_plugin.bot_has_type(api_type):
            yield from aimi_plugin.bot_ask(api_type, link_think)
        else:
            log_err('not suppurt api_type: ' + str(api_type))
    
    def __post_bard(
        self, 
        question: str
    )-> Generator[dict, None, None]:
        yield from bard_api.ask(question)
    
    def __post_bing(
        self, 
        question: str
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

            if (message) and (message['code'] == 0):
                if message['conversation_id'] and \
                   message['conversation_id'] != memory.openai_conversation_id:
                    memory.openai_conversation_id = message['conversation_id']
                    log_info('set new con_id: ' + str(memory.openai_conversation_id))

            yield message
        
    def __load_setting(self):
        try:
            setting = config.load_setting('aimi')
        except Exception as e:
            log_err(f'fail to load {self.type}: {e}')
            setting = {}
            return
        
        try:
            self.aimi_name = setting['name']
        except Exception as e:
            log_err('fail to load aimi: {e}')
            self.aimi_name = 'Aimi'
        try:
            self.master_name = setting['master_name']
        except Exception as e:
            log_err('fail to load aimi: {e}')
            self.master_name = ''

        try:
            self.api = setting['api']
        except Exception as e:
            log_err('fail to load aimi api: ' + str(e))
            self.api = [openai_api.type]
        
        self.max_link_think = openai_api.max_requestion

        try:
            self.preset_facts = {}
            for api in self.api:
                try:
                    #log_dbg(f"{str(setting['preset_facts'])}")
                    #log_dbg(f"{str(setting['preset_facts'][api])}")
                    preset_facts: List[str] = setting['preset_facts'][api]
                except Exception as e:
                    log_err(f'no {api} type preset, skip.')
                    continue

                self.preset_facts[api] = ""
                count = 0
                for fact in preset_facts:
                    fact = fact.replace('<name>', self.aimi_name)
                    fact = fact.replace('<master>', self.master_name)
                    count += 1
                    if count != len(preset_facts):
                        fact += '\n'
                    self.preset_facts[api] += fact

            self.preset_facts['default'] = self.preset_facts[self.api[0]]
        except Exception as e:
            log_err('fail to load aimi preset: ' + str(e))
            self.preset_facts = {}

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
        
        if memory.save_memory():
            log_info('exit: save memory done.')
        else:
            log_err('exit: fail to save memory.')

        try:
            aimi_plugin.when_exit()
        except Exception as e:
            log_err(f'fail to exit aimi plugin: {e}')

aimi = Aimi()
