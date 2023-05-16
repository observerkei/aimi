import asyncio
from EdgeGPT import Chatbot
from EdgeGPT import ConversationStyle as EdgeConversationStyle
from contextlib import suppress
from typing import Generator, List, Any, Dict
import time
from concurrent.futures import ThreadPoolExecutor

from tool.util import log_dbg, log_err, log_info
from tool.config import config

class BingAPI:
    type: str = 'bing'
    chatbot: Chatbot
    max_requestion: int = 1024
    max_repeat_times: int = 3
    cookie_path: str = ''
    wss_link: str = ''
    countdown: List[str] = [
        '?', 
        'I',     'II',   'III',   'IV',  'V',
        'VI',   'VII',  'VIII',  'VIV',  'X',
        'XI',   'XII',  'XIII',  'XIV', 'XV',
        'XVI', 'XVII', 'XVIII', 'XVIV', 'XX'
    ]
    loop: Any
    trigger: Dict[str, List[str]] = {}
    init: bool = False

    class ConversationStyle:
        creative: str = 'creative'
        balanced: str = 'balanced'
        precise: str = 'precise'

    def is_call(self, question) -> bool:
        for default in self.trigger['default']:
            if default.lower() in question.lower():
                return True
        
        return False

    def __get_conversation_style(self, question: str):
        for precise in self.trigger[self.ConversationStyle.precise]:
            if precise.lower() in question.lower():
                return EdgeConversationStyle.precise
        for balanced in self.trigger[self.ConversationStyle.balanced]:
            if balanced.lower() in question.lower():
                return EdgeConversationStyle.balanced
        for creative in self.trigger[self.ConversationStyle.creative]:
            if creative.lower() in question.lower():
                return EdgeConversationStyle.creative
        
        return EdgeConversationStyle.precise

    def ask(
        self,
        question: str,
        timeout: int = 360,
    ) -> Generator[dict, None, None]:
        yield from self.__fuck_async(self.web_ask(question, timeout))

    async def web_ask(
        self,
        question: str,
        timeout: int = 360,
    ) -> Generator[dict, None, None]:
        answer = { 
           "message": '',
           "code": 1
        }

        if (not self.init) and (not await self.__bot_create()):
            log_err('fail to load bing bot')
            answer['code'] = -1
            yield answer
            return
            
        req_cnt = 0
        conversation_style = self.__get_conversation_style(question)
        
        while req_cnt < self.max_repeat_times:
            req_cnt += 1
            answer['code'] = 1
            
            try:
                log_dbg('try ask: ' + str(question))

                async for final, response in self.chatbot.ask_stream(
                    prompt = question, 
                    conversation_style = conversation_style,
                    wss_link = self.wss_link
                ):
                    if not response:
                        continue
                    if not final:
                        answer['message'] = response
                        yield answer
                        continue
                    
                    cur_messages = 0
                    max_messages = 0
                    with suppress(KeyError):
                        cur_messages = response["item"]["throttling"]["numUserMessagesInConversation"]
                        max_messages = response["item"]["throttling"]["maxNumUserMessagesInConversation"]

                        if cur_messages == max_messages:
                            asyncio.run(self.__bot_create())
                        
                    raw_text = ''
                    with suppress(KeyError):
                        raw_text = response["item"]["messages"][1]["adaptiveCards"][0]["body"][0]["text"]

                    cd_idx = 1 + max_messages - cur_messages 
                    res_all = raw_text + '\n' + '[{}]'.format(self.countdown[cd_idx])

                    answer['message'] = res_all

                if '> Conversation disengaged' == answer['message']:
                    answer['code'] = -1
                    log_err('bing search fail.')
                    raise Exception(str(answer))


                answer['code'] = 0
                yield answer
             
            except Exception as e:
                log_err('fail to ask: ' + str(e))
                log_info('server fail, sleep 15')
                time.sleep(15)

                await self.__bot_reload()
                
                answer['message'] = str(e)
                answer['code'] = -1
                yield answer

            # request complate.
            if answer['code'] == 0:
                break
    
    def __fuck_async(self, async_gen):        
       while True:
           try:
               yield self.loop.run_until_complete(async_gen.__anext__())
           except StopAsyncIteration:
               log_dbg("stop: " +str(StopAsyncIteration))
               break
           except Exception as e:
               log_dbg("fail to get res " + str(e))
               break

    def __init__(self) -> None:

        self.__load_setting()
        
        asyncio.run(self.__bot_create())

        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop = asyncio.get_event_loop()
        
    async def __bot_create(self):
        try:        
            self.chatbot = await Chatbot.create(None, None, self.cookie_path)
            self.init = True
        except Exception as e:
            log_err('fail to create bing bot: ' + str(e))
            self.init = False

        return self.init
    
    async def __bot_reload(self):
        log_dbg('try reload chatbing bot')
        try:
            await self.chatbot.close()
        except:
            log_err('fail to close edge')

        log_info('create new edge.')
        await self.__bot_create()
        
    def __load_setting(self):
        try:
            setting = config.load_setting(self.type)
        except Exception as e:
            log_err(f'fail to load {self.type}: {e}')
            setting = {}
            return
        
        try:
            self.max_requestion = setting['max_requestion']
        except Exception as e:
            log_err('fail to load bing config: ' + str(e))
            self.max_requestion = 512
        try:
            self.max_repeat_times = setting['max_repeat_times']
        except Exception as e:
            log_err('fail to load bing config: ' + str(e))
            self.max_repeat_times = 3
        try:
            self.cookie_path = setting['cookie_path']
        except Exception as e:
            log_err('fail to load bing config: ' + str(e))
            self.cookie_path = ''

        try:
            self.wss_link = setting['wss_link']
        except Exception as e:
            log_err('fail to load bing config: ' + str(e))
            self.wss_link = ''

        try:
            self.trigger['default'] = setting['trigger']['default']
        except Exception as e:
            log_err('fail to load bing config: ' + str(e))
            self.trigger['default'] = [ '#bing', '@bing' ]
        try:
            self.trigger[self.ConversationStyle.creative] = setting['trigger'][self.ConversationStyle.creative]
        except Exception as e:
            log_err('fail to load bing config: ' + str(e))
            self.trigger[self.ConversationStyle.creative] = []
        try:
            self.trigger[self.ConversationStyle.balanced] = setting['trigger'][self.ConversationStyle.balanced]
        except Exception as e:
            log_err('fail to load bing config: ' + str(e))
            self.trigger[self.ConversationStyle.balanced] = []
        try:
            self.trigger[self.ConversationStyle.precise] = setting['trigger'][self.ConversationStyle.precise]
        except Exception as e:
            log_err('fail to load bing config: ' + str(e))
            self.trigger[self.ConversationStyle.precise] = []

bing_api = BingAPI()
