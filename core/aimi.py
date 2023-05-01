import atexit
import signal
import asyncio
from typing import Generator, List, Tuple, Union, Set, Any

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
    running: bool = True

    def __init__(self):
        'void'
        self.__load_setting()

        # 注册意外退出保护记忆
        atexit.register(self.__when_exit)
        signal.signal(signal.SIGTERM, self.__when_exit)
        signal.signal(signal.SIGINT, self.__when_exit)

    def make_link_think(
        self,
        question: str,
        nickname: str = None
    ) -> str:

        nickname = nickname if len(nickname) else self.master_name
        
        # append setting
        link_think = '设定: {{\n“{}”\n}}.\n\n'.format(self.preset_facts)
        link_think += '请只关注最新消息,历史如下: {\n'

        # cul question
        question_item = '}}.\n\n请根据设定和对话历史,不用“{}:”开头,回答如下问题: {{\n{}说: “{}”\n}}.'.format(
            self.aimi_name, nickname, question)

        # append history
        link_think += memory.search(question, self.max_link_think)
        # append question
        link_think += question_item

        return link_think

    def run(self):
        qq_server = asyncio.ensure_future(chat_qq.listen())
        aimi_read = asyncio.ensure_future(self.read())
        loop = asyncio.get_event_loop()
        loop.run_until_complete(asyncio.gather(qq_server, aimi_read))

    async def read(self):
        while self.running:
            if chat_qq.has_message():
                for msg in chat_qq:
                    nickname = chat_qq.get_name(msg)
                    message = chat_qq.get_message(msg)
                    user_id = chat_qq.get_user_id(msg)
                    reply = ''
                    for answer in self.ask(message, nickname):
                        reply = answer['message']
                    log_info('{}: {}'.format(nickname, message))
                    log_info('{}: {}'.format(self.aimi_name, str(reply)))

                    if chat_qq.is_private(msg):
                        chat_qq.reply_private(user_id, reply)
                    elif chat_qq.is_group(msg):
                        group_id = chat_qq.get_group_id(msg)
                        chat_qq.reply_group(group_id, user_id, reply)
                        
            else:
                await asyncio.sleep(1)

    def ask(
        self,
        question: str,
        nickname: str = None
    ) -> Generator[dict, None, None]:

        link_think = self.make_link_think(question, nickname)    
        answer = self.__post_question(link_think)
        for message in answer:
            yield from answer
            
            if (not message) or (message['code'] != 0):
                continue
            
            memory.append(q = question, a = message['message'])
            
    
    def __post_question(
        self, 
        link_think: str
    )-> Generator[dict, None, None]:
        yield from self.__post_openai(link_think, memory.openai_conversation_id)

    def __post_openai(
        self, 
        question: str,
        openai_conversation_id: str = None
    )-> Generator[dict, None, None]:
        answer = openai_api.ask(question, openai_conversation_id)
        # get yield last val
        for message in answer:
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
        self.running = False
        bye_string = 'server unknow error. sweven-box ready to go offline\n'
        if memory.save_memory():
            log_info('exit: save memory done.')
        else:
            log_err('exit: fail to save memory.')


aimi = Aimi()
