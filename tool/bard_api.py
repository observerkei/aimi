import os
import time
from typing import Generator, List
from Bard import Chatbot

from tool.util import log_dbg, log_err, log_info
from tool.config import config

class BardAPI:
    chatbot: Chatbot
    cookie_key: str = ''
    max_requestion: int = 1024
    max_repeat_times: int = 3
    type: str = 'bard'
    trigger: List[str] = []

    def is_call(self, question) -> bool:
        for call in self.trigger:
            if call.lower() in question.lower():
                return True
        return False
    
    def ask(
        self,
        question: str,
        timeout: int = 360,
    ) -> Generator[dict, None, None]:
        yield from self.web_ask(question, timeout)
        
    def web_ask(
        self,
        question: str,
        timeout: int = 360,
    ) -> Generator[dict, None, None]:
        answer = { 
           "message": '',
           "code": 1
        }

        req_cnt = 0
        
        while req_cnt < self.max_repeat_times:
            req_cnt += 1
            answer['code'] = 1
            
            try:
                log_dbg('try ask: ' + str(question))

                data = self.chatbot.ask(question)
                
                answer['message'] = data['content']
                answer['code'] = 0
                yield answer
             
            except Exception as e:
                log_err('fail to ask: ' + str(e))
                log_info('server fail, sleep 15')
                time.sleep(15)

                answer['message'] = str(e)
                answer['code'] = -1
                yield answer

            # request complate.
            if answer['code'] == 0:
                break

    def __init__(self) -> None:

        self.__load_setting()
        
        try:
            cookie_key = self.cookie_key
            if cookie_key and len(cookie_key):
                self.chatbot = Chatbot(cookie_key)
        except Exception as e:
            log_err('fail to init Bard: ' + str(e))

    def __load_setting(self):
        try:
            self.max_requestion = config.setting['bard']['max_requestion']
        except Exception as e:
            log_err('fail to load bard config: ' + str(e))
            self.max_requestion = 1024
        try:
            self.cookie_key = config.setting['bard']['cookie_1psd']
        except Exception as e:
            log_err('fail to load bard config: ' + str(e))
            self.cookie_key = ''
        try:
            self.max_repeat_times = config.setting['bard']['max_repeat_times']
        except Exception as e:
            log_err('fail to load bard config: ' + str(e))
            self.max_repeat_times = 3
        try:
            self.trigger = config.setting['bard']['trigger']
        except Exception as e:
            log_err('fail to load bard config: ' + str(e))
            self.trigger = [ '@bard', '#bard' ]

bard_api = BardAPI()
