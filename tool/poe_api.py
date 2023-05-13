import asyncio
from typing import Generator, List, Any, Dict
import time
import poe

from tool.util import log_dbg, log_err, log_info
from tool.config import config

class PoeAPI:
    type: str = 'poe'
    chatbot: Any
    max_requestion: int = 1024
    max_repeat_times: int = 3
    cookie_key: str = ''
    models: Dict[str, Dict] = {}
    init: bool = False

    def is_call(self, question) -> bool:
        for default in self.models['default']['trigger']:
            if default.lower() in question.lower():
                return True
        
        return False

    def __get_bot_model(self, question: str):
        for model_name, model_info in self.models.items():
            if 'default' == model_name:
                continue
            
            model_trigger = model_info['trigger']
            if not model_trigger:
                continue

            for call in model_trigger:
                if call.lower() in question.lower():
                    return model_info['model']
        
        return self.models['default']['model']

    def ask(
        self,
        question: str,
        timeout: int = 360,
    ) -> Generator[dict, None, None]:
        yield from self.api_ask(question, timeout)

    def api_ask(
        self,
        question: str,
        timeout: int = 360,
    ) -> Generator[dict, None, None]:
        answer = { 
           "message": '',
           "code": 1
        }

        if (not self.init) and (not self.__create_bot()):
            log_err('fail to create qoe bot')
            answer['code'] = -1
            return answer

        req_cnt = 0
        bot_model = self.__get_bot_model(question)
        
        while req_cnt < self.max_repeat_times:
            req_cnt += 1
            answer['code'] = 1
            
            try:
                log_dbg('try ask: ' + str(question))

                for chunk in self.chatbot.send_message(
                    bot_model,
                    question
                ):
                    answer['message'] = chunk['text']
                    yield answer

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

    def __create_bot(self):
        if self.cookie_key and len(self.cookie_key):
            try:
                self.chatbot = poe.Client(self.cookie_key)
                self.init = True
                log_info('load poe bot: ' + str(self.chatbot.bot_names))
            except Exception as e:
                log_err('fail to init poe bot: ' + str(e))
                self.init = False

        return self.init
    
    def __init__(self) -> None:
        self.__load_setting()
        self.__create_bot()
        
    def __try_load_trigger(self, name: str):
        try:
            self.trigger[name] = config.setting['poe']['trigger'][name]
        except Exception as e:
            log_err('fail to load poe config: {}, err: {}'.format(str(name), str(e)))
            self.trigger[name] = []

    def __load_models(self):
        try:
            models = config.setting['poe']['models']

            for model_name, model_info in models.items():
                self.models[model_name] = {}
                try:
                    self.models[model_name]['model'] = model_info['model']
                except Exception as e:
                    log_err('model_name:{} no model, err:{}'.format(str(model_name), str(e)))
                    self.models[model_name]['model'] = None

                try:
                    self.models[model_name]['trigger'] = model_info['trigger']
                except Exception as e:
                    log_dbg('model_name:{} no trigger, err:{}'.format(str(model_name), str(e)))
                    self.models[model_name]['trigger'] = None
                    
        except Exception as e:
            self.models = {}
            log_err('fail to load poe model cfg: ' + str(e))
    
    def __load_setting(self):
        try:
            self.max_requestion = config.setting['poe']['max_requestion']
        except Exception as e:
            log_err('fail to load poe config: ' + str(e))
            self.max_requestion = 512
        try:
            self.max_repeat_times = config.setting['poe']['max_repeat_times']
        except Exception as e:
            log_err('fail to load poe config: ' + str(e))
            self.max_repeat_times = 3
        try:
            self.cookie_key = config.setting['poe']['cookie_p-b']
        except Exception as e:
            log_err('fail to load poe config: ' + str(e))
            self.cookie_key = ''

        self.__load_models()


poe_api = PoeAPI()
