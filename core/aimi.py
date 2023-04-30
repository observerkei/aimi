import atexit
import signal
from typing import Generator, List, Tuple, Union, Set

from tool.config import config
from tool.openai_api import openai_api
from tool.util import log_dbg, log_err, log_info
from chat.qq import chat_qq

from core.memory import memory

class Aimi:
    timeout: int = 360
    master_name: str = ''
    aimi_name: str = 'Aimi'
    preset_facts: str = ''
    max_link_think: int = 1024

    def __init__(self):
        'void'
        self.__load_setting()

        # 注册意外退出保护记忆
        atexit.register(self.__when_exit)
        signal.signal(signal.SIGTERM, self.__when_exit)

    def make_link_think(
        self,
        question: str
    ) -> str:

        # append setting
        link_think = '设定: {{\n“{}”\n}}.\n\n'.format(self.preset_facts)
        link_think += '请只关注最新消息,历史如下: {\n'

        # cul question
        question_item = '}}.\n\n请根据设定和对话历史,不用“{}:”开头,回答如下问题: {{\n{}说: “{}”\n}}.'.format(
            self.aimi_name, self.master_name, question)

        # append history
        link_think += memory.search(question, self.max_link_think)
        # append question
        link_think += question_item

        return link_think
    
    def ask(
        self,
        question: str
    ) -> Generator[dict, None, None]:

        link_think = self.make_link_think(question)
        yield link_think
        '''
        answer = self.__post_question(link_think, memory.openai_conversation_id)   
        
        # get yield last val
        for message in answer:
            yield from answer

            if (not message) or (message['code'] != 0):
                continue
            
            memory.append(q = question, a = message['message'])
            if message['conversation_id'] and message['conversation_id'] != memory.openai_conversation_id:
                memory.openai_conversation_id = message['conversation_id']
                log_info('set new con_id: ' + str(memory.openai_conversation_id))
        '''
    def __post_question(
        self, 
        question: str,
        openai_conversation_id: str = None
    )-> Generator[dict, None, None]:
        yield from openai_api.ask(question, openai_conversation_id)

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
            self.max_link_think = openai_api.max_requestion
        except:
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
    
    def __when_exit(self):
        bye_string = 'server unknow error. sweven-box ready to go offline\n'
        if memory.save_memory():
            log_info('exit: save memory done.')
        else:
            log_err('exit: fail to save memory.')


aimi = Aimi()
