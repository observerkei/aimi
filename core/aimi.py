import atexit
import signal
import threading
import time
from typing import Generator, List

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
    api: List = []

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
        dream = threading.Thread(target = memory.dream)
        # 同时退出
        dream.setDaemon(True)
        dream.start()

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

    def question_api_type(self, question: str) -> str:
        if '用必应' in question:
            return bing_api.type
        return openai_api.type

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

                api_type = self.question_api_type(question) 

                reply = ''
                reply_line = ''
                reply_div = ''

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
                            self.now_list_line_cnt += 1
                            self.list_line_cnt_max += 1
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
                    
                    

                talk_list = TalkList()
                math_list = MathList()
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

        api_type = self.question_api_type(question) 

        if api_type == bing_api.type:
            link_think = question
        else:
            link_think = self.make_link_think(question, nickname)

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
            yield from self.__post_bing(link_think, memory.openai_conversation_id)
     
    def __post_bing(
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
            self.api = config.setting['aimi']['api']
        except:
            self.api = [openai_api.type]
            
        if openai_api.type in self.api:
            self.max_link_think = openai_api.max_requestion
        elif bing_api.type in self.api:
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
        
        if memory.save_memory():
            log_info('exit: save memory done.')
        else:
            log_err('exit: fail to save memory.')



aimi = Aimi()
